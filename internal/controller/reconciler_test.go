// SPDX-License-Identifier: Apache-2.0
package controller

import (
	"context"
	"encoding/json"
	"errors"
	api "github.com/floriankesslergmbh/bartl-paperless/api/v1alpha1"
	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"testing"
	"time"
)

func applicationFixture() *api.PaperlessApplication {
	return &api.PaperlessApplication{TypeMeta: metav1.TypeMeta{APIVersion: api.GroupVersion.String(), Kind: "PaperlessApplication"}, ObjectMeta: metav1.ObjectMeta{Name: "paperless", Namespace: "test", UID: "application-uid", Generation: 1}, Spec: api.PaperlessApplicationSpec{Identity: api.Identity{Installation: "installation", Instance: "instance"}, Replicas: pointer(int32(1)), Version: "3.3.1", Images: api.Images{Runtime330: "runtime:3.3.0", Runtime331: "runtime:3.3.1", Postgres: "postgres:17.6", Redis: "redis:7"}, Claims: api.Claims{Storage: "storage", Database: "database", Broker: "broker", Staging: "staging"}, ConfigurationSecret: "configuration", Backup: api.BackupSpec{Repository: "rest:https://backup.test/paperless", WriterSecret: "writer"}}}
}
func fixture(t *testing.T, objects ...client.Object) (*Reconciler, context.Context) {
	t.Helper()
	s := runtime.NewScheme()
	for _, add := range []func(*runtime.Scheme) error{api.AddToScheme, corev1.AddToScheme, appsv1.AddToScheme, batchv1.AddToScheme, networkingv1.AddToScheme} {
		if err := add(s); err != nil {
			t.Fatal(err)
		}
	}
	for _, obj := range objects {
		if obj.GetResourceVersion() == "" {
			obj.SetResourceVersion("1")
		}
	}
	c := fake.NewClientBuilder().WithScheme(s).WithStatusSubresource(&api.PaperlessApplication{}).WithObjects(objects...).Build()
	return &Reconciler{Client: c, Reader: c, Scheme: s, Namespace: "test"}, context.Background()
}
func owner(t *testing.T, r *Reconciler, a client.Object, b client.Object) {
	t.Helper()
	if err := controllerutil.SetControllerReference(a, b, r.Scheme); err != nil {
		t.Fatal(err)
	}
}
func TestPlannedJobAdmissionIsIdempotentAcrossReconcile(t *testing.T) {
	a := applicationFixture()
	r, ctx := fixture(t, a)
	op := newOperation(a, "inspect", "3.3.1", "")
	for range 2 {
		done, _, err := r.observeJob(ctx, a, op)
		if err != nil || done {
			t.Fatalf("unexpected observation done=%v error=%v", done, err)
		}
	}
	jobs := &batchv1.JobList{}
	if err := r.List(ctx, jobs); err != nil {
		t.Fatal(err)
	}
	if len(jobs.Items) != 1 || op.Phase != "Admitted" {
		t.Fatalf("duplicate or unbound admission: %#v", op)
	}
}
func TestAdmittedMissingJobNeverReplays(t *testing.T) {
	a := applicationFixture()
	r, ctx := fixture(t, a)
	op := newOperation(a, "prepare", "3.3.1", "Empty")
	op.Phase = "Admitted"
	_, _, err := r.observeJob(ctx, a, op)
	if !permanentOperation(err) {
		t.Fatalf("missing admitted Job must fail permanently: %v", err)
	}
	j := &batchv1.Job{}
	if err := r.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: op.JobName}, j); !apierrors.IsNotFound(err) {
		t.Fatalf("Job was replayed: %v", err)
	}
}
func TestForeignJobNameCannotBeAdopted(t *testing.T) {
	a := applicationFixture()
	op := newOperation(a, "inspect", "3.3.1", "")
	j := jobFor(a, op)
	j.UID = "foreign-job"
	r, ctx := fixture(t, a, j)
	_, _, err := r.observeJob(ctx, a, op)
	if !permanentOperation(err) {
		t.Fatalf("foreign Job was admitted: %v", err)
	}
}
func TestResultMustBindBothApplicationAndOperation(t *testing.T) {
	for _, tc := range []struct{ name, uid, operation string }{{"wrong application", "other", "current"}, {"wrong operation", "application-uid", "old"}} {
		t.Run(tc.name, func(t *testing.T) {
			a := applicationFixture()
			op := newOperation(a, "inspect", "3.3.1", "")
			op.ID = "current"
			op.Phase = "Admitted"
			j := jobFor(a, op)
			j.UID = "job-uid"
			j.Status.Conditions = []batchv1.JobCondition{{Type: batchv1.JobComplete, Status: corev1.ConditionTrue}}
			p := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "result", Namespace: a.Namespace, Labels: map[string]string{"batch.kubernetes.io/job-name": j.Name}}}
			data, _ := json.Marshal(api.NativeResult{ApplicationUID: tc.uid, Operation: tc.operation, State: "Existing", Version: "3.3.1"})
			p.Status.ContainerStatuses = []corev1.ContainerStatus{{Name: containerName, State: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{ExitCode: 0, Message: string(data)}}}}
			r, ctx := fixture(t, a)
			owner(t, r, a, j)
			owner(t, r, j, p)
			if err := r.Create(ctx, j); err != nil {
				t.Fatal(err)
			}
			if err := r.Create(ctx, p); err != nil {
				t.Fatal(err)
			}
			_, _, err := r.observeJob(ctx, a, op)
			if !permanentOperation(err) {
				t.Fatalf("unbound result accepted: %v", err)
			}
		})
	}
}
func TestStopPreemptsCompletedButUnobservedTransition(t *testing.T) {
	a := applicationFixture()
	a.Spec.Replicas = pointer(int32(0))
	a.Status.Operation = newOperation(a, "prepare", "3.3.1", "Empty")
	a.Status.Operation.Phase = "Admitted"
	r, ctx := fixture(t, a)
	j := jobFor(a, a.Status.Operation)
	j.UID = "job-uid"
	j.Status.Conditions = []batchv1.JobCondition{{Type: batchv1.JobComplete, Status: corev1.ConditionTrue}}
	owner(t, r, a, j)
	if err := r.Create(ctx, j); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Reconcile(ctx, ctrl.Request{NamespacedName: client.ObjectKeyFromObject(a)}); err != nil {
		t.Fatal(err)
	}
	fresh := &api.PaperlessApplication{}
	if err := r.Get(ctx, client.ObjectKeyFromObject(a), fresh); err != nil {
		t.Fatal(err)
	}
	if fresh.Status.Failure == "" || fresh.Status.Operation.Phase != "Interrupted" {
		t.Fatalf("stop completion overrode intent: %#v", fresh.Status)
	}
	d := &appsv1.Deployment{}
	if err := r.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: "paperless"}, d); !apierrors.IsNotFound(err) {
		t.Fatalf("ordinary app launched after stop: %v", err)
	}
}
func TestLifecycleDrainDoesNotCancelAdmittedPreparation(t *testing.T) {
	a := applicationFixture()
	r, ctx := fixture(t, a)
	op := newOperation(a, "prepare", "3.3.1", "Empty")
	j := jobFor(a, op)
	owner(t, r, a, j)
	if err := r.Create(ctx, j); err != nil {
		t.Fatal(err)
	}
	done, err := r.drain(ctx, a, false)
	if err != nil || !done {
		t.Fatalf("app-only drain failed: %v", err)
	}
	if err := r.Get(ctx, client.ObjectKeyFromObject(j), &batchv1.Job{}); err != nil {
		t.Fatalf("active preparation was cancelled: %v", err)
	}
}
func TestStopWaitsForTerminatingPods(t *testing.T) {
	a := applicationFixture()
	now := metav1.Now()
	p := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "terminating", Namespace: a.Namespace, Labels: labels(a, "app"), Finalizers: []string{"test/hold"}, DeletionTimestamp: &now}}
	d := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "paperless", Namespace: a.Namespace, UID: "dep"}, Spec: appsv1.DeploymentSpec{Replicas: pointer(int32(0))}}
	rs := &appsv1.ReplicaSet{ObjectMeta: metav1.ObjectMeta{Name: "rs", Namespace: a.Namespace, UID: "rs"}, Spec: appsv1.ReplicaSetSpec{Replicas: pointer(int32(0))}}
	r, ctx := fixture(t, a)
	owner(t, r, a, d)
	owner(t, r, d, rs)
	owner(t, r, rs, p)
	for _, obj := range []client.Object{d, rs, p} {
		if err := r.Create(ctx, obj); err != nil {
			t.Fatal(err)
		}
	}
	done, err := r.drain(ctx, a, true)
	if err != nil {
		t.Fatal(err)
	}
	if done {
		t.Fatal("terminating Pod was reported as stopped")
	}
}
func TestFailureSurvivesRunIntentAndCannotLaunchNewWork(t *testing.T) {
	a := applicationFixture()
	a.Status.Failure = "interrupted import"
	r, ctx := fixture(t, a)
	if _, err := r.Reconcile(ctx, ctrl.Request{NamespacedName: client.ObjectKeyFromObject(a)}); err != nil {
		t.Fatal(err)
	}
	jobs := &batchv1.JobList{}
	if err := r.List(ctx, jobs); err != nil {
		t.Fatal(err)
	}
	if len(jobs.Items) != 0 {
		t.Fatal("sticky failure launched a new Job")
	}
}
func TestContainerRestartWithinSamePodInvalidatesCapture(t *testing.T) {
	a := applicationFixture()
	a.Status.Backup = api.BackupStatus{Phase: "Capturing", CaptureOperation: "capture", PodName: "app", PodUID: "pod-uid", ContainerID: "container-old", Execution: "old-execution"}
	p := capturePod(a)
	r, ctx := fixture(t, a, p)
	_, err := r.backup(ctx, a, p, &NativeStatus{Execution: "new-execution"})
	if err != nil {
		t.Fatal(err)
	}
	if a.Status.Failure == "" || a.Status.Backup.Phase != "Failed" {
		t.Fatal("same Pod UID incorrectly authorized another container execution")
	}
}
func capturePod(a *api.PaperlessApplication) *corev1.Pod {
	return &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "app", Namespace: a.Namespace, UID: "pod-uid", Labels: labels(a, "app")}, Status: corev1.PodStatus{Conditions: []corev1.PodCondition{{Type: corev1.PodReady, Status: corev1.ConditionTrue}}, ContainerStatuses: []corev1.ContainerStatus{{Name: containerName, ContainerID: "container-current", State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}}}}}}
}

