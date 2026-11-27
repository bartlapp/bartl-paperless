// SPDX-License-Identifier: Apache-2.0
package controller

import (
	"context"
	"fmt"
	api "github.com/floriankesslergmbh/bartl-paperless/api/v1alpha2"
	"github.com/google/uuid"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"strconv"
	"time"
)

func captureDeadline(a *api.PaperlessApplication) error {
	admitted, err := time.Parse(time.RFC3339Nano, a.Status.Backup.AdmittedAt)
	if err != nil {
		return fmt.Errorf("pending capture lacks its admission timestamp")
	}
	drain := a.Spec.Backup.DrainSeconds
	if drain == 0 {
		drain = 300
	}
	if time.Now().After(admitted.Add(time.Hour + time.Duration(drain)*time.Second)) {
		return fmt.Errorf("capture execution exceeded its finite deadline; native outcome remains uncertain")
	}
	return nil
}

func completedCapture(a *api.PaperlessApplication, st *NativeStatus) bool {
	c := st.Capture
	b := &a.Status.Backup
	if c == nil || c.State != "Captured" || c.Operation != b.CaptureOperation ||
		c.Execution != b.Execution || c.Path != "/staging/captures/"+b.CaptureOperation ||
		c.CapturedAt == "" {
		return false
	}
	known := st.Failure == "" || expectedCaptureTransition(st.Failure, b.CaptureOperation, b.Execution)
	return known && (c.Resumed || c.ResumptionError != "" || !running(a) || (st.Execution != "" && st.Execution != b.Execution))
}

func intactCaptureFailure(a *api.PaperlessApplication, st *NativeStatus) bool {
	c := st.Capture
	b := &a.Status.Backup
	return c != nil && c.State == "Failed" && c.SourceIntact &&
		c.Operation == b.CaptureOperation && c.Execution == b.Execution &&
		(st.Failure == "" || expectedCaptureTransition(st.Failure, b.CaptureOperation, b.Execution))
}

