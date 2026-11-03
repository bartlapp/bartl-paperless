// SPDX-License-Identifier: Apache-2.0
package controller

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	api "github.com/floriankesslergmbh/bartl-paperless/api/v1alpha1"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/remotecommand"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"time"
)

type Executor interface {
	Exec(context.Context, *corev1.Pod, []string) ([]byte, error)
}
type PodExecutor struct {
	Config *rest.Config
	Kube   kubernetes.Interface
}

func (e *PodExecutor) Exec(ctx context.Context, p *corev1.Pod, command []string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req := e.Kube.CoreV1().RESTClient().Post().Resource("pods").Namespace(p.Namespace).Name(p.Name).SubResource("exec").VersionedParams(&corev1.PodExecOptions{Container: containerName, Command: command, Stdout: true, Stderr: true}, scheme.ParameterCodec)
	ex, err := remotecommand.NewSPDYExecutor(e.Config, "POST", req.URL())
	if err != nil {
		return nil, err
	}
	var out, stderr bytes.Buffer
	if err := ex.StreamWithContext(ctx, remotecommand.StreamOptions{Stdout: &out, Stderr: &stderr}); err != nil {
		return nil, fmt.Errorf("native exec: %w: %s", err, stderr.String())
	}
	return out.Bytes(), nil
}

type CaptureObservation struct {
	Operation       string `json:"operation"`
	State           string `json:"state"`
	Execution       string `json:"execution"`
	Path            string `json:"path"`
	Error           string `json:"error"`
	StartedAt       string `json:"startedAt"`
	CapturedAt      string `json:"capturedAt"`
	Resumed         bool   `json:"resumed"`
	ResumptionError string `json:"resumptionError"`
}
type NativeStatus struct {
	Execution string              `json:"execution"`
	Ready     bool                `json:"ready"`
	Failure   string              `json:"failure"`
	Capture   *CaptureObservation `json:"capture"`
}

