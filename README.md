# Paperless lifecycle evidence

The native exporter/importer passed the [25 October recovery proof](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-25-paperless-native.json); its millisecond timestamp precision and controlled records-release review are accepted. Helm integration remains to be implemented after Keycloak, following the [startup contract](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/Kubernetes-Lifecycle.md#startup) and [implementation handoff](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/README.md#implementation-handoff). New implementation, image builds and provisioning remain stopped.

Ordinary container start observes actual owned state and compatibility, then retains upstream `/init`, s6 ordering and normal readiness. Same-Pod restart repeats observation. It needs neither backup access nor a records-release review, token-reacquisition exercise or repeated document/SSO qualification. Initialization and reconstruction must prevent incomplete state from serving; recovery additionally verifies restored documents, permissions, search and token reacquisition and applies the [later-records review](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/Kubernetes-Lifecycle.md#records-after-restore) before release.

## Native backup and recovery

The [native procedure](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/Kubernetes-Lifecycle.md#native-backup-and-restore) uses upstream document export/import after settling work and stopping writers through s6, then Restic publication of the complete export. Resume the same permitted execution after sealing the capture. Native import rebuilds search; API tokens are reacquired.

The Paperless 3.3.1 proof restored original/version bytes, metadata, ownership and permissions after source deletion. It verified token reacquisition, search and a subsequent backup restored into fresh storage. Export truncates version `added` timestamps to milliseconds; do not use that timestamp alone as document identity or ordering.

This proves the settled-work, same-version native procedure. Interrupted capture/import, same-Pod restart and combined SSO remain package qualification work. Preserve native work rather than purging queues or introducing a replay engine.
