# Bartlized Paperless

Local package 0.1.0 supplies a namespace-local application controller, Helm chart and finite native procedures. Build and import its offline artifacts using the recipe below. Artifact publication and repository integration remain outstanding and require separate authorization.

The [Bartl application contract](../bartl-app/README.md#application-contract-and-qualification) and [How to bartlize](../bartl-app/docs/how-to-bartlize.md) own the general behavior and implementation method. [ADR-10](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-10-Kubernetes-fuer-Kundenumgebungen/README.md) selects an application controller; [ADR-11](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-11-Uebergebbare-Backup-Architektur/README.md) owns the backup/handover boundary. The native exporter/importer baseline is the [25 October recovery proof](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-25-paperless-native.json).

The experimental supervisor, scripts, chart and records-reconciliation implementation were retired in `82e4357`. This package does not reuse them. `/init`, s6, native migrations, `document_exporter` and `document_importer` retain their upstream responsibilities.

Integration dependencies are published Bartlized Keycloak 0.5.1 and Bartlized Restic 0.2.1. They are installed independently, not embedded as subcharts. Paperless writes to one backup endpoint; the backup service owns replication and retention.

## Package and target

The package contains Paperless 3.3.0 and 3.3.1 runtimes, PostgreSQL 17.6, Redis 8.2.1 and Restic 0.19.1. The supported forward transition is 3.3.0 to 3.3.1, both in place and through same-version import followed by native migration. Downgrades, other Paperless versions and PostgreSQL major upgrades are refused or outside this package's supported configuration.

Use Linux amd64 Kubernetes with enforced NetworkPolicy, Helm 3 or 4, and four operator-owned ReadWriteOnce claims: database, broker, application storage and protected staging. The filesystem must support POSIX permissions, file locks, atomic rename and fsync. Native image setup needs root to arrange owned directories; ordinary Paperless services run as upstream's UID 1000. One namespace contains one release named `paperless`, one logical application and no unrelated workloads. The initial profile has one Paperless container and one Celery worker with one processing thread. The qualified placement is one K3s node with local-path volumes, not HA or multi-node RWO scheduling.

Use Traefik in `kube-system` for the supplied ingress policy and an independently supplied TLS Secret. The chart does not provision DNS, certificates, storage or the identity/backup services. Retain exact images, chart, configuration, Paperless secret key, OIDC client settings and backup keys/reader credentials independently of the source installation. API/browser intake and native metadata-assignment workflows form the initial profile; mail polling, remote OCR/AI, custom scripts and externally effective workflows require separate qualification.

The supplied route uses Traefik's HTTPS `websecure` entrypoint only. A minimal Django settings extension sets secure session and CSRF cookies, because these Paperless releases expose no native environment switches for those flags. It otherwise imports upstream settings unchanged; do not override `DJANGO_SETTINGS_MODULE`.

### Build and import without publishing

On a Linux amd64 builder with Podman, Skopeo, Helm 3/4, Mike Farah yq 4 and `sha256sum`:

```sh
OUT="$PWD/dist" bash build.sh
```

Choose a fresh output directory. The build creates OCI archives, `bartl-paperless-0.1.0.tgz`, digest-bound `image-values.yaml` and `SHA256SUMS`; it never pushes. The packaged chart, rather than the source chart's local build tags, carries the immutable built image references. Transfer the complete output to independently retained storage. On every target node:

```sh
sudo bash import.sh k3s
```

The import helper verifies `SHA256SUMS`, imports the archives and registers the exact image digest references carried by the chart. For another containerd installation use `sudo bash import.sh containerd`. Published Restic and Keycloak images/charts must also remain independently obtainable.

The exercised delivery can be retained as a smaller, deduplicated amd64 bundle. After importing the declared images on a Linux node, run `sudo OUT=/new/compact-directory bash compact.sh k3s` from the bundle directory (`containerd` selects plain containerd). Native image export preserves the chart's immutable image identities; gzip compresses only the transport. The resulting directory uses the same `import.sh` command and streams decompression without needing an expanded tar file on the recipient.

### Installation inputs

Select the intended kubeconfig/context. Prepare namespace `paperless-blue`, four distinct existing claims and protected inputs. Claim names below are examples, not automatically created storage:

```sh
NS=paperless-blue
CHART=/protected/packages/bartl-paperless-0.1.0.tgz
kubectl config current-context
kubectl -n "$NS" get pvc paperless-data paperless-db paperless-broker paperless-staging
kubectl -n "$NS" create secret generic paperless-configuration \
  --from-env-file=/protected/paperless/configuration.env
kubectl -n "$NS" create secret generic paperless-bootstrap \
  --from-env-file=/protected/paperless/bootstrap.env
```

`configuration.env` supplies `PAPERLESS_SECRET_KEY`, `PAPERLESS_DBPASS` and the HTTPS `PAPERLESS_URL`, plus the supported native settings/OIDC configuration. Preserve the secret key across recovery; a new empty target may use a new database password. Do not put bootstrap administrator settings, database host/name/user, broker URL, concurrency overrides or custom-init/consume scripts in this Secret. The controller fixes the owned database, broker and single-writer topology.

The optional bootstrap Secret contains `PAPERLESS_ADMIN_USER` and `PAPERLESS_ADMIN_PASSWORD`. It is mounted only for an empty installation with no selected backup, never for existing state or import. Test accounts are not package inputs.

With a backup endpoint, create separate reader and writer Secrets from the independently retained Bartlized Restic credentials:

```sh
kubectl -n "$NS" create secret generic paperless-backup-reader \
  --from-file=username=/protected/backup/reader.username \
  --from-file=restPassword=/protected/backup/reader.restPassword \
  --from-file=password=/protected/backup/password --from-file=ca.crt=/protected/backup/ca.crt
kubectl -n "$NS" create secret generic paperless-backup-writer \
  --from-file=username=/protected/backup/writer.username \
  --from-file=restPassword=/protected/backup/writer.restPassword \
  --from-file=password=/protected/backup/password --from-file=ca.crt=/protected/backup/ca.crt
```

The username files contain `reader` and `writer` respectively. Never mount backup maintenance/admin credentials. The CA file may be omitted for an endpoint trusted by the runtime's system CA bundle.

Installation values contain references, not passwords:

```yaml
identity:
  installation: customer-installation
  instance: records
replicas: 1
version: "3.3.1"
claims:
  storage: paperless-data
  database: paperless-db
  broker: paperless-broker
  staging: paperless-staging
configurationSecret: paperless-configuration
bootstrapSecret: paperless-bootstrap
backup:
  repository: rest:https://backup.example.org/paperless/
  readerSecret: paperless-backup-reader
  writerSecret: paperless-backup-writer
  schedule: "0 3 * * *"
  timeZone: Europe/Berlin
  drainSeconds: 300
ingress:
  enabled: true
  host: paperless.example.org
  className: traefik
  tlsSecret: paperless-tls
```

Omit `backup` for an installation without a backup store. An empty `schedule` disables scheduled capture without disabling manual backup. Select staging capacity and the accepted drain deadline for the installation; these example values are not a customer interruption commitment. Logical identity and claim names are immutable. Reuse identity, not CR UID or PVC annotations, for independent reconstruction.

```sh
helm upgrade --install paperless "$CHART" -n "$NS" -f installation-values.yaml \
  --wait=legacy --timeout=5m
kubectl -n "$NS" wait --for=condition=Ready paperlessapplication/paperless --timeout=30m
kubectl -n "$NS" get paperlessapplication paperless -o json
```

`--wait=legacy` is Helm 4 syntax; omit `=legacy` with Helm 3. Helm completion means controller infrastructure exists, not that application recovery succeeded. Require both `status.observedGeneration` and the requested condition's `observedGeneration` to equal live `metadata.generation`. `Ready=True` and `status.version` must match the intended release. `Failed=True` retains a refused/interrupted transition; inspect `status.operation`, `status.operations`, Job termination messages and native logs.

The controller starts the owned dependencies, observes database/file state, selects and verifies the latest matching complete point only when local state is absent, prepares/imports on the source version and performs the supported forward migration if needed. Its native gate checks ownership and the actual container execution before `/init` can reach migrations and ordinary services. Successful reconstruction needs no second technical release command. Existing state and ordinary container restart do not need backup access.

### Capture, publication and retry

```sh
REQUEST="manual-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl -n "$NS" annotate paperlessapplication paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl -n "$NS" get paperlessapplication paperless -o json
```

Wait for `status.backup.request` to equal this request and `status.backup.phase` to become `Published`. Inspect the result's `captureOperation`, `capturedAt`, `resumed`, `repositoryID`, full `snapshotID` and `publishedAt`. `BackupFailed=True` is a failed backup, independently of application `Ready`. Scheduled requests enter this same controller path.

The finite capture stops native admission, waits for one responsive worker with empty active/reserved/scheduled work and broker queues, then stops the worker and checks that UID-1000 writers/descendants have ended. It exports without filtering, inventories every member and resumes only the same currently permitted container execution. Publication uses a separate writer-scoped Job and a read-only staging mount. A candidate snapshot is fully restored and byte-checked before a complete-tag snapshot of the same tree is published.

After publication failure, correct the endpoint/credential/capacity problem and issue a new request. The controller retries the retained complete capture rather than silently recapturing; its capture boundary therefore does not advance. Request another backup after successful retry to include later work. Never infer inclusion from publication time.

Local captures are not automatically pruned. Monitor staging capacity, failed/overdue requests and backup age independently. Remove an old local capture only after its publication and required independent replication are verified, it is not the active/retry capture, and the customer's retention rules permit removal. Capacity exhaustion must not delete the last usable point.

### Durable stop, restart and removal

Keep run/stop intent in the installation's values, not in generated Deployment replica counts:

```sh
helm upgrade paperless "$CHART" -n "$NS" -f installation-values.yaml --set replicas=0
kubectl -n "$NS" wait --for=condition=Stopped paperlessapplication/paperless --timeout=10m
kubectl -n "$NS" get paperlessapplication paperless -o json
kubectl -n "$NS" get pods,jobs,deployments,replicasets
```

Require current-generation `Stopped=True` and no application/native-Job Pods, including terminating Pods. The controller withdraws its ingress and confirms Deployment/ReplicaSet drainage; PostgreSQL and Redis may remain for diagnosis. Stop cancels finite work and wins over completion. Interrupted mutation remains failed across later run intent. Export needed logs before stopping because drainage removes Jobs and their Pods.

A running application continues through controller/API observation loss. No lease expiry or recurring custom supervisor stops a healthy service. A new container execution must obtain fresh native admission. While the controller cannot observe or enforce a stop, the old service may continue; a submitted stop request or unreachable source is not confirmed retirement. Do not activate a competing replacement until actual drainage or independent retirement is established.

For an ordinary restart after a completed, nonfailed stop, use the same values with `replicas: 1`. For supported uninstall, keep the controller alive until application finalization:

```sh
kubectl -n "$NS" delete paperlessapplication paperless --wait=true --timeout=10m
helm uninstall paperless -n "$NS" --wait --timeout=5m
kubectl -n "$NS" get pvc,secrets
```

Do not remove finalizers or delete the namespace/controller first. Finalization drains dependencies too and releases only this CR's claim bindings. Claims, data and operator Secrets survive. Reinstall with the same logical identity, claims and retained inputs and `replicas: 1`; existing-state observation and native startup must succeed before service returns. A failed target's durable transition marker is not cleared by uninstall; preserve diagnostics and independently recoverable state, then use fresh storage rather than deleting markers or replaying import.

For replacement, stop the source and confirm retirement, retain any required final/secondary point, then install with fresh claims, the same logical identity/configuration and the selected surviving repository. Backup selection binds that repository's own full snapshot ID. To upgrade, select `version: "3.3.1"` with the complete installation values; do not roll back the software against migrated data. Helm does not update an existing CRD: apply the selected package's `crds/` before a CRD-changing package upgrade.

### OIDC, MFA and token recovery

Configure native allauth OIDC in the protected configuration Secret:

```text
PAPERLESS_APPS=allauth.socialaccount.providers.openid_connect
PAPERLESS_SOCIALACCOUNT_PROVIDERS={"openid_connect":{"SCOPE":["openid","profile","email"],"OAUTH_PKCE_ENABLED":true,"APPS":[{"provider_id":"keycloak","name":"Keycloak","client_id":"paperless","secret":"PROTECTED_CLIENT_SECRET","settings":{"server_url":"https://identity.example.org/realms/records"}}]}}
```

Register `https://paperless.example.org/accounts/oidc/keycloak/login/callback/` in Keycloak and require the selected user's TOTP MFA there. Paperless retains its own users, groups and object permissions. Deliberately link an existing account through its native profile; do not assume that matching email establishes identity. First-login provisioning and permission assignment are native administration, not package startup tests.

A read-only browser group needs `view_document`, `view_uisettings`, `add_uisettings`, `change_uisettings` and `view_savedview`, in addition to its document object grants. Native metadata views may also need `view_tag`, `view_correspondent`, `view_documenttype` and `view_storagepath`. UI-settings permissions do not grant document modification or user administration.

Native import excludes DRF API tokens. Local password accounts can reacquire their token with `POST /api/token/`; Paperless-local MFA, when enabled, additionally requires its native `code`. For a restored SSO-only user, an authorized operator uses the native management command:

```sh
# Treat stdout as a secret; do not put it in general logs.
kubectl -n "$NS" exec deployment/paperless -c paperless -- \
  uv run --no-project python manage.py drf_create_token USERNAME
```

Omit `--reset`/`-r`: default `get_or_create` returns an existing token without rotation. This does not set a local password or elevate the user's permissions. Deliver the token through the installation's protected credential channel; the authenticated user's `GET /api/profile/` also exposes that user's existing token. The profile's `generate_auth_token` endpoint deliberately rotates tokens and is not this recovery procedure. MFA protects interactive identity login, not every use of a bearer API token. Token issuance, account probes and records review are never ordinary startup dependencies.

## State boundary

Preserve originals and required versions, metadata, ownership and permissions, users/groups, and used workflows/configuration. Retain external settings, secrets and evidence of relevant later records decisions independently. Native import rebuilds search; API tokens are reacquired. Keep native export defaults rather than adding custom filtering to remove harmless extra state. Never discard a rendition under hold.

## Native procedures and failure boundaries

The supported capture boundary is settled work: completed ingestion, no active/reserved/scheduled tasks, and empty broker queues. Interrupted ingestion is not recovered by a custom replay engine. The application has one writer execution; the controller and a target-local file lock exclude conflicting preparation and capture.

Finite preparation uses upstream `init-folders`, the native compatibility check and migrations, then same-version `document_importer`. Native folder preparation matters: the importer expects the search-index directory to exist before rebuilding it. Before import, the worker rejects existing business documents/users, API tokens and document files rather than relying on upstream warnings. Only successful preparation and any subsequent supported migration permit the ordinary `/init` container to start.

The package retains a database/file-store binding and a durable pending-transition marker. They distinguish owned state from absence and prevent partial import or ambiguous capture from turning into ordinary startup. A separate s6 prerequisite before migrations and `init-complete` checks that binding and current authority; the upstream custom-init hook alone cannot enforce this because it logs errors and continues. This is not a second native supervisor or recurring schema-certification engine.

Capture stops the native admission services before draining the worker. Writer termination requires both ended UID-1000 processes/descendants and no remaining PostgreSQL client sessions in the owned database. A killed client can leave its database query executing. Export also preserves the native media lock's UID-1000 ownership, so a backup of an empty library cannot break later ingestion. Staging remains root-protected.

The controller binds work to the application, operation, Pod UID, Kubernetes container ID and native execution UUID. Detached capture has a durable admission timestamp and a one-hour execution bound in addition to the configured drain budget. A positively observed unfinished operation beyond that bound fails and is drained; timeout is not proof of termination. Native Jobs have a six-hour outer deadline and no Kubernetes retry. Native command timeouts and the drain budget do not constitute a guaranteed maximum service outage after failure.

Unambiguous capture completion can be observed after controller outage and ordinary container replacement. That only permits publication of the original protected capture; it never permits an old operation to mutate or resume a replacement execution. Missing or ambiguous completion remains failed and isolated. Failed capture/preparation is not repaired by clearing markers, purging queues or replaying tasks. Replace a failed target only when independently retained inputs preserve the required state within the accepted data-loss boundary.

### Backup service interface

The [backup service](../bartl-restic/README.md#service-and-state-boundary) owns replication and retention. Writer credentials are append-only; recovery credentials can read backup contents and create/remove native lock objects. Neither application worker has destructive maintenance credentials. Do not bypass locks or automatically unlock on retry: first establish that the owning native operation has ended.

The complete export directory is the recovery artifact, without another tar/zip layer. Its manifest binds logical identity, native version, capture boundary and every member's length/SHA-256. Only a verified `complete`-tag point is eligible; retention must preserve usable complete points rather than count incomplete candidate snapshots as replacements. Lookup uses strict native object enumeration because `restic snapshots --json` can warn about an unreadable object and omit it while returning success.

Reconstruction binds the selected repository's own identity and full snapshot ID. An independently initialized/copied repository need not retain the source repository or snapshot IDs. Logical identity, supported native version and complete inventory integrity remain mandatory. The [replication contract](../bartl-restic/README.md#replication-mechanism) owns copy correspondence. Repository/credential changes during active native work are not a credential-rotation procedure.


## Source retention

Confirm ingestion completed and the original is readable. Keep the source until a subsequent capture containing it has been independently published and verified, then perform only permitted source-copy cleanup. Paper, email or a device is sufficient if it survives the failure being covered; otherwise use an ordinary durable holding copy, not a new intake service or receipt ledger.

The verified copy containing the ingested original must survive the failure being covered before source-copy cleanup is permitted. Primary publication alone does not establish that condition when the profile also requires a secondary copy. Establish that protection through the backup service's result, not a Paperless replication workflow.

The backup result identifies installation, capture boundary, publication/verification completion, exact Restic point and outcome. Completion after an upload does not prove inclusion if capture began earlier. Check the native inventory and original checksums where uncertain. Unsettled ingestion is not covered; a successful backup does not authorize destruction of legally required originals.

After recovery, compare retained sources with the restored library before re-ingesting missing documents. Do not blindly replay or merge records solely because their bytes match.

## Records after restore

An export reflects records at capture, not later deletion, hold or restriction decisions. Its restored audit history cannot supply missing later changes. After technical recovery in isolation, the responsible person checks independently surviving approvals, disposal records, correspondence or newer evidence and applies corrections through native administration before affected use resumes. This is a records-policy review, not a second technical startup authorization; it applies neither to ordinary restart nor nightly capture.

Where evidence is insufficient, keep affected access/processing closed and resolve the exception. Review cannot reconstruct missing information. A new decision file is justified only by a demonstrated gap. The [GmbH records policy](../../floriankesslergmbh/floriankesslergmbh/adr/ADR-2-Toolstack/README.md#adr-29-verwaltung-und-verwahrung-von-dokumenten-und-e-mails) and [operating profile](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsangebot/README.md#gmbh-betriebsprofil) own the customer-specific responsibilities and timing.

## Qualification scope

The native proof restored after deletion of the source VM. It verified original/version bytes and relationships, metadata, ownership and permissions, token reacquisition, browser search, and another backup restored into fresh database, file and Redis storage. Export truncates version `added` timestamps from microseconds to milliseconds. That limit was accepted for the GmbH filing profile; do not patch upstream or use this timestamp alone as document identity or order.

The package's supported transition is Paperless 3.3.0 to 3.3.1, using same-version import before native forward migration. The selected authentication profile is Keycloak OIDC with TOTP for an SSO-only user, plus native token acquisition without password assignment, rotation or privilege elevation. Paperless-local MFA is not part of this qualification.

Package acceptance checks original/version/rendition bytes, metadata, user/group/object grants, a used metadata-assignment workflow, rebuilt search, authentication, new work and another recoverable point. Fault cases cover incomplete import, execution replacement, controller absence, failed publication, bounded drainage, damaged history, persistent stop and retained-storage reuse. The current package lab removes source installations, their physical storage directories and the primary repository on one disposable K3s host. This establishes that failure boundary and independent-repository recovery, not host/provider-loss failover or cross-cluster fencing.

The exercised target was Debian 13, amd64, K3s `v1.36.5+k3s1` with its enforcing CNI and Traefik, cert-manager 1.21.3 and Helm 4.3.0. Builds used Podman 5.4.2. The shared CRD remains installed across namespace removal.

Repeatable regression and synthetic-library checks are in source:

```sh
go test ./...
uv run --no-project python -m unittest discover -s tests -v
node tests/check-library.mjs baseline /protected/library-inputs.json
node tests/check-library.mjs verify /protected/library-inputs.json
```

The optional library checker is separate from startup. Use only synthetic documents whose titles start with `Synthetic `. `tokensFile` maps `admin`, `reader` and `denied` to already acquired native API tokens; these are test roles, not required account names. `fixturesDir` contains the retained original/version/rendition files. Keep credentials, expected state and output outside Git. A minimal input shape is:

```json
{
  "url": "https://paperless.example.org",
  "tokensFile": "/protected/tokens.json",
  "expectedFile": "/protected/library-expected.json",
  "fixturesDir": "/protected/originals",
  "files": [{"route": "/api/documents/1/download/?original=true", "file": "example.pdf"}],
  "searches": [{"query": "EXAMPLE", "ids": [1]}],
  "readOnlyDocument": 1
}
```

Add all required versions and renditions. A file can specify `actor` and `deniedActors`; a search can specify `actor`. Run `baseline` before capture and `verify` after each transition with the recovered credentials. Browser SSO/MFA and the responsible person's records-release review remain separate usable-service checks. Exact artifact identities, raw-run results and material verification limits belong in the delivery/integration description, not new per-session reports.

The [GmbH operating profile](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsangebot/README.md#gmbh-betriebsprofil) supplies the initial customer's accepted interruption, data-loss and replacement choices, including permitted nightly capture interruption and a stopped source during replacement checks. Maximum capture pause and staging capacity remain to be set there. These are customer choices, not universal package defaults or a zero-downtime requirement.

The [24 October characterization](../../floriankesslergmbh/floriankesslergmbh/workstreams/betriebsphilosophie/proof/evidence/2026-10-24-paperless-native.json) is historical native-behavior evidence, not a current implementation specification. Its prescriptions for a restricted dispatcher, durable task-denial plans, records reconciliation, custom Redis recovery and multi-store fencing belong to the retired design and are superseded.

Retain the observations: queued work survived replacement in the tested cases; interrupted active work did not settle within the observation window; task revocation did not survive worker replacement. Warm shutdown allowed the tested task to complete but did not independently prove worker/descendant termination. These findings constrain the supported procedure; they do not authorize a replay or reconciliation engine.


## Native sources

- [Exporter](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_exporter.py) and [importer](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_importer.py).
- [Token endpoint](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/paperless/views.py) and [inherited token acquisition](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/views.py).
- [Native folder preparation](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/docker/rootfs/etc/s6-overlay/s6-rc.d/init-folders/run) and [nonrotating token administration](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/management/commands/drf_create_token.py).
