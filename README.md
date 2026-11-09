# Bartlized Paperless

Release 0.1.0 supplies a namespace-local application controller, Helm chart and finite native procedures. Install the public, digest-pinned GHCR artifacts without a source build or manual image import. The [release description](https://codeberg.org/bartlapp/bartl-paperless/pulls/1) records immutable identities, verified behavior and material limits.

The [Bartl application contract](https://codeberg.org/bartlapp/bartl-app/src/branch/main/docs/application-contract.md#application-contract-and-qualification) owns general behavior. [How to bartlize](https://codeberg.org/bartlapp/bartl-app/src/branch/main/docs/how-to-bartlize.md#kubernetes-operating-packages) explains the Kubernetes application-controller model; the [installation operating guide](https://codeberg.org/bartlapp/bartl-app/src/branch/main/docs/how-to-bartlize.md#operate-and-hand-over-an-installation) owns the human-executed cross-application sequence. The [Restic package](https://codeberg.org/bartlapp/bartl-restic/src/branch/main/README.md#service-and-state-boundary) owns backup storage, replication and retention procedures.

Install Bartlized Keycloak 0.5.1 and Restic 0.2.1 independently; neither is a subchart. Paperless publishes to one backup endpoint. The backup service owns replication and retention; `/init`, s6, migrations and the native exporter/importer retain their upstream responsibilities.

## Package and target

The package contains Paperless 3.3.0 and 3.3.1 runtimes, PostgreSQL 17.6, Redis 8.2.1 and Restic 0.19.1. The supported forward transition is 3.3.0 to 3.3.1, both in place and through same-version import followed by native migration. Downgrades, other Paperless versions and PostgreSQL major upgrades are refused or outside this package's supported configuration.

Use Linux amd64 Kubernetes with enforced NetworkPolicy, Helm 3 or 4, and four operator-owned ReadWriteOnce claims: database, broker, application storage and protected staging. The filesystem must support POSIX permissions, file locks, atomic rename and fsync. Native image setup needs root to arrange owned directories; ordinary Paperless services run as upstream's UID 1000. One namespace contains one release named `paperless`, one logical application and no unrelated workloads. The initial profile has one Paperless container and one Celery worker with one processing thread. The qualified placement is one K3s node with local-path volumes, not HA or multi-node RWO scheduling.

Use Traefik in `kube-system` for the supplied ingress policy and an independently supplied TLS Secret. The chart does not provision DNS, certificates, storage or the identity/backup services. Retain exact images, chart, configuration, Paperless secret key, OIDC client settings and backup keys/reader credentials independently of the source installation. API/browser intake and native metadata-assignment workflows form the initial profile; mail polling, remote OCR/AI, custom scripts and externally effective workflows require separate qualification.

The supplied route uses Traefik's HTTPS `websecure` entrypoint only. A minimal Django settings extension sets secure session and CSRF cookies, because these Paperless releases expose no native environment switches for those flags. It otherwise imports upstream settings unchanged; do not override `DJANGO_SETTINGS_MODULE`.

### Published release 0.1.0

The chart pins both Paperless runtimes, controller, PostgreSQL and Redis by immutable digest:

```sh
CHART=oci://ghcr.io/bartlapp/bartl-paperless@sha256:ef2bf48e83bb7b919d85d36d18ad6191373e401c74f03c402e88c749d1601c0d
```

The chart version is `0.1.0`; runtime tags are `3.3.0-0.1.0` and `3.3.1-0.1.0` in `ghcr.io/bartlapp/bartl-paperless-runtime`, and the controller tag is `0.1.0` in `ghcr.io/bartlapp/bartl-paperless-controller`. Use the chart digest above, not a mutable tag, for installation and recovery. Its archive SHA-256 is `dc87e82d5350a4f31850ef801521f836e4567e8ecf81e3a7e319e7935e48dfa8`.

### Installation inputs

Keep the following decisions and effective values in the [customer installation repository](https://codeberg.org/bartlapp/bartl-app/src/branch/main/docs/how-to-bartlize.md#customer-installation-repository), with references to independently protected inputs rather than secrets:

- Exact package artifacts, logical identity, target/storage capabilities, complete Helm values, native configuration and dependency endpoints. Identify who operates Paperless, identity and backup services, and who can authorize replacement and activation.
- Accepted interruption and data-loss limits, capture schedule and drain budget, recovery-point selection, source retirement and route-switch procedure. Settled-work capture interrupts intake and processing; its drain budget is not a maximum outage guarantee.
- Staging capacity, monitoring and cleanup responsibility, retained capture count/size allowance and failure headroom. Captures are not automatically pruned; size staging for retained exports and publication outages rather than assuming one export is enough.
- Required primary/secondary protection, retention and hold rules, permitted source-copy cleanup, and who confirms protection before cleanup. Independently retain sources or holding copies until the required protection is demonstrated.
- The records-review owner, required surviving evidence, review timing and authority to reopen affected access after restore. Identify where later deletion, hold and restriction decisions survive independently of the captured library.
- Useful-service acceptance checks, including restored originals/versions/renditions, permissions, search, OIDC/API access as used, new ingestion and another recoverable backup. Record whether the timestamp-precision limit below is acceptable for the intended records use.

Missing decisions are installation prerequisites, not implied consent to example values. A customer may choose another policy within the supported package boundary; the package does not provide zero-downtime capture, interrupted-ingestion replay or automatic records reconciliation.

Select the intended kubeconfig/context. Prepare namespace `paperless-blue`, four distinct existing claims and protected inputs. Claim names below are examples, not automatically created storage:

```sh
NS=paperless-blue
kubectl config current-context
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
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

The controller starts dependencies and observes database/file state. Only absent local state triggers selection and verification of the latest matching complete backup, same-version preparation/import and any supported forward migration. Before `/init` can reach migrations or ordinary services, the native gate checks ownership and actual container execution. A replacement waits for all predecessor application Pods, including terminating Pods, to disappear; RWO storage and Deployment `Recreate` alone do not prevent overlap after Pod deletion. Recovery needs no second technical release command. Existing state and ordinary restart need no backup access.

### Capture, publication and retry

```sh
REQUEST="manual-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl -n "$NS" annotate paperlessapplication paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl -n "$NS" get paperlessapplication paperless -o json
```

Wait for `status.backup.request` to equal this request and `status.backup.phase` to become `Published`. Inspect the result's `captureOperation`, `capturedAt`, `resumed`, `repositoryID`, full `snapshotID` and `publishedAt`. `BackupFailed=True` is a failed backup, independently of application `Ready`. Scheduled requests enter this same controller path.

Capture stops native admission, drains one responsive worker and its broker queues, then stops writers before an unfiltered export and full member inventory. The native procedure below defines the settled-work boundary and termination checks. Only the same currently permitted execution may resume. A separate writer-scoped Job publishes from read-only staging, restores and byte-checks a candidate, then publishes a complete-tag snapshot of the same tree.

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

Require current-generation `Stopped=True` and no application/native-Job Pods, including terminating Pods. The controller withdraws ingress and confirms Deployment/ReplicaSet drainage; PostgreSQL and Redis may remain for diagnosis. Stop cancels finite work and wins over completion. Interrupted mutation stays failed across later run intent. Export needed logs first because drainage deletes Jobs and their Pods.

A running application continues through controller/API observation loss without lease expiry or a recurring custom supervisor. Each new container execution needs fresh native admission. A submitted stop request or unreachable source is not retirement: while observation/enforcement is unavailable, the old service may continue. Confirm drainage or independent retirement before activating a replacement.

After a completed, nonfailed stop, restart with the same values and `replicas: 1`. For uninstall, keep the controller alive through application finalization:

```sh
kubectl -n "$NS" delete paperlessapplication paperless --wait=true --timeout=10m
helm uninstall paperless -n "$NS" --wait --timeout=5m
kubectl -n "$NS" get pvc,secrets
```

Do not bypass finalizers or delete the namespace/controller first. Finalization drains dependencies, removes controller-owned fixed-name resources and only then releases this CR's claim bindings. Claims, data and operator Secrets survive. Reinstall with the same logical identity, claims and retained inputs and `replicas: 1`; existing-state observation and native startup must succeed. Uninstall does not clear a failed target's durable transition marker. Preserve diagnostics and independently recoverable state, then use fresh storage, not marker deletion or import replay.

For replacement, confirm source retirement and retain any required final/secondary point, then install on fresh claims with the same logical identity/configuration and the surviving repository. Selection binds that repository's full snapshot ID. Upgrade with `version: "3.3.1"` and complete values; never roll software back against migrated data. Before a CRD-changing upgrade, apply the selected package's `crds/`; Helm does not update an existing CRD.

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

Preserve originals and required versions, metadata, ownership/permissions, users/groups and used workflows/configuration. Retain external settings, secrets and evidence of later records decisions independently. Native import rebuilds search; reacquire API tokens as above. Keep native export defaults without filtering harmless extra state. Never discard a rendition under hold.

## Native procedures and failure boundaries

The supported capture boundary is settled work: completed ingestion, no active/reserved/scheduled tasks, and empty broker queues. Interrupted ingestion is not recovered by a custom replay engine. The application has one writer execution; the controller and a target-local file lock exclude conflicting preparation and capture.

Finite preparation uses upstream `init-folders`, the native compatibility check and migrations, then same-version `document_importer`. Native folder preparation matters: the importer expects the search-index directory to exist before rebuilding it. Before import, the worker rejects existing business documents/users, API tokens and document files rather than relying on upstream warnings. Only successful preparation and any subsequent supported migration permit the ordinary `/init` container to start.

The package retains a database/file-store binding and a durable pending-transition marker. They distinguish owned state from absence and prevent partial import or ambiguous capture from turning into ordinary startup. Capture retains that marker until successful same-execution resumption is durably recorded; failed or interrupted resumption therefore remains isolated across container replacement and retained-storage reinstall. A separate s6 prerequisite before migrations and `init-complete` checks the binding and current authority; the upstream custom-init hook alone cannot enforce this because it logs errors and continues. This is not a second native supervisor or recurring schema-certification engine.

Capture stops the native admission services before draining the worker. Writer termination requires both ended UID-1000 processes/descendants and no remaining PostgreSQL client sessions in the owned database. A killed client can leave its database query executing. Export also preserves the native media lock's UID-1000 ownership, so a backup of an empty library cannot break later ingestion. Staging remains root-protected.

The controller binds work to the application, operation, Pod UID, Kubernetes container ID and native execution UUID. Detached capture has a durable admission timestamp and a one-hour execution bound in addition to the configured drain budget. A positively observed unfinished operation beyond that bound fails and is drained; timeout is not proof of termination. Native Jobs have a six-hour outer deadline and no Kubernetes retry. Native command timeouts and the drain budget do not constitute a guaranteed maximum service outage after failure.

Unambiguous capture completion can be observed after controller outage and ordinary container replacement. That only permits publication of the original protected capture; it never permits an old operation to mutate or resume a replacement execution. Missing or ambiguous completion remains failed and isolated. Failed capture/preparation is not repaired by clearing markers, purging queues or replaying tasks. Replace a failed target only when independently retained inputs preserve the required state within the accepted data-loss boundary.

### Backup service interface

The [backup service](https://codeberg.org/bartlapp/bartl-restic/src/branch/main/README.md#service-and-state-boundary) owns replication and retention. Writer credentials are append-only; recovery credentials can read backup contents and create/remove native lock objects. Neither application worker has destructive maintenance credentials. Do not bypass locks or automatically unlock on retry: first establish that the owning native operation has ended.

The complete export directory is the recovery artifact, without another tar/zip layer. Its manifest binds logical identity, native version, capture boundary and every member's length/SHA-256. Only a verified `complete`-tag point is eligible; retention must preserve usable complete points rather than count incomplete candidate snapshots as replacements. Lookup uses strict native object enumeration because `restic snapshots --json` can warn about an unreadable object and omit it while returning success.

Reconstruction binds the selected repository's own identity and full snapshot ID. An independently initialized/copied repository need not retain the source repository or snapshot IDs. Logical identity, supported native version and complete inventory integrity remain mandatory. The [replication contract](https://codeberg.org/bartlapp/bartl-restic/src/branch/main/README.md#replication-mechanism) owns copy correspondence. Repository/credential changes during active native work are not a credential-rotation procedure.


## Source retention

Confirm completed ingestion and a readable original. Keep its source until a capture containing it has been published, verified and protected against the failure declared in the customer installation repository. If that protection requires a secondary, primary publication alone is insufficient; use the backup service's result to establish protection. Paper, email or a device suffices if it survives that failure; otherwise retain a durable holding copy, not a new intake service or receipt ledger.

The result identifies installation, capture boundary, publication/verification completion, exact Restic point and outcome. Publication after upload does not prove inclusion if capture began earlier; check native inventory and original checksums when uncertain. Unsettled ingestion is not covered. Then perform only permitted source-copy cleanup; backup success never authorizes destruction of legally required originals.

After recovery, compare retained sources with the restored library before re-ingesting missing documents. Do not blindly replay or merge records solely because their bytes match.

## Records after restore

An export reflects records at capture, not later deletion, hold or restriction decisions. Its restored audit history cannot supply missing later changes. After technical recovery in isolation, the responsible person checks independently surviving approvals, disposal records, correspondence or newer evidence and applies corrections through native administration before affected use resumes. This is a records-policy review, not a second technical startup authorization; it applies neither to ordinary restart nor nightly capture.

Where evidence is insufficient, keep affected access/processing closed and resolve the exception with the installation's named records owner. Review cannot reconstruct missing information. Use the independently surviving decision evidence and review responsibilities recorded in the [customer installation repository](https://codeberg.org/bartlapp/bartl-app/src/branch/main/docs/how-to-bartlize.md#customer-installation-repository); retain the review result and any unresolved restrictions there, with protected evidence referenced as appropriate. Existing approvals, disposal records and correspondence may suffice; a new decision file is justified only by a demonstrated gap.

## Qualification scope

Native recovery tests on 25 October 2026 restored after source-VM deletion. They checked original/version bytes and relationships, metadata, ownership/permissions, token reacquisition, browser search and a further backup restored into fresh database, file and Redis storage. Export truncates version `added` timestamps from microseconds to milliseconds. This is a package fidelity limit, not a universal records-policy acceptance. The customer must decide whether that precision is sufficient for the intended use before relying on this recovery path; do not use this timestamp alone as identity or order.

Package acceptance additionally checks rendition bytes, user/group/object grants, a used metadata-assignment workflow, rebuilt search, new work and another recoverable point. It exercises the supported 3.3.0-to-3.3.1 transition and Keycloak OIDC/TOTP for an SSO-only user, including token acquisition without local password assignment, rotation or elevation. Paperless-local MFA is not qualified.

Fault cases cover incomplete import, execution replacement, controller absence, failed publication, bounded drainage, damaged history, persistent stop and retained-storage reuse. The lab removes source installations, physical storage directories and the primary repository on one disposable K3s host. This qualifies independent-repository recovery at that boundary, not host/provider-loss failover or cross-cluster fencing.

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

Include all required versions/renditions. Files accept `actor` and `deniedActors`; searches accept `actor`. Run `baseline` before capture and `verify` after each transition with recovered credentials. Browser SSO/MFA and records review remain separate usable-service checks. Record exact artifacts, results and material limits in the delivery/integration description, not session reports.

Installation acceptance records the customer's interruption, data-loss, retention, staging and replacement decisions alongside the exercised useful-service checks. It must account for capture interruption and the time needed for source retirement, recovery, records review and activation. A schedule, drain timeout or passing package test does not establish that the installation meets those accepted limits.

Native-behavior tests on 24 October 2026 explain the settled-work boundary: queued work survived tested replacements, but interrupted active work did not settle within the observation window and revocation did not survive worker replacement. Warm shutdown completed the tested task without independently proving writer/descendant termination. These findings constrain capture; they do not authorize replay or reconciliation.

The experimental supervisor, scripts, chart and records-reconciliation code were retired in `82e4357`, not reused here. Their restricted dispatcher, durable task-denial plans, records reconciliation, custom Redis recovery and multi-store fencing prescriptions are superseded.

## Building and publishing a candidate

Build on a Linux amd64 host with Podman, Skopeo, Helm 3/4, Mike Farah yq 4 and `sha256sum`. Inspect the source/registry access policy and existing versions first; never reuse a published version. Set the selected version in `chart/Chart.yaml`, then build into a fresh directory:

```sh
OUT=/protected/paperless-candidate
OUT="$OUT" bash build.sh
```

The output contains three OCI image directories, a digest-pinned chart, `image-values.yaml`, image digests and `SHA256SUMS`. These are retained build artifacts, not an offline installation product. Qualify that exact chart and those images on the target platform, then publish them from the builder without rebuilding. Keep the original tested candidate until its required artifacts have been durably retained and their identities verified.

After registry login, `REGISTRY_AUTH_FILE` names the protected registry configuration outside Git. Publish only absent version tags:

```sh
RELEASE=$(yq -r '.version' "$OUT/chart/Chart.yaml")
skopeo copy --authfile "$REGISTRY_AUTH_FILE" --preserve-digests \
  "oci:$OUT/paperless-3.3.0" "docker://ghcr.io/bartlapp/bartl-paperless-runtime:3.3.0-$RELEASE"
skopeo copy --authfile "$REGISTRY_AUTH_FILE" --preserve-digests \
  "oci:$OUT/paperless-3.3.1" "docker://ghcr.io/bartlapp/bartl-paperless-runtime:3.3.1-$RELEASE"
skopeo copy --authfile "$REGISTRY_AUTH_FILE" --preserve-digests \
  "oci:$OUT/paperless-controller" "docker://ghcr.io/bartlapp/bartl-paperless-controller:$RELEASE"
helm push "$OUT/bartl-paperless-$RELEASE.tgz" oci://ghcr.io/bartlapp \
  --registry-config "$REGISTRY_AUTH_FILE"
```

New GHCR packages default to private. Enable public access only for the new release packages, without changing existing package or source-repository access. Verify anonymous acquisition, the chart archive checksum, image manifests and actual running images. Retain immutable identities, exercised results and material limits in the release/integration description; raw logs stay outside Git.

## Native sources

- [Exporter](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_exporter.py) and [importer](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_importer.py).
- [Token endpoint](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/paperless/views.py) and [inherited token acquisition](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/views.py).
- [Native folder preparation](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/docker/rootfs/etc/s6-overlay/s6-rc.d/init-folders/run) and [nonrotating token administration](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/management/commands/drf_create_token.py).
