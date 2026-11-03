# Paperless lifecycle evidence and integration

The native exporter/importer passed the [25 October recovery proof](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-25-paperless-native.json). Packaged lifecycle integration and combined Keycloak/Paperless qualification remain parked pending approval. This repository does not yet provide an installable bartlized Paperless package.

Implement against the [Bartl application contract](../bartl-app/README.md#application-contract-and-qualification) using [How to bartlize](../bartl-app/docs/how-to-bartlize.md). [ADR-10](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-10-Kubernetes-fuer-Kundenumgebungen/README.md) selects an application controller for our Kubernetes packages; [ADR-11](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-11-Uebergebbare-Backup-Architektur/README.md) selects Restic and the backup/handover boundary. The application-specific requirements below are the basis for that integration, not evidence that it exists.

The experimental supervisor, scripts, chart and records-reconciliation implementation were retired in `82e4357`. They are not the implementation baseline. Reuse the demonstrated native behavior and its exact-version evidence, not the retired architecture.

Use published Bartlized Keycloak 0.5.1 and Bartlized Restic 0.2.1 as the initial integration baseline. [Keycloak's published-package verification](../bartl-keycloak/DESIGN.md#qualified-package-and-scope) covers native Restic locking and recovery from an independently copied repository. Paperless integration and combined service recovery remain to be qualified.

## State boundary

Preserve originals and required versions, metadata, ownership and permissions, users/groups, and used workflows/configuration. Retain external settings, secrets and evidence of relevant later records decisions independently. Native import rebuilds search; API tokens are reacquired. Keep native export defaults rather than adding custom filtering to remove harmless extra state. Never discard a rendition under hold.

## Native backup and recovery

The qualified native path uses Paperless 3.3.1, PostgreSQL 17.6, Redis and Restic on Debian 13. Upstream `/init` and s6 retain process supervision and ordering.

The proof used one writer, completed ingestion, no active, reserved or scheduled tasks, and empty broker queues before capture. It establishes settled-work recovery on the recorded versions, not recovery of interrupted ingestion. Preserve this distinction when choosing the supported package configuration.

```sh
document_exporter /capture/paperless
document_importer /restore/paperless
```

### Backup service interface

Paperless publishes to one configured Restic endpoint. The [backup service](../bartl-restic/README.md#service-and-state-boundary) owns replication and retention; Paperless owns consistent capture, publication verification and reconstruction. Use append-only writer credentials and recovery credentials that permit native lock operations while keeping backup contents read-only. Destructive maintenance credentials do not belong in application workers.

Recovery must also accept a compatible Paperless recovery point copied into an independently initialized repository. Preserve logical application identity and integrity checks, but bind the recovery operation to the selected repository and its full snapshot ID rather than requiring the original repository or snapshot IDs. Use native locking; do not bypass locks or automatically unlock on retry. The [Restic replication contract](../bartl-restic/README.md#replication-mechanism) defines copy correspondence and locking.

### Capture

1. Exclude conflicting startup, restore and capture. Stop admission of new work and let accepted processing settle within a bounded deadline. If it does not settle, fail visibly; do not purge queues.
2. Stop the webserver, scheduler, consumer and worker through native s6 commands. PostgreSQL remains available. Export into an existing empty protected directory, retaining the export defaults; verify its complete inventory and keep the capture stable.
3. Explicitly resume only the same still-permitted container execution. Persistent stop takes precedence; neither a Job nor cleanup restores an earlier replica count.
4. Publish the complete export directory through Restic with scoped writer credentials and verify the published point. Another tar/zip layer is unnecessary. Report capture, publication and resumption separately.

The upload need not prolong the pause if the capture remains stable. Publication failure retains that capture for retry and reports the failed backup; it must not silently leave an otherwise healthy service stopped. Capacity exhaustion alerts rather than deletes the last usable point. Protect local exports and independently retain any export-encryption passphrase.

Scheduled and manual capture must use the same controller-coordinated procedure and exclusion. CronJob concurrency policy alone cannot exclude a manual request. Finite work gets scoped credentials and no replica-changing permission. The controller propagates stop/cancellation; process or connection loss is not proof that native work stopped. Validate container execution identity before mutation and resumption, not only Pod UID.

### Reconstruction

Use native migrations to prepare an empty, same-version installation, then import the complete export. Explicitly check that business documents/users, tokens and document files are absent; native warnings alone do not enforce these prerequisites. Upgrade afterward if a supported path is qualified. PostgreSQL and required native processes may run for preparation, but incomplete import must not admit ordinary writers or external effects.

Import restores document versions, users, object permissions and much application configuration; environment-provided inputs must be supplied separately. Native import does not restore API tokens. The proof reacquired them through `POST /api/token/` using restored local password accounts; repeated acquisition returned the existing token. SSO-only accounts and MFA were not exercised. Qualify the supported credential-recovery procedure for the chosen authentication profile without assuming local passwords, rotating profile tokens or granting administrator rights. Token reacquisition is not a prerequisite for ordinary application startup.

## Startup and failure

Existing owned state follows normal native startup. Observation must cover the application's database and document/file state sufficiently to select that path; it is not a separate schema-certification engine. Ordinary restart, including a container restart inside the same Pod, needs neither backup access nor records review, token reacquisition or repeated document/SSO qualification. Dependency unavailability must not become a liveness restart loop.

Paperless's custom-init hook logs failures and continues, so it cannot alone prevent incomplete recovery from serving. An init container cannot wait for its own Pod's database main process. Retain `/init` and s6 rather than introducing another native supervisor.

Paperless import changes several kinds of state; PostgreSQL transactional-restore guarantees do not transfer to it. Failed or ambiguous import may remain isolated with diagnostics. Replace the failed target and retry only when the required state remains independently recoverable within the accepted data-loss boundary. Preserve source and backup history; do not add a repair or task-replay engine. Controller restart and work completion must preserve stop intent.

Helm declares installation configuration and run/stop intent. The application controller owns lifecycle sequencing; finite workers execute the native procedures without independently changing that intent. Choose their implementation from the actual coordination needs, not the retired package's language or architecture.

Supported removal must stop Paperless writers and maintenance work before releasing ownership. Retained database and document storage, together with independently retained configuration and secrets, must remain usable by a subsequent authorized installation without admitting a competing predecessor. Qualify this procedure rather than treating surviving volumes as proof of reinstallability.

## Source retention

Confirm ingestion completed and the original is readable. Keep the source until a subsequent capture containing it has been independently published and verified, then perform only permitted source-copy cleanup. Paper, email or a device is sufficient if it survives the failure being covered; otherwise use an ordinary durable holding copy, not a new intake service or receipt ledger.

The verified copy containing the ingested original must survive the failure being covered before source-copy cleanup is permitted. Primary publication alone does not establish that condition when the profile also requires a secondary copy. Establish that protection through the backup service's result, not a Paperless replication workflow.

The backup result identifies installation, capture boundary, publication/verification completion, exact Restic point and outcome. Completion after an upload does not prove inclusion if capture began earlier. Check the native inventory and original checksums where uncertain. Unsettled ingestion is not covered; a successful backup does not authorize destruction of legally required originals.

After recovery, compare retained sources with the restored library before re-ingesting missing documents. Do not blindly replay or merge records solely because their bytes match.

## Records after restore

An export reflects records at capture, not later deletion, hold or restriction decisions. Its restored audit history cannot supply missing later changes. After technical recovery in isolation, the responsible person checks independently surviving approvals, disposal records, correspondence or newer evidence and applies corrections through native administration before affected use resumes. This is a records-policy review, not a second technical startup authorization; it applies neither to ordinary restart nor nightly capture.

Where evidence is insufficient, keep affected access/processing closed and resolve the exception. Review cannot reconstruct missing information. A new decision file is justified only by a demonstrated gap. The [GmbH records policy](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-2-Toolstack/README.md#adr-29-verwaltung-und-verwahrung-von-dokumenten-und-e-mails) and [operating profile](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsangebot/README.md#gmbh-betriebsprofil) own the customer-specific responsibilities and timing.

## Qualification and current status

The native proof restored after deletion of the source VM. It verified original/version bytes and relationships, metadata, ownership and permissions, token reacquisition, browser search, and another backup restored into fresh database, file and Redis storage. Export truncates version `added` timestamps from microseconds to milliseconds. That limit was accepted for the GmbH filing profile; do not patch upstream or use this timestamp alone as document identity or order.

This qualifies the settled-work, same-version native procedure only. Integration still needs the [contract's package evidence](../bartl-app/README.md#supported-configuration-and-catalogue-evidence). Resolve and exercise these application-specific questions:

- Capture: how are new submissions excluded, accepted work allowed to settle, and writer termination established? What happens when the drain deadline expires?
- Interruption: after container or controller restart, can incomplete import remain isolated and intentional stop remain effective without reconstructing ambiguous progress?
- Publication failure: does a complete capture remain protected for retry while a healthy service resumes only under current running authority?
- Upgrade: which exact forward transition is supported, and what native import/migration sequence implements it? Same-version recovery is not upgrade evidence.
- Authentication: which SSO/MFA and API-token paths are supported after recovery, and do permissions still hold?
- Continued operation: what happens when controller observation is unavailable, and how is stop completion established before replacement takes production authority?
- Retained state: does supported uninstall/reinstall preserve usable documents, identity and subsequent backup capability?

Qualification checks originals/versions, permissions, supported token reacquisition and rebuilt search through usable service, not just Job success. Exercise combined SSO and the customer records-release procedure before affected service use. Test accounts do not become routine startup dependencies.

The [GmbH operating profile](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsangebot/README.md#gmbh-betriebsprofil) supplies the initial customer's accepted interruption, data-loss and replacement choices, including permitted nightly capture interruption and a stopped source during replacement checks. Maximum capture pause and staging capacity remain to be set there. These are customer choices, not universal package defaults or a zero-downtime requirement.

The [24 October characterization](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-24-paperless-native.json) is historical native-behavior evidence, not a current implementation specification. Its prescriptions for a restricted dispatcher, durable task-denial plans, records reconciliation, custom Redis recovery and multi-store fencing belong to the retired design and are superseded.

Retain the observations: queued work survived replacement in the tested cases; interrupted active work did not settle within the observation window; task revocation did not survive worker replacement. Warm shutdown allowed the tested task to complete but did not independently prove worker/descendant termination. These findings constrain the supported procedure; they do not authorize a replay or reconciliation engine.

Reuse the completed native proof rather than repeating it for unrelated integration changes. No implementation, build, production deployment or new paid lab is authorized by these results.

## Native sources

- [Exporter](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_exporter.py) and [importer](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_importer.py).
- [Token endpoint](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/paperless/views.py) and [inherited token acquisition](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/views.py).
