# Bartlized Paperless

Release 0.2.0 supplies a namespace-local application controller, shared-file Helm interface and finite native procedures. Install the public, digest-pinned GHCR artifacts without a source build or manual image import. Release records retain exact identities, exercised behavior and material limits; historical 0.1.0 evidence does not qualify the new configuration procedure.

The [Bartl application contract](https://github.com/bartlapp/bartl-app/blob/main/docs/application-contract.md#application-contract-and-qualification) owns general behavior. [How to bartlize](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md#kubernetes-operating-packages) explains the Kubernetes application-controller model; the [installation operating guide](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md#operate-and-hand-over-an-installation) owns the human-executed cross-application sequence. The [Restic package](https://github.com/bartlapp/bartl-restic/blob/main/README.md#service-and-state-boundary) owns backup storage, replication and retention procedures.

Paperless is an independent release, not a Keycloak or Restic subchart. Compatible external OIDC and HTTPS Restic services suffice; neither Bartl package nor an installation/company repository is required. Paperless publishes to one backup endpoint. That service owns replication and retention; `/init`, s6, migrations and the native exporter/importer retain their upstream responsibilities.

## Package and target

The package contains Paperless 3.3.0 and 3.3.1 runtimes, PostgreSQL 17.6, Redis 8.2.1 and Restic 0.19.1. The supported forward transition is 3.3.0 to 3.3.1, both in place and through same-version import followed by native migration. Downgrades, other Paperless versions and PostgreSQL major upgrades are refused or outside this package's supported configuration.

Use Linux amd64 Kubernetes with enforced NetworkPolicy and four operator-owned ReadWriteOnce claims: database, broker, application storage and protected staging. The operator recipe below uses Helm 4 under the shared workstation requirements. The filesystem must support POSIX permissions, file locks, atomic rename and fsync. Native image setup needs root to arrange owned directories; ordinary Paperless services run as upstream's UID 1000. One namespace contains one release named `paperless`, one logical application and no unrelated workloads. The initial profile has one Paperless container and one Celery worker with one processing thread. The qualified placement is one K3s node with local-path volumes, not HA or multi-node RWO scheduling.

Use Traefik in `kube-system` for the supplied ingress policy. The default TLS path uses cert-manager with a namespace-local ACME Issuer and Certificate; alternatively supply a TLS Secret. The chart does not provision DNS, PVCs or identity/backup services. Retain exact images, chart, effective configuration, Paperless secret key, OIDC client settings and backup keys/reader credentials independently of the source installation. API/browser intake and native metadata-assignment workflows form the supported profile; mail polling, remote OCR/AI, custom scripts and externally effective workflows require separate qualification.

The supplied route uses Traefik's HTTPS `websecure` entrypoint only. A minimal Django settings extension sets secure session and CSRF cookies, because these Paperless releases expose no native environment switches for those flags. It otherwise imports upstream settings unchanged; do not override `DJANGO_SETTINGS_MODULE`.

### Obtain release 0.2.0

Use the [operator workstation](https://github.com/bartlapp/bartl-app/blob/main/docs/operator-workstation.md) with Bash, Helm 4.x (minimum supported recipe version 4.3.0), kubectl compatible with the target, Mike Farah yq v4, jq, curl, OpenSSL 3, dig and shasum. The workstation guide selects the current installation version; historical qualification retains the version actually exercised. Keep shell tracing off. Reuse the installation's exported absolute `VALUES` and `WORK_DIR` in every package terminal. For a new installation only, the defaults below create its one shared file; the public artifacts need no registry login or source checkout:

```bash
set -euo pipefail
umask 077
INSTALLATION_ID=${INSTALLATION_ID:-acme}
WORK_DIR=${WORK_DIR:-"$HOME/bartl/$INSTALLATION_ID"}
mkdir -p "$WORK_DIR"
WORK_DIR=$(cd "$WORK_DIR" && pwd -P)
export WORK_DIR VALUES="${VALUES:-$WORK_DIR/installation.yaml}"
case "$VALUES" in /*) ;; *) printf 'VALUES must be absolute\n' >&2; exit 1 ;; esac
mkdir -p "$WORK_DIR/packages"
```

Retain the selected archive and the expected `packages.<package>.chartSha256` in `installation.yaml` outside the target's failure domain. The selection block below acquires and verifies that archive; its immutable OCI manifest is recorded with the release. The source/release-record repository may require access, but obtaining the public GHCR chart and images does not. Release 0.2.0 changes the chart only: it reuses immutable 0.1.0 controller/runtime image digests instead of rebuilding them under new tags.

For the historical upgrade baseline, retain chart 0.1.0 separately: OCI `oci://ghcr.io/bartlapp/bartl-paperless@sha256:ef2bf48e83bb7b919d85d36d18ad6191373e401c74f03c402e88c749d1601c0d`, archive SHA-256 `dc87e82d5350a4f31850ef801521f836e4567e8ecf81e3a7e319e7935e48dfa8`. Its flat values interface is historical, not accepted by 0.2.0.

### Installation inputs

Keep the following decisions and effective values in independently accessible [installation inputs](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md#installation-inputs), with references to protected inputs rather than secrets. A working directory suffices; creating an installation repository is optional:

- Exact package artifacts, logical identity, target/storage capabilities, complete Helm values, native configuration and dependency endpoints. Identify who operates Paperless, identity and backup services, and who can authorize replacement and activation.
- Accepted interruption and data-loss limits, capture schedule and drain budget, recovery-point selection, source retirement and route-switch procedure. Settled-work capture interrupts intake and processing; its drain budget is not a maximum outage guarantee.
- Staging capacity, monitoring and cleanup responsibility, retained capture count/size allowance and failure headroom. Captures are not automatically pruned; size staging for retained exports and publication outages rather than assuming one export is enough.
- Required primary/secondary protection, retention and hold rules, permitted source-copy cleanup, and who confirms protection before cleanup. Independently retain sources or holding copies until the required protection is demonstrated.
- The records-review owner, required surviving evidence, review timing and authority to reopen affected access after restore. Identify where later deletion, hold and restriction decisions survive independently of the captured library.
- Useful-service acceptance checks, including restored originals/versions/renditions, permissions, search, OIDC/API access as used, new ingestion and another recoverable backup. Record whether the timestamp-precision limit below is acceptable for the intended records use.

Missing decisions are installation prerequisites, not implied consent to example values. A customer may choose another policy within the supported package boundary; the package does not provide zero-downtime capture, interrupted-ingestion replay or automatic records reconciliation.

### Select the target and shared file

The [base-k3s recipe](https://github.com/bartlapp/base-k3s/blob/main/README.md#what-this-recipe-delivers), completed through its handover checks, supplies the supported single-node base. Retain its absolute exported `KUBECONFIG` in every terminal. Any equivalent cluster meeting the prerequisites above suffices. Confirm available disk/memory and expected reconstruction/staging capacity before deployment; a default StorageClass does not establish capacity.

```bash
test -f "$VALUES" || printf '{}\n' > "$VALUES"
INSTALLATION_ID="$INSTALLATION_ID" WORK_DIR="$WORK_DIR" yq -i '
  .installation = (.installation // strenv(INSTALLATION_ID)) |
  .dns.root = (.dns.root // "acme.fke.systems") |
  .services.paperless.release = (.services.paperless.release // "0.2.0") |
  .packages.paperless = (.packages.paperless // {
    "version": "0.2.0", "chart": "oci://ghcr.io/bartlapp/bartl-paperless",
    "chartSha256": "4c6df6106efb35b2c4a25e4bb77d7ad98765572154dbcd380a9742f20bfac5c9"}) |
  .deployments.paperless = (.deployments.paperless // {
    "instance": "paperless", "cluster": "blue", "namespace": "paperless-blue",
    "release": "paperless", "package": "paperless"})
' "$VALUES"
```

Retain the target context in `clusters.<cluster>.kubeconfig.context` using base handover or an equivalent cluster. Supply protected `KUBECONFIG` or use the cluster-derived local file; do not store a workstation path in inventory or substitute the terminal's current context on resume:

```bash
DEPLOYMENT=${DEPLOYMENT:-paperless}
INSTANCE=$(DEPLOYMENT="$DEPLOYMENT" yq -er '.deployments[strenv(DEPLOYMENT)].instance' "$VALUES")
HELM_INSTANCE=${INSTANCE//./\\.}
CLUSTER=$(DEPLOYMENT="$DEPLOYMENT" yq -er '.deployments[strenv(DEPLOYMENT)].cluster' "$VALUES")
NS=$(DEPLOYMENT="$DEPLOYMENT" yq -er '.deployments[strenv(DEPLOYMENT)].namespace' "$VALUES")
RELEASE=$(DEPLOYMENT="$DEPLOYMENT" yq -er '.deployments[strenv(DEPLOYMENT)].release' "$VALUES")
PACKAGE=$(DEPLOYMENT="$DEPLOYMENT" yq -er '.deployments[strenv(DEPLOYMENT)].package' "$VALUES")
if [ -z "${ACCESS_CLUSTER:-}" ]; then
  ACCESS_CLUSTER="$CLUSTER"
  ACCESS_FILE=${KUBECONFIG:-}
fi
if [ "$CLUSTER" = "$ACCESS_CLUSTER" ] && [ -n "$ACCESS_FILE" ]; then
  export KUBECONFIG="$ACCESS_FILE"
else
  export KUBECONFIG="$WORK_DIR/clusters/$CLUSTER/base/kubeconfig"
fi

# ACCESS_FILE remains bound to ACCESS_CLUSTER; another target uses its own base file.
# To supply a different protected access file, set both variables for that cluster.
CTX=$(CLUSTER="$CLUSTER" yq -er '.clusters[strenv(CLUSTER)].kubeconfig.context' "$VALUES")
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" config view --minify >/dev/null
VERSION=$(PACKAGE="$PACKAGE" yq -er '.packages[strenv(PACKAGE)].version' "$VALUES")
CHART="$WORK_DIR/packages/bartl-paperless-$VERSION.tgz"
CHART_REF=$(PACKAGE="$PACKAGE" yq -er '.packages[strenv(PACKAGE)].chart' "$VALUES")
CHART_SHA256=$(PACKAGE="$PACKAGE" yq -er '.packages[strenv(PACKAGE)].chartSha256' "$VALUES")
if [ ! -f "$CHART" ]; then helm pull "$CHART_REF" --version "$VERSION" --destination "$WORK_DIR/packages"; fi
printf '%s  %s\n' "$CHART_SHA256" "$CHART" | shasum -a 256 --check -
test "$RELEASE" = paperless # This package owns fixed-name resources.
INSTALL_DIR="$WORK_DIR/clusters/$CLUSTER/applications/$INSTANCE"
if [ "$DEPLOYMENT" != "$INSTANCE" ]; then INSTALL_DIR="$INSTALL_DIR/deployments/$DEPLOYMENT"; fi
mkdir -p "$INSTALL_DIR/protected"
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" get nodes,storageclass
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" create namespace "$NS" --dry-run=client -o yaml |
  kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" apply -f -
```

Placement-local intent is retained separately from stable service choices. Derive optional Helm arguments after selecting a deployment and again after changing its ingress intent:

```bash
INGRESS=$(DEPLOYMENT="$DEPLOYMENT" yq -r '.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled | select(. != null)' "$VALUES")
HELM_ARGS=()
if [ -n "$INGRESS" ]; then HELM_ARGS+=(--set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS"); fi
```

The DNS root derives the hostname, native version 3.3.1, one replica and the four claim/Secret names used below. Explicit `services.paperless.hostname` overrides the DNS rule; removing it restores derivation. Another logical instance uses its own service key and deployment entry, retaining Helm release `paperless`. `--set-string instance="$INSTANCE"` selects the service; it does not rename a release. The chart refuses a selected `release` differing from its chart version. Shared infrastructure and unrelated services are ignored; selected service fields are strict. Keep protected files independently recoverable; when using a password store, use the store named by `credentials.passStore` and stable `applications/<instance>/...` entries. Supplied protected files remain sufficient; no password store is required.

Advanced controller/image overrides belong inside `services.<instance>`, not at the file root. Keep the supported pinned defaults unless qualifying a deliberate change. Installation and instance identity and claim names are immutable; retain them during reconstruction, independently of namespace, CR UID and PVC annotations.

### Declare connections and create storage

Declarations are finite, nonsecret, offline output: they neither contact a provider nor provision clients, credentials or repositories. Render before deploying either application and rerender after changing choices:

```bash
helm template paperless "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" "${HELM_ARGS[@]}" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
cat "$INSTALL_DIR/paperless-connections.yaml"
```

The declaration reports HTTPS access, OIDC consumer/client/callback requirements when selected, credential origins and Kubernetes Secret bindings, backup requirements and the four storage requirements. Use these public fields for preparation, not internal `PaperlessApplication` scraping.

Public paths are `services.<instance>.endpoints.https.{url,hostname,ingressClass,tlsManaged}`, `oidc.requests.<instance>.{enabled,provider,issuer,clientId,providerId,name,redirectUris,webOrigins}`, `backup.requests.<instance>`, `credentials.{requirements,bindings}.<instance>` and `storage.claims.<instance>.<role>.claimName`. Composition declares `provider`; standalone OIDC declares its `issuer` directly. Secret keys and credential sources travel with the chart.

Unreleased source correction: `backup.requests.<instance>.enabled` consistently means eligibility for connection preparation: omission is eligible, explicit `backup.enabled: false` opts out. Conditional reader/writer requirements describe what a selected backup needs, not credentials to create for an unbound application. Standalone deployment without a destination still has no backup; `enabled: true` in service choices requires a destination. Released 0.2.0 declares an omitted choice ineligible; the correction needs a new chart release and is not covered by that release's qualification.

```bash
PAPERLESS_URL=$(INSTANCE="$INSTANCE" yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(INSTANCE="$INSTANCE" yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
```

For the example defaults, create four distinct operator-owned PVCs. These disposable-lab sizes are choices, not a production sizing promise: staging must hold retained complete exports plus failed-publication headroom. Adjust sizes and, if necessary, `storageClassName` before creation. A `WaitForFirstConsumer` class may leave claims Pending until the application is scheduled.

```bash
for entry in paperless-data:10Gi paperless-db:5Gi paperless-broker:1Gi paperless-staging:20Gi; do
  name=${entry%:*}; size=${entry#*:}
  kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $name
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: $size
EOF
done
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" get pvc
```

Override claim names under `services.<instance>.claims.{storage,database,broker,staging}` and create those names instead if required. Never attach a replacement to a live predecessor's storage.

### HTTPS and optional dependencies

Point the declared HTTPS hostname to your cluster ingress address at your DNS provider. With the base recipe, obtain it using `kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n kube-system get service traefik -o wide`; confirm authoritative and public `dig` answers match before expecting ACME. Permit public ports 80/443. Default `tls.managed: true` creates namespace-local `paperless-letsencrypt` Issuer and Certificate using Let's Encrypt production HTTP-01 through Traefik. `services.<instance>.tls.acmeServer` can select staging; staging is not browser-trusted. cert-manager owns renewal.

For external TLS, set `services.<instance>.tls.managed: false` and create the selected `ingress.tlsSecret` (default `paperless-tls`) from independently retained certificate/key:

```bash
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" create secret tls paperless-tls \
  --cert=/protected/tls/fullchain.pem --key=/protected/tls/key.pem \
  --dry-run=client -o yaml | kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" apply -f -
```

Retain external TLS mode for an existing manually managed Certificate; an upgrade must not silently adopt it. `ingress.enabled: false` withholds routing without disabling managed certificate preparation.

**External identity (optional).** For a compatible OIDC provider, set `services.<instance>.oidc.issuer` to its supplied issuer. Optional `clientId`, `providerId` and `name` default to the instance, `keycloak` and `Keycloak`. Rerender declarations, register exactly the declared client/callback at that provider and retain the issued client secret as `"$INSTALL_DIR/protected/oidc-client-secret"` with no newline. Never put it in values or regenerate it on replay. Without OIDC selection no identity service is required. For Bartlized Keycloak composition use the next section instead of constructing a `resolved` binding manually.

**External backup (optional).** Set `services.<instance>.backup.repository`, for example `rest:https://backup.example/learning-lab-paperless/`, for an initialized HTTPS Restic repository. No `resolved` section or Bartlized Restic is needed. Supply independently retained repository key and scoped access under `"$INSTALL_DIR/protected/backup/reader/"` and `writer/`; each directory contains `password` (the same encryption key), `username`, `restPassword` and optionally `ca.crt` for a private CA. Reader access may write/remove native lock objects but not backup contents; writer access must be append-only. Never use maintenance/admin access. Do not generate a new key for an existing repository.

```bash
for role in reader writer; do
  kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" create secret generic "paperless-backup-$role" \
    --from-file="$INSTALL_DIR/protected/backup/$role/" --dry-run=client -o yaml |
    kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" apply -f -
done
```

Run that block only when enabling backup. Secret-name overrides are `backup.readerSecret` and `backup.writerSecret`; use the names in declarations. Omit backup entirely for no store; explicit `backup.enabled: false` disables it. `backup.schedule` defaults to empty (manual capture only), `timeZone` to `UTC` and `drainSeconds` to 300. A schedule or drain budget is not an outage guarantee. Configure endpoint protection, retention and replication independently against the accepted failure boundary.

For optional backup-service composition, `services.<instance>.backup.endpoint` selects a named provider instead of a direct `repository`. Preparation must initialize a dedicated repository there and supply `resolved.backup.bindings.<instance>` with matching `endpoint`, `repository` and optional `enabled`, `readerSecret`, `writerSecret`. This is the same nonsecret binding shape as Keycloak; reader/writer protected inputs remain separate. Never set both `endpoint` and `repository` in service choices. Direct external `backup.repository` above is the complete standalone path and needs none of this cross-service preparation.

### Prepare retained credentials and native configuration

For recovery, copy independently retained credentials into the protected directory first. Never generate a new `PAPERLESS_SECRET_KEY` for a restored library. This fresh-initialization block creates missing values once and preserves them on repetition; credential rotation is separate:

```bash
for key in secret-key database-password bootstrap-password; do
  file="$INSTALL_DIR/protected/$key"
  if [ -e "$file" ]; then
    test -s "$file" || { printf 'Empty retained credential: %s\n' "$file" >&2; exit 1; }
  else
    (set -o noclobber; openssl rand -hex 32 | tr -d '\n' > "$file")
  fi
done
```

The bootstrap account is used only for an empty installation without a selected backup, never existing state/import. Do not put bootstrap settings, database host/name/user, broker URL, concurrency overrides or custom-init/consume scripts in the configuration Secret: the controller owns that topology. The package's configuration rendering below supplies derived native environment values; the operator does not invent allauth JSON.

### Optional: compose with independently released Keycloak

Skip this section for no OIDC or a compatible external provider. This fresh Keycloak example needs no source checkout or backup service. An existing/recovered provider uses its retained deployment configuration and current administrator credentials; never generate replacements for restored credentials. The current [Keycloak operating procedure](https://github.com/bartlapp/bartl-keycloak/blob/main/README.md) owns lifecycle, backup/recovery and administrative limits for its selected immutable release. Select its deployment against this same absolute `"$VALUES"`; do not repeat an older tagged README's working-directory or file-creation example. The fresh composition below uses Keycloak 0.6.1:

```bash
KC_DEPLOYMENT=${KC_DEPLOYMENT:-keycloak}
KC_DEPLOYMENT="$KC_DEPLOYMENT" CLUSTER="$CLUSTER" INSTANCE="$INSTANCE" yq -i '
  .packages.keycloak = (.packages.keycloak // {
    "version": "0.6.1", "chart": "oci://ghcr.io/bartlapp/bartl-keycloak",
    "chartSha256": "7abb55bcefbcde70dc8f29309d508d314a48783547067b529d48617d23c9225a"}) |
  .deployments[strenv(KC_DEPLOYMENT)] = (.deployments[strenv(KC_DEPLOYMENT)] // {
    "instance": "keycloak", "cluster": strenv(CLUSTER),
    "namespace": "keycloak-blue", "release": "keycloak", "package": "keycloak"}) |
  .services.keycloak.release = (.services.keycloak.release // "0.6.1")
' "$VALUES"
KC_INSTANCE=$(KC_DEPLOYMENT="$KC_DEPLOYMENT" yq -er '.deployments[strenv(KC_DEPLOYMENT)].instance' "$VALUES")
KC_CLUSTER=$(KC_DEPLOYMENT="$KC_DEPLOYMENT" yq -er '.deployments[strenv(KC_DEPLOYMENT)].cluster' "$VALUES")
KC_INSTANCE="$KC_INSTANCE" INSTANCE="$INSTANCE" yq -i '
  .services[strenv(INSTANCE)].identityProvider = (.services[strenv(INSTANCE)].identityProvider // strenv(KC_INSTANCE))
' "$VALUES"
INSTANCE="$INSTANCE" KC_INSTANCE="$KC_INSTANCE" yq -e '
  .services[strenv(INSTANCE)].identityProvider == strenv(KC_INSTANCE) and
  .services[strenv(INSTANCE)].oidc.issuer == null
' "$VALUES" >/dev/null
KC_NS=$(KC_DEPLOYMENT="$KC_DEPLOYMENT" yq -er '.deployments[strenv(KC_DEPLOYMENT)].namespace' "$VALUES")
KC_RELEASE=$(KC_DEPLOYMENT="$KC_DEPLOYMENT" yq -er '.deployments[strenv(KC_DEPLOYMENT)].release' "$VALUES")
KC_PACKAGE=$(KC_DEPLOYMENT="$KC_DEPLOYMENT" yq -er '.deployments[strenv(KC_DEPLOYMENT)].package' "$VALUES")
KC_CTX=$(CLUSTER="$KC_CLUSTER" yq -er '.clusters[strenv(CLUSTER)].kubeconfig.context' "$VALUES")
if [ -z "${KC_ACCESS_CLUSTER:-}" ]; then
  KC_ACCESS_CLUSTER="$KC_CLUSTER"
  KC_ACCESS_FILE=${KC_KUBECONFIG:-}
  if [ "$KC_CLUSTER" = "$CLUSTER" ] && [ -z "$KC_ACCESS_FILE" ]; then KC_ACCESS_FILE="$KUBECONFIG"; fi
fi
if [ "$KC_CLUSTER" = "$KC_ACCESS_CLUSTER" ] && [ -n "$KC_ACCESS_FILE" ]; then
  KC_KUBECONFIG="$KC_ACCESS_FILE"
else
  KC_KUBECONFIG="$WORK_DIR/clusters/$KC_CLUSTER/base/kubeconfig"
fi
KC_VERSION=$(PACKAGE="$KC_PACKAGE" yq -er '.packages[strenv(PACKAGE)].version' "$VALUES")
KC_CHART="$WORK_DIR/packages/bartl-keycloak-$KC_VERSION.tgz"
KC_CHART_REF=$(PACKAGE="$KC_PACKAGE" yq -er '.packages[strenv(PACKAGE)].chart' "$VALUES")
KC_CHART_SHA256=$(PACKAGE="$KC_PACKAGE" yq -er '.packages[strenv(PACKAGE)].chartSha256' "$VALUES")
if [ ! -f "$KC_CHART" ]; then helm pull "$KC_CHART_REF" --version "$KC_VERSION" --destination "$WORK_DIR/packages"; fi
printf '%s  %s\n' "$KC_CHART_SHA256" "$KC_CHART" | shasum -a 256 --check -
test "$KC_RELEASE" = keycloak
KC_DIR="$WORK_DIR/clusters/$KC_CLUSTER/applications/$KC_INSTANCE"
if [ "$KC_DEPLOYMENT" != "$KC_INSTANCE" ]; then KC_DIR="$KC_DIR/deployments/$KC_DEPLOYMENT"; fi
mkdir -p "$KC_DIR"
KC_HELM_INSTANCE=${KC_INSTANCE//./\\.}
KC_INTENT_ARGS=()
for field in replicas:application.replicas ingressEnabled:ingress.enabled maintenance:ingress.maintenance backupSuspend:backup.suspend; do
  value=$(DEPLOYMENT="$KC_DEPLOYMENT" FIELD="${field%%:*}" yq -r '.operations.deployments[strenv(DEPLOYMENT)][strenv(FIELD)] | select(. != null)' "$VALUES")
  [ -z "$value" ] || KC_INTENT_ARGS+=(--set "services.$KC_HELM_INSTANCE.${field#*:}=$value")
done
kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" config view --minify >/dev/null
helm template keycloak "$KC_CHART" -n "$KC_NS" -f "$VALUES" \
  --set-string instance="$KC_INSTANCE" --set-string "services.$KC_HELM_INSTANCE.release=$KC_VERSION" "${KC_INTENT_ARGS[@]}" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$KC_DIR/keycloak-connections.yaml"
helm template paperless "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" "${HELM_ARGS[@]}" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
```

Declarations work before Keycloak runs and before `resolved` exists. A selected provider does not deploy it implicitly. For fresh Keycloak only, create missing credentials once, preserving retained files, then create the declared Secrets. Keycloak provisions its own database claim (default 5Gi) through the same StorageClass:

```bash
(
  set -euo pipefail
  umask 077
  KC_PROTECTED="$KC_DIR/protected"
  mkdir -p "$KC_PROTECTED/database" "$KC_PROTECTED/database-admin" "$KC_PROTECTED/bootstrap"
  keep_input() {
    local file="$1" fixed="$2"
    if [ -e "$file" ]; then
      test -s "$file"
      if [ -n "$fixed" ]; then
        test "$(cat "$file")" = "$fixed" || {
          printf 'Retained value conflicts with fresh example: %s\n' "$file" >&2
          return 1
        }
      fi
    elif [ -n "$fixed" ]; then
      (set -o noclobber; printf '%s' "$fixed" > "$file")
    else
      (set -o noclobber; openssl rand -hex 32 | tr -d '\n' > "$file")
    fi
  }
  keep_input "$KC_PROTECTED/database/username" keycloak
  keep_input "$KC_PROTECTED/database/database" keycloak
  keep_input "$KC_PROTECTED/database/password" ""
  keep_input "$KC_PROTECTED/database-admin/username" postgres
  keep_input "$KC_PROTECTED/database-admin/password" ""
  keep_input "$KC_PROTECTED/bootstrap/username" admin
  keep_input "$KC_PROTECTED/bootstrap/password" ""
  mkdir -p "$INSTALL_DIR/protected/keycloak-admin"
  for key in username password; do
    retained="$INSTALL_DIR/protected/keycloak-admin/$key"
    if [ -e "$retained" ]; then
      cmp -s "$retained" "$KC_PROTECTED/bootstrap/$key" || {
        printf 'Retained administrator differs; use the existing-provider path.\n' >&2
        exit 1
      }
    else
      (set -o noclobber; cat "$KC_PROTECTED/bootstrap/$key" > "$retained")
    fi
  done
  kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" create namespace "$KC_NS" --dry-run=client -o yaml |
    kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" apply -f -
  for pair in database:database database-admin:databaseAdmin bootstrap:bootstrapAdmin; do
    directory=${pair%%:*}; role=${pair#*:}
    name=$(KC_INSTANCE="$KC_INSTANCE" ROLE="$role" yq -er \
      '.credentials.bindings[strenv(KC_INSTANCE)][strenv(ROLE)].secretName' \
      "$KC_DIR/keycloak-connections.yaml")
    kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" -n "$KC_NS" create secret generic "$name" \
      --from-file="$KC_PROTECTED/$directory/" --dry-run=client -o yaml |
      kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" apply -f -
  done
)
KC_HOST=$(KC_INSTANCE="$KC_INSTANCE" yq -er '.services[strenv(KC_INSTANCE)].endpoints.https.hostname' "$KC_DIR/keycloak-connections.yaml")
```

Point `"$KC_HOST"` to the ingress address and verify DNS as for Paperless. The default namespace-local managed certificate uses the same cert-manager/Traefik prerequisites. Retain both sets of protected credentials outside the cluster before relying on either application. Deploy the independent Keycloak release:

```bash
helm upgrade --install "$KC_RELEASE" "$KC_CHART" --kubeconfig "$KC_KUBECONFIG" --kube-context "$KC_CTX" -n "$KC_NS" \
  -f "$VALUES" --set-string instance="$KC_INSTANCE" --set-string "services.$KC_HELM_INSTANCE.release=$KC_VERSION" \
  "${KC_INTENT_ARGS[@]}" --wait=legacy --timeout=5m
KC_GENERATION=$(kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" -n "$KC_NS" get keycloakapplication keycloak -o jsonpath='{.metadata.generation}')
kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" -n "$KC_NS" wait keycloakapplication/keycloak \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$KC_GENERATION" --timeout=30m
kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" -n "$KC_NS" wait --for=condition=Ready \
  keycloakapplication/keycloak --timeout=30m
if KC_INSTANCE="$KC_INSTANCE" yq -e '.services[strenv(KC_INSTANCE)].endpoints.https.tlsManaged' \
  "$KC_DIR/keycloak-connections.yaml" >/dev/null; then
  KC_TLS_SECRET=$(KC_INSTANCE="$KC_INSTANCE" yq -er \
    '.credentials.bindings[strenv(KC_INSTANCE)].tls.secretName' "$KC_DIR/keycloak-connections.yaml")
  kubectl --kubeconfig "$KC_KUBECONFIG" --context "$KC_CTX" -n "$KC_NS" wait "certificate/$KC_TLS_SECRET" \
    --for=condition=Ready --timeout=10m
fi
```

Check Keycloak's current-generation readiness, certificate readiness and administration console before provisioning the consumer. Connect public declarations without rebuilding the provider issuer or copying data out of an internal CR:

```bash
KC_URL=$(KC_INSTANCE="$KC_INSTANCE" yq -er '.services[strenv(KC_INSTANCE)].endpoints.https.url' "$KC_DIR/keycloak-connections.yaml")
OIDC_ISSUER=$(KC_INSTANCE="$KC_INSTANCE" yq -er '.services[strenv(KC_INSTANCE)].oidc.issuer' "$KC_DIR/keycloak-connections.yaml")
OIDC_CLIENT_ID=$(INSTANCE="$INSTANCE" yq -er '.oidc.requests[strenv(INSTANCE)].clientId' "$INSTALL_DIR/paperless-connections.yaml")
INSTANCE="$INSTANCE" KC_INSTANCE="$KC_INSTANCE" OIDC_ISSUER="$OIDC_ISSUER" \
OIDC_CLIENT_ID="$OIDC_CLIENT_ID" yq -i '
  .resolved.oidc.bindings[strenv(INSTANCE)] = {
    "provider": strenv(KC_INSTANCE),
    "issuer": strenv(OIDC_ISSUER),
    "clientId": strenv(OIDC_CLIENT_ID)
  }
' "$VALUES"
```

`resolved.oidc.bindings.<instance>` holds nonsecret connection results, not operator overrides. `provider` must match `identityProvider`; `issuer` is required and `clientId` may be omitted to use the instance. No `clientSecretFile` or secret belongs in values. Refresh bindings when provider/consumer choices change. Deployment/configuration refuse missing or mismatched selected bindings; declarations remain renderable.

Use native Keycloak Admin REST below. Supply `"$INSTALL_DIR/protected/keycloak-admin/username"` and `password` for a current authorized master-realm administrator with `admin-cli` password grant usable without interactive required actions. These credentials are preparation-only; never mount them in Paperless. Administrative authorization must cover realm/client creation, client read and secret retrieval. The block creates only an absent declared realm; an existing realm and its users are never reset. Assign users and MFA through native Keycloak administration.

```bash
(
  set -euo pipefail
  umask 077
  ADMIN_DIR="$INSTALL_DIR/protected/keycloak-admin"
  WORK=$(mktemp -d "$INSTALL_DIR/protected/keycloak-client.XXXXXX")
  trap 'rm -rf "$WORK"' EXIT
  curl --fail-with-body --silent --show-error \
    "$KC_URL/realms/master/protocol/openid-connect/token" \
    --data-urlencode client_id=admin-cli --data-urlencode grant_type=password \
    --data-urlencode "username@$ADMIN_DIR/username" \
    --data-urlencode "password@$ADMIN_DIR/password" > "$WORK/token.json"
  TOKEN=$(jq -er '.access_token | select(length > 0)' "$WORK/token.json")
  kc_admin() {
    printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
      curl --config - --fail-with-body --silent --show-error "$@"
  }
  REALM=${OIDC_ISSUER##*/}
  REALM_PATH=$(jq -nr --arg realm "$REALM" '$realm | @uri')
  ADMIN_URL="$KC_URL/admin/realms/$REALM_PATH"
  kc_admin "$KC_URL/admin/realms" > "$WORK/realms.json"
  REALM_COUNT=$(jq --arg realm "$REALM" '[.[] | select(.realm == $realm)] | length' "$WORK/realms.json")
  if [ "$REALM_COUNT" = 0 ]; then
    jq -n --arg realm "$REALM" '{realm: $realm, enabled: true}' > "$WORK/realm.json"
    kc_admin --request POST "$KC_URL/admin/realms" \
      --header 'Content-Type: application/json' --data-binary "@$WORK/realm.json"
  else
    jq -e --arg realm "$REALM" '
      [.[] | select(.realm == $realm)] | length == 1 and .[0].enabled == true
    ' "$WORK/realms.json" >/dev/null
  fi
  INSTANCE="$INSTANCE" yq -o=json '.oidc.requests[strenv(INSTANCE)]' \
    "$INSTALL_DIR/paperless-connections.yaml" |
    jq '{
      clientId, redirectUris, webOrigins, protocol: "openid-connect",
      enabled: true, publicClient: false, standardFlowEnabled: true,
      directAccessGrantsEnabled: false, implicitFlowEnabled: false,
      serviceAccountsEnabled: false,
      attributes: {"pkce.code.challenge.method": "S256"}
    }' > "$WORK/desired-client.json"
  kc_admin --get "$ADMIN_URL/clients" \
    --data-urlencode "clientId=$OIDC_CLIENT_ID" > "$WORK/clients.json"
  COUNT=$(jq --arg id "$OIDC_CLIENT_ID" '[.[] | select(.clientId == $id)] | length' "$WORK/clients.json")
  if [ "$COUNT" = 0 ]; then
    kc_admin --request POST "$ADMIN_URL/clients" \
      --header 'Content-Type: application/json' --data-binary "@$WORK/desired-client.json"
    kc_admin --get "$ADMIN_URL/clients" \
      --data-urlencode "clientId=$OIDC_CLIENT_ID" > "$WORK/clients.json"
  fi
  CLIENT_UUID=$(jq -er --arg id "$OIDC_CLIENT_ID" '
    [.[] | select(.clientId == $id)] |
    if length == 1 then .[0].id else error("Expected exactly one client") end
  ' "$WORK/clients.json")
  kc_admin "$ADMIN_URL/clients/$CLIENT_UUID" > "$WORK/current-client.json"
  jq -e --slurpfile desired "$WORK/desired-client.json" '
    . as $actual | $desired[0] |
    .clientId == $actual.clientId and .protocol == $actual.protocol and
    .redirectUris == $actual.redirectUris and .webOrigins == $actual.webOrigins and
    .enabled == $actual.enabled and .publicClient == $actual.publicClient and
    .standardFlowEnabled == $actual.standardFlowEnabled and
    .directAccessGrantsEnabled == ($actual.directAccessGrantsEnabled // false) and
    .implicitFlowEnabled == ($actual.implicitFlowEnabled // false) and
    .serviceAccountsEnabled == ($actual.serviceAccountsEnabled // false) and
    .attributes["pkce.code.challenge.method"] == $actual.attributes["pkce.code.challenge.method"]
  ' "$WORK/current-client.json" >/dev/null || {
    printf 'Existing client differs; review instead of overwriting it.\n' >&2
    exit 1
  }
  # GET retrieves the existing secret; POST would rotate it and is deliberately absent.
  kc_admin "$ADMIN_URL/clients/$CLIENT_UUID/client-secret" > "$WORK/client-secret.json"
  jq -erj '.value | select(type == "string" and length > 0)' \
    "$WORK/client-secret.json" > "$WORK/client-secret"
  RETAINED="$INSTALL_DIR/protected/oidc-client-secret"
  if [ -e "$RETAINED" ]; then
    cmp -s "$RETAINED" "$WORK/client-secret" || {
      printf 'Issued secret conflicts with retained secret; coordinate rotation/recovery.\n' >&2
      exit 1
    }
  else
    (set -o noclobber; cat "$WORK/client-secret" > "$RETAINED")
  fi
)
```

Replay retrieves and retains the same secret, never silently resets it. Conflicting client settings or retained secrets stop preparation. Reconcile deliberately with the identity operator; do not delete/recreate a restored client to bypass refusal.

For a synthetic acceptance user, open `"$KC_URL/admin/"`, select the declared realm, create an enabled user, set its provider-side password and add the native **Configure OTP** required action. On first Paperless SSO login, enroll TOTP and retain recovery material through the protected channel. Log out completely and require password plus TOTP on a new login. Use the installation's approved MFA policy for real users; test-user creation and enrollment are not startup dependencies.

### Render configuration and create Secrets

This applies equally to no OIDC, standalone external OIDC and composition. Configuration rendering is finite and offline but requires any selected provider binding. Its YAML output is `configuration.<instance>.secretName` and `environment` (native string values). With OIDC, `PAPERLESS_SOCIALACCOUNT_PROVIDERS` is native JSON serialized as a string, deliberately lacking `openid_connect.APPS[0].secret`, and `oidc.clientSecretRequired` is true. Assemble that mapping with protected inputs before deployment:

```bash
helm template paperless "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" "${HELM_ARGS[@]}" --set-string renderMode=configuration \
  --show-only templates/configuration.yaml > "$INSTALL_DIR/configuration.yaml"
CONFIG_SECRET=$(INSTANCE="$INSTANCE" yq -er '.configuration[strenv(INSTANCE)].secretName' "$INSTALL_DIR/configuration.yaml")
INSTANCE="$INSTANCE" yq -o=json '.configuration[strenv(INSTANCE)]' \
  "$INSTALL_DIR/configuration.yaml" > "$INSTALL_DIR/configuration.json"
(
  set -euo pipefail
  umask 077
  jq --rawfile secretKey "$INSTALL_DIR/protected/secret-key" \
    --rawfile dbPassword "$INSTALL_DIR/protected/database-password" '
    .environment + {
      PAPERLESS_SECRET_KEY: ($secretKey | rtrimstr("\n")),
      PAPERLESS_DBPASS: ($dbPassword | rtrimstr("\n"))
    }
  ' "$INSTALL_DIR/configuration.json" > "$INSTALL_DIR/protected/environment.json"
  if jq -e '.oidc.clientSecretRequired == true' "$INSTALL_DIR/configuration.json" >/dev/null; then
    test -s "$INSTALL_DIR/protected/oidc-client-secret"
    jq --rawfile clientSecret "$INSTALL_DIR/protected/oidc-client-secret" '
      .PAPERLESS_SOCIALACCOUNT_PROVIDERS |=
        (fromjson | .openid_connect.APPS[0].secret = ($clientSecret | rtrimstr("\n")) | tojson)
    ' "$INSTALL_DIR/protected/environment.json" > "$INSTALL_DIR/protected/environment-oidc.json"
    mv "$INSTALL_DIR/protected/environment-oidc.json" "$INSTALL_DIR/protected/environment.json"
  fi
  jq -n --arg name "$CONFIG_SECRET" --arg namespace "$NS" \
    --slurpfile environment "$INSTALL_DIR/protected/environment.json" '{
      apiVersion: "v1", kind: "Secret", type: "Opaque",
      metadata: {name: $name, namespace: $namespace}, stringData: $environment[0]
    }' | kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" apply -f -
  BOOTSTRAP_SECRET=$(INSTANCE="$INSTANCE" yq -r '.credentials.bindings[strenv(INSTANCE)].bootstrap.secretName // ""' "$INSTALL_DIR/paperless-connections.yaml")
  if [ -n "$BOOTSTRAP_SECRET" ]; then
    if [ -e "$INSTALL_DIR/protected/bootstrap-user" ]; then
      test -s "$INSTALL_DIR/protected/bootstrap-user"
    else
      (set -o noclobber; printf '%s' admin > "$INSTALL_DIR/protected/bootstrap-user")
    fi
    kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" create secret generic "$BOOTSTRAP_SECRET" \
      --from-file=PAPERLESS_ADMIN_USER="$INSTALL_DIR/protected/bootstrap-user" \
      --from-file=PAPERLESS_ADMIN_PASSWORD="$INSTALL_DIR/protected/bootstrap-password" \
      --dry-run=client -o yaml | kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" apply -f -
  fi
)
```

Do not print assembled environment, Secret YAML or client secrets. Keep protected files mode 0600, outside Git and independently recoverable. Retain the Paperless key, identity client and access to the backed-up realm: native import restores Paperless users, not an external provider. Changing issuer/client on a restored library is an explicit identity migration, not ordinary startup.


### Deploy and check readiness

After completing configuration preparation above:

```bash
REPLICAS=$(DEPLOYMENT="$DEPLOYMENT" INSTANCE="$INSTANCE" yq -er '.operations.deployments[strenv(DEPLOYMENT)].replicas // .services[strenv(INSTANCE)].replicas // 1' "$VALUES")
helm upgrade --install "$RELEASE" "$CHART" --kubeconfig "$KUBECONFIG" --kube-context "$CTX" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" "${HELM_ARGS[@]}" --wait=legacy --timeout=5m
GENERATION=$(kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" get paperlessapplication paperless -o jsonpath='{.metadata.generation}')
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.observedGeneration}=$GENERATION" --timeout=30m
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" wait --for=condition=Ready \
  paperlessapplication/paperless --timeout=30m
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" get paperlessapplication paperless -o json
if INSTANCE="$INSTANCE" yq -e '.services[strenv(INSTANCE)].endpoints.https.tlsManaged' \
  "$INSTALL_DIR/paperless-connections.yaml" >/dev/null; then
  TLS_SECRET=$(INSTANCE="$INSTANCE" yq -er '.credentials.bindings[strenv(INSTANCE)].tls.secretName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" wait "certificate/$TLS_SECRET" \
    --for=condition=Ready --timeout=10m
fi
if INSTANCE="$INSTANCE" yq -e '.services[strenv(INSTANCE)].endpoints.https.ingressEnabled' \
  "$INSTALL_DIR/paperless-connections.yaml" >/dev/null; then
  curl --fail --silent --show-error --output /dev/null "$PAPERLESS_URL"
fi
```

`--wait=legacy` is Helm 4 syntax. Helm completion means controller infrastructure exists, not that application recovery succeeded. Require both `status.observedGeneration` and the requested condition's `observedGeneration` to equal live `metadata.generation`. `Ready=True` and `status.version` must match the intended release. `Failed=True` retains a refused/interrupted transition; inspect `status.operation`, `status.operations`, Job termination messages and native logs.

The controller starts dependencies and observes database/file state. Only absent local state triggers selection and verification of the latest matching complete backup, same-version preparation/import and any supported forward migration. Before `/init` can reach migrations or ordinary services, the native gate checks ownership and actual container execution. A replacement waits for all predecessor application Pods, including terminating Pods, to disappear; RWO storage and Deployment `Recreate` alone do not prevent overlap after Pod deletion. Recovery needs no second technical release command. Existing state and ordinary restart need no backup access.

### Capture, publication and retry

```sh
REQUEST="manual-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" annotate paperlessapplication paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" get paperlessapplication paperless -o json
```

Wait for `status.backup.request` to equal this request and `status.backup.phase` to become `Published`. Inspect the result's `captureOperation`, `capturedAt`, `resumed`, `repositoryID`, full `snapshotID` and `publishedAt`. `BackupFailed=True` is a failed backup, independently of application `Ready`. Scheduled requests enter this same controller path.

Capture stops native admission, drains one responsive worker and its broker queues, then stops writers before an unfiltered export and full member inventory. The native procedure below defines the settled-work boundary and termination checks. Only the same currently permitted execution may resume. A separate writer-scoped Job publishes from read-only staging, restores and byte-checks a candidate, then publishes a complete-tag snapshot of the same tree.

After publication failure, correct the endpoint/credential/capacity problem and issue a new request. The controller retries the retained complete capture rather than silently recapturing; its capture boundary therefore does not advance. Request another backup after successful retry to include later work. Never infer inclusion from publication time.

Local captures are not automatically pruned. Monitor staging capacity, failed/overdue requests and backup age independently. Remove an old local capture only after its publication and required independent replication are verified, it is not the active/retry capture, and the customer's retention rules permit removal. Capacity exhaustion must not delete the last usable point.

### Durable stop, restart and removal

Keep run/stop intent in the installation's values, not in generated Deployment replica counts:

```sh
DEPLOYMENT="$DEPLOYMENT" yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 0' "$VALUES"
REPLICAS=$(DEPLOYMENT="$DEPLOYMENT" yq -er '.operations.deployments[strenv(DEPLOYMENT)].replicas' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kubeconfig "$KUBECONFIG" --kube-context "$CTX" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" "${HELM_ARGS[@]}" --wait=legacy --timeout=5m
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" wait --for=condition=Stopped paperlessapplication/paperless --timeout=10m
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" get paperlessapplication paperless -o json
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" get pods,jobs,deployments,replicasets
```

Require current-generation `Stopped=True` and no application/native-Job Pods, including terminating Pods. The controller withdraws ingress and confirms Deployment/ReplicaSet drainage; PostgreSQL and Redis may remain for diagnosis. Stop cancels finite work and wins over completion. Interrupted mutation stays failed across later run intent. Export needed logs first because drainage deletes Jobs and their Pods.

A running application continues through controller/API observation loss without lease expiry or a recurring custom supervisor. Each new container execution needs fresh native admission. A submitted stop request or unreachable source is not retirement: while observation/enforcement is unavailable, the old service may continue. Confirm drainage or independent retirement before activating a replacement.

After a completed, nonfailed stop, restart with durable run intent:

```bash
DEPLOYMENT="$DEPLOYMENT" yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 1' "$VALUES"
REPLICAS=$(DEPLOYMENT="$DEPLOYMENT" yq -er '.operations.deployments[strenv(DEPLOYMENT)].replicas' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kubeconfig "$KUBECONFIG" --kube-context "$CTX" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" "${HELM_ARGS[@]}" --wait=legacy --timeout=5m
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" wait --for=condition=Ready \
  paperlessapplication/paperless --timeout=30m
```

For an ordinary native restart, without backup access:

```bash
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" rollout restart deployment/paperless
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" rollout status deployment/paperless --timeout=10m
```

Recheck current-generation readiness and useful service. For uninstall, keep the controller alive through application finalization:

```sh
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" delete paperlessapplication paperless --wait=true --timeout=10m
helm uninstall "$RELEASE" --kubeconfig "$KUBECONFIG" --kube-context "$CTX" -n "$NS" --wait --timeout=5m
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" get pvc,secrets
```

Do not bypass finalizers or delete the namespace/controller first. Finalization drains dependencies, removes controller-owned fixed-name resources and only then releases this CR's claim bindings. Claims, data and operator Secrets survive. Reinstall with the same logical identity, claims and retained inputs and `replicas: 1`; existing-state observation and native startup must succeed. Uninstall does not clear a failed target's durable transition marker. Preserve diagnostics and independently recoverable state, then use fresh storage, not marker deletion or import replay.

For replacement, confirm source retirement and retain any required final/secondary point. Keep its stopped `operations.deployments.<source>.replicas: 0`; do not change shared `services.<instance>.replicas` to run the target. Add `deployments.paperless-replacement` with the **same instance**, retained package key, target cluster, fresh namespace and release `paperless`. Record target `replicas: 1` and `ingressEnabled: false` under `operations.deployments.paperless-replacement`, select `DEPLOYMENT=paperless-replacement`, then rerun mapping and optional Helm-argument blocks and repeat declaration, four-PVC and retained-Secret preparation. The mapping derives a separate deployment subdirectory whenever deployment ID differs from instance. Use the same absolute `VALUES`; never copy it, generate recovery credentials or copy source-local state. Run the ordinary deployment command above; startup binds the repository's full snapshot ID and reconstructs automatically. After technical checks and records review, record target `ingressEnabled: true`, refresh the Helm arguments, redeploy and perform the authorized route switch. DNS alone never retires the predecessor. Recheck new work and another usable capture before recording acceptance.

For the supported native upgrade, persist `services.<instance>.version: "3.3.1"` in `"$VALUES"` and run the same Helm upgrade with complete values. To exercise 3.3.0-to-3.3.1, install 3.3.0 first, perform useful work and a verified capture, then select 3.3.1. Never roll software back against migrated data. For a 0.1.0 chart upgrade retain its old archive/configuration as evidence, translate every flat value into the selected shared-file service before rendering 0.2.0, and retain the same identity, claims, Secrets and immutable images. Do not pass the old flat file as an additional compatibility layer.

Before a CRD-changing upgrade, extract the selected verified archive and apply its `crds/`; Helm does not update an existing CRD:

```bash
mkdir -p "$INSTALL_DIR/selected-chart"
tar -xzf "$CHART" -C "$INSTALL_DIR/selected-chart"
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" apply -f "$INSTALL_DIR/selected-chart/bartl-paperless/crds/"
```

### OIDC, MFA and token recovery

Use the package configuration rendering and provider preparation above; do not hand-author allauth JSON. Require TOTP MFA for the intended users at the identity provider and verify an actual fresh browser login, not only an existing session. Paperless retains its own users, groups and object permissions. Deliberately link an existing account through its native profile; do not assume matching email establishes identity. First-login provisioning and permission assignment are native administration, not package startup tests.

A read-only browser group needs `view_document`, `view_uisettings`, `add_uisettings`, `change_uisettings` and `view_savedview`, in addition to its document object grants. Native metadata views may also need `view_tag`, `view_correspondent`, `view_documenttype` and `view_storagepath`. UI-settings permissions do not grant document modification or user administration.

Native import excludes DRF API tokens. Local password accounts can reacquire their token with `POST /api/token/`; Paperless-local MFA, when enabled, additionally requires its native `code`. For a restored SSO-only user, an authorized operator uses the native management command:

```sh
# Treat stdout as a secret; do not put it in general logs.
kubectl --kubeconfig "$KUBECONFIG" --context "$CTX" -n "$NS" exec deployment/paperless -c paperless -- \
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

The [backup service](https://github.com/bartlapp/bartl-restic/blob/main/README.md#service-and-state-boundary) owns replication and retention. Writer credentials are append-only; recovery credentials can read backup contents and create/remove native lock objects. Neither application worker has destructive maintenance credentials. Do not bypass locks or automatically unlock on retry: first establish that the owning native operation has ended.

The complete export directory is the recovery artifact, without another tar/zip layer. Its manifest binds logical identity, native version, capture boundary and every member's length/SHA-256. Only a verified `complete`-tag point is eligible; retention must preserve usable complete points rather than count incomplete candidate snapshots as replacements. Lookup uses strict native object enumeration because `restic snapshots --json` can warn about an unreadable object and omit it while returning success.

Reconstruction binds the selected repository's own identity and full snapshot ID. An independently initialized/copied repository need not retain the source repository or snapshot IDs. Logical identity, supported native version and complete inventory integrity remain mandatory. The [replication contract](https://github.com/bartlapp/bartl-restic/blob/main/README.md#replication-mechanism) owns copy correspondence. Repository/credential changes during active native work are not a credential-rotation procedure.


## Source retention

Confirm completed ingestion and a readable original. Keep its source until a capture containing it has been published, verified and protected against the failure declared in the retained installation inputs. If that protection requires a secondary, primary publication alone is insufficient; use the backup service's result to establish protection. Paper, email or a device suffices if it survives that failure; otherwise retain a durable holding copy, not a new intake service or receipt ledger.

The result identifies installation, capture boundary, publication/verification completion, exact Restic point and outcome. Publication after upload does not prove inclusion if capture began earlier; check native inventory and original checksums when uncertain. Unsettled ingestion is not covered. Then perform only permitted source-copy cleanup; backup success never authorizes destruction of legally required originals.

After recovery, compare retained sources with the restored library before re-ingesting missing documents. Do not blindly replay or merge records solely because their bytes match.

## Records after restore

An export reflects records at capture, not later deletion, hold or restriction decisions. Its restored audit history cannot supply missing later changes. After technical recovery in isolation, the responsible person checks independently surviving approvals, disposal records, correspondence or newer evidence and applies corrections through native administration before affected use resumes. This is a records-policy review, not a second technical startup authorization; it applies neither to ordinary restart nor nightly capture.

Where evidence is insufficient, keep affected access/processing closed and resolve the exception with the installation's named records owner. Review cannot reconstruct missing information. Use the independently surviving decision evidence and review responsibilities recorded in the [installation inputs](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md#installation-inputs); retain the review result and unresolved restrictions there, with protected evidence referenced as appropriate. Existing approvals, disposal records and correspondence may suffice; a new decision file is justified only by a demonstrated gap.

## Useful-service verification and evidence

For the exact candidate, exercise first initialization both without a store and with an empty compatible external repository; then capture and reconstruct on fresh claims with source access unavailable. After each transition, use the actual HTTPS path to:

1. Log in locally and, when configured, through OIDC with fresh TOTP MFA. Confirm the intended SSO-only user has no newly assigned local password.
2. Ingest a synthetic PDF, wait for completed OCR/processing, find it by title and document text, and download its original. Check the used metadata-assignment workflow and retained versions/renditions.
3. Confirm reader access to granted documents and denial of ungranted ones, with no document modification or user-administration authority.
4. Repeat after ordinary restart and durable stop/start. Existing state must start without backup access, without initialization or restore.
5. Publish a capture and record its capture boundary/full repository and snapshot identity; reconstruct with source unavailable, compare originals/version/rendition bytes and metadata/grants, complete records review, ingest new work, and publish another point that itself restores successfully.
6. Exercise 3.3.0-to-3.3.1 and repeat these checks, including restart and source-independent reconstruction. Failed transition must remain failed/stopped; never delete markers to make it pass.

Retain exact archive/OCI/image identities, effective nonsecret inputs, observed results, selected recovery points, timings and material limits in the release/integration record and the installation's operating inputs. The procedure is not evidence that it was executed. Do not claim host/provider-loss recovery from another namespace on one host.

### Historical runtime evidence

The following observations belong to the 0.1.0 runtime qualification, not proof of the 0.2.0 shared-file procedure. Native recovery tests on 25 October 2026 restored after source-VM deletion. They checked original/version bytes and relationships, metadata, ownership/permissions, token reacquisition, browser search and a further backup restored into fresh database, file and Redis storage. Export truncates version `added` timestamps from microseconds to milliseconds. This remains a package fidelity limit, not a universal records-policy acceptance. Decide whether that precision is sufficient before relying on this recovery path; do not use this timestamp alone as identity or order.

Package acceptance additionally checks rendition bytes, user/group/object grants, a used metadata-assignment workflow, rebuilt search, new work and another recoverable point. It exercises the supported 3.3.0-to-3.3.1 transition and Keycloak OIDC/TOTP for an SSO-only user, including token acquisition without local password assignment, rotation or elevation. Paperless-local MFA is not qualified.

Fault cases cover incomplete import, execution replacement, controller absence, failed publication, bounded drainage, damaged history, persistent stop and retained-storage reuse. The lab removes source installations, physical storage directories and the primary repository on one disposable K3s host. This qualifies independent-repository recovery at that boundary, not host/provider-loss failover or cross-cluster fencing.

The exercised target was Debian 13, amd64, K3s `v1.36.5+k3s1` with its enforcing CNI and Traefik, cert-manager 1.21.3 and Helm 4.3.0. Builds used Podman 5.4.2. The shared CRD remains installed across namespace removal.

Repeatable regression and synthetic-library checks are in source:

```sh
go test ./...
uv run --no-project python -m unittest discover -s tests -v
node tests/chart.mjs
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
For the chart-only 0.2.0 release, do not run the runtime builder or republish runtime/controller tags. Package the chart with its existing immutable image digests and retain a checksum file as a release asset:

```bash
OUT=/protected/paperless-chart-candidate
mkdir "$OUT"
helm package chart --destination "$OUT"
(cd "$OUT"; shasum -a 256 bartl-paperless-0.2.0.tgz > SHA256SUMS)
```

Qualify these exact bytes and publish the chart to `oci://ghcr.io/bartlapp`. Embed its computed archive checksum in the acquisition block above; retain `SHA256SUMS`, the immutable OCI manifest digest, exact image identities and observed results with the release. Do not require access to a private source/release-record repository for anonymous chart acquisition.

The following runtime build procedure applies only when runtime/controller changes justify a new image release:


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