func (r *Reconciler) backupFailure(ctx context.Context, a *api.PaperlessApplication, err error, isolate bool) (ctrl.Result, error) {
	a.Status.Backup.Phase = "Failed"
	a.Status.Backup.Error = err.Error()
	condition(a, "BackupFailed", metav1.ConditionTrue, "BackupFailed", err.Error())
	if isolate {
		return r.fail(ctx, a, err)
	}
	return r.save(ctx, a)
}
func (r *Reconciler) backup(ctx context.Context, a *api.PaperlessApplication, p *corev1.Pod, st *NativeStatus) (ctrl.Result, error) {
	b := &a.Status.Backup
	switch b.Phase {
	case "Admitting", "Capturing":
		if !completedCapture(a, st) && !intactCaptureFailure(a, st) && (b.PodName != p.Name || b.PodUID != string(p.UID) || b.ContainerID != containerID(p) || b.Execution != st.Execution) {
			return r.backupFailure(ctx, a, fmt.Errorf("capture execution changed; incomplete capture remains isolated"), true)
		}
		c := st.Capture
		if c != nil && c.Operation == b.CaptureOperation {
			if c.Execution != b.Execution {
				return r.backupFailure(ctx, a, fmt.Errorf("capture result execution mismatch"), true)
			}
			switch c.State {
			case "Failed":
				return r.backupFailure(ctx, a, fmt.Errorf("native capture failed: %s", c.Error), !intactCaptureFailure(a, st))
			case "Captured":
				if c.CapturedAt == "" || c.Path != "/staging/captures/"+b.CaptureOperation {
					return r.backupFailure(ctx, a, fmt.Errorf("capture result lacks protected path and capture boundary"), true)
				}
				b.CapturedAt = c.CapturedAt
				b.Resumed = c.Resumed
				b.ResumptionError = c.ResumptionError
				if c.ResumptionError != "" {
					return r.backupFailure(ctx, a, fmt.Errorf("native resumption failed after complete capture: %s", c.ResumptionError), false)
				}
				if !completedCapture(a, st) {
					if err := captureDeadline(a); err != nil {
						return r.backupFailure(ctx, a, err, false)
					}
					return r.save(ctx, a)
				}
				b.Phase = "Captured"
				return r.save(ctx, a)
			case "Capturing":
				if err := captureDeadline(a); err != nil {
					return r.backupFailure(ctx, a, err, true)
				}
				b.Phase = "Capturing"
				return r.save(ctx, a)
			default:
				return r.backupFailure(ctx, a, fmt.Errorf("unknown native capture state %q", c.State), true)
			}
		}
		if err := captureDeadline(a); err != nil {
			return r.backupFailure(ctx, a, err, true)
		}
		if expectedCaptureTransition(st.Failure, b.CaptureOperation, b.Execution) {
			return r.save(ctx, a)
		}
		if b.Phase == "Capturing" {
			return r.backupFailure(ctx, a, fmt.Errorf("admitted capture disappeared from its execution"), true)
		}
		if c != nil && (c.State == "Capturing" || (c.State == "Failed" && !c.SourceIntact)) {
			return r.backupFailure(ctx, a, fmt.Errorf("conflicting native capture %s", c.Operation), true)
		}
		// Read status again immediately before mutation; transport loss is not proof
		// of termination and retries always use this same persisted operation.
		fresh, err := r.readStatus(ctx, a, p)
		if err != nil {
			return ctrl.Result{RequeueAfter: 2 * time.Second}, nil
		}
		if fresh.Execution != b.Execution {
			return r.backupFailure(ctx, a, fmt.Errorf("container execution changed before admission"), true)
		}
		if fresh.Capture != nil && fresh.Capture.Operation == b.CaptureOperation {
			return ctrl.Result{RequeueAfter: time.Second}, nil
		}
		if expectedCaptureTransition(fresh.Failure, b.CaptureOperation, b.Execution) {
			return r.save(ctx, a)
		}
		if fresh.Failure != "" || (fresh.Capture != nil && (fresh.Capture.State == "Capturing" || (fresh.Capture.State == "Failed" && !fresh.Capture.SourceIntact))) {
			return r.backupFailure(ctx, a, fmt.Errorf("native state changed before capture admission"), true)
		}
		if !fresh.Ready {
			return r.save(ctx, a)
		}
		if err := r.captureAuthority(ctx, a, p); err != nil {
			return ctrl.Result{}, err
		}
		drain := a.Spec.Backup.DrainSeconds
		if drain == 0 {
			drain = 300
		}
		command := append(nativeCommand("begin-capture"), b.CaptureOperation, b.Execution, strconv.Itoa(drain))
		if _, err := r.Executor.Exec(ctx, p, command); err != nil {
			b.Error = "Capture admission response unavailable; observing same operation: " + err.Error()
			return r.save(ctx, a)
		}
		b.Phase = "Capturing"
		b.Error = ""
		return r.save(ctx, a)
	case "Captured":
		if a.Spec.Backup.Repository == "" || a.Spec.Backup.WriterSecret == "" {
			return r.backupFailure(ctx, a, fmt.Errorf("publication requires repository and writerSecret"), false)
		}
		remember(a, b.Publication)
		b.Publication = newOperation(a, "publish", a.Status.Version, "")
		b.Phase = "Publishing"
		return r.save(ctx, a)
	case "Publishing":
		if b.Publication == nil {
			return r.backupFailure(ctx, a, fmt.Errorf("publication admission missing"), false)
		}
		done, result, err := r.observeJob(ctx, a, b.Publication)
		if err != nil {
			if permanentOperation(err) {
				return r.backupFailure(ctx, a, err, false)
			}
			return ctrl.Result{}, err
		}
		if !done {
			return r.save(ctx, a)
		}
		if result.State != "Published" || len(result.RepositoryID) != 64 || len(result.SnapshotID) != 64 || result.CapturedAt != b.CapturedAt || result.PublishedAt == "" {
			return r.backupFailure(ctx, a, fmt.Errorf("invalid bound publication result"), false)
		}
		b.RepositoryID = result.RepositoryID
		b.SnapshotID = result.SnapshotID
		b.PublishedAt = result.PublishedAt
		b.Phase = "Published"
		b.Error = ""
		condition(a, "BackupFailed", metav1.ConditionFalse, "Published", "Capture completely published and verified")
		return r.save(ctx, a)
	}
	// Manual and scheduled requests converge here; no second capture dispatcher.
	request := ""
	manualRequest := a.Annotations["paperless.bartl.sh/backup-request"]
	if manualRequest != "" && manualRequest != b.LastManualRequest {
		request = manualRequest
		b.LastManualRequest = request
	}
	now := time.Now()
	if b.ScheduleBaseline == nil {
		v := metav1.NewTime(now)
		b.ScheduleBaseline = &v
	}
	if request == "" && running(a) && a.Spec.Backup.Schedule != "" {
		s, err := schedule(a)
		if err != nil {
			return r.backupFailure(ctx, a, err, false)
		}
		base := b.ScheduleBaseline.Time
		if b.LastScheduleTime != nil && b.LastScheduleTime.Time.After(base) {
			base = b.LastScheduleTime.Time
		}
		due := s.Next(base)
		if !due.After(now) {
			request = "schedule:" + due.UTC().Format(time.RFC3339)
			v := metav1.NewTime(due)
			b.LastScheduleTime = &v
			baseline := metav1.NewTime(now)
			b.ScheduleBaseline = &baseline
		}
	}
	if request == "" {
		return r.save(ctx, a)
	}
	if a.Spec.Backup.Repository == "" || a.Spec.Backup.WriterSecret == "" {
		b.Request = request
		return r.backupFailure(ctx, a, fmt.Errorf("backup requires repository and writerSecret"), false)
	}
	if b.CaptureOperation != "" && b.CapturedAt != "" && b.PublishedAt == "" {
		b.Request = request
		b.Error = ""
		b.Phase = "Captured"
		return r.save(ctx, a)
	}
	if !st.Ready || !podReady(p) {
		return r.save(ctx, a)
	}
	if st.Capture != nil && (st.Capture.State == "Capturing" || (st.Capture.State == "Failed" && !st.Capture.SourceIntact)) {
		return r.backupFailure(ctx, a, fmt.Errorf("unresolved native capture prevents admission"), true)
	}
	remember(a, b.Publication)
	b.Resumed = false
	b.ResumptionError = ""
	b.Request = request
	b.CaptureOperation = uuid.NewString()
	b.AdmittedAt = now.UTC().Format(time.RFC3339Nano)
	b.Phase = "Admitting"
	b.PodName = p.Name
	b.PodUID = string(p.UID)
	b.ContainerID = containerID(p)
	b.Execution = st.Execution
	b.CapturedAt = ""
	b.PublishedAt = ""
	b.RepositoryID = ""
	b.SnapshotID = ""
	b.Error = ""
	b.Publication = nil
	condition(a, "BackupFailed", metav1.ConditionFalse, "CaptureAdmitted", "One capture operation admitted")
	return r.save(ctx, a)
}

