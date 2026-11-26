// SPDX-License-Identifier: Apache-2.0
package v1alpha2

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

var GroupVersion = schema.GroupVersion{Group: "paperless.bartl.sh", Version: "v1alpha2"}
var SchemeBuilder = runtime.NewSchemeBuilder(func(s *runtime.Scheme) error {
	s.AddKnownTypes(GroupVersion, &PaperlessApplication{}, &PaperlessApplicationList{})
	metav1.AddToGroupVersion(s, GroupVersion)
	return nil
})
var AddToScheme = SchemeBuilder.AddToScheme

type Identity struct {
	Installation string `json:"installation"`
	Instance     string `json:"instance"`
}
type Images struct {
	Runtime330 string `json:"runtime330"`
	Runtime331 string `json:"runtime331"`
	Postgres   string `json:"postgres"`
	Redis      string `json:"redis"`
}
type Claims struct {
	Storage  string `json:"storage"`
	Database string `json:"database"`
	Broker   string `json:"broker"`
	Staging  string `json:"staging"`
}
type BackupSpec struct {
	Repository   string `json:"repository,omitempty"`
	ReaderSecret string `json:"readerSecret,omitempty"`
	WriterSecret string `json:"writerSecret,omitempty"`
	Schedule     string `json:"schedule,omitempty"`
	TimeZone     string `json:"timeZone,omitempty"`
	DrainSeconds int    `json:"drainSeconds,omitempty"`
}
type IngressSpec struct {
	Enabled   bool   `json:"enabled,omitempty"`
	Host      string `json:"host,omitempty"`
	ClassName string `json:"className,omitempty"`
	TLSSecret string `json:"tlsSecret,omitempty"`
}
type PaperlessApplicationSpec struct {
	Identity            Identity    `json:"identity"`
	Running             *bool       `json:"running,omitempty"`
	Replicas            *int32      `json:"replicas,omitempty"`
	Version             string      `json:"version,omitempty"`
	Images              Images      `json:"images"`
	Claims              Claims      `json:"claims"`
	ConfigurationSecret string      `json:"configurationSecret"`
	BootstrapSecret     string      `json:"bootstrapSecret,omitempty"`
	Backup              BackupSpec  `json:"backup,omitempty"`
	Ingress             IngressSpec `json:"ingress,omitempty"`
}