type lostResponseExecutor struct {
	Status NativeStatus
	Begins int
}

func (e *lostResponseExecutor) Exec(_ context.Context, _ *corev1.Pod, command []string) ([]byte, error) {
	if command[len(command)-1] == "status" {
		return json.Marshal(e.Status)
	}
	for _, arg := range command {
		if arg == "begin-capture" {
			e.Begins++
			return nil, errors.New("connection lost after admission")
		}
	}
	return nil, errors.New("unexpected command")
}
func captureFixture(t *testing.T) (*Reconciler, context.Context, *api.PaperlessApplication, *corev1.Pod) {
	a := applicationFixture()
	p := capturePod(a)
	a.Status.Backup = api.BackupStatus{Phase: "Admitting", CaptureOperation: "capture", PodName: p.Name, PodUID: string(p.UID), ContainerID: containerID(p), Execution: "execution"}
	a.Status.Backup.AdmittedAt = time.Now().UTC().Format(time.RFC3339Nano)
	r, ctx := fixture(t, a)
	d := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "paperless", Namespace: a.Namespace, UID: "deployment-uid"}}
	rs := &appsv1.ReplicaSet{ObjectMeta: metav1.ObjectMeta{Name: "app-rs", Namespace: a.Namespace, UID: "rs-uid"}}
	owner(t, r, a, d)
	owner(t, r, d, rs)
	owner(t, r, rs, p)
	for _, obj := range []client.Object{d, rs, p} {
		if err := r.Create(ctx, obj); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range claimNames(a.Spec.Claims) {
		if err := r.Create(ctx, &corev1.PersistentVolumeClaim{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: a.Namespace, Annotations: map[string]string{ownerAnnotation: string(a.UID)}}}); err != nil {
			t.Fatal(err)
		}
	}
	return r, ctx, a, p
}
func TestLostCaptureResponsePollsSameAdmittedOperation(t *testing.T) {
	r, ctx, a, p := captureFixture(t)
	e := &lostResponseExecutor{Status: NativeStatus{Execution: "execution", Ready: true}}
	r.Executor = e
	if _, err := r.backup(ctx, a, p, &e.Status); err != nil {
		t.Fatal(err)
	}
	if e.Begins != 1 || a.Status.Backup.Phase != "Admitting" {
		t.Fatal("uncertain admission was incorrectly treated as termination")
	}
	e.Status.Capture = &CaptureObservation{Operation: "capture", Execution: "execution", State: "Capturing"}
	if _, err := r.backup(ctx, a, p, &e.Status); err != nil {
		t.Fatal(err)
	}
	if e.Begins != 1 || a.Status.Backup.Phase != "Capturing" {
		t.Fatal("admitted native capture was duplicated")
	}
}
func TestPublicationFailureDoesNotFailApplication(t *testing.T) {
	a := applicationFixture()
	op := newOperation(a, "publish", "3.3.1", "")
	op.Phase = "Admitted"
	a.Status.Backup = api.BackupStatus{Phase: "Publishing", CaptureOperation: "capture", CapturedAt: "2026-11-03T00:00:00Z", Publication: op}
	r, ctx := fixture(t, a)
	p := capturePod(a)
	if _, err := r.backup(ctx, a, p, &NativeStatus{Execution: "execution", Ready: true}); err != nil {
		t.Fatal(err)
	}
	if a.Status.Failure != "" || a.Status.Backup.Phase != "Failed" || a.Status.Backup.CaptureOperation != "capture" {
		t.Fatalf("publication failure affected app or lost capture: %#v", a.Status)
	}
}
func TestNewRequestRetriesProtectedPublicationWithoutRecapture(t *testing.T) {
	a := applicationFixture()
	a.Annotations = map[string]string{"paperless.bartl.sh/backup-request": "retry"}
	a.Status.Backup = api.BackupStatus{Request: "old", LastManualRequest: "old", Phase: "Failed", CaptureOperation: "protected", CapturedAt: "2026-11-03T00:00:00Z"}
	r, ctx := fixture(t, a)
	p := capturePod(a)
	if _, err := r.backup(ctx, a, p, &NativeStatus{Execution: "execution", Ready: true}); err != nil {
		t.Fatal(err)
	}
	if a.Status.Backup.Phase != "Captured" || a.Status.Backup.CaptureOperation != "protected" {
		t.Fatal("publication retry recaptured or replaced the protected export")
	}
}
func TestScheduleDoesNotReconsumeManualRequest(t *testing.T) {
	a := applicationFixture()
	a.Annotations = map[string]string{"paperless.bartl.sh/backup-request": "manual"}
	a.Status.Backup = api.BackupStatus{Request: "schedule:old", LastManualRequest: "manual", Phase: "Published"}
	r, ctx := fixture(t, a)
	if _, err := r.backup(ctx, a, capturePod(a), &NativeStatus{Execution: "execution", Ready: true}); err != nil {
		t.Fatal(err)
	}
	if a.Status.Backup.Phase != "Published" {
		t.Fatal("previous manual request admitted a second time")
	}
}
func TestClaimCollisionDoesNotAcquireOtherClaims(t *testing.T) {
	a := applicationFixture()
	objects := []client.Object{a}
	for _, n := range claimNames(a.Spec.Claims) {
		p := &corev1.PersistentVolumeClaim{ObjectMeta: metav1.ObjectMeta{Name: n, Namespace: a.Namespace}}
		if n == a.Spec.Claims.Staging {
			p.Annotations = map[string]string{ownerAnnotation: "competitor"}
		}
		objects = append(objects, p)
	}
	r, ctx := fixture(t, objects...)
	if err := r.acquire(ctx, a); !permanentOperation(err) {
		t.Fatalf("collision not permanent: %v", err)
	}
	p := &corev1.PersistentVolumeClaim{}
	if err := r.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: a.Spec.Claims.Storage}, p); err != nil {
		t.Fatal(err)
	}
	if p.Annotations[ownerAnnotation] != "" {
		t.Fatal("partially acquired claims despite known competitor")
	}
}
func TestJobAndAppCredentialAndEntrypointBoundary(t *testing.T) {
	a := applicationFixture()
	a.Spec.Backup.ReaderSecret = "reader"
	p := appPod(a, "3.3.1", "")
	if len(p.Containers[0].Command) != 0 || p.EnableServiceLinks == nil || *p.EnableServiceLinks {
		t.Fatal("ordinary app lost /init or allowed Service env collision")
	}
	for _, v := range p.Volumes {
		if v.Secret != nil {
			t.Fatal("ordinary app mounted backup credentials")
		}
	}
	j := jobFor(a, newOperation(a, "inspect", "3.3.1", ""))
	found := false
	for _, v := range j.Spec.Template.Spec.Volumes {
		if v.Secret != nil {
			found = true
			if v.Secret.Optional == nil || !*v.Secret.Optional {
				t.Fatal("missing recovery secret blocks existing-state startup")
			}
		}
	}
	if !found {
		t.Fatal("inspection cannot access recovery credentials")
	}
	prepare := jobFor(a, newOperation(a, "prepare", "3.3.1", "Existing"))
	for _, v := range prepare.Spec.Template.Spec.Volumes {
		if v.Secret != nil {
			t.Fatal("existing preparation mounted recovery credentials")
		}
	}
}
func TestScheduleUsesRealTimezoneAndRejectsInvalidInput(t *testing.T) {
	a := applicationFixture()
	a.Spec.Backup.Schedule = "0 2 * * *"
	a.Spec.Backup.TimeZone = "Europe/Berlin"
	s, err := schedule(a)
	if err != nil {
		t.Fatal(err)
	}
	next := s.Next(time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	zone, err := time.LoadLocation("Europe/Berlin")
	if err != nil {
		t.Fatal(err)
	}
	if next.In(zone).Hour() != 2 || next.UTC().Hour() != 1 {
		t.Fatalf("unexpected zone schedule %v", next)
	}
	a.Spec.Backup.TimeZone = "Not/AZone"
	if _, err := schedule(a); err == nil {
		t.Fatal("unknown timezone was accepted")
	}
}
func TestReplacedAdmittedJobCannotSupplyCompletion(t *testing.T) {
	a := applicationFixture()
	op := newOperation(a, "inspect", "3.3.1", "")
	op.JobUID = "original"
	op.Phase = "Admitted"
	j := jobFor(a, op)
	j.UID = types.UID("replacement")
	r, ctx := fixture(t, a)
	owner(t, r, a, j)
	if err := r.Create(ctx, j); err != nil {
		t.Fatal(err)
	}
	_, _, err := r.observeJob(ctx, a, op)
	if !permanentOperation(err) {
		t.Fatalf("replacement Job admitted: %v", err)
	}
}
func TestGateDiagnosticsDistinguishObservationFromDurableFailure(t *testing.T) {
	a := applicationFixture()
	p := capturePod(a)
	if stickyNativeFailure(`{"sticky":false,"error":"API unavailable"}`) {
		t.Fatal("transient observation classified as durable failure")
	}
	if !stickyNativeFailure(`{"operation":"capture","state":"Capturing"}`) {
		t.Fatal("pending transition did not remain sticky")
	}
	p.Status.ContainerStatuses[0].State = corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"}}
	p.Status.ContainerStatuses[0].LastTerminationState = corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{Message: `{"state":"Failed","sticky":false,"error":"API unavailable","applicationUID":"application-uid"}`}}
	if err := gateFailure(a, p); err != nil {
		t.Fatalf("observation outage stopped restart: %v", err)
	}
	p.Status.ContainerStatuses[0].LastTerminationState.Terminated.Message = `{"state":"Failed","sticky":true,"error":"interrupted import","applicationUID":"application-uid"}`
	if err := gateFailure(a, p); err == nil {
		t.Fatal("durable gate failure invisible in terminated container")
	}
}
func TestCapturedResultWaitsForSameExecutionResumption(t *testing.T) {
	r, ctx, a, p := captureFixture(t)
	a.Status.Backup.Phase = "Capturing"
	st := &NativeStatus{Execution: "execution", Capture: &CaptureObservation{Operation: "capture", Execution: "execution", State: "Captured", CapturedAt: "2026-11-03T00:00:00Z", Path: "/staging/captures/capture"}}
	if _, err := r.backup(ctx, a, p, st); err != nil {
		t.Fatal(err)
	}
	if a.Status.Backup.Phase != "Capturing" || a.Status.Backup.Resumed {
		t.Fatal("capture was published before resumption outcome")
	}
	st.Capture.Resumed = true
	if _, err := r.backup(ctx, a, p, st); err != nil {
		t.Fatal(err)
	}
	if a.Status.Backup.Phase != "Captured" || !a.Status.Backup.Resumed {
		t.Fatal("successful same-execution resumption was not reported")
	}
}
func TestPublicationCannotReadApplicationSecretsOrStorage(t *testing.T) {
	a := applicationFixture()
	a.Status.Backup.CaptureOperation = "capture"
	j := jobFor(a, newOperation(a, "publish", "3.3.1", ""))
	p := j.Spec.Template.Spec
	if len(p.InitContainers) != 0 || len(p.Containers[0].EnvFrom) != 0 {
		t.Fatal("publication received native configuration or mutating initialization")
	}
	for _, v := range p.Volumes {
		if v.PersistentVolumeClaim != nil && (v.PersistentVolumeClaim.ClaimName != a.Spec.Claims.Staging || !v.PersistentVolumeClaim.ReadOnly) {
			t.Fatal("publication can access application state")
		}
		if v.Secret != nil && v.Secret.SecretName != a.Spec.Backup.WriterSecret {
			t.Fatal("publication received wrong credentials")
		}
	}
	for _, m := range p.Containers[0].VolumeMounts {
		if !m.ReadOnly {
			t.Fatal("publication mounted writable state")
		}
	}
}
func TestCaptureCompletionAndMarkerRemovalAreNotAtomic(t *testing.T) {
	marker := `{"operation":"capture","execution":"execution","state":"Capturing"}`
	if !expectedCaptureTransition(marker, "capture", "execution") {
		t.Fatal("same operation marker was treated as failed during completion write boundary")
	}
	if expectedCaptureTransition(marker, "other", "execution") || expectedCaptureTransition(marker, "capture", "another") {
		t.Fatal("foreign operation or execution marker accepted")
	}
	if expectedCaptureTransition(`{"operation":"capture","execution":"execution","state":"Failed"}`, "capture", "execution") {
		t.Fatal("failed transition treated as expected capture progress")
	}
}
func TestCaptureAdmissionMarkerMayPrecedeCaptureObservation(t *testing.T) {
	r, ctx, a, p := captureFixture(t)
	st := &NativeStatus{Execution: "execution", Failure: `{"operation":"capture","execution":"execution","state":"Capturing"}`}
	if _, err := r.backup(ctx, a, p, st); err != nil {
		t.Fatal(err)
	}
	if a.Status.Failure != "" || a.Status.Backup.Phase != "Admitting" {
		t.Fatal("valid partial admission observation caused failure or duplicate launch")
	}
}

