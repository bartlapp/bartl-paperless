# Paperless lifecycle evidence

The experimental implementation was retired on 25 October 2026. The native exporter/importer subsequently passed the [25 October recovery proof](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-25-paperless-native.json); its millisecond timestamp precision and controlled records-release review are accepted. Replacement runtime work remains stopped. Follow the corrected [startup contract](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/Kubernetes-Lifecycle.md#startup) and [implementation handoff](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/README.md#implementation-handoff), after Keycloak. No image builds, new lab or production deployment are authorized by this document correction.

Ordinary container start observes actual owned state and compatibility, then retains upstream `/init`, s6 ordering and normal readiness. Same-Pod restart repeats observation. It needs neither backup access nor a records-release review, token-reacquisition exercise or repeated document/SSO qualification. Initialization and reconstruction must prevent incomplete state from serving; recovery additionally verifies restored documents, permissions, search and token reacquisition and applies the [later-records review](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/Kubernetes-Lifecycle.md#records-after-restore) before release.

## Native state and lifecycle findings

The experiment covered Paperless 3.3.0/3.3.1 with PostgreSQL 17.6, document files and Redis. Upstream /init and s6 already supply native process management. The retired Python service replaced that entrypoint and launched Granian, Celery worker/beat and the document consumer itself; this is not a requirement for the replacement.

The retained native profiles distinguish the fresh and dump/restored schema representations. PostgreSQL deparses an equivalent MFA partial-index predicate differently after restore. The profiles, complete state inventory and exact native checks remain in the [read-only source snapshot](../floriankesslergmbh/workstreams/betriebsphilosophie/.lab/keycloak-shared-2026-10-24/retained/reset-2026-10-25/working-source/paperless/).

The experimental capture bundled database.dump, files.tar, manifest.json and SHA256SUMS, with data/media/consume and broker state. That historical format is not the selected replacement. The [native procedure](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/Kubernetes-Lifecycle.md#native-backup-and-restore) uses upstream document export/import after settling work and stopping writers, then Restic publication of the complete export. Native import rebuilds search; API tokens are reacquired. The settled-work proof does not qualify arbitrary busy-crash recovery.

## Records and processing findings

The old records helper applied explicit deletion, hold and restriction decisions through native models and verified residues and permissions. It required settled tasks and was not a crash-safe general work-replay mechanism. Ordinary SIGTERM differed from its separate drain path.

The [24 October native characterization](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-24-paperless-native.json) records queued-work continuation, the bounded active-crash observation, warm-stop settlement and revocation that did not survive container replacement. Those results do not qualify the proposed new integration. Existing records duties are not removed by retiring this implementation.

## Executed component qualification

The 21 October stopped-work profile exercised initialization, restart, supported 3.3.0 to 3.3.1 transition, downgrade refusal, state-loss refusal and database/files/Redis reconstruction. Integrated identity, document and records checks retain their original scope; they do not prove general busy-crash continuation.

The [full former operating document](../floriankesslergmbh/workstreams/betriebsphilosophie/.lab/keycloak-shared-2026-10-24/retained/reset-2026-10-25/working-source/paperless/README.md) and source commit bf0edcc4c762ef77fe33b6f348142bf16edce12f retain pins, payload details and qualification limits. The [reset receipt](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-25-reset.json) locates the protected archives. Repository history, upstream licensing evidence and ownership are unchanged.