// Operation is persisted before Job creation; its deterministic name makes admission restart-safe.
type Operation struct {
	ID         string        `json:"id"`
	Kind       string        `json:"kind"`
	JobName    string        `json:"jobName"`
	JobUID     string        `json:"jobUID,omitempty"`
	Generation int64         `json:"generation"`
	Version    string        `json:"version"`
	Mode       string        `json:"mode,omitempty"`
	Phase      string        `json:"phase"`
	Result     *NativeResult `json:"result,omitempty"`
}
type NativeResult struct {
	ApplicationUID string `json:"applicationUID,omitempty"`
	Operation      string `json:"operation"`
	State          string `json:"state"`
	Version        string `json:"version,omitempty"`
	RepositoryID   string `json:"repositoryID,omitempty"`
	SnapshotID     string `json:"snapshotID,omitempty"`
	CapturedAt     string `json:"capturedAt,omitempty"`
	PublishedAt    string `json:"publishedAt,omitempty"`
}
type BackupStatus struct {
	LastManualRequest    string       `json:"lastManualRequest,omitempty"`
	Resumed              bool         `json:"resumed,omitempty"`
	WithdrawAfterCapture bool         `json:"withdrawAfterCapture,omitempty"`
	Withdrawn            bool         `json:"withdrawn,omitempty"`
	ResumptionError      string       `json:"resumptionError,omitempty"`
	Request              string       `json:"request,omitempty"`
	Phase                string       `json:"phase,omitempty"`
	CaptureOperation     string       `json:"captureOperation,omitempty"`
	AdmittedAt           string       `json:"admittedAt,omitempty"`
	PodName              string       `json:"podName,omitempty"`
	PodUID               string       `json:"podUID,omitempty"`
	ContainerID          string       `json:"containerID,omitempty"`
	Execution            string       `json:"execution,omitempty"`
	CapturedAt           string       `json:"capturedAt,omitempty"`
	PublishedAt          string       `json:"publishedAt,omitempty"`
	RepositoryID         string       `json:"repositoryID,omitempty"`
	SnapshotID           string       `json:"snapshotID,omitempty"`
	Error                string       `json:"error,omitempty"`
	Publication          *Operation   `json:"publication,omitempty"`
	LastScheduleTime     *metav1.Time `json:"lastScheduleTime,omitempty"`
	ScheduleBaseline     *metav1.Time `json:"scheduleBaseline,omitempty"`
}
type PaperlessApplicationStatus struct {
	Operations         []Operation        `json:"operations,omitempty"`
	ObservedGeneration int64              `json:"observedGeneration,omitempty"`
	Replicas           int32              `json:"replicas"`
	State              string             `json:"state,omitempty"`
	Failure            string             `json:"failure,omitempty"`
	Identity           *Identity          `json:"identity,omitempty"`
	Claims             *Claims            `json:"claims,omitempty"`
	Version            string             `json:"version,omitempty"`
	PreparedVersion    string             `json:"preparedVersion,omitempty"`
	TargetVersion      string             `json:"targetVersion,omitempty"`
	Operation          *Operation         `json:"operation,omitempty"`
	Backup             BackupStatus       `json:"backup,omitempty"`
	Conditions         []metav1.Condition `json:"conditions,omitempty"`
}
type PaperlessApplication struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`
	Spec              PaperlessApplicationSpec   `json:"spec"`
	Status            PaperlessApplicationStatus `json:"status,omitempty"`
}
type PaperlessApplicationList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []PaperlessApplication `json:"items"`
}

func (in *PaperlessApplication) DeepCopy() *PaperlessApplication {
	if in == nil {
		return nil
	}
	out := new(PaperlessApplication)
	*out = *in
	in.ObjectMeta.DeepCopyInto(&out.ObjectMeta)
	if in.Spec.Running != nil {
		v := *in.Spec.Running
		out.Spec.Running = &v
	}
	if in.Spec.Replicas != nil {
		v := *in.Spec.Replicas
		out.Spec.Replicas = &v
	}
	if in.Status.Identity != nil {
		v := *in.Status.Identity
		out.Status.Identity = &v
	}
	if in.Status.Claims != nil {
		v := *in.Status.Claims
		out.Status.Claims = &v
	}
	out.Status.Operation = copyOperation(in.Status.Operation)
	out.Status.Backup.Publication = copyOperation(in.Status.Backup.Publication)
	out.Status.Operations = make([]Operation, len(in.Status.Operations))
	for i := range in.Status.Operations {
		out.Status.Operations[i] = *copyOperation(&in.Status.Operations[i])
	}
	if in.Status.Backup.LastScheduleTime != nil {
		out.Status.Backup.LastScheduleTime = in.Status.Backup.LastScheduleTime.DeepCopy()
	}
	if in.Status.Backup.ScheduleBaseline != nil {
		out.Status.Backup.ScheduleBaseline = in.Status.Backup.ScheduleBaseline.DeepCopy()
	}
	out.Status.Conditions = append([]metav1.Condition(nil), in.Status.Conditions...)
	return out
}
func copyOperation(in *Operation) *Operation {
	if in == nil {
		return nil
	}
	v := *in
	if in.Result != nil {
		r := *in.Result
		v.Result = &r
	}
	return &v
}
func (in *PaperlessApplication) DeepCopyObject() runtime.Object { return in.DeepCopy() }
func (in *PaperlessApplicationList) DeepCopyObject() runtime.Object {
	if in == nil {
		return nil
	}
	out := new(PaperlessApplicationList)
	*out = *in
	in.ListMeta.DeepCopyInto(&out.ListMeta)
	out.Items = make([]PaperlessApplication, len(in.Items))
	for i := range in.Items {
		out.Items[i] = *in.Items[i].DeepCopy()
	}
	return out
}