// An explicit backup request and ordinary stop can be submitted together.
// Finish the admitted capture/publication without restarting any workload.
func (r *Reconciler) stoppingBackup(ctx context.Context, a *api.PaperlessApplication) (bool, ctrl.Result, error) {
	b := &a.Status.Backup
	active := b.Phase == "Admitting" || b.Phase == "Capturing"
	publication := b.Phase == "Captured" || b.Phase == "Publishing"
	request := a.Annotations["paperless.bartl.sh/backup-request"]
	requested := request != "" && request != b.LastManualRequest
	if !active && !publication && !requested {
		return false, ctrl.Result{}, nil
	}
	condition(a, "Ready", metav1.ConditionFalse, "Stopping", "Finishing requested backup before ordinary stop")
	condition(a, "Stopped", metav1.ConditionFalse, "BackupDraining", "Waiting for capture and publication to finish")
	if publication || (!active && requested && b.CapturedAt != "" && b.PublishedAt == "") {
		result, err := r.backup(ctx, a, nil, nil)
		return true, result, err
	}
	pod, err := r.liveAppPod(ctx, a)
	if err != nil {
		return true, ctrl.Result{}, err
	}
	if pod == nil || containerID(pod) == "" {
		if active {
			result, err := r.backupFailure(ctx, a, fmt.Errorf("capture execution ended before its outcome was established"), false)
			return true, result, err
		}
		b.Request, b.LastManualRequest = request, request
		result, err := r.backupFailure(ctx, a, fmt.Errorf("capture requires an existing running application; stop will not start it"), false)
		return true, result, err
	}
	st, err := r.readStatus(ctx, a, pod)
	if err != nil {
		return true, ctrl.Result{}, err
	}
	if !active && (!st.Ready || !podReady(pod) || st.Failure != "") {
		b.Request, b.LastManualRequest = request, request
		result, err := r.backupFailure(ctx, a, fmt.Errorf("capture requires confirmed native readiness; stop will not start it"), false)
		return true, result, err
	}
	result, err := r.backup(ctx, a, pod, st)
	return true, result, err
}
