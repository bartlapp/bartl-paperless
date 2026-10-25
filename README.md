# Paperless lifecycle evidence

The experimental Python supervisor, native helpers, chart, build scripts and tests were retired on 25 October 2026 at Florian's request. No replacement implementation is approved. The [consolidated design review](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/Kubernetes-Lifecycle.md) is the active carrier.

## Native state and lifecycle findings

The experiment covered Paperless 3.3.0/3.3.1 with PostgreSQL 17.6, document files and Redis. Upstream /init and s6 already supply native process management. The retired Python service replaced that entrypoint and launched Granian, Celery worker/beat and the document consumer itself; this is not a requirement for the replacement.

The retained native profiles distinguish the fresh and dump/restored schema representations. PostgreSQL deparses an equivalent MFA partial-index predicate differently after restore. The profiles, complete state inventory and exact native checks remain in the [read-only source snapshot](../floriankesslergmbh/workstreams/betriebsphilosophie/.lab/keycloak-shared-2026-10-24/retained/reset-2026-10-25/working-source/paperless/).

The experimental capture bundled database.dump, files.tar, manifest.json and SHA256SUMS, with data/media/consume and broker state. That is a tested format, not the selected format for the replacement. Native document export/import and database/files capture are being compared in the design review.

## Records and processing findings

The old records helper applied explicit deletion, hold and restriction decisions through native models and verified residues and permissions. It required settled tasks and was not a crash-safe general work-replay mechanism. Ordinary SIGTERM differed from its separate drain path.

The [24 October native characterization](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-24-paperless-native.json) records queued-work continuation, the bounded active-crash observation, warm-stop settlement and revocation that did not survive container replacement. Those results do not qualify the proposed new integration. Existing records duties are not removed by retiring this implementation.

## Executed component qualification

The 21 October stopped-work profile exercised initialization, restart, supported 3.3.0 to 3.3.1 transition, downgrade refusal, state-loss refusal and database/files/Redis reconstruction. Integrated identity, document and records checks retain their original scope; they do not prove general busy-crash continuation.

The [full former operating document](../floriankesslergmbh/workstreams/betriebsphilosophie/.lab/keycloak-shared-2026-10-24/retained/reset-2026-10-25/working-source/paperless/README.md) and source commit bf0edcc4c762ef77fe33b6f348142bf16edce12f retain pins, payload details and qualification limits. The [reset receipt](../floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-25-reset.json) locates the protected archives. Repository history, upstream licensing evidence and ownership are unchanged.
