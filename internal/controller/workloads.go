// SPDX-License-Identifier: Apache-2.0
package controller

import (
	"context"
	"fmt"
	api "github.com/floriankesslergmbh/bartl-paperless/api/v1alpha2"
	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"
	"net/url"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"slices"
	"strconv"
)

const ownerAnnotation = "paperless.bartl.sh/owner"
const finalizer = "paperless.bartl.sh/drain"
const containerName = "paperless"

func pointer[T any](v T) *T { return &v }
func labels(a *api.PaperlessApplication, role string) map[string]string {
	return map[string]string{"app.kubernetes.io/name": "paperless", "paperless.bartl.sh/uid": string(a.UID), "paperless.bartl.sh/role": role}
}
func image(a *api.PaperlessApplication, v string) string {
	if v == "3.3.0" {
		return a.Spec.Images.Runtime330
	}
	return a.Spec.Images.Runtime331
}
func desired(a *api.PaperlessApplication) string {
	if a.Spec.Version == "" {
		return "3.3.1"
	}
	return a.Spec.Version
}
func enabled(a *api.PaperlessApplication) bool {
	return a.DeletionTimestamp.IsZero() && (a.Spec.Running == nil || *a.Spec.Running)
}
func running(a *api.PaperlessApplication) bool {
	return enabled(a) && (a.Spec.Replicas == nil || *a.Spec.Replicas == 1)
}
func env(name, value string) corev1.EnvVar { return corev1.EnvVar{Name: name, Value: value} }
func fieldEnv(name, path string) corev1.EnvVar {
	return corev1.EnvVar{Name: name, ValueFrom: &corev1.EnvVarSource{FieldRef: &corev1.ObjectFieldSelector{FieldPath: path}}}
}
func commonEnv(a *api.PaperlessApplication, version, operation string) []corev1.EnvVar {
	drain := a.Spec.Backup.DrainSeconds
	if drain == 0 {
		drain = 300
	}
	return []corev1.EnvVar{fieldEnv("BARTL_NAMESPACE", "metadata.namespace"), fieldEnv("BARTL_POD_UID", "metadata.uid"), fieldEnv("BARTL_POD_NAME", "metadata.name"), env("BARTL_NAME", a.Name), env("BARTL_UID", string(a.UID)), env("BARTL_INSTALLATION", a.Spec.Identity.Installation), env("BARTL_INSTANCE", a.Spec.Identity.Instance), env("BARTL_VERSION", version), env("BARTL_OPERATION", operation), env("BARTL_REPOSITORY", a.Spec.Backup.Repository), env("BARTL_DRAIN_SECONDS", strconv.Itoa(drain)), env("PAPERLESS_DBHOST", "paperless-db"), env("PAPERLESS_DBNAME", "paperless"), env("PAPERLESS_DBUSER", "paperless"), env("PAPERLESS_REDIS", "redis://paperless-redis:6379"), env("PAPERLESS_TASK_WORKERS", "1"), env("PAPERLESS_THREADS_PER_WORKER", "1")}
}
func nativeCommand(command string) []string {
	return []string{"uv", "run", "--no-project", "python", "/opt/bartl/native.py", command}
}
func (r *Reconciler) owned(ctx context.Context, a *api.PaperlessApplication, obj client.Object, mutate func() error) error {
	obj.SetNamespace(a.Namespace)
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, obj, func() error {
		if obj.GetResourceVersion() != "" && !metav1.IsControlledBy(obj, a) {
			return invalidOperation("refusing foreign %T %s", obj, obj.GetName())
		}
		if err := ctrl.SetControllerReference(a, obj, r.Scheme); err != nil {
			return err
		}
		return mutate()
	})
	return err
}
func appPod(a *api.PaperlessApplication, version, operation string) corev1.PodSpec {
	mounts := []corev1.VolumeMount{{Name: "storage", MountPath: "/state"}, {Name: "storage", MountPath: "/usr/src/paperless/data", SubPath: "data"}, {Name: "storage", MountPath: "/usr/src/paperless/media", SubPath: "media"}, {Name: "storage", MountPath: "/usr/src/paperless/consume", SubPath: "consume"}, {Name: "staging", MountPath: "/staging"}, {Name: "client-ca", MountPath: "/configuration", ReadOnly: true}}
	return corev1.PodSpec{
		EnableServiceLinks:            pointer(false),
		ServiceAccountName:            "paperless-native",
		TerminationGracePeriodSeconds: pointer(int64(60)),
		SecurityContext:               &corev1.PodSecurityContext{RunAsUser: pointer(int64(0))},
		Volumes: []corev1.Volume{
			{Name: "storage", VolumeSource: corev1.VolumeSource{PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: a.Spec.Claims.Storage}}},
			{Name: "staging", VolumeSource: corev1.VolumeSource{PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: a.Spec.Claims.Staging}}},
			{Name: "client-ca", VolumeSource: corev1.VolumeSource{Secret: &corev1.SecretVolumeSource{SecretName: a.Spec.ConfigurationSecret + "-client-ca", Optional: pointer(true)}}},
		},
		InitContainers: []corev1.Container{{
			Name: "directories", Image: image(a, version),
			Command:         []string{"/bin/sh", "-ec", "mkdir -p /state/data /state/media /state/consume; chown 1000:1000 /state/data /state/media /state/consume; chown 0:0 /staging; chmod 0700 /staging"},
			SecurityContext: &corev1.SecurityContext{RunAsUser: pointer(int64(0))},
			VolumeMounts:    []corev1.VolumeMount{{Name: "storage", MountPath: "/state"}, {Name: "staging", MountPath: "/staging"}},
		}},
		Containers: []corev1.Container{{
			Name: containerName, Image: image(a, version),
			Env:            commonEnv(a, version, operation),
			EnvFrom:        []corev1.EnvFromSource{{SecretRef: &corev1.SecretEnvSource{LocalObjectReference: corev1.LocalObjectReference{Name: a.Spec.ConfigurationSecret}}}},
			VolumeMounts:   mounts,
			Ports:          []corev1.ContainerPort{{Name: "http", ContainerPort: 8000}},
			ReadinessProbe: &corev1.Probe{ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{Path: "/", Port: intstr.FromInt32(8000)}}, PeriodSeconds: 5, TimeoutSeconds: 3},
		}},
	}
}
func (r *Reconciler) dependencies(ctx context.Context, a *api.PaperlessApplication) error {
	sa := &corev1.ServiceAccount{ObjectMeta: metav1.ObjectMeta{Name: "paperless-native"}}
	// Helm supplies the read-only Role; retain an existing Helm-owned account.
	if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: sa.Name}, sa); err != nil {
		return fmt.Errorf("native service account: %w", err)
	}
	for _, role := range []string{"db", "redis"} {
		name := "paperless-" + role
		d := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: name}}
		err := r.owned(ctx, a, d, func() error {
			d.Labels = labels(a, role)
			d.Spec.Replicas = pointer(int32(1))
			d.Spec.Strategy = appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType}
			d.Spec.Selector = &metav1.LabelSelector{MatchLabels: labels(a, role)}
			d.Spec.Template.ObjectMeta.Labels = labels(a, role)
			claim := a.Spec.Claims.Database
			im := a.Spec.Images.Postgres
			port := int32(5432)
			path := "/var/lib/postgresql/data"
			c := corev1.Container{Name: role, Image: im, Env: []corev1.EnvVar{env("POSTGRES_DB", "paperless"), env("POSTGRES_USER", "paperless"), {Name: "POSTGRES_PASSWORD", ValueFrom: &corev1.EnvVarSource{SecretKeyRef: &corev1.SecretKeySelector{LocalObjectReference: corev1.LocalObjectReference{Name: a.Spec.ConfigurationSecret}, Key: "PAPERLESS_DBPASS"}}}, env("PGDATA", "/var/lib/postgresql/data/pgdata")}, ReadinessProbe: &corev1.Probe{ProbeHandler: corev1.ProbeHandler{Exec: &corev1.ExecAction{Command: []string{"pg_isready", "-U", "paperless", "-d", "paperless"}}}, PeriodSeconds: 5}}
			if role == "redis" {
				claim = a.Spec.Claims.Broker
				port = 6379
				path = "/data"
				c = corev1.Container{Name: role, Image: a.Spec.Images.Redis, Args: []string{"redis-server", "--appendonly", "yes", "--appendfsync", "everysec"}, ReadinessProbe: &corev1.Probe{ProbeHandler: corev1.ProbeHandler{Exec: &corev1.ExecAction{Command: []string{"redis-cli", "ping"}}}, PeriodSeconds: 5}}
			}
			c.Ports = []corev1.ContainerPort{{ContainerPort: port}}
			c.VolumeMounts = []corev1.VolumeMount{{Name: "data", MountPath: path}}
			d.Spec.Template.Spec = corev1.PodSpec{AutomountServiceAccountToken: pointer(false), Containers: []corev1.Container{c}, Volumes: []corev1.Volume{{Name: "data", VolumeSource: corev1.VolumeSource{PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: claim}}}}}
			return nil
		})
		if err != nil {
			return err
		}
		port := int32(5432)
		if role == "redis" {
			port = 6379
		}
		s := &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: name}}
		if err := r.owned(ctx, a, s, func() error {
			s.Spec.Selector = labels(a, role)
			s.Spec.Ports = []corev1.ServicePort{{Name: role, Port: port, TargetPort: intstr.FromInt32(port)}}
			return nil
		}); err != nil {
			return err
		}
	}
	if err := r.network(ctx, a); err != nil {
		return err
	}
	return nil
}

