// SPDX-License-Identifier: Apache-2.0
package controller

import (
	"context"
	"fmt"
	api "github.com/floriankesslergmbh/bartl-paperless/api/v1alpha2"
	"github.com/google/uuid"
	"github.com/robfig/cron/v3"
	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"time"
)

type Reconciler struct {
	client.Client
	Reader    client.Reader
	Scheme    *runtime.Scheme
	Executor  Executor
	Namespace string
}

func (r *Reconciler) SetupWithManager(m ctrl.Manager) error {
	intentChanges := predicate.Funcs{UpdateFunc: func(e event.UpdateEvent) bool {
		return e.ObjectOld.GetGeneration() != e.ObjectNew.GetGeneration() ||
			e.ObjectOld.GetDeletionTimestamp().IsZero() != e.ObjectNew.GetDeletionTimestamp().IsZero() ||
			e.ObjectOld.GetAnnotations()["paperless.bartl.sh/backup-request"] != e.ObjectNew.GetAnnotations()["paperless.bartl.sh/backup-request"]
	}}
	return ctrl.NewControllerManagedBy(m).
		For(&api.PaperlessApplication{}, builder.WithPredicates(intentChanges)).
		Owns(&batchv1.Job{}).
		Owns(&appsv1.Deployment{}, builder.WithPredicates(predicate.GenerationChangedPredicate{})).
		Owns(&corev1.Pod{}).Complete(r)
}
func condition(a *api.PaperlessApplication, name string, status metav1.ConditionStatus, reason, message string) {
	meta.SetStatusCondition(&a.Status.Conditions, metav1.Condition{Type: name, Status: status, Reason: reason, Message: message, ObservedGeneration: a.Generation})
}
func remember(a *api.PaperlessApplication, op *api.Operation) {
	if op == nil {
		return
	}
	for _, old := range a.Status.Operations {
		if old.ID == op.ID {
			return
		}
	}
	a.Status.Operations = append(a.Status.Operations, *op)
}
func (r *Reconciler) save(ctx context.Context, a *api.PaperlessApplication) (ctrl.Result, error) {
	a.Status.ObservedGeneration = a.Generation
	return ctrl.Result{RequeueAfter: 2 * time.Second}, r.Status().Update(ctx, a)
}
func (r *Reconciler) fail(ctx context.Context, a *api.PaperlessApplication, err error) (ctrl.Result, error) {
	a.Status.Failure = err.Error()
	a.Status.State = "Failed"
	if a.Status.Operation != nil && a.Status.Operation.Phase != "Succeeded" && a.Status.Operation.Phase != "Interrupted" {
		a.Status.Operation.Phase = "Failed"
	}
	condition(a, "Failed", metav1.ConditionTrue, "LifecycleFailed", err.Error())
	condition(a, "Ready", metav1.ConditionFalse, "LifecycleFailed", err.Error())
	return r.save(ctx, a)
}
func validVersion(v string) bool { return v == "3.3.0" || v == "3.3.1" }
func validate(a *api.PaperlessApplication) error {
	if a.Name != "paperless" {
		return fmt.Errorf("only application name paperless is supported")
	}
	if !validVersion(desired(a)) {
		return fmt.Errorf("unsupported version %q", desired(a))
	}
	if a.Spec.Replicas != nil && *a.Spec.Replicas != 0 && *a.Spec.Replicas != 1 {
		return fmt.Errorf("replicas must be zero or one")
	}
	if a.Spec.Identity.Installation == "" || a.Spec.Identity.Instance == "" || a.Spec.ConfigurationSecret == "" {
		return fmt.Errorf("identity and configurationSecret are required")
	}
	if a.Spec.Images.Runtime330 == "" || a.Spec.Images.Runtime331 == "" || a.Spec.Images.Postgres == "" || a.Spec.Images.Redis == "" {
		return fmt.Errorf("all four immutable image references are required")
	}
	seen := map[string]bool{}
	for _, n := range claimNames(a.Spec.Claims) {
		if n == "" || seen[n] {
			return fmt.Errorf("four distinct existing claims are required")
		}
		seen[n] = true
	}
	if a.Status.Identity != nil && *a.Status.Identity != a.Spec.Identity {
		return fmt.Errorf("logical identity is immutable")
	}
	if a.Status.Claims != nil && *a.Status.Claims != a.Spec.Claims {
		return fmt.Errorf("claims are immutable")
	}
	if a.Status.Version == "3.3.1" && desired(a) == "3.3.0" {
		return fmt.Errorf("downgrade 3.3.1 to 3.3.0 is unsupported")
	}
	if a.Spec.Backup.DrainSeconds < 0 {
		return fmt.Errorf("drainSeconds must be positive")
	}
	return nil
}
func claimNames(c api.Claims) []string { return []string{c.Storage, c.Database, c.Broker, c.Staging} }
func (r *Reconciler) acquire(ctx context.Context, a *api.PaperlessApplication) error {
	// Observe every claim before acquiring any; resourceVersion updates arbitrate competitors.
	for _, name := range claimNames(a.Spec.Claims) {
		p := &corev1.PersistentVolumeClaim{}
		if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: name}, p); err != nil {
			return err
		}
		if p.DeletionTimestamp != nil {
			return invalidOperation("claim %s is deleting", name)
		}
		if owner := p.Annotations[ownerAnnotation]; owner != "" && owner != string(a.UID) {
			return invalidOperation("claim %s belongs to %s", name, owner)
		}
	}
	for _, name := range claimNames(a.Spec.Claims) {
		p := &corev1.PersistentVolumeClaim{}
		if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: name}, p); err != nil {
			return err
		}
		owner := p.Annotations[ownerAnnotation]
		if owner == string(a.UID) {
			continue
		}
		if owner != "" {
			return invalidOperation("claim %s acquired by competitor", name)
		}
		if p.Annotations == nil {
			p.Annotations = map[string]string{}
		}
		p.Annotations[ownerAnnotation] = string(a.UID)
		if err := r.Update(ctx, p); err != nil {
			return err
		}
	}
	return nil
}
func (r *Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (result ctrl.Result, reconcileErr error) {
	a := &api.PaperlessApplication{}
	if err := r.Reader.Get(ctx, req.NamespacedName, a); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}
	defer func() {
		if reconcileErr == nil {
			return
		}
		// Failed management observation cannot certify a new configuration or
		// terminate already admitted execution.
		condition(a, "Ready", metav1.ConditionUnknown, "ReconciliationUnavailable", reconcileErr.Error())
		if !running(a) {
			condition(a, "Stopped", metav1.ConditionUnknown, "TerminationUnconfirmed", reconcileErr.Error())
		}
		if err := r.Status().Update(ctx, a); err != nil {
			reconcileErr = fmt.Errorf("%w; reporting observation failure: %v", reconcileErr, err)
		}
	}()
	// Current stop/deletion preempts even completed Jobs and invalid new configuration.
	if !running(a) {
		return r.stop(ctx, a, !a.DeletionTimestamp.IsZero())
	}
	if a.Status.Failure != "" {
		a.Status.State = "Failed"
		condition(a, "Failed", metav1.ConditionTrue, "LifecycleFailed", a.Status.Failure)
		condition(a, "Ready", metav1.ConditionFalse, "LifecycleFailed", a.Status.Failure)
		cancelled, err := r.cancelActiveJobs(ctx, a)
		if err != nil {
			return ctrl.Result{}, err
		}
		done, err := r.drain(ctx, a, false)
		if err != nil {
			return ctrl.Result{}, err
		}
		condition(a, "Stopped", metav1.ConditionFalse, "FailureIsolating", "Waiting for all owned execution to stop")
		if done && cancelled {
			dependenciesStopped, err := r.stopDependencies(ctx, a)
			if err != nil {
				return ctrl.Result{}, err
			}
			if dependenciesStopped {
				a.Status.Replicas = 0
				condition(a, "Stopped", metav1.ConditionTrue, "FailureIsolated", a.Status.Failure)
			}
		}
		return r.save(ctx, a)
	}
	if err := validate(a); err != nil {
		return r.fail(ctx, a, err)
	}
	if !controllerutil.ContainsFinalizer(a, finalizer) {
		controllerutil.AddFinalizer(a, finalizer)
		return ctrl.Result{Requeue: true}, r.Update(ctx, a)
	}
	if a.Status.Identity == nil {
		id := a.Spec.Identity
		c := a.Spec.Claims
		a.Status.Identity = &id
		a.Status.Claims = &c
		return r.save(ctx, a)
	}
	if err := r.acquire(ctx, a); err != nil {
		if permanentOperation(err) {
			return r.fail(ctx, a, err)
		}
		return ctrl.Result{}, err
	}
	if err := r.dependencies(ctx, a); err != nil {
		if permanentOperation(err) {
			return r.fail(ctx, a, err)
		}
		return ctrl.Result{}, err
	}
	condition(a, "Stopped", metav1.ConditionFalse, "RunRequested", "Run intent is active")
	if a.Status.TargetVersion != "" && a.Status.TargetVersion != desired(a) && a.Status.PreparedVersion != a.Status.TargetVersion {
		return r.fail(ctx, a, fmt.Errorf("version changed during admitted transition"))
	}
	if a.Status.PreparedVersion != desired(a) {
		dependenciesReady, err := r.dependenciesReady(ctx, a)
		if err != nil {
			return ctrl.Result{}, err
		}
		if !dependenciesReady {
			condition(a, "Ready", metav1.ConditionFalse, "DependenciesStarting", "Waiting for native database and broker readiness")
			return r.save(ctx, a)
		}
		if a.Status.Backup.Phase == "Capturing" || a.Status.Backup.Phase == "Admitting" {
			return r.backupFailure(ctx, a, fmt.Errorf("capture interrupted by version change"), true)
		}
		if a.Status.TargetVersion != desired(a) {
			done, err := r.cancelActiveJobs(ctx, a)
			if err != nil {
				return ctrl.Result{}, err
			}
			if !done {
				return ctrl.Result{RequeueAfter: 2 * time.Second}, nil
			}
			if a.Status.Backup.Phase == "Publishing" {
				a.Status.Backup.Phase = "Failed"
				a.Status.Backup.Error = "Publication cancelled by version change"
				condition(a, "BackupFailed", metav1.ConditionTrue, "PublicationCancelled", a.Status.Backup.Error)
			}
		}
		done, err := r.drain(ctx, a, false)
		if err != nil {
			return ctrl.Result{}, err
		}
		if !done {
			return ctrl.Result{RequeueAfter: 2 * time.Second}, nil
		}
		if a.Status.TargetVersion != desired(a) {
			remember(a, a.Status.Operation)
			a.Status.TargetVersion = desired(a)
			a.Status.Operation = nil
			a.Status.State = "Inspecting"
			condition(a, "Ready", metav1.ConditionFalse, "Preparing", "Preparing native state")
			return r.save(ctx, a)
		}
		if a.Status.Operation == nil {
			a.Status.Operation = newOperation(a, "inspect", desired(a), "")
			return r.save(ctx, a)
		}
		op := a.Status.Operation
		finished, result, err := r.observeJob(ctx, a, op)
		if err != nil {
			if permanentOperation(err) {
				return r.fail(ctx, a, err)
			}
			return ctrl.Result{}, err
		}
		if !finished {
			return r.save(ctx, a)
		}
		remember(a, op)
		switch op.Kind {
		case "inspect":
			if result.State != "Existing" && result.State != "Empty" && result.State != "Recovery" {
				return r.fail(ctx, a, fmt.Errorf("invalid inspection state %q", result.State))
			}
			if !validVersion(result.Version) || result.Version > desired(a) {
				return r.fail(ctx, a, fmt.Errorf("unsupported source version %q", result.Version))
			}
			if result.State == "Recovery" && (len(result.RepositoryID) != 64 || len(result.SnapshotID) != 64) {
				return r.fail(ctx, a, fmt.Errorf("recovery result lacks full repository and snapshot binding"))
			}
			a.Status.Operation = newOperation(a, "prepare", result.Version, result.State)
			a.Status.State = "Preparing"
		case "prepare":
			if result.State != "Prepared" || result.Version != op.Version {
				return r.fail(ctx, a, fmt.Errorf("invalid preparation result"))
			}
			if op.Version != desired(a) {
				a.Status.Operation = newOperation(a, "migrate", desired(a), "")
				a.Status.State = "Migrating"
			} else {
				a.Status.PreparedVersion = result.Version
				a.Status.Version = result.Version
				a.Status.State = "Starting"
			}
		case "migrate":
			if result.State != "Prepared" || result.Version != desired(a) {
				return r.fail(ctx, a, fmt.Errorf("invalid migration result"))
			}
			a.Status.PreparedVersion = result.Version
			a.Status.Version = result.Version
			a.Status.State = "Starting"
		default:
			return r.fail(ctx, a, fmt.Errorf("unexpected lifecycle operation %s", op.Kind))
		}
		return r.save(ctx, a)
	}
	if err := r.application(ctx, a, 1); err != nil {
		if permanentOperation(err) {
			return r.fail(ctx, a, err)
		}
		return ctrl.Result{}, err
	}
	pod, err := r.liveAppPod(ctx, a)
	if err != nil {
		if permanentOperation(err) {
			return r.fail(ctx, a, err)
		}
		return ctrl.Result{}, err
	}
	pendingCapture := a.Status.Backup.Phase == "Capturing" || a.Status.Backup.Phase == "Admitting"
	if pod == nil || containerID(pod) == "" {
		if pod != nil {
			if err := gateFailure(a, pod); err != nil {
				if pendingCapture {
					return r.backupFailure(ctx, a, err, true)
				}
				return r.fail(ctx, a, err)
			}
		}
		a.Status.State = "Starting"
		condition(a, "Ready", metav1.ConditionFalse, "Starting", "Waiting for application Pod and native gate")
		return r.save(ctx, a)
	}
	st, err := r.readStatus(ctx, a, pod)
	if err != nil { // Observation outage never changes established workload replicas.
		condition(a, "Ready", metav1.ConditionUnknown, "ObservationUnavailable", err.Error())
		return r.save(ctx, a)
	}
	ownCapture := pendingCapture && expectedCaptureTransition(st.Failure, a.Status.Backup.CaptureOperation, a.Status.Backup.Execution)
	if st.Failure != "" && !stickyNativeFailure(st.Failure) {
		condition(a, "Ready", metav1.ConditionUnknown, "ObservationUnavailable", st.Failure)
		return r.save(ctx, a)
	}
	if st.Failure != "" && !ownCapture {
		if pendingCapture {
			return r.backupFailure(ctx, a, fmt.Errorf("native capture failure: %s", st.Failure), true)
		}
		return r.fail(ctx, a, fmt.Errorf("native gate failure: %s", st.Failure))
	}
	deployment := &appsv1.Deployment{}
	if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: "paperless"}, deployment); err != nil {
		return ctrl.Result{}, err
	}
	a.Status.Replicas = deployment.Status.Replicas
	ready := st.Ready && podReady(pod) &&
		deployment.Status.ObservedGeneration >= deployment.Generation &&
		deployment.Status.UpdatedReplicas == 1 && deployment.Status.ReadyReplicas == 1
	if ready {
		a.Status.State = "Running"
		condition(a, "Ready", metav1.ConditionTrue, "NativeReady", "Native gate and HTTP readiness succeeded")
		condition(a, "Failed", metav1.ConditionFalse, "Healthy", "No lifecycle failure")
	} else {
		condition(a, "Ready", metav1.ConditionFalse, "NativeNotReady", "Waiting for native readiness")
	}
	if a.Status.Backup.Phase == "Capturing" || a.Status.Backup.Phase == "Admitting" || a.Status.Backup.Phase == "Captured" || a.Status.Backup.Phase == "Publishing" {
		return r.backup(ctx, a, pod, st)
	}
	if ready && a.Spec.Backup.Schedule != "" {
		if _, err := schedule(a); err != nil {
			condition(a, "Ready", metav1.ConditionFalse, "BackupConfigurationRefused", err.Error())
			return r.backupFailure(ctx, a, err, false)
		}
	}
	if ready {
		return r.backup(ctx, a, pod, st)
	}
	return r.save(ctx, a)
}
func newOperation(a *api.PaperlessApplication, kind, version, mode string) *api.Operation {
	id := uuid.NewString()
	return &api.Operation{ID: id, Kind: kind, Version: version, Mode: mode, Generation: a.Generation, JobName: "paperless-" + kind + "-" + id[:12], Phase: "Planned"}
}
func podReady(p *corev1.Pod) bool {
	for _, c := range p.Status.Conditions {
		if c.Type == corev1.PodReady {
			return c.Status == corev1.ConditionTrue
		}
	}
	return false
}
func (r *Reconciler) drain(ctx context.Context, a *api.PaperlessApplication, all bool) (bool, error) {
	// Scale only an existing deployment; never render a new image or create writers while stopping.
	d := &appsv1.Deployment{}
	err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: "paperless"}, d)
	acknowledged := true
	if err == nil {
		if !metav1.IsControlledBy(d, a) {
			return false, fmt.Errorf("foreign application deployment prevents confirmed drainage")
		}
		if d.Spec.Replicas == nil || *d.Spec.Replicas != 0 {
			d.Spec.Replicas = pointer(int32(0))
			if err := r.Update(ctx, d); err != nil {
				return false, err
			}
			acknowledged = false
		}
		if d.Status.ObservedGeneration < d.Generation || d.Status.Replicas != 0 {
			acknowledged = false
		}
	} else if !apierrors.IsNotFound(err) {
		return false, err
	}
	jobs := &batchv1.JobList{}
	if err := r.Reader.List(ctx, jobs, client.InNamespace(a.Namespace), client.MatchingLabels{"paperless.bartl.sh/uid": string(a.UID)}); err != nil {
		return false, err
	}
	for i := range jobs.Items {
		j := &jobs.Items[i]
		if !metav1.IsControlledBy(j, a) {
			return false, fmt.Errorf("foreign labeled Job %s", j.Name)
		}
		if all {
			if err := r.Delete(ctx, j, client.PropagationPolicy(metav1.DeletePropagationForeground)); client.IgnoreNotFound(err) != nil {
				return false, err
			}
			acknowledged = false
		}
	}
	pods := &corev1.PodList{}
	if err := r.Reader.List(ctx, pods, client.InNamespace(a.Namespace), client.MatchingLabels{"paperless.bartl.sh/uid": string(a.UID)}); err != nil {
		return false, err
	}
	for i := range pods.Items {
		p := &pods.Items[i]
		role := p.Labels["paperless.bartl.sh/role"]
		if role != "app" && role != "job" {
			continue
		}
		if role == "job" && !all {
			continue
		}
		if err := r.verifyDrainPod(ctx, a, p); err != nil {
			return false, err
		}
		if err := r.Delete(ctx, p); client.IgnoreNotFound(err) != nil {
			return false, err
		}
		acknowledged = false
	}
	rs := &appsv1.ReplicaSetList{}
	if err := r.Reader.List(ctx, rs, client.InNamespace(a.Namespace), client.MatchingLabels(labels(a, "app"))); err != nil {
		return false, err
	}
	for _, s := range rs.Items {
		if s.Spec.Replicas == nil || *s.Spec.Replicas != 0 || s.Status.Replicas != 0 || s.Status.ObservedGeneration < s.Generation {
			acknowledged = false
		}
	}
	return acknowledged, nil
}
func (r *Reconciler) stop(ctx context.Context, a *api.PaperlessApplication, deleting bool) (ctrl.Result, error) {
	ingress := &networkingv1.Ingress{}
	err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: "paperless"}, ingress)
	if err == nil {
		if !metav1.IsControlledBy(ingress, a) {
			return ctrl.Result{}, fmt.Errorf("foreign ingress prevents confirmed route withdrawal")
		}
		if err := r.Delete(ctx, ingress); client.IgnoreNotFound(err) != nil {
			return ctrl.Result{}, err
		}
	} else if !apierrors.IsNotFound(err) {
		return ctrl.Result{}, err
	}
	if op := a.Status.Operation; op != nil && op.Phase != "Succeeded" && op.Phase != "Interrupted" && op.Phase != "Failed" {
		op.Phase = "Interrupted"
		a.Status.Failure = "Lifecycle operation interrupted by stop; replace failed target before retry"
	}
	b := &a.Status.Backup
	if b.Phase == "Capturing" || b.Phase == "Admitting" {
		// Observe a durable completion before cancelling, without authorizing
		// resumption or publication under stopped intent.
		pod, observationErr := r.liveAppPod(ctx, a)
		if observationErr == nil && pod != nil && containerID(pod) != "" {
			if st, err := r.readStatus(ctx, a, pod); err == nil && completedCapture(a, st) {
				b.CapturedAt = st.Capture.CapturedAt
				b.Resumed = true
				b.Phase = "Captured"
			}
		}
	}
	if b.Phase == "Capturing" || b.Phase == "Admitting" {
		b.Phase = "Failed"
		b.Error = "Capture interrupted by stop"
		a.Status.Failure = "Capture interrupted; replace failed target before retry"
	}
	if b.Phase == "Publishing" {
		b.Phase = "Failed"
		b.Error = "Publication cancelled by stop"
	}
	if a.Status.Failure != "" {
		condition(a, "Failed", metav1.ConditionTrue, "InterruptedOrFailed", a.Status.Failure)
	}
	if b.Error != "" {
		condition(a, "BackupFailed", metav1.ConditionTrue, "CancelledOrFailed", b.Error)
	}
	done, err := r.drain(ctx, a, true)
	if err != nil {
		return ctrl.Result{}, err
	}
	condition(a, "Ready", metav1.ConditionFalse, "StopRequested", "Waiting for confirmed drainage")
	condition(a, "Stopped", metav1.ConditionFalse, "Draining", "App and finite work are being drained")
	if !done {
		return r.save(ctx, a)
	}
	a.Status.Replicas = 0
	if enabled(a) && a.Status.Failure == "" {
		// Serving-component zero is not whole-application stop. Dependencies
		// remain available, but no startup/capture work is admitted.
		if err := validate(a); err != nil {
			return r.fail(ctx, a, err)
		}
		if !controllerutil.ContainsFinalizer(a, finalizer) {
			controllerutil.AddFinalizer(a, finalizer)
			return ctrl.Result{Requeue: true}, r.Update(ctx, a)
		}
		if a.Status.Identity == nil {
			id, claims := a.Spec.Identity, a.Spec.Claims
			a.Status.Identity, a.Status.Claims = &id, &claims
			return r.save(ctx, a)
		}
		if err := r.acquire(ctx, a); err != nil {
			return ctrl.Result{}, err
		}
		if err := r.dependencies(ctx, a); err != nil {
			return ctrl.Result{}, err
		}
		a.Status.State = "ApplicationStopped"
		condition(a, "Stopped", metav1.ConditionFalse, "ApplicationOnlyStopped", "Application execution stopped; dedicated dependencies remain enabled")
		return r.save(ctx, a)
	}
	dependenciesStopped, err := r.stopDependencies(ctx, a)
	if err != nil {
		return ctrl.Result{}, err
	}
	if !dependenciesStopped {
		return r.save(ctx, a)
	}
	a.Status.State = "Stopped"
	condition(a, "Stopped", metav1.ConditionTrue, "DrainConfirmed", "All owned execution and dedicated dependencies have stopped")
	if !deleting {
		return r.save(ctx, a)
	}
	// Dependencies must also disappear before claim release permits a successor.
	for _, name := range []string{"paperless-db", "paperless-redis"} {
		d := &appsv1.Deployment{}
		err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: name}, d)
		if err == nil {
			if !metav1.IsControlledBy(d, a) {
				return ctrl.Result{}, fmt.Errorf("foreign dependency %s", name)
			}
			if err := r.Delete(ctx, d, client.PropagationPolicy(metav1.DeletePropagationForeground)); client.IgnoreNotFound(err) != nil {
				return ctrl.Result{}, err
			}
			return r.save(ctx, a)
		}
		if !apierrors.IsNotFound(err) {
			return ctrl.Result{}, err
		}
	}
	pods := &corev1.PodList{}
	if err := r.Reader.List(ctx, pods, client.InNamespace(a.Namespace), client.MatchingLabels{"paperless.bartl.sh/uid": string(a.UID)}); err != nil {
		return ctrl.Result{}, err
	}
	if len(pods.Items) != 0 {
		return r.save(ctx, a)
	}
	// Fixed-name dependents must be gone before a new CR can acquire these claims.
	// Otherwise asynchronous GC can make a valid successor look like a foreign owner.
	for _, obj := range []client.Object{
		&appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "paperless"}},
		&corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: "paperless"}},
		&corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: "paperless-db"}},
		&corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: "paperless-redis"}},
		&networkingv1.Ingress{ObjectMeta: metav1.ObjectMeta{Name: "paperless"}},
		&networkingv1.NetworkPolicy{ObjectMeta: metav1.ObjectMeta{Name: "paperless-app"}},
		&networkingv1.NetworkPolicy{ObjectMeta: metav1.ObjectMeta{Name: "paperless-db"}},
		&networkingv1.NetworkPolicy{ObjectMeta: metav1.ObjectMeta{Name: "paperless-redis"}},
		&networkingv1.NetworkPolicy{ObjectMeta: metav1.ObjectMeta{Name: "paperless-job"}},
	} {
		obj.SetNamespace(a.Namespace)
		if err := r.Reader.Get(ctx, client.ObjectKeyFromObject(obj), obj); err != nil {
			if apierrors.IsNotFound(err) {
				continue
			}
			return ctrl.Result{}, err
		}
		if !metav1.IsControlledBy(obj, a) {
			return ctrl.Result{}, fmt.Errorf("foreign resource %T %s prevents finalization", obj, obj.GetName())
		}
		if err := r.Delete(ctx, obj, client.PropagationPolicy(metav1.DeletePropagationForeground)); client.IgnoreNotFound(err) != nil {
			return ctrl.Result{}, err
		}
		return r.save(ctx, a)
	}
	claims := a.Spec.Claims
	if a.Status.Claims != nil {
		claims = *a.Status.Claims
	}
	for _, name := range claimNames(claims) {
		if name == "" {
			continue
		}
		p := &corev1.PersistentVolumeClaim{}
		err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: name}, p)
		if apierrors.IsNotFound(err) {
			continue
		}
		if err != nil {
			return ctrl.Result{}, err
		}
		if p.Annotations[ownerAnnotation] == string(a.UID) {
			delete(p.Annotations, ownerAnnotation)
			if err := r.Update(ctx, p); err != nil {
				return ctrl.Result{}, err
			}
		}
	}
	controllerutil.RemoveFinalizer(a, finalizer)
	return ctrl.Result{}, r.Update(ctx, a)
}