func TestFailedTargetReportsCurrentRunIntentWithoutReplaying(t *testing.T) {
	a := applicationFixture()
	a.Generation = 3
	a.Status.State = "Stopped"
	a.Status.Failure = "interrupted import"
	a.Status.Conditions = []metav1.Condition{
		{Type: "Failed", Status: metav1.ConditionTrue, ObservedGeneration: 2},
		{Type: "Ready", Status: metav1.ConditionFalse, ObservedGeneration: 2},
	}
	r, ctx := fixture(t, a)
	if _, err := r.Reconcile(ctx, ctrl.Request{NamespacedName: client.ObjectKeyFromObject(a)}); err != nil {
		t.Fatal(err)
	}
	actual := &api.PaperlessApplication{}
	if err := r.Get(ctx, client.ObjectKeyFromObject(a), actual); err != nil {
		t.Fatal(err)
	}
	if actual.Status.State != "Failed" || actual.Status.Failure == "" {
		t.Fatal("running intent obscured the durable failure")
	}
	for _, condition := range actual.Status.Conditions {
		if (condition.Type == "Ready" || condition.Type == "Failed") && condition.ObservedGeneration != actual.Generation {
			t.Fatalf("condition does not describe current intent: %#v", condition)
		}
	}
	jobs := &batchv1.JobList{}
	if err := r.List(ctx, jobs); err != nil {
		t.Fatal(err)
	}
	if len(jobs.Items) != 0 {
		t.Fatal("failed native transition was replayed")
	}
}

