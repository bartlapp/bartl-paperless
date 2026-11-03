// SPDX-License-Identifier: Apache-2.0
package controller

import (
	"context"
	"encoding/json"
	"fmt"
	api "github.com/floriankesslergmbh/bartl-paperless/api/v1alpha1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

func jobTerminal(j *batchv1.Job) bool {
	for _, c := range j.Status.Conditions {
		if (c.Type == batchv1.JobComplete || c.Type == batchv1.JobFailed) && c.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
}

type operationError struct{ error }

func invalidOperation(format string, args ...any) error {
	return operationError{fmt.Errorf(format, args...)}
}
func permanentOperation(err error) bool { _, ok := err.(operationError); return ok }
func (r *Reconciler) observeJob(ctx context.Context, a *api.PaperlessApplication, op *api.Operation) (bool, *api.NativeResult, error) {
	if op.Phase == "Succeeded" {
		if op.Result == nil {
			return false, nil, invalidOperation("successful operation lacks bound result")
		}
		return true, op.Result, nil
	}
	if op.Phase == "Interrupted" || op.Phase == "Failed" {
		return false, nil, invalidOperation("operation %s is durably %s", op.ID, op.Phase)
	}
	job := &batchv1.Job{}
	err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: op.JobName}, job)
	if apierrors.IsNotFound(err) {
		if op.Phase != "Planned" {
			return false, nil, invalidOperation("admitted Job %s is missing; refusing replay", op.JobName)
		}
		// Recheck live run intent immediately before creation. A concurrent stop can
		// still race the API call; native authority checks and next reconcile drain it.
		current := &api.PaperlessApplication{}
		if err := r.Reader.Get(ctx, client.ObjectKeyFromObject(a), current); err != nil {
			return false, nil, err
		}
		if current.UID != a.UID || !running(current) {
			return false, nil, invalidOperation("run authority withdrawn before Job admission")
		}
		job = jobFor(a, op)
		if err := controllerutil.SetControllerReference(a, job, r.Scheme); err != nil {
			return false, nil, err
		}
		if err := r.Create(ctx, job); err != nil {
			return false, nil, err
		}
	} else if err != nil {
		return false, nil, err
	}
	if !metav1.IsControlledBy(job, a) || job.Annotations["paperless.bartl.sh/operation"] != op.ID {
		return false, nil, invalidOperation("Job %s identity collision", op.JobName)
	}
	if op.JobUID != "" && op.JobUID != string(job.UID) {
		return false, nil, invalidOperation("admitted Job %s replaced", op.JobName)
	}
	op.JobUID = string(job.UID)
	op.Phase = "Admitted"
	for _, c := range job.Status.Conditions {
		if c.Type == batchv1.JobFailed && c.Status == corev1.ConditionTrue {
			op.Phase = "Failed"
			return false, nil, invalidOperation("native %s Job failed: %s %s", op.Kind, c.Reason, c.Message)
		}
	}
	if !jobTerminal(job) {
		return false, nil, nil
	}
	pods := &corev1.PodList{}
	if err := r.Reader.List(ctx, pods, client.InNamespace(a.Namespace), client.MatchingLabels{"batch.kubernetes.io/job-name": job.Name}); err != nil {
		return false, nil, err
	}
	var result *api.NativeResult
	for i := range pods.Items {
		p := &pods.Items[i]
		if !metav1.IsControlledBy(p, job) {
			continue
		}
		for _, c := range p.Status.ContainerStatuses {
			if c.Name != containerName || c.State.Terminated == nil {
				continue
			}
			t := c.State.Terminated
			if t.ExitCode != 0 {
				return false, nil, invalidOperation("native %s exited %d: %s", op.Kind, t.ExitCode, t.Message)
			}
			if result != nil {
				return false, nil, invalidOperation("multiple execution results for %s", op.ID)
			}
			v := &api.NativeResult{}
			if err := json.Unmarshal([]byte(t.Message), v); err != nil {
				return false, nil, invalidOperation("invalid native termination result: %v", err)
			}
			if v.ApplicationUID != string(a.UID) || v.Operation != op.ID {
				return false, nil, invalidOperation("native result does not bind current application and operation")
			}
			result = v
		}
	}
	if result == nil {
		return false, nil, invalidOperation("completed Job %s lacks native execution result", op.JobName)
	}
	op.Result = result
	op.Phase = "Succeeded"
	return true, result, nil
}