// Stop dependencies only after application and finite native writers are gone.
// Observe Deployments, ReplicaSets and Pods: requested replicas alone are not
// evidence that a database process (including a terminating Pod) has ended.
func (r *Reconciler) stopDependencies(ctx context.Context, a *api.PaperlessApplication) (bool, error) {
	done := true
	for _, role := range []string{"db", "redis"} {
		d := &appsv1.Deployment{}
		err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: "paperless-" + role}, d)
		if err == nil {
			if !metav1.IsControlledBy(d, a) {
				return false, fmt.Errorf("foreign dependency %s prevents confirmed stop", d.Name)
			}
			if d.Spec.Replicas == nil || *d.Spec.Replicas != 0 {
				d.Spec.Replicas = pointer(int32(0))
				if err := r.Update(ctx, d); err != nil {
					return false, err
				}
				done = false
			}
			if d.Status.ObservedGeneration < d.Generation || d.Status.Replicas != 0 {
				done = false
			}
		} else if !apierrors.IsNotFound(err) {
			return false, err
		}
		sets := &appsv1.ReplicaSetList{}
		if err := r.Reader.List(ctx, sets, client.InNamespace(a.Namespace), client.MatchingLabels(labels(a, role))); err != nil {
			return false, err
		}
		for i := range sets.Items {
			s := &sets.Items[i]
			if d.UID == "" || !metav1.IsControlledBy(s, d) {
				return false, fmt.Errorf("foreign dependency ReplicaSet %s", s.Name)
			}
			if s.Spec.Replicas == nil || *s.Spec.Replicas != 0 || s.Status.Replicas != 0 || s.Status.ObservedGeneration < s.Generation {
				done = false
			}
		}
		pods := &corev1.PodList{}
		if err := r.Reader.List(ctx, pods, client.InNamespace(a.Namespace), client.MatchingLabels(labels(a, role))); err != nil {
			return false, err
		}
		if len(pods.Items) != 0 {
			done = false
		}
	}
	return done, nil
}