func TestLostCaptureCompletionExpiresWithoutClaimingStopped(t *testing.T) {
	r, ctx, a, p := captureFixture(t)
	a.Status.Backup.AdmittedAt = "2000-01-01T00:00:00Z"
	st := &NativeStatus{Execution: "execution", Capture: &CaptureObservation{
		Operation: "capture", Execution: "execution", State: "Capturing",
	}}
	if _, err := r.backup(ctx, a, p, st); err != nil {
		t.Fatal(err)
	}
	if a.Status.Failure == "" || a.Status.Backup.Phase != "Failed" {
		t.Fatal("lost native completion remained pending indefinitely")
	}
	for _, condition := range a.Status.Conditions {
		if condition.Type == "Stopped" && condition.Status == metav1.ConditionTrue {
			t.Fatal("timeout was incorrectly treated as proof of native termination")
		}
	}
}

func TestCompletedCaptureSurvivesLongControllerOutage(t *testing.T) {
	r, ctx, a, p := captureFixture(t)
	a.Status.Backup.AdmittedAt = "2000-01-01T00:00:00Z"
	st := &NativeStatus{Execution: "execution", Ready: true, Capture: &CaptureObservation{
		Operation: "capture", Execution: "execution", State: "Captured",
		CapturedAt: "2000-01-01T00:01:00Z", Path: "/staging/captures/capture", Resumed: true,
	}}
	if _, err := r.backup(ctx, a, p, st); err != nil {
		t.Fatal(err)
	}
	if a.Status.Failure != "" || a.Status.Backup.Phase != "Captured" {
		t.Fatal("unambiguous native completion was lost solely because observation was unavailable")
	}
}