func (r *Reconciler) dependenciesReady(ctx context.Context, a *api.PaperlessApplication) (bool, error) {
	for _, name := range []string{"paperless-db", "paperless-redis"} {
		deployment := &appsv1.Deployment{}
		if err := r.Reader.Get(ctx, client.ObjectKey{Namespace: a.Namespace, Name: name}, deployment); err != nil {
			return false, err
		}
		if deployment.Status.ObservedGeneration < deployment.Generation || deployment.Status.ReadyReplicas != 1 {
			return false, nil
		}
	}
	return true, nil
}
func (r *Reconciler) network(ctx context.Context, a *api.PaperlessApplication) error {
	tcp := corev1.ProtocolTCP
	udp := corev1.ProtocolUDP
	for _, role := range []string{"db", "redis", "app", "job"} {
		n := &networkingv1.NetworkPolicy{ObjectMeta: metav1.ObjectMeta{Name: "paperless-" + role}}
		if err := r.owned(ctx, a, n, func() error {
			n.Spec = networkingv1.NetworkPolicySpec{PodSelector: metav1.LabelSelector{MatchLabels: labels(a, role)}, PolicyTypes: []networkingv1.PolicyType{networkingv1.PolicyTypeIngress, networkingv1.PolicyTypeEgress}}
			if role == "db" || role == "redis" {
				port := intstr.FromInt32(5432)
				if role == "redis" {
					port = intstr.FromInt32(6379)
				}
				n.Spec.Ingress = []networkingv1.NetworkPolicyIngressRule{{From: []networkingv1.NetworkPolicyPeer{{PodSelector: &metav1.LabelSelector{MatchLabels: map[string]string{"paperless.bartl.sh/uid": string(a.UID)}, MatchExpressions: []metav1.LabelSelectorRequirement{{Key: "paperless.bartl.sh/role", Operator: metav1.LabelSelectorOpIn, Values: []string{"app", "job"}}}}}}, Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: &port}}}}
				return nil
			}
			if role == "app" {
				p := intstr.FromInt32(8000)
				n.Spec.Ingress = []networkingv1.NetworkPolicyIngressRule{{From: []networkingv1.NetworkPolicyPeer{{NamespaceSelector: &metav1.LabelSelector{MatchLabels: map[string]string{"kubernetes.io/metadata.name": "kube-system"}}, PodSelector: &metav1.LabelSelector{MatchLabels: map[string]string{"app.kubernetes.io/name": "traefik"}}}}, Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: &p}}}}
			}
			dns := intstr.FromInt32(53)
			https := intstr.FromInt32(443)
			http := intstr.FromInt32(80)
			n.Spec.Egress = []networkingv1.NetworkPolicyEgressRule{{To: []networkingv1.NetworkPolicyPeer{{NamespaceSelector: &metav1.LabelSelector{MatchLabels: map[string]string{"kubernetes.io/metadata.name": "kube-system"}}}}, Ports: []networkingv1.NetworkPolicyPort{{Protocol: &udp, Port: &dns}, {Protocol: &tcp, Port: &dns}}}, {To: []networkingv1.NetworkPolicyPeer{{PodSelector: &metav1.LabelSelector{MatchLabels: labels(a, "db")}}}, Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: pointer(intstr.FromInt32(5432))}}}, {To: []networkingv1.NetworkPolicyPeer{{PodSelector: &metav1.LabelSelector{MatchLabels: labels(a, "redis")}}}, Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: pointer(intstr.FromInt32(6379))}}}, {Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: &https}}}}
			// API HTTPS may use the service port or its post-DNAT target port.
			apiport := intstr.FromInt32(6443)
			n.Spec.Egress = append(n.Spec.Egress, networkingv1.NetworkPolicyEgressRule{Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: &apiport}}})
			// Traefik and Bartlized Restic expose HTTPS on target port 8443.
			// NetworkPolicy evaluates the post-DNAT port on the qualified CNI.
			tlsTarget := intstr.FromInt32(8443)
			n.Spec.Egress = append(n.Spec.Egress, networkingv1.NetworkPolicyEgressRule{Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: &tlsTarget}}})
			if role == "job" && a.Spec.Backup.Repository != "" {
				raw := a.Spec.Backup.Repository
				if len(raw) > 5 && raw[:5] == "rest:" {
					raw = raw[5:]
				}
				if u, err := url.Parse(raw); err == nil {
					p := https
					if u.Scheme == "http" {
						p = http
					}
					if u.Port() != "" {
						if num, e := strconv.Atoi(u.Port()); e == nil {
							p = intstr.FromInt(num)
						}
					}
					n.Spec.Egress = append(n.Spec.Egress, networkingv1.NetworkPolicyEgressRule{Ports: []networkingv1.NetworkPolicyPort{{Protocol: &tcp, Port: &p}}})
				}
			}
			return nil
		}); err != nil {
			return err
		}
	}
	return nil
}
func (r *Reconciler) application(ctx context.Context, a *api.PaperlessApplication, replicas int32) error {
	d := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "paperless"}}
	if err := r.owned(ctx, a, d, func() error {
		d.Labels = labels(a, "app")
		d.Spec.Replicas = &replicas
		d.Spec.Strategy = appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType}
		d.Spec.Selector = &metav1.LabelSelector{MatchLabels: labels(a, "app")}
		d.Spec.Template.ObjectMeta.Labels = labels(a, "app")
		d.Spec.Template.Spec = appPod(a, desired(a), "")
		return nil
	}); err != nil {
		return err
	}
	s := &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: "paperless"}}
	if err := r.owned(ctx, a, s, func() error {
		s.Spec.Selector = labels(a, "app")
		s.Spec.Ports = []corev1.ServicePort{{Name: "http", Port: 8000, TargetPort: intstr.FromInt32(8000)}}
		return nil
	}); err != nil {
		return err
	}
	in := &networkingv1.Ingress{ObjectMeta: metav1.ObjectMeta{Name: "paperless", Namespace: a.Namespace}}
	if !a.Spec.Ingress.Enabled {
		if err := r.Reader.Get(ctx, client.ObjectKeyFromObject(in), in); err == nil {
			if !metav1.IsControlledBy(in, a) {
				return fmt.Errorf("foreign ingress paperless")
			}
			return r.Delete(ctx, in)
		} else {
			return client.IgnoreNotFound(err)
		}
	}
	return r.owned(ctx, a, in, func() error {
		in.Annotations = map[string]string{"traefik.ingress.kubernetes.io/router.entrypoints": "websecure"}
		pathType := networkingv1.PathTypePrefix
		in.Spec = networkingv1.IngressSpec{Rules: []networkingv1.IngressRule{{Host: a.Spec.Ingress.Host, IngressRuleValue: networkingv1.IngressRuleValue{HTTP: &networkingv1.HTTPIngressRuleValue{Paths: []networkingv1.HTTPIngressPath{{Path: "/", PathType: &pathType, Backend: networkingv1.IngressBackend{Service: &networkingv1.IngressServiceBackend{Name: "paperless", Port: networkingv1.ServiceBackendPort{Number: 8000}}}}}}}}}}
		if a.Spec.Ingress.ClassName != "" {
			in.Spec.IngressClassName = &a.Spec.Ingress.ClassName
		}
		if a.Spec.Ingress.TLSSecret != "" {
			in.Spec.TLS = []networkingv1.IngressTLS{{Hosts: []string{a.Spec.Ingress.Host}, SecretName: a.Spec.Ingress.TLSSecret}}
		}
		return nil
	})
}
func jobFor(a *api.PaperlessApplication, op *api.Operation) *batchv1.Job {
	pod := appPod(a, op.Version, op.ID)
	pod.RestartPolicy = corev1.RestartPolicyNever
	pod.Containers[0].Command = nativeCommand(op.Kind)
	pod.Containers[0].ReadinessProbe = nil
	pod.Containers[0].Ports = nil
	pod.Containers[0].Env = append(pod.Containers[0].Env, env("BARTL_TARGET_VERSION", desired(a)), env("BARTL_PREPARE_MODE", op.Mode))
	if op.Kind == "prepare" && op.Mode == "Empty" && a.Spec.BootstrapSecret != "" {
		pod.Containers[0].EnvFrom = append(pod.Containers[0].EnvFrom, corev1.EnvFromSource{SecretRef: &corev1.SecretEnvSource{LocalObjectReference: corev1.LocalObjectReference{Name: a.Spec.BootstrapSecret}}})
	}
	secret := ""
	optional := false
	if op.Kind == "inspect" {
		secret = a.Spec.Backup.ReaderSecret
		optional = true
		pod.Containers[0].EnvFrom = nil
		pod.Containers[0].Env = append(pod.Containers[0].Env, corev1.EnvVar{Name: "PAPERLESS_DBPASS", ValueFrom: &corev1.EnvVarSource{SecretKeyRef: &corev1.SecretKeySelector{LocalObjectReference: corev1.LocalObjectReference{Name: a.Spec.ConfigurationSecret}, Key: "PAPERLESS_DBPASS"}}})
		pod.Volumes = slices.DeleteFunc(pod.Volumes, func(v corev1.Volume) bool { return v.Name == "client-ca" })
		pod.Containers[0].VolumeMounts = slices.DeleteFunc(pod.Containers[0].VolumeMounts, func(v corev1.VolumeMount) bool { return v.Name == "client-ca" })
	}
	if op.Kind == "publish" {
		secret = a.Spec.Backup.WriterSecret
		pod.Containers[0].Command = append(pod.Containers[0].Command, a.Status.Backup.CaptureOperation)
		pod.Containers[0].EnvFrom = nil
		pod.Containers[0].VolumeMounts = []corev1.VolumeMount{{Name: "staging", MountPath: "/staging", ReadOnly: true}}
		pod.Volumes = []corev1.Volume{{Name: "staging", VolumeSource: corev1.VolumeSource{PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: a.Spec.Claims.Staging, ReadOnly: true}}}}
		pod.InitContainers = nil
	}
	if secret != "" {
		pod.Volumes = append(pod.Volumes, corev1.Volume{Name: "credentials", VolumeSource: corev1.VolumeSource{Secret: &corev1.SecretVolumeSource{SecretName: secret, Optional: &optional}}})
		pod.Containers[0].VolumeMounts = append(pod.Containers[0].VolumeMounts, corev1.VolumeMount{Name: "credentials", MountPath: "/credentials", ReadOnly: true})
	}
	return &batchv1.Job{ObjectMeta: metav1.ObjectMeta{Name: op.JobName, Namespace: a.Namespace, Labels: labels(a, "job"), Annotations: map[string]string{"paperless.bartl.sh/operation": op.ID}}, Spec: batchv1.JobSpec{BackoffLimit: pointer(int32(0)), ActiveDeadlineSeconds: pointer(int64(21600)), Template: corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{Labels: labels(a, "job"), Annotations: map[string]string{"paperless.bartl.sh/operation": op.ID}}, Spec: pod}}}
}