func containerID(p *corev1.Pod) string {
	for _, c := range p.Status.ContainerStatuses {
		if c.Name == containerName && c.State.Running != nil {
			return c.ContainerID
		}
	}
	return ""
}
func (r *Reconciler) liveAppPod(ctx context.Context, a *api.PaperlessApplication) (*corev1.Pod, error) {
	pods := &corev1.PodList{}
	if err := r.Reader.List(ctx, pods, client.InNamespace(a.Namespace), client.MatchingLabels(labels(a, "app"))); err != nil {
		return nil, err
	}
	var live *corev1.Pod
	for i := range pods.Items {
		p := &pods.Items[i]
		if p.DeletionTimestamp != nil || p.Status.Phase == corev1.PodSucceeded || p.Status.Phase == corev1.PodFailed {
			continue
		}
		if err := r.verifyPodOwner(ctx, a, p); err != nil {
			return nil, err
		}
		if live != nil {
			return nil, fmt.Errorf("multiple application Pods; refusing mutation")
		}
		live = p
	}
	return live, nil
}
func (r *Reconciler) samePod(ctx context.Context, p *corev1.Pod) error {
	fresh := &corev1.Pod{}
	if err := r.Reader.Get(ctx, client.ObjectKeyFromObject(p), fresh); err != nil {
		return err
	}
	if fresh.UID != p.UID || fresh.DeletionTimestamp != nil || containerID(fresh) == "" || containerID(fresh) != containerID(p) {
		return fmt.Errorf("Pod or container execution changed")
	}
	return nil
}
func (r *Reconciler) readStatus(ctx context.Context, a *api.PaperlessApplication, p *corev1.Pod) (*NativeStatus, error) {
	if p.Labels["paperless.bartl.sh/uid"] != string(a.UID) {
		return nil, fmt.Errorf("Pod application identity mismatch")
	}
	if err := r.samePod(ctx, p); err != nil {
		return nil, err
	}
	out, err := r.Executor.Exec(ctx, p, nativeCommand("status"))
	if err != nil {
		return nil, err
	}
	st := &NativeStatus{}
	if err := json.Unmarshal(bytes.TrimSpace(out), st); err != nil {
		return nil, fmt.Errorf("native status response: %w", err)
	}
	if st.Execution == "" && st.Failure == "" {
		return nil, fmt.Errorf("native status lacks container execution UUID")
	}
	if err := r.samePod(ctx, p); err != nil {
		return nil, err
	}
	return st, nil
}
func (r *Reconciler) captureAuthority(ctx context.Context, a *api.PaperlessApplication, p *corev1.Pod) error {
	live := &api.PaperlessApplication{}
	if err := r.Reader.Get(ctx, client.ObjectKeyFromObject(a), live); err != nil {
		return err
	}
	if live.UID != a.UID || !running(live) || live.Generation != a.Generation {
		return fmt.Errorf("current application no longer authorizes this capture")
	}
	for _, name := range claimNames(a.Spec.Claims) {
		claim := &corev1.PersistentVolumeClaim{}
		if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: name}, claim); err != nil {
			return err
		}
		if claim.Annotations[ownerAnnotation] != string(a.UID) {
			return fmt.Errorf("claim %s authority changed", name)
		}
	}
	if err := r.verifyPodOwner(ctx, a, p); err != nil {
		return err
	}
	return r.samePod(ctx, p)
}
func (r *Reconciler) verifyPodOwner(ctx context.Context, a *api.PaperlessApplication, p *corev1.Pod) error {
	owner := metav1.GetControllerOf(p)
	if owner == nil || owner.Kind != "ReplicaSet" {
		return invalidOperation("application Pod has foreign owner")
	}
	rs := &appsv1.ReplicaSet{}
	if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: p.Namespace, Name: owner.Name}, rs); err != nil {
		return err
	}
	if rs.UID != owner.UID {
		return invalidOperation("application ReplicaSet replaced")
	}
	depOwner := metav1.GetControllerOf(rs)
	if depOwner == nil || depOwner.Kind != "Deployment" || depOwner.Name != "paperless" {
		return invalidOperation("application ReplicaSet has foreign owner")
	}
	d := &appsv1.Deployment{}
	if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: p.Namespace, Name: depOwner.Name}, d); err != nil {
		return err
	}
	if d.UID != depOwner.UID || !metav1.IsControlledBy(d, a) {
		return invalidOperation("application Deployment has foreign owner")
	}
	return nil
}
func stickyNativeFailure(message string) bool {
	var diagnostic struct {
		Sticky *bool `json:"sticky"`
	}
	if json.Unmarshal([]byte(message), &diagnostic) == nil && diagnostic.Sticky != nil {
		return *diagnostic.Sticky
	}
	return true
}
func gateFailure(a *api.PaperlessApplication, p *corev1.Pod) error {
	for _, c := range p.Status.ContainerStatuses {
		if c.Name != containerName {
			continue
		}
		for _, term := range []*corev1.ContainerStateTerminated{c.State.Terminated, c.LastTerminationState.Terminated} {
			if term == nil {
				continue
			}
			var diagnostic struct {
				State          string `json:"state"`
				Sticky         bool   `json:"sticky"`
				Error          string `json:"error"`
				ApplicationUID string `json:"applicationUID"`
			}
			if json.Unmarshal([]byte(term.Message), &diagnostic) == nil && diagnostic.State == "Failed" && diagnostic.Sticky && diagnostic.ApplicationUID == string(a.UID) {
				return fmt.Errorf("native startup gate failed: %s", diagnostic.Error)
			}
		}
	}
	return nil
}
func expectedCaptureTransition(message, operation, execution string) bool {
	var marker struct {
		Operation string `json:"operation"`
		Execution string `json:"execution"`
		State     string `json:"state"`
	}
	if json.Unmarshal([]byte(message), &marker) != nil {
		return false
	}
	return marker.Operation == operation && marker.Execution == execution && (marker.State == "Capturing" || marker.State == "Captured")
}