func schedule(a *api.PaperlessApplication) (cron.Schedule, error) {
	zone := a.Spec.Backup.TimeZone
	if zone == "" {
		zone = "UTC"
	}
	if _, err := time.LoadLocation(zone); err != nil {
		return nil, fmt.Errorf("invalid backup timeZone: %w", err)
	}
	s, err := cron.ParseStandard("CRON_TZ=" + zone + " " + a.Spec.Backup.Schedule)
	if err != nil {
		return nil, fmt.Errorf("invalid backup schedule: %w", err)
	}
	return s, nil
}

// Preserve terminal Jobs for diagnostics, but never let an uncertain active
// execution survive failure isolation or start a competing transition.
func (r *Reconciler) cancelActiveJobs(ctx context.Context, a *api.PaperlessApplication) (bool, error) {
	jobs := &batchv1.JobList{}
	if err := r.Reader.List(ctx, jobs, client.InNamespace(a.Namespace), client.MatchingLabels{"paperless.bartl.sh/uid": string(a.UID)}); err != nil {
		return false, err
	}
	done := true
	for i := range jobs.Items {
		j := &jobs.Items[i]
		if !metav1.IsControlledBy(j, a) {
			return false, fmt.Errorf("foreign labeled Job %s", j.Name)
		}
		if !jobTerminal(j) || j.DeletionTimestamp != nil {
			if err := r.Delete(ctx, j, client.PropagationPolicy(metav1.DeletePropagationForeground)); client.IgnoreNotFound(err) != nil {
				return false, err
			}
			done = false
		}
	}
	pods := &corev1.PodList{}
	if err := r.Reader.List(ctx, pods, client.InNamespace(a.Namespace), client.MatchingLabels(labels(a, "job"))); err != nil {
		return false, err
	}
	for i := range pods.Items {
		p := &pods.Items[i]
		if p.Status.Phase != corev1.PodSucceeded && p.Status.Phase != corev1.PodFailed || p.DeletionTimestamp != nil {
			if err := r.verifyDrainPod(ctx, a, p); err != nil {
				return false, err
			}
			if err := r.Delete(ctx, p); client.IgnoreNotFound(err) != nil {
				return false, err
			}
			done = false
		}
	}
	return done, nil
}
func (r *Reconciler) verifyDrainPod(ctx context.Context, a *api.PaperlessApplication, p *corev1.Pod) error {
	if p.Labels["paperless.bartl.sh/role"] == "app" {
		return r.verifyPodOwner(ctx, a, p)
	}
	o := metav1.GetControllerOf(p)
	if o == nil || o.Kind != "Job" {
		return invalidOperation("foreign labeled Job Pod %s", p.Name)
	}
	j := &batchv1.Job{}
	if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: p.Namespace, Name: o.Name}, j); err != nil {
		return err
	}
	if j.UID != o.UID || !metav1.IsControlledBy(j, a) {
		return invalidOperation("foreign Job Pod %s", p.Name)
	}
	return nil
}
