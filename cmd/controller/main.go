// SPDX-License-Identifier: Apache-2.0
package main

import (
	"flag"
	api "github.com/floriankesslergmbh/bartl-paperless/api/v1alpha2"
	"github.com/floriankesslergmbh/bartl-paperless/internal/controller"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"os"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
)

func main() {
	var metrics, health string
	var leader bool
	flag.StringVar(&metrics, "metrics-bind-address", ":8080", "Metrics address")
	flag.StringVar(&health, "health-probe-bind-address", ":8081", "Health probe address")
	flag.BoolVar(&leader, "leader-elect", true, "Use leader election")
	options := zap.Options{}
	options.BindFlags(flag.CommandLine)
	flag.Parse()
	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&options)))
	namespace := os.Getenv("WATCH_NAMESPACE")
	if namespace == "" {
		ctrl.Log.Error(nil, "WATCH_NAMESPACE is required")
		os.Exit(1)
	}
	scheme := runtime.NewScheme()
	must(clientgoscheme.AddToScheme(scheme))
	must(api.AddToScheme(scheme))
	config := ctrl.GetConfigOrDie()
	mgr, err := ctrl.NewManager(config, ctrl.Options{Scheme: scheme, Cache: cache.Options{DefaultNamespaces: map[string]cache.Config{namespace: {}}}, Metrics: metricsserver.Options{BindAddress: metrics}, HealthProbeBindAddress: health, LeaderElection: leader, LeaderElectionID: "paperless.bartl.sh", LeaderElectionNamespace: namespace})
	must(err)
	kube, err := kubernetes.NewForConfig(config)
	must(err)
	r := &controller.Reconciler{Client: mgr.GetClient(), Reader: mgr.GetAPIReader(), Scheme: scheme, Executor: &controller.PodExecutor{Config: config, Kube: kube}, Namespace: namespace}
	must(r.SetupWithManager(mgr))
	must(mgr.AddHealthzCheck("healthz", healthz.Ping))
	must(mgr.AddReadyzCheck("readyz", healthz.Ping))
	must(mgr.Start(ctrl.SetupSignalHandler()))
}
func must(err error) {
	if err != nil {
		ctrl.Log.Error(err, "Controller cannot continue")
		os.Exit(1)
	}
}