func TestDurableCaptureCompletionSurvivesContainerReplacement(t *testing.T) {
	r, ctx, a, p := captureFixture(t)
	a.Status.Backup.Phase = "Capturing"
	p.UID = "replacement-pod"
	p.Status.ContainerStatuses[0].ContainerID = "replacement-container"
	st := &NativeStatus{Execution: "replacement-execution", Ready: true, Capture: &CaptureObservation{
		Operation: "capture", Execution: "execution", State: "Captured",
		CapturedAt: "2026-11-03T00:00:00Z", Path: "/staging/captures/capture", Resumed: true,
	}}
	if _, err := r.backup(ctx, a, p, st); err != nil {
		t.Fatal(err)
	}
	if a.Status.Failure != "" || a.Status.Backup.Phase != "Captured" ||
		a.Status.Backup.Execution != "execution" {
		t.Fatal("completed original capture was lost or rebound to the replacement execution")
	}
}

func TestFinalizationWaitsForFixedResourcesBeforeReleasingClaims(t *testing.T) {
	a := applicationFixture()
	now := metav1.Now()
	a.DeletionTimestamp = &now
	a.Finalizers = []string{finalizer}
	claim := &corev1.PersistentVolumeClaim{ObjectMeta: metav1.ObjectMeta{
		Name: a.Spec.Claims.Storage, Namespace: a.Namespace,
		Annotations: map[string]string{ownerAnnotation: string(a.UID)},
	}}
	r, ctx := fixture(t, a, claim)
	service := &corev1.Service{ObjectMeta: metav1.ObjectMeta{
		Name: "paperless-db", Namespace: a.Namespace, Finalizers: []string{"test/hold"},
	}}
	owner(t, r, a, service)
	if err := r.Create(ctx, service); err != nil {
		t.Fatal(err)
	}
	if _, err := r.stop(ctx, a, true); err != nil {
		t.Fatal(err)
	}
	if err := r.Get(ctx, client.ObjectKeyFromObject(claim), claim); err != nil {
		t.Fatal(err)
	}
	if claim.Annotations[ownerAnnotation] != string(a.UID) {
		t.Fatal("claim released while a fixed-name resource still blocks successor admission")
	}
	if err := r.Get(ctx, client.ObjectKeyFromObject(a), a); err != nil {
		t.Fatal("application finalized before resource cleanup:", err)
	}
	if err := r.Get(ctx, client.ObjectKeyFromObject(service), service); err != nil {
		t.Fatal(err)
	}
	if service.DeletionTimestamp == nil {
		t.Fatal("finalization did not start fixed-resource deletion")
	}
	service.Finalizers = nil
	if err := r.Update(ctx, service); err != nil {
		t.Fatal(err)
	}
	if _, err := r.stop(ctx, a, true); err != nil {
		t.Fatal(err)
	}
	if err := r.Get(ctx, client.ObjectKeyFromObject(claim), claim); err != nil {
		t.Fatal(err)
	}
	if claim.Annotations[ownerAnnotation] != "" {
		t.Fatal("claim remained bound after complete finalization")
	}
}
