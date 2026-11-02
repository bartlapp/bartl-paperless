# Paperless lifecycle evidence and integration

The native exporter/importer passed the [25 October recovery proof](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-25-paperless-native.json). Packaged lifecycle integration and combined Keycloak/Paperless qualification remain parked pending approval. This repository does not yet provide an installable bartlized Paperless package.

Implement against the [Bartl application contract](../bartl-app/README.md#application-contract-and-qualification) using [How to bartlize](../bartl-app/docs/how-to-bartlize.md). [ADR-10](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-10-Kubernetes-fuer-Kundenumgebungen/README.md) selects an application controller for our Kubernetes packages; [ADR-11](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-11-Uebergebbare-Backup-Architektur/README.md) selects Restic and the backup/handover boundary. The application-specific requirements below are the basis for that integration, not evidence that it exists.

## State boundary

Preserve originals and required versions, metadata, ownership and permissions, users/groups, and used workflows/configuration. Retain external settings, secrets and evidence of relevant later records decisions independently. Native import rebuilds search; API tokens are reacquired. Keep native export defaults rather than adding custom filtering to remove harmless extra state. Never discard a rendition under hold.

## Native backup and recovery

The qualified native path uses Paperless 3.3.1, PostgreSQL 17.6, Redis and Restic on Debian 13. Upstream `/init` and s6 retain process supervision and ordering.

```sh
document_exporter /capture/paperless
document_importer /restore/paperless
```

### Capture

1. Exclude conflicting startup, restore and capture. Stop admission of new work and let accepted processing settle within a bounded deadline. If it does not settle, fail visibly; do not purge queues.
2. Stop the webserver, scheduler, consumer and worker through native s6 commands. PostgreSQL remains available. Export into an existing empty protected directory, retaining the export defaults; verify its complete inventory and keep the capture stable.
3. Explicitly resume only the same still-permitted container execution. Persistent stop takes precedence; neither a Job nor cleanup restores an earlier replica count.
4. Publish the complete export directory through Restic with scoped writer credentials and verify the published point. Another tar/zip layer is unnecessary. Report capture, publication and resumption separately.

The upload need not prolong the pause if the capture remains stable. Publication failure retains that capture for retry and reports the failed backup; it must not silently leave an otherwise healthy service stopped. Capacity exhaustion alerts rather than deletes the last usable point. Protect local exports and independently retain any export-encryption passphrase.

Scheduled and manual capture must use the same controller-coordinated procedure and exclusion. CronJob concurrency policy alone cannot exclude a manual request. Finite work gets scoped credentials and no replica-changing permission. The controller propagates stop/cancellation; process or connection loss is not proof that native work stopped. Validate container execution identity before mutation and resumption, not only Pod UID.

### Reconstruction

Use native migrations to prepare an empty, same-version installation, then import the complete export. Explicitly check that business documents/users, tokens and document files are absent; native warnings alone do not enforce these prerequisites. Upgrade afterward if a supported path is qualified. PostgreSQL and required native processes may run for preparation, but incomplete import must not admit ordinary writers or external effects.

Import restores document versions, users, object permissions and much application configuration; environment-provided inputs and API tokens must be supplied separately. Each intended restored account reacquires its token through `POST /api/token/`, with independently available authentication inputs and MFA where enabled. Native get-or-create returns an existing token or creates the missing one. Do not rotate profile tokens or grant administrator rights for credential recovery.

## Startup and failure

Existing owned state follows normal native startup. Observation must cover the application's database and document/file state sufficiently to select that path; it is not a separate schema-certification engine. Ordinary restart, including a container restart inside the same Pod, needs neither backup access nor records review, token reacquisition or repeated document/SSO qualification. Dependency unavailability must not become a liveness restart loop.

Paperless's custom-init hook logs failures and continues, so it cannot alone prevent incomplete recovery from serving. An init container cannot wait for its own Pod's database main process. Retain `/init` and s6 rather than introducing another native supervisor.

Paperless import changes several kinds of state; PostgreSQL transactional-restore guarantees do not transfer to it. Failed or ambiguous state-changing work may remain isolated with diagnostics until the failed target is replaced and the ordinary procedure retried. Preserve source and backup history. Do not add a repair or task-replay engine. Controller restart and work completion must preserve stop intent.

Finite native coordination was approved initially in Bash. A different implementation for those steps needs a concrete limitation and discussion of the alternative, not a generic framework project.

## Source retention

Confirm ingestion completed and the original is readable. Keep the source until a subsequent capture containing it has been independently published and verified, then perform only permitted source-copy cleanup. Paper, email or a device is sufficient if it survives the failure being covered; otherwise use an ordinary durable holding copy, not a new intake service or receipt ledger.

The backup result identifies installation, capture boundary, publication/verification completion, exact Restic point and outcome. Completion after an upload does not prove inclusion if capture began earlier. Check the native inventory and original checksums where uncertain. Unsettled ingestion is not covered; a successful backup does not authorize destruction of legally required originals.

After recovery, compare retained sources with the restored library before re-ingesting missing documents. Do not blindly replay or merge records solely because their bytes match.

## Records after restore

An export reflects records at capture, not later deletion, hold or restriction decisions. Its restored audit history cannot supply missing later changes. After technical recovery in isolation, the responsible person checks independently surviving approvals, disposal records, correspondence or newer evidence and applies corrections through native administration before affected use resumes. This is a records-policy review, not a second technical startup authorization; it applies neither to ordinary restart nor nightly capture.

Where evidence is insufficient, keep affected access/processing closed and resolve the exception. Review cannot reconstruct missing information. A new decision file is justified only by a demonstrated gap. The [GmbH records policy](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-2-Toolstack/README.md#adr-29-verwaltung-und-verwahrung-von-dokumenten-und-e-mails) and [operating profile](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsangebot/README.md#gmbh-betriebsprofil) own the customer-specific responsibilities and timing.

## Qualification and current status

The native proof restored after deletion of the source VM. It verified original/version bytes and relationships, metadata, ownership and permissions, token reacquisition, browser search, and another backup restored into fresh database, file and Redis storage. Export truncates version `added` timestamps from microseconds to milliseconds. That limit was accepted for the GmbH filing profile; do not patch upstream or use this timestamp alone as document identity or order.

This qualifies the settled-work, same-version native procedure only. Integration still needs the [contract's package evidence](../bartl-app/README.md#supported-configuration-and-catalogue-evidence), especially interrupted capture/import, same-Pod and controller restart, stop during maintenance, failed-publication recovery, supported upgrade and combined SSO/records-release behavior. Qualification checks originals/versions, permissions, token reacquisition and rebuilt search through usable service, not just Job success. Its test accounts do not become routine startup dependencies.

The [24 October characterization](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-24-paperless-native.json) recorded queued-work continuation but unresolved active-work interruption; native revoke did not survive replacement. Keep that limit visible without treating it as a requirement for a replay engine. Reuse the completed native proof rather than repeating it for unrelated integration changes. No implementation, build, production deployment or new paid lab is authorized by these results.

## Native sources

- [Exporter](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_exporter.py) and [importer](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_importer.py).
- [Token endpoint](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/paperless/views.py) and [inherited token acquisition](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/views.py).
