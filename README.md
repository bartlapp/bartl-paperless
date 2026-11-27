# Bartlized Paperless

Paperless over HTTPS with PostgreSQL, Redis, automatic initialization/reconstruction, settled-work capture and native forward migration. Compatible external OIDC and HTTPS Restic services suffice; Keycloak and Bartlized Restic are optional independent packages.

New deployment: follow the steps below. Existing deployment: [resume access](#resume-an-existing-deployment), then select an operation. Use workstation Bash, keep tracing off and stop at a failed command. Creation is not a replay or partial-state repair program.

This checkout selects candidate `0.3.0-dev.9`: final capture uses ordinary stop intent instead of withdrawal/cancellation state. Use its exact pinned archive and images with these procedures. The [live evidence and limits](#maintainer-procedures-and-evidence) do not establish complete release qualification; earlier candidates do not qualify changed lifecycle paths.

- [Install](#package-and-target), [resume](#resume-an-existing-deployment) and [operate](#stop-start-and-restart)
- [Capture](#capture-publication-and-retry), [recover and update by replacement](#recovery-and-replacement-upgrade)
- [Remove](#remove-the-release)

## Package and target

Candidate **0.3.0-dev.9** targets Paperless 3.3.1, PostgreSQL 17.6, Redis 8.2.1 and Restic 0.19.1 through API `paperless.bartl.sh/v1alpha2`. Updates replace the installation on independent storage; in-place package/native upgrades and predecessor Kubernetes-resource adoption are not supported. Format-2 complete database/file backups from Paperless **3.3.0 and 3.3.1** are supported inputs. The target automatically restores with the matching immutable runtime, then performs the native 3.3.0 → 3.3.1 transition when necessary. Both runtime digests ship in the selected chart. This transition updates the Tantivy search schema from 3 to 4; it is not a new Django database migration. Other source versions, downgrades and format-1 document exports are refused. Format-1 exports omit workflow execution history and cannot provide complete application-state recovery; historical candidates and evidence remain separate.

Use the [operator tools](https://github.com/bartlapp/bartl-app/blob/main/docs/operator-workstation.md#check-the-workstation) and a Linux amd64 single-node K3s profile with enforced NetworkPolicy, Traefik in kube-system and four ReadWriteOnce claims. Storage must support POSIX permissions, locks, atomic rename and fsync. Native setup needs root; ordinary services use UID 1000. One namespace holds one release named paperless and no unrelated workloads. The supported profile has one container, one Celery worker/thread and local-path storage, not HA or multi-node RWO placement. [Base](https://github.com/bartlapp/base-k3s/blob/main/README.md) supplies this profile.

Supply its existing version-1 installation record, complete cluster/resource references and retained access. Default HTTPS uses cert-manager and public ports 80/443; external TLS is supported. API/browser intake and native metadata-assignment workflows are covered. Mail polling, remote OCR/AI, custom scripts and external-effect workflows need separate qualification. Do not override DJANGO_SETTINGS_MODULE or the controller-owned database/broker/concurrency topology.

Before relying on the service, agree interruption/data loss, source retirement, backup protection/retention, staging headroom and alert ownership. Captures interrupt intake and retain complete database/file points without automatic pruning. Name the records-review owner and independently surviving evidence of later deletion/hold/access decisions. Complete database capture preserves native timestamp precision and security state at the selected point, not subsequent changes. Paperless-local MFA is not qualified; configured provider TOTP needs its own fresh-login check.

## Select cluster access and obtain the release

Use direnv-hooked Bash and the prepared installation's cluster directory. For an equivalent externally supplied K3s cluster, use the shared [supplied cluster access](https://github.com/bartlapp/bartl-app/blob/main/docs/operator-workstation.md#use-supplied-cluster-access) procedure; no Hetzner machine records are required.

```bash
cd "${WORK_DIR_ROOT:-$HOME/bartl}/acme/acme-installation/clusters/cluster-1"
```

At the next prompt, obtain the selected package. For an unpublished candidate, use the exact supplied archive and checksum through [candidate acquisition](#building-and-publishing), not the latest stable chart. Published 0.2.1 uses the old API and does not implement this procedure:

```bash
set -euo pipefail
umask 077
kubectl --context "$KUBE_CONTEXT" get nodes,storageclass
mkdir -p "$WORK_DIR/packages"
CHART_STAGE=$(mktemp -d "$WORK_DIR/packages/.paperless.XXXXXX")
export PACKAGE_VERSION=0.3.0-dev.9
helm pull oci://ghcr.io/bartlapp/bartl-paperless --version "$PACKAGE_VERSION" --untar --untardir "$CHART_STAGE"
export PACKAGE_VERSION
PACKAGE_VERSION=$(helm show chart "$CHART_STAGE/bartl-paperless" | yq -er '.version')
```

Retain the selected chart archive/checksum, its independently obtainable image digests, configuration, Paperless key, selected identity inputs and repository credentials independently of the source. Candidate bytes and qualification limits belong in the package's draft release; a candidate upload is not public release activation or acceptance.

## Configure a new deployment

Choose unused deployment and service keys and a fresh namespace. Reuse a package key only when its recorded chart and version match the acquired artifact; otherwise choose an unused package key. These assignments preserve unrelated installation entries. A replacement must retain the original instance instead.

```bash
{
export DEPLOYMENT=paperless
export INSTANCE=paperless
export NS=paperless-blue
export RELEASE=paperless
export PACKAGE=paperless
yq -e '.packages[strenv(PACKAGE)] == null or
  (.packages[strenv(PACKAGE)].version == strenv(PACKAGE_VERSION) and
   .packages[strenv(PACKAGE)].chart == "oci://ghcr.io/bartlapp/bartl-paperless")' "$VALUES" >/dev/null
yq -i '
  .deployments[strenv(DEPLOYMENT)] = {
    "instance": strenv(INSTANCE), "cluster": strenv(CLUSTER_ID),
    "namespace": strenv(NS), "release": strenv(RELEASE), "package": strenv(PACKAGE)
  } |
  .services[strenv(INSTANCE)] = {} |
  .packages[strenv(PACKAGE)] = (.packages[strenv(PACKAGE)] // {
    "version": strenv(PACKAGE_VERSION), "chart": "oci://ghcr.io/bartlapp/bartl-paperless"
  })
' "$VALUES"
DEPLOYMENT_DIR="$WORK_DIR/clusters/$CLUSTER_ID/applications/$INSTANCE"
CLUSTER_ENV=../../.envrc
if [ "$DEPLOYMENT" != "$INSTANCE" ]; then
  DEPLOYMENT_DIR="$DEPLOYMENT_DIR/deployments/$DEPLOYMENT"
  CLUSTER_ENV=../../../../.envrc
fi
mkdir -p "$DEPLOYMENT_DIR" "$WORK_DIR/packages/$PACKAGE"
(
  set -o noclobber
  printf 'source_env %s\nload_deployment "%s"\n' "$CLUSTER_ENV" "$DEPLOYMENT" > "$DEPLOYMENT_DIR/.envrc"
)
if [ ! -d "$WORK_DIR/packages/$PACKAGE/$PACKAGE_VERSION" ]; then
  mv "$CHART_STAGE/bartl-paperless" "$WORK_DIR/packages/$PACKAGE/$PACKAGE_VERSION"
fi
rm -r "$CHART_STAGE"
direnv allow "$DEPLOYMENT_DIR"
cd "$DEPLOYMENT_DIR"
}
```

Wait for the next prompt: direnv loads the recorded deployment and chart path. Optional hostname, claims, TLS and dependency choices belong under `services.<instance>`. The package selects the native version. Runtime `running` and `replicas` belong only to the application resource, never services or deployment overrides. Render declarations from the selected static configuration:

```bash
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
mkdir -p "$INSTALL_DIR/protected"
kubectl --context "$KUBE_CONTEXT" get nodes,storageclass
kubectl --context "$KUBE_CONTEXT" create namespace "$NS"
```

Never inherit another target's kubeconfig. Declarations report public endpoints, credential bindings, optional OIDC/backup requests and claims; they neither issue credentials nor create dependencies.

Create the four declared claims. Adjust the capacities once before this block; staging must hold retained database/file captures and failed-publication headroom, not merely one point:

```bash
for entry in storage:10Gi database:5Gi broker:1Gi staging:20Gi; do
  role=${entry%:*}; size=${entry#*:}
  name=$(ROLE="$role" yq -er '.storage.claims[strenv(INSTANCE)][strenv(ROLE)].claimName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" create -f - <<EOF
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
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pvc
```

WaitForFirstConsumer claims may stay Pending until scheduling. Logical installation/instance and claim names remain stable through reconstruction; target namespaces and PVC identities are independent.

## DNS and external TLS

Inspect the selected ingress address, create or deliberately update only the authorized hostname's DNS record, and correct conflicting AAAA records:

```bash
kubectl --context "$KUBE_CONTEXT" -n kube-system get service traefik -o wide
printf '%s\n' "$PAPERLESS_HOST"
dig "$PAPERLESS_HOST" A +trace
dig @1.1.1.1 +short "$PAPERLESS_HOST" A
dig @8.8.8.8 +short "$PAPERLESS_HOST" A
```

Require authoritative/public answers reaching this ingress before ACME issuance. Default managed TLS uses Let's Encrypt production and cert-manager renewal. For **external TLS only**, set tls.managed: false before rendering and supply the certificate/key covering the declared hostname:

```bash
TLS_SECRET=$(helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --set "operations.deployments.${DEPLOYMENT//./\\.}.ingressEnabled=true" \
  --show-only templates/connections.yaml |
  yq -er '.credentials.bindings[strenv(INSTANCE)].tls.secretName')
kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret tls "$TLS_SECRET" \
  --cert="$INSTALL_DIR/tls/fullchain.pem" --key="$INSTALL_DIR/tls/key.pem"
```

This offline lookup asks for the future route's TLS binding; it does not change VALUES or apply an ingress. When the recorded deployment disables ingress, the explicit one-off render enables it solely to inspect a prospective external TLS binding. Preserve external ownership on subsequent upgrades. Disabling ingress omits access without disabling managed certificate preparation.

### Diagnose delayed managed TLS

If the managed-certificate wait times out, keep the selected deployment's administration context and inspect the existing issuance; do not repeat installation. After a DNS move, authoritative and public resolvers can reach the target while its cluster resolver still returns the predecessor:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" get certificate,certificaterequest,order,challenge -o yaml
PAPERLESS_HOST=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.spec.ingress.host}')
TLS_SECRET=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.spec.ingress.tlsSecret}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" exec deployment/paperless -c paperless -- \
  uv run --no-project python -c 'import socket,sys; print(*sorted({r[4][0] for r in socket.getaddrinfo(sys.argv[1],443)}),sep="\n")' "$PAPERLESS_HOST"
```

For an HTTP-01 self-check reporting 404, compare those resolved addresses with the target ingress already established above. If they still name the predecessor, let the previously advertised DNS TTL expire; lowering the new record's TTL does not expire existing caches. During replacement, keep the source stopped and the target isolated. cert-manager retries the same challenge automatically. If the addresses already name the target, diagnose the reported challenge error rather than assuming a cache delay.

Once the diagnosed cause is resolved, repeat only the certificate wait:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait "certificate/$TLS_SECRET" --for=condition=Ready --timeout=10m
```

Then continue immediately after the failed wait in installation or reconstruction. Do not copy the predecessor's certificate, change the issuer or disable TLS verification to bypass issuance.

## Optional identity and backup

### External OIDC

For a compatible external provider, select its supplied issuer, then render the exact client/callback requirements:

```bash
export OIDC_ISSUER=https://login.example.org/realms/acme
yq -i '.services[strenv(INSTANCE)].oidc.issuer = strenv(OIDC_ISSUER)' "$VALUES"
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
yq '.oidc.requests[strenv(INSTANCE)]' "$INSTALL_DIR/paperless-connections.yaml"
```

Register that client at the provider and retain its client secret without a newline at INSTALL_DIR/protected/oidc-client-secret. Do not generate a replacement during resumption or recovery. No OIDC choice means no identity-provider dependency. Use the next section instead for composed Keycloak.

### Compose with an existing Keycloak

First install/resume and verify Keycloak through its [own release procedure](https://github.com/bartlapp/bartl-keycloak/blob/main/README.md), including DNS, TLS, credentials and useful login. Do not provision it again here. Supply its current nonsecret declaration file.

Starting condition: this consumer has no direct `oidc.issuer` override; composition selects the provider through `identityProvider`. Supply an authorized current master-realm administrator at `INSTALL_DIR/protected/keycloak-admin/{username,password}`, with usable `admin-cli` password grant and no interactive required actions. These credentials are preparation-only.

```bash
export KC_DEPLOYMENT=keycloak
export KC_CONNECTIONS="$WORK_DIR/clusters/cluster-1/applications/keycloak/connections.yaml"
KC_INSTANCE=$(yq -er '.deployments[strenv(KC_DEPLOYMENT)].instance' "$VALUES")
export KC_INSTANCE
yq -i '.services[strenv(INSTANCE)].identityProvider = strenv(KC_INSTANCE)' "$VALUES"
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
KC_URL=$(yq -er '.services[strenv(KC_INSTANCE)].endpoints.https.url' "$KC_CONNECTIONS")
OIDC_ISSUER=$(yq -er '.services[strenv(KC_INSTANCE)].oidc.issuer' "$KC_CONNECTIONS")
OIDC_CLIENT_ID=$(yq -er '.oidc.requests[strenv(INSTANCE)].clientId' "$INSTALL_DIR/paperless-connections.yaml")
export OIDC_ISSUER OIDC_CLIENT_ID
yq -i '.resolved.oidc.bindings[strenv(INSTANCE)] = {
  "provider": strenv(KC_INSTANCE), "issuer": strenv(OIDC_ISSUER), "clientId": strenv(OIDC_CLIENT_ID)
}' "$VALUES"
```

The resolved provider binding must match `identityProvider`. Refresh it when provider choices change.

If this provider's HTTPS endpoint needs a supplied private/staging root, select its complete trusted PEM bundle for native curl in this shell before the commands below:

```bash
export CURL_CA_BUNDLE=/absolute/path/to/supplied/operator-ca-bundle.pem
```

Otherwise keep curl's default trust. This does not configure Paperless runtime trust; supply that separately under [custom client CA trust](#custom-client-ca-trust). Never disable TLS verification. Authenticate and inspect the provider's realms and declared client:

```bash
ADMIN_DIR="$INSTALL_DIR/protected/keycloak-admin"
CLIENT_WORK=$(mktemp -d "$INSTALL_DIR/protected/keycloak-client.XXXXXX")
curl --fail-with-body --silent --show-error "$KC_URL/realms/master/protocol/openid-connect/token" \
  --data-urlencode client_id=admin-cli --data-urlencode grant_type=password \
  --data-urlencode "username@$ADMIN_DIR/username" --data-urlencode "password@$ADMIN_DIR/password" > "$CLIENT_WORK/token.json"
TOKEN=$(jq -er '.access_token' "$CLIENT_WORK/token.json")
REALM=${OIDC_ISSUER##*/}
REALM_PATH=$(jq -nr --arg realm "$REALM" '$realm | @uri')
ADMIN_URL="$KC_URL/admin/realms/$REALM_PATH"
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
  curl --config - --fail-with-body --silent --show-error "$KC_URL/admin/realms" | jq '.[].realm'
yq -o=json '.oidc.requests[strenv(INSTANCE)]' "$INSTALL_DIR/paperless-connections.yaml" |
  jq '{clientId, redirectUris, webOrigins, protocol: "openid-connect", enabled: true,
    publicClient: false, standardFlowEnabled: true, directAccessGrantsEnabled: false,
    implicitFlowEnabled: false, serviceAccountsEnabled: false,
    attributes: {"pkce.code.challenge.method": "S256"}}' > "$CLIENT_WORK/client.json"
cat "$CLIENT_WORK/client.json"
```

If the declared realm is absent and its creation authorized, create it once. Otherwise keep the existing enabled realm and its users unchanged:

```bash
jq -n --arg realm "$REALM" '{realm: $realm, enabled: true}' > "$CLIENT_WORK/realm.json"
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
  curl --config - --fail-with-body --silent --show-error --request POST "$KC_URL/admin/realms" \
    --header 'Content-Type: application/json' --data-binary "@$CLIENT_WORK/realm.json"
```

Inspect the exact client before creation:

```bash
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
  curl --config - --fail-with-body --silent --show-error --get "$ADMIN_URL/clients" \
    --data-urlencode "clientId=$OIDC_CLIENT_ID" > "$CLIENT_WORK/clients.json"
jq . "$CLIENT_WORK/clients.json"
```

For an absent authorized client only, create it once. An existing client must have the declared callbacks/origins, confidential standard flow and S256 PKCE, with implicit/direct grants/service accounts disabled. Reconcile differences deliberately; never reset an existing realm/client to make this recipe pass.

```bash
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
  curl --config - --fail-with-body --silent --show-error --request POST "$ADMIN_URL/clients" \
    --header 'Content-Type: application/json' --data-binary "@$CLIENT_WORK/client.json"
```

Retrieve the issued secret with GET, not POST (which rotates it). For an already retained secret, compare the retrieved bytes and coordinate any mismatch instead of replacing them:

```bash
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
  curl --config - --fail-with-body --silent --show-error --get "$ADMIN_URL/clients" \
    --data-urlencode "clientId=$OIDC_CLIENT_ID" > "$CLIENT_WORK/clients.json"
CLIENT_UUID=$(jq -er --arg id "$OIDC_CLIENT_ID" '[.[] | select(.clientId == $id)] |
  if length == 1 then .[0].id else error("Expected exactly one client") end' "$CLIENT_WORK/clients.json")
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
  curl --config - --fail-with-body --silent --show-error "$ADMIN_URL/clients/$CLIENT_UUID/client-secret" > "$CLIENT_WORK/secret.json"
jq -erj '.value | select(length > 0)' "$CLIENT_WORK/secret.json" > "$CLIENT_WORK/secret"
(set -o noclobber; cat "$CLIENT_WORK/secret" > "$INSTALL_DIR/protected/oidc-client-secret")
unset TOKEN
rm -r "$CLIENT_WORK"
```

Independently retain the client secret. Configure intended users and, when selected for this profile, TOTP through native Keycloak administration; test fresh login and account linking, not matching-email assumptions. This preparation does not create a second provider installation.

### External backup inputs

Choose one repository source below: a direct compatible endpoint or an existing composed Restic provider. Both require a dedicated initialized HTTPS Restic repository. For fresh initialization it must contain no matching application history; existing history belongs in recovery with the retained Paperless key.

#### Select an external repository

Use the supplied endpoint:

```bash
export REPOSITORY_URL=rest:https://backup.example.org/paperless/
yq -i '.services[strenv(INSTANCE)].backup.repository = strenv(REPOSITORY_URL)' "$VALUES"
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
```

#### Select a composed Restic repository

Instead of the direct URL block, use a provider already operated through its [own release procedure](https://github.com/bartlapp/bartl-restic/blob/main/README.md). Starting condition: no direct `backup.repository` override and an admitted dedicated repository. Read its current declaration file:

```bash
export RESTIC_DEPLOYMENT=restic
export RESTIC_CONNECTIONS="$WORK_DIR/clusters/cluster-1/applications/restic/restic-connections.yaml"
export REPOSITORY_NAME=paperless
RESTIC_INSTANCE=$(yq -er '.deployments[strenv(RESTIC_DEPLOYMENT)].instance' "$VALUES")
export RESTIC_INSTANCE
BACKUP_REPOSITORY=$(yq -er '.backup.providers[strenv(RESTIC_INSTANCE)].repositories[strenv(REPOSITORY_NAME)].repository' "$RESTIC_CONNECTIONS")
export BACKUP_REPOSITORY
yq -i '.services[strenv(INSTANCE)].backup.endpoint = strenv(RESTIC_INSTANCE) |
  .resolved.backup.bindings[strenv(INSTANCE)] = {
    "endpoint": strenv(RESTIC_INSTANCE), "repository": strenv(BACKUP_REPOSITORY)
  }' "$VALUES"
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
```

Declarations select the repository; they do not create it or prove its protection. Continue with the same credential handoff below.

#### Supply repository credentials

For either selection, [Restic's application handoff](https://github.com/bartlapp/bartl-restic/blob/main/README.md#connect-an-application) supplies compatible files; equivalent external credentials also suffice.

Supply repository/reader/ and repository/writer/ under INSTALL_DIR, each with password (the same repository encryption key), username, restPassword and optional ca.crt. Restore the retained files for existing history; do not regenerate them. Reader may manage native locks, not backup contents; writer is append-only. Admin credentials stay with the backup service. Create runtime copies:

```bash
for pair in reader:backupReader writer:backupWriter; do
  directory=${pair%%:*}; role=${pair#*:}
  name=$(ROLE="$role" yq -er '.credentials.bindings[strenv(INSTANCE)][strenv(ROLE)].secretName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret generic "$name" \
    --from-file="$INSTALL_DIR/repository/$directory/"
done
```

Omission means no backup; explicit backup.enabled: false disables it. Default schedule is empty (manual only), timeZone UTC and drainSeconds 300. Set an agreed schedule in services.<instance>.backup.schedule before deployment. A drain budget is not a maximum outage guarantee. For existing composed backup.endpoint settings, preserve the matching resolved.backup.bindings entry; never combine endpoint and direct repository choices. The standalone URL path requires no resolved data.

## Prepare application credentials and configuration

For fresh initialization only, generate the independent Paperless key and database/bootstrap passwords once in an empty input directory. For recovery, restore retained inputs instead; never replace PAPERLESS_SECRET_KEY for a restored library.

```bash
(
  set -o noclobber
  for key in secret-key database-password bootstrap-password; do
    openssl rand -hex 32 | tr -d '\n' > "$INSTALL_DIR/protected/$key"
  done
  printf admin > "$INSTALL_DIR/protected/bootstrap-user"
)
```

### Custom client CA trust

For optional private/staging issuer trust, retain a complete PEM root bundle at `$INSTALL_DIR/protected/client-ca/ca-bundle.pem` before rendering configuration. This selects the native Requests `REQUESTS_CA_BUNDLE` for OIDC discovery, token exchange and userinfo. It **replaces**, rather than extends, Requests' certifi roots: include every root these clients must trust, including public roots when needed. Without that file, configuration generation leaves ordinary runtime trust unchanged. Do not set verification-disabling options or modify workstation/system trust.

The separate optional client-CA Secret carries `ca-bundle.pem`; the configuration Secret contains only `REQUESTS_CA_BUNDLE=/configuration/ca-bundle.pem`. The chart declares its clientCA binding, derived from the configuration Secret name. Keeping PEM bytes out of the EnvFrom Secret avoids exporting a complete root bundle as an oversized environment variable. The controller mounts the CA Secret read-only for the application and native configuration-consuming Jobs. Missing/unreadable selected paths and invalid/untrusted bundles fail native HTTPS requests, never fall back to unverified TLS. This is application client configuration, not Paperless identity, its ingress certificate, Restic trust or library backup state. Retain the file independently with installation inputs, restore it before regenerating configuration on recovery, and retain both Secrets on reinstall. Restart the application after changing trust configuration.

### Render configuration

Starting condition: the selected chart and current declarations are available, together with the deployment's retained application key, database password and any OIDC/client-CA inputs. For an existing deployment, [prepare the chart-backed operation](#prepare-a-chart-backed-operation) first. This procedure creates or updates configuration only; it does not generate identity or bootstrap credentials. Render native configuration and add protected inputs without printing the result:

```bash
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=configuration \
  --show-only templates/configuration.yaml > "$INSTALL_DIR/configuration.yaml"
CONFIG_SECRET=$(yq -er '.configuration[strenv(INSTANCE)].secretName' "$INSTALL_DIR/configuration.yaml")
yq -o=json '.configuration[strenv(INSTANCE)]' "$INSTALL_DIR/configuration.yaml" > "$INSTALL_DIR/configuration.json"
jq --rawfile secretKey "$INSTALL_DIR/protected/secret-key" \
  --rawfile dbPassword "$INSTALL_DIR/protected/database-password" '
  .environment + {PAPERLESS_SECRET_KEY: ($secretKey | rtrimstr("\n")), PAPERLESS_DBPASS: ($dbPassword | rtrimstr("\n"))}
' "$INSTALL_DIR/configuration.json" > "$INSTALL_DIR/protected/environment.json"
if jq -e '.oidc.clientSecretRequired == true' "$INSTALL_DIR/configuration.json" >/dev/null; then
  jq --rawfile clientSecret "$INSTALL_DIR/protected/oidc-client-secret" '
    .PAPERLESS_SOCIALACCOUNT_PROVIDERS |=
      (fromjson | .openid_connect.APPS[0].secret = ($clientSecret | rtrimstr("\n")) | tojson)
  ' "$INSTALL_DIR/protected/environment.json" > "$INSTALL_DIR/protected/environment-oidc.json"
  mv "$INSTALL_DIR/protected/environment-oidc.json" "$INSTALL_DIR/protected/environment.json"
fi
if [ -e "$INSTALL_DIR/protected/client-ca/ca-bundle.pem" ] || [ -L "$INSTALL_DIR/protected/client-ca/ca-bundle.pem" ]; then
  test -s "$INSTALL_DIR/protected/client-ca/ca-bundle.pem"
  CLIENT_CA_SECRET=$(yq -er '.credentials.bindings[strenv(INSTANCE)].clientCA.secretName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret generic "$CLIENT_CA_SECRET" \
    --from-file=ca-bundle.pem="$INSTALL_DIR/protected/client-ca/ca-bundle.pem" --dry-run=client -o yaml | \
    kubectl --context "$KUBE_CONTEXT" apply --server-side --field-manager=paperless-preparation -f -
  jq '
    . + {REQUESTS_CA_BUNDLE: "/configuration/ca-bundle.pem"}
  ' "$INSTALL_DIR/protected/environment.json" > "$INSTALL_DIR/protected/environment-ca.json"
  mv "$INSTALL_DIR/protected/environment-ca.json" "$INSTALL_DIR/protected/environment.json"
fi
jq -n --arg name "$CONFIG_SECRET" --arg namespace "$NS" \
  --slurpfile environment "$INSTALL_DIR/protected/environment.json" '{
    apiVersion: "v1", kind: "Secret", type: "Opaque",
    metadata: {name: $name, namespace: $namespace}, stringData: $environment[0]
  }' | kubectl --context "$KUBE_CONTEXT" apply --server-side --field-manager=paperless-preparation -f -
```

### Create the bootstrap Secret

For fresh initialization with the default bootstrap binding, create its Secret. When rendering configuration for an existing or recovered deployment, stop at the end of [configuration rendering](#render-configuration); do not repeat this first-time step. If bootstrapSecret was deliberately disabled, skip this block and create the first administrator [after installation](#create-an-administrator-without-bootstrap):

```bash
BOOTSTRAP_SECRET=$(yq -er '.credentials.bindings[strenv(INSTANCE)].bootstrap.secretName' "$INSTALL_DIR/paperless-connections.yaml")
kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret generic "$BOOTSTRAP_SECRET" \
  --from-file=PAPERLESS_ADMIN_USER="$INSTALL_DIR/protected/bootstrap-user" \
  --from-file=PAPERLESS_ADMIN_PASSWORD="$INSTALL_DIR/protected/bootstrap-password"
```

Keep protected files mode 0600, outside Git and independently available. The bootstrap account applies only to an empty installation, never restored state. Do not add controller-owned topology or custom-init/consume scripts to the configuration Secret. Reconstruction restores Paperless accounts, not the identity provider; retain that provider and client independently.

Protected custody follows scope: `protected/secret-key`, `protected/oidc-client-secret` and `repository/{reader,writer}` identify the logical application and survive replacement. `protected/database-password`, bootstrap inputs and externally supplied `tls/` files serve the selected deployment; restore the required original inputs during recovery rather than running fresh generation. `protected/environment.json` is regenerated from those inputs. Keycloak administrator files are preparation-only, never application runtime credentials.

### Change client CA trust

Starting condition: a running deployment with no executing capture or failed transition. Load retained context and [prepare the chart-backed operation](#prepare-a-chart-backed-operation). Replace the retained `protected/client-ca/ca-bundle.pem` with the intended complete root bundle, or remove that selected file to return to native default trust. Repeat [configuration rendering](#render-configuration), then restart the application so native clients reload configuration:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" rollout restart deployment/paperless
kubectl --context "$KUBE_CONTEXT" -n "$NS" rollout status deployment/paperless --timeout=10m
```

Verify a fresh OIDC browser login through discovery, token exchange and userinfo when OIDC is selected. Startup alone does not establish client trust. This changes neither ingress TLS nor Restic CA inputs.

## Install and verify

Create the application once with explicit target runtime intent, before installing its controller. Run this same creation block for a replacement after preparing its target inputs. A compatible existing v1alpha2 CRD may be reused; a v1alpha1 source requires a **new target cluster**, not CRD replacement or conversion. An occupied namespace/slot is not an empty target.

```bash
kubectl --context "$KUBE_CONTEXT" get crd paperlessapplications.paperless.bartl.sh \
  --ignore-not-found -o json > "$INSTALL_DIR/existing-crd.json"
if [ -s "$INSTALL_DIR/existing-crd.json" ]; then
  jq -e '.spec.versions | length == 1 and .[0].name == "v1alpha2" and .[0].served and .[0].storage' \
    "$INSTALL_DIR/existing-crd.json"
else
  kubectl --context "$KUBE_CONTEXT" create -f "$CHART/crds/paperlessapplications.yaml"
fi
kubectl --context "$KUBE_CONTEXT" wait crd/paperlessapplications.paperless.bartl.sh \
  --for=condition=Established --timeout=60s
export INITIAL_RUNNING=true INITIAL_REPLICAS=1
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --show-only templates/application.yaml |
  yq '.spec.running = env(INITIAL_RUNNING) | .spec.replicas = env(INITIAL_REPLICAS) |
    .metadata.labels."app.kubernetes.io/managed-by" = "Helm" |
    .metadata.annotations."meta.helm.sh/release-name" = strenv(RELEASE) |
    .metadata.annotations."meta.helm.sh/release-namespace" = strenv(NS)' |
  kubectl --context "$KUBE_CONTEXT" -n "$NS" create -f -
unset INITIAL_RUNNING INITIAL_REPLICAS
```

The defaults above select an enabled target with one application replica. Select `false` or `0` here only if intentionally preparing a stopped target; no later Helm apply may reset that decision. The following Ready wait applies to the enabled, one-replica path. For an initially stopped target, inspect Stopped instead and use the ordinary start interface when ready. When sharing a cluster, verify the existing CRD schema against the selected archive and every installed controller before creation; an API name alone does not prove compatibility.

```bash
helm install "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --wait=legacy --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
if yq -e '.services[strenv(INSTANCE)].endpoints.https.tlsManaged' "$INSTALL_DIR/paperless-connections.yaml" >/dev/null; then
  TLS_SECRET=$(yq -er '.credentials.bindings[strenv(INSTANCE)].tls.secretName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" wait "certificate/$TLS_SECRET" --for=condition=Ready --timeout=10m
fi
curl --fail --silent --show-error --output /dev/null "$PAPERLESS_URL"
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o yaml
```

A managed-certificate timeout follows [delayed TLS diagnosis](#diagnose-delayed-managed-tls), then resumes at HTTPS verification above.

Require current-generation Ready and status.version matching the intended native version. Helm only waits for controller infrastructure. Startup observes owned state; absence selects the latest complete matching point, native database/file restore and supported migration. Lookup/integrity/identity failures never mean empty state. Existing-state restart needs no backup access.

### Create an administrator without bootstrap

Only for a freshly initialized library where `bootstrapSecret` was deliberately disabled and no administrator exists, run Paperless's native interactive command after Ready:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" exec -it deployment/paperless -c paperless -- \
  uv run --no-project python manage.py createsuperuser
```

Retain the selected administrator credentials through the installation's protected channel. This is not a recovery/reset step; restored accounts already exist.

### Verify useful behavior

First check Paperless's native **System Status** with the existing administrator account. Require database, Redis and Celery status `OK` before starting document acceptance. The authenticated native `GET /api/status/` exposes these as `database.status`, `tasks.redis_status` and `tasks.celery_status`; the same check is available in the application UI. Workload rollout and the package's gate/HTTP Ready condition alone do not establish dependency connectivity. If native health does not settle after the operation, retain its errors and diagnose them; do not restart companion components or repeat writes to conceal failure.

Dependency probes use PostgreSQL TCP readiness, excluding its temporary socket-only initialization server, and Redis's error-exit mode. These are startup prerequisites, not a substitute for the native application and document checks below.

Through real HTTPS, verify the installation's agreed useful behavior: local login or the selected OIDC login, document intake/processing, search and original download. Check the grants and workflows actually used by this installation. Verify fresh provider MFA where selected. [OIDC, MFA and token recovery](#oidc-mfa-and-token-recovery) lists the native reader permissions. The full synthetic-library matrix belongs to [package qualification](#maintainer-procedures-and-evidence), not every installation or restart.

## Resume an existing deployment

### Load retained context

In direnv-hooked Bash, enter the actual retained deployment directory; replacements use their nested `deployments/<deployment>` directory.

```bash
cd "${WORK_DIR_ROOT:-$HOME/bartl}/acme/acme-installation/clusters/cluster-1/applications/paperless"
```

At the next prompt, the selector has loaded this deployment's recorded cluster access, namespace, release and installation paths:

```bash
set -euo pipefail
umask 077
```

Context alone is sufficient for status inspection, capture/publication retry and native restart. These operations neither download a chart nor render declarations or recreate credentials.

### Inspect an installed deployment

For status inspection of an application expected to exist:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o yaml
```

### Prepare a chart-backed operation

Starting condition: retained context loaded. Use this preparation only before a Helm operation or configuration/connection rendering. Reacquire the recorded chart when absent and refresh declarations; restore protected files only when the selected operation needs them. This block creates no cluster resources or credentials:

```bash
if [ ! -d "$CHART" ]; then
  mkdir -p "$WORK_DIR/packages/$PACKAGE"
  CHART_STAGE=$(mktemp -d "$WORK_DIR/packages/.paperless.XXXXXX")
  helm pull "$CHART_REF" --version "$PACKAGE_VERSION" --untar --untardir "$CHART_STAGE"
  mv "$CHART_STAGE/bartl-paperless" "$CHART"
  rm -r "$CHART_STAGE"
fi
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
```

Continue with the selected operation.

## Capture, publication and retry

Load [retained context](#load-retained-context) only; no chart preparation is needed. A new capture requires an existing running application, backup configured and sufficient staging. Retrying publication requires a retained complete capture and working repository access, not running writers: leave runtime intent unchanged, including an intentional stop. Both use the request below. Ordinary capture resumes writers when run intent permits it. For a final point followed by ordinary stop, use the atomic request in [Final capture and source stop](#final-capture-and-source-stop).

```bash
REQUEST="manual-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl --context "$KUBE_CONTEXT" -n "$NS" annotate paperlessapplication/paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.backup.request}=$REQUEST" --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=jsonpath='{.status.backup.phase}'=Published --timeout=6h -o json > "$INSTALL_DIR/backup-result.json"
jq -e --arg request "$REQUEST" '.status.backup |
  .request == $request and .phase == "Published" and (.snapshotID | test("^[a-f0-9]{64}$"))' "$INSTALL_DIR/backup-result.json"
```

The receipt is the object that satisfied the publication wait. Do not replace it with a later `get`: a scheduled capture may already have advanced the live status. The request-ID check remains mandatory.

Require this request's Published result; inspect captureOperation, capturedAt, resumed, repositoryID, full snapshotID and publishedAt. BackupFailed is separate from application Ready. Publication restores and byte-checks a candidate before publishing the complete-tag point. The capture boundary is settled work: no active/reserved/scheduled tasks and empty queues, not interrupted-ingestion replay.

A failed publication retains its complete capture. Correct the endpoint/credential/capacity issue and issue a new request; it retries that capture, not newer work. After success, request another capture for later work. A failed capture is not publishable. If writers were quiesced and native checks reconfirm an intact source after the read-only snapshot failed, ordinary run/stop remains usable and a new request may retry capture. Unresolved work, unconfirmed source integrity and incomplete native data transitions remain isolated; never purge queues or manually clear markers. Native Jobs have six-hour outer deadlines, detached capture a one-hour bound; timeout is not proof of termination.

Monitor staging, overdue/failed requests, capture age and required independent replication. Do not prune an active/retry capture or the last usable point. Old capture cleanup needs verified publication/protection and the customer's retention authorization.

## Apply changes to a running deployment

Starting condition: a running, Ready deployment with capture/publication settled and no state-changing native work executing. Edit the intended retained configuration, then [prepare the chart-backed operation](#prepare-a-chart-backed-operation) to refresh declarations. Apply scheduling changes without changing run or routing intent:

```bash
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values --force-conflicts -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --wait=legacy --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
```

`--force-conflicts` transfers the chart's static fields from the initial `kubectl-create` manager to Helm. The chart omits both runtime fields, so this does not authorize resetting live intent. Use the same static Helm command for a deliberately stopped deployment, then wait for Stopped rather than Ready; for an enabled zero-replica deployment, verify ApplicationStopped and available database/broker instead. Do not change package/native image selection in place.

Use the dedicated version-transition and replacement procedures for those operations. Configuration changes do not repair failed state.

## Stop, start and restart

Load [retained context](#load-retained-context) only. None of these operations downloads a chart, renders connections or edits installation values.

### Stop

Whole-application stop withdraws access, finishes an explicitly requested or already admitted capture/publication without resuming writers, then stops dedicated PostgreSQL and Redis. It retains data, credentials and the selected replica count; the controller stays available. With no pending backup, stop proceeds directly. A backup failure remains visible and does not become a successful recovery point. Stop never starts a stopped application merely to satisfy a backup request.

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" patch paperlessapplication/paperless \
  --type=merge -p '{"spec":{"running":false}}'
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=condition=Stopped --timeout=7h
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication,pods,jobs,deployments,replicasets
```

Require no application, database, Redis or native-Job Pods, including terminating Pods. Requested zero replicas, a submitted stop or an unreachable API is not confirmed termination. Shared/external OIDC and backup services are outside this stop boundary. Interrupted native mutations remain failed across start and controller restart; preserve diagnostics and reconstruct an independent target.

### Start

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" patch paperlessapplication/paperless \
  --type=merge -p '{"spec":{"running":true}}'
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless
```

Start preserves the selected replica count. With one replica, wait for Ready and [verify useful behavior](#verify-useful-behavior). With zero replicas only PostgreSQL and Redis run.

### Scale the application component

The supported single-worker/RWO profile permits zero or one application replica. Zero stops the application container and its consumer, scheduler and worker, not its database/broker. Capture requires the application to be running so it can settle work through native controls.

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" scale paperlessapplication/paperless --replicas=0
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication,pods,deployments
kubectl --context "$KUBE_CONTEXT" -n "$NS" scale paperlessapplication/paperless --replicas=1
```

Scaling does not change `spec.running`; a whole-application stop wins over any replica count. `ApplicationStopped` is distinct from whole-application `Stopped`.

### Restart an independent component

Select the component requiring restart; do not restart its companions:

```bash
export COMPONENT=paperless  # paperless, paperless-db or paperless-redis
kubectl --context "$KUBE_CONTEXT" -n "$NS" rollout restart "deployment/$COMPONENT"
kubectl --context "$KUBE_CONTEXT" -n "$NS" rollout status "deployment/$COMPONENT" --timeout=10m
```

A restart does not change runtime intent or bypass failed-state isolation. For a running application, require current-generation Ready, then [native System Status and useful document acceptance](#verify-useful-behavior). For a stopped application, require that it remains stopped. Do not interrupt an admitted capture or native transition as routine maintenance.

Unavailable observation blocks dependent management work but does not revoke established execution. Ready becomes unconfirmed rather than certifying unapplied configuration. Stop remains unconfirmed until termination is observed. Invalid backup scheduling is reported separately without stopping healthy application execution; failed publication retains its capture and is not application failure.

## Recovery and replacement upgrade

Use this ordered sequence for same-release recovery or the supported 3.3.0 → 3.3.1 replacement. Supply an independent target cluster/namespace, four empty claims, retained Paperless key/client inputs, a usable repository and an authorized recovery point. Source and target share VALUES and logical instance, not storage or deployment intent.

The Base profile uses the administrator-only Traefik review route below, while the package's ordinary ingress remains disabled. Supply a reviewer IPv4/CIDR distinguishable from ordinary clients; shared NAT/proxy addresses are unsuitable. Keep production outbound effects isolated and exclude direct-service or alternate-route bypass. Other environments must supply equivalent verified isolation. Source-provider loss also needs independently enforced retirement, including a returning predecessor; DNS/unreachability alone do not provide it.

Before interrupting a reachable source, acquire the selected replacement package (or exact supplied candidate archive). For a lost source, use independently retained installation context without calling its API:

```bash
export TARGET_PACKAGE=paperless-replacement
mkdir -p "$WORK_DIR/packages"
TARGET_STAGE=$(mktemp -d "$WORK_DIR/packages/.paperless.XXXXXX")
export TARGET_PACKAGE_VERSION=0.3.0-dev.9
helm pull oci://ghcr.io/bartlapp/bartl-paperless --version "$TARGET_PACKAGE_VERSION" --untar --untardir "$TARGET_STAGE"
export TARGET_PACKAGE_VERSION
TARGET_PACKAGE_VERSION=$(helm show chart "$TARGET_STAGE/bartl-paperless" | yq -er '.version')
MATCHING_PACKAGE=$(yq -o=json '.packages // {}' "$VALUES" |
  jq -r --arg version "$TARGET_PACKAGE_VERSION" '[to_entries[] |
    select(.value.chart == "oci://ghcr.io/bartlapp/bartl-paperless" and .value.version == $version) | .key][0] // empty')
if [ -n "$MATCHING_PACKAGE" ]; then TARGET_PACKAGE="$MATCHING_PACKAGE"; fi
```

### Final capture and source stop

This source procedure uses the ordinary runtime stop field and ordinary backup request in one API update. There is no persistent withdrawal gate or cancellation operation. Keep the source installed until the target is accepted; old export-only backups remain unsupported by the complete-state path.

For a reachable source, load its retained context and [prepare the chart-backed operation](#prepare-a-chart-backed-operation), then withdraw all intake paths and prevent concurrent publication/configuration changes. Keep its writer execution running for final capture. Disable public ingress and schedules, then capture:

```bash
export SOURCE_DEPLOYMENT="$DEPLOYMENT"
export SOURCE_DIR="$INSTALL_DIR"
if [ ! -e "$SOURCE_DIR/backup-schedule-before-operation" ]; then
  (set -o noclobber; yq -r '.services[strenv(INSTANCE)].backup.schedule // ""' "$VALUES" \
    > "$SOURCE_DIR/backup-schedule-before-operation")
fi
BACKUP_SCHEDULE=$(cat "$SOURCE_DIR/backup-schedule-before-operation")
export BACKUP_SCHEDULE
yq -i '.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled = false |
  .services[strenv(INSTANCE)].backup.schedule = ""' "$VALUES"
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values --force-conflicts -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --wait=legacy --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
```

First settle any existing capture/publication, including publication retry of an older retained point, through the ordinary backup procedure while the source remains running. Then submit the final backup request and stop intent together. Capture runs only in the already-existing application execution, keeps native writers closed after the consistent point and publishes it before the ordinary stop completes. The request must not be split into two API calls: an ordinary capture could otherwise resume writers before stop is requested.

If acknowledgement is lost, inspect the live request, capture boundary and phase before doing anything else. Keep the same request identity while observing its result. Do not start the source or submit a different capture merely because a client wait timed out.

```bash
REQUEST="final-$(openssl rand -hex 8)"
kubectl --context "$KUBE_CONTEXT" -n "$NS" patch paperlessapplication/paperless --type=merge \
  -p "$(jq -nc --arg request "$REQUEST" \
    '{metadata:{annotations:{"paperless.bartl.sh/backup-request":$request}},spec:{running:false}}')"
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.backup.request}=$REQUEST" --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=jsonpath='{.status.backup.phase}'=Published --timeout=6h -o json > "$INSTALL_DIR/backup-result.json"
jq -e --arg request "$REQUEST" '.status.backup |
  .request == $request and .phase == "Published" and
  .resumed != true and
  (.captureOperation | length > 0) and
  (.snapshotID | test("^[a-f0-9]{64}$"))' "$INSTALL_DIR/backup-result.json"
```

Require this completed point and any required secondary protection. A publication failure retains the point and leaves ordinary stop intent intact. A new ordinary backup request can retry its publication while stopped; it must not start application writers. Failed or uncertain capture is not a usable point and remains visible. A completed backup does not create a separate startup lock.

Wait for the already requested ordinary stop, retaining the controller and application resource:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Stopped --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Stopped" and .status == "True" and .observedGeneration == $g)'
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pods,jobs,deployments,replicasets
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pvc -o json > "$SOURCE_DIR/source-pvc.json"
```

Require no source application, database, broker or native-Job Pods, including terminating Pods. Ordinary stopped intent survives controller/component restart. Direct and stale-address requests must fail before target activation. For an unavailable source, enforce withdrawal independently before activation; DNS or unreachability is insufficient.

For a lost source, select `SOURCE_DEPLOYMENT` and the independently recovered `SOURCE_DIR` without contacting it. Retain the original `backup.schedule` in `"$SOURCE_DIR/backup-schedule-before-operation"`; do not overwrite an existing interrupted operation's saved value with the temporarily empty schedule.

### Abandon a switch before production activation

First establish that the target has not accepted production work or caused production effects and cannot do so while the source resumes. Stop any prepared target and confirm termination. If production effects may have occurred, keep the source stopped and reconcile authority and data before deciding how to recover. The package does not inspect another installation.

If a target was prepared, remove its operator-owned review route in the target-administration terminal after confirming its stop:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete ingress/paperless-review --ignore-not-found --wait=true
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete middleware/paperless-review --ignore-not-found
```

Return to the original source-administration terminal and [load the source's retained context](#load-retained-context), not the replacement deployment. Use ordinary start:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" patch paperlessapplication/paperless \
  --type=merge -p '{"spec":{"running":true}}'
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=condition=Ready --timeout=30m
```

Start does not enable ingress or select the production route. It does not repair a genuinely incomplete restore/migration. The old point remains a historical backup, not proof of later source work; a later switch requires a new final capture.

With the target confirmed stopped and the intact source Ready, [prepare the source's chart-backed operation](#prepare-a-chart-backed-operation). If DNS was moved, restore the hostname to the source ingress through [DNS and external TLS](#dns-and-external-tls), retaining its existing TLS configuration and credentials. Restore the source's ordinary route and saved schedule:

```bash
BACKUP_SCHEDULE=$(cat "$INSTALL_DIR/backup-schedule-before-operation")
export BACKUP_SCHEDULE
yq -i '.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled = true |
  .services[strenv(INSTANCE)].backup.schedule = strenv(BACKUP_SCHEDULE)' "$VALUES"
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values --force-conflicts -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --wait=legacy --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=condition=Ready --timeout=30m
```

Verify the source's [native health and useful behavior](#verify-useful-behavior) through its actual HTTPS address, and verify the restored schedule. An originally empty schedule remains manual-only. Only then remove this operation's temporary schedule input so a later switch records the then-current schedule:

```bash
rm "$INSTALL_DIR/backup-schedule-before-operation"
```



### Prepare the independent target

Choose a fresh deployment/namespace and existing compatible target cluster. Preserve logical identity and static service settings. The selected destination package determines the native target and performs every required restore/migration step. Never copy source runtime intent, CR status, ownership annotations or controller operation records. Blue/green namespaces may coexist only with compatible cluster-wide APIs; an incompatible API requires an independent target cluster.

```bash
{
export DEPLOYMENT=paperless-replacement
export TARGET_CLUSTER=cluster-2
export TARGET_NAMESPACE=paperless-green
export SOURCE_DEPLOYMENT SOURCE_DIR
INSTANCE=$(yq -er '.deployments[strenv(SOURCE_DEPLOYMENT)].instance' "$VALUES")
export INSTANCE
yq -e '.packages[strenv(TARGET_PACKAGE)] == null or
  (.packages[strenv(TARGET_PACKAGE)].version == strenv(TARGET_PACKAGE_VERSION) and
   .packages[strenv(TARGET_PACKAGE)].chart == "oci://ghcr.io/bartlapp/bartl-paperless")' "$VALUES" >/dev/null
yq -i '.deployments[strenv(DEPLOYMENT)] = {
  "instance": strenv(INSTANCE), "cluster": strenv(TARGET_CLUSTER),
  "namespace": strenv(TARGET_NAMESPACE), "release": "paperless", "package": strenv(TARGET_PACKAGE)
} | .packages[strenv(TARGET_PACKAGE)] = (.packages[strenv(TARGET_PACKAGE)] // {
  "version": strenv(TARGET_PACKAGE_VERSION), "chart": "oci://ghcr.io/bartlapp/bartl-paperless"
}) | .operations.deployments[strenv(DEPLOYMENT)] = {"ingressEnabled": false} |
  .services[strenv(INSTANCE)].backup.schedule = "" |
  del(.services[strenv(INSTANCE)].replicas, .services[strenv(INSTANCE)].running,
      .services[strenv(INSTANCE)].version)' "$VALUES"
TARGET_DIR="$WORK_DIR/clusters/$TARGET_CLUSTER/applications/$INSTANCE/deployments/$DEPLOYMENT"
mkdir -p "$TARGET_DIR" "$WORK_DIR/packages/$TARGET_PACKAGE"
(
  set -o noclobber
  printf 'source_env ../../../../.envrc\nload_deployment "%s"\n' "$DEPLOYMENT" > "$TARGET_DIR/.envrc"
)
if [ ! -d "$WORK_DIR/packages/$TARGET_PACKAGE/$TARGET_PACKAGE_VERSION" ]; then
  mv "$TARGET_STAGE/bartl-paperless" "$WORK_DIR/packages/$TARGET_PACKAGE/$TARGET_PACKAGE_VERSION"
fi
rm -r "$TARGET_STAGE"
direnv allow "$TARGET_DIR"
cd "$TARGET_DIR"
}
```

Wait for the next prompt. Keep `SOURCE_DIR` and the retained backup schedule through acceptance; source and target retain distinct context and operation intent.


```bash
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
kubectl --context "$KUBE_CONTEXT" get nodes,storageclass
kubectl --context "$KUBE_CONTEXT" create namespace "$NS"
for entry in storage:10Gi database:5Gi broker:1Gi staging:20Gi; do
  role=${entry%:*}; size=${entry#*:}
  name=$(ROLE="$role" yq -er '.storage.claims[strenv(INSTANCE)][strenv(ROLE)].claimName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" create -f - <<EOF
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
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pvc
cp -R "$SOURCE_DIR/protected" "$INSTALL_DIR/protected"
```

The protected copy supplies the original Paperless key, database password and OIDC client secret, not source-local database/media or ownership annotations. For a surviving secondary, select its URL in backup.repository (or refresh the existing composed binding) and supply its actual reader/writer files in target repository/{reader,writer}. Preserve its destination snapshot identity rather than assuming primary IDs. For an unchanged surviving repository, restore the retained original repository files.

Refresh declarations after the selected destination, prepare scoped Secrets and render target configuration:

```bash
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
for pair in reader:backupReader writer:backupWriter; do
  directory=${pair%%:*}; role=${pair#*:}
  name=$(ROLE="$role" yq -er '.credentials.bindings[strenv(INSTANCE)][strenv(ROLE)].secretName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret generic "$name" \
    --from-file="$INSTALL_DIR/repository/$directory/"
done
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=configuration \
  --show-only templates/configuration.yaml > "$INSTALL_DIR/configuration.yaml"
CONFIG_SECRET=$(yq -er '.configuration[strenv(INSTANCE)].secretName' "$INSTALL_DIR/configuration.yaml")
yq -o=json '.configuration[strenv(INSTANCE)]' "$INSTALL_DIR/configuration.yaml" > "$INSTALL_DIR/configuration.json"
jq --rawfile secretKey "$INSTALL_DIR/protected/secret-key" \
  --rawfile dbPassword "$INSTALL_DIR/protected/database-password" '
  .environment + {PAPERLESS_SECRET_KEY: ($secretKey | rtrimstr("\n")), PAPERLESS_DBPASS: ($dbPassword | rtrimstr("\n"))}
' "$INSTALL_DIR/configuration.json" > "$INSTALL_DIR/protected/environment.json"
if jq -e '.oidc.clientSecretRequired == true' "$INSTALL_DIR/configuration.json" >/dev/null; then
  jq --rawfile clientSecret "$INSTALL_DIR/protected/oidc-client-secret" '
    .PAPERLESS_SOCIALACCOUNT_PROVIDERS |=
      (fromjson | .openid_connect.APPS[0].secret = ($clientSecret | rtrimstr("\n")) | tojson)
  ' "$INSTALL_DIR/protected/environment.json" > "$INSTALL_DIR/protected/environment-oidc.json"
  mv "$INSTALL_DIR/protected/environment-oidc.json" "$INSTALL_DIR/protected/environment.json"
fi
if [ -e "$INSTALL_DIR/protected/client-ca/ca-bundle.pem" ] || [ -L "$INSTALL_DIR/protected/client-ca/ca-bundle.pem" ]; then
  test -s "$INSTALL_DIR/protected/client-ca/ca-bundle.pem"
  CLIENT_CA_SECRET=$(yq -er '.credentials.bindings[strenv(INSTANCE)].clientCA.secretName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret generic "$CLIENT_CA_SECRET" \
    --from-file=ca-bundle.pem="$INSTALL_DIR/protected/client-ca/ca-bundle.pem" --dry-run=client -o yaml | \
    kubectl --context "$KUBE_CONTEXT" apply --server-side --field-manager=paperless-preparation -f -
  jq '
    . + {REQUESTS_CA_BUNDLE: "/configuration/ca-bundle.pem"}
  ' "$INSTALL_DIR/protected/environment.json" > "$INSTALL_DIR/protected/environment-ca.json"
  mv "$INSTALL_DIR/protected/environment-ca.json" "$INSTALL_DIR/protected/environment.json"
fi
jq -n --arg name "$CONFIG_SECRET" --arg namespace "$NS" \
  --slurpfile environment "$INSTALL_DIR/protected/environment.json" '{
    apiVersion: "v1", kind: "Secret", type: "Opaque",
    metadata: {name: $name, namespace: $namespace}, stringData: $environment[0]
  }' | kubectl --context "$KUBE_CONTEXT" apply --server-side --field-manager=paperless-preparation -f -
```

Do not create a new bootstrap identity for restored state. For external TLS only, supply its target certificate/key and retain tls.managed: false:

```bash
TLS_SECRET=$(helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --set "operations.deployments.${DEPLOYMENT//./\\.}.ingressEnabled=true" \
  --show-only templates/connections.yaml |
  yq -er '.credentials.bindings[strenv(INSTANCE)].tls.secretName')
kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret tls "$TLS_SECRET" \
  --cert="$INSTALL_DIR/tls/fullchain.pem" --key="$INSTALL_DIR/tls/key.pem"
```

Only this offline declaration lookup enables routing in its render inputs, so the chart emits the future TLS binding. The retained recovery ingress intent remains false; no route is applied.

Inspect the target ingress and point the authorized hostname to it. Require authoritative/public DNS and no conflicting AAAA before managed issuance; the application route remains disabled:

```bash
kubectl --context "$KUBE_CONTEXT" -n kube-system get service traefik -o wide
printf '%s\n' "$PAPERLESS_HOST"
dig "$PAPERLESS_HOST" A +trace
dig @1.1.1.1 +short "$PAPERLESS_HOST" A
dig @8.8.8.8 +short "$PAPERLESS_HOST" A
```

### Reconstruct, review and activate

The source is write-withdrawn and stopped, or independently prevented from serving and causing production effects. Run the one-time application-creation block in [Install and verify](#install-and-verify) using this target's context and explicit new runtime intent; then install with target routing still disabled:

```bash
helm install "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --wait=legacy --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
if yq -e '.services[strenv(INSTANCE)].endpoints.https.tlsManaged' "$INSTALL_DIR/paperless-connections.yaml" >/dev/null; then
  TLS_SECRET=$(yq -er '.credentials.bindings[strenv(INSTANCE)].tls.secretName' "$INSTALL_DIR/paperless-connections.yaml")
  kubectl --context "$KUBE_CONTEXT" -n "$NS" wait "certificate/$TLS_SECRET" --for=condition=Ready --timeout=10m
fi
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json > "$INSTALL_DIR/recovery-result.json"
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pvc -o json > "$INSTALL_DIR/target-pvc.json"
```

A managed-certificate timeout follows [delayed TLS diagnosis](#diagnose-delayed-managed-tls), then resumes with the recovery-result and target-PVC records above. Keep ordinary access disabled.

Inspect status.operation/status.operations and native Job results. Require the authorized repository/full snapshot, expected native version and independent PVC UIDs/backing volumes. Ready with an empty initialization is not recovery of expected history. Failure stays isolated; preserve diagnostics and use another independent empty target, never clear markers or replay an ambiguous restore.

The target ingress must preserve real client addresses for the review allowlist. Base establishes this during provisioning; the administrator of an equivalent supplied cluster provides that behavior.

Confirm source withdrawal and no ordinary route for this hostname. Create a separate, operator-owned review Ingress and namespace-local allowlist. Do not edit the controller-owned `paperless` Ingress; it must remain absent. The offline lookup below obtains TLS/class settings without enabling a route:

```bash
export REVIEW_CIDR=203.0.113.10/32  # Replace with the authorized reviewer's actual source CIDR.
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait ingress/paperless --for=delete --timeout=5m
kubectl --context "$KUBE_CONTEXT" get ingress --all-namespaces
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --set-string renderMode=connections \
  --set "operations.deployments.${DEPLOYMENT//./\\.}.ingressEnabled=true" \
  --show-only templates/connections.yaml > "$INSTALL_DIR/review-connections.yaml"
TLS_SECRET=$(yq -er '.credentials.bindings[strenv(INSTANCE)].tls.secretName' "$INSTALL_DIR/review-connections.yaml")
INGRESS_CLASS=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.ingressClass' "$INSTALL_DIR/review-connections.yaml")
kubectl --context "$KUBE_CONTEXT" -n "$NS" create -f - <<EOF
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: paperless-review
spec:
  ipAllowList:
    sourceRange: ["$REVIEW_CIDR"]
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: paperless-review
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.middlewares: "$NS-paperless-review@kubernetescrd"
spec:
  ingressClassName: "$INGRESS_CLASS"
  tls:
    - hosts: ["$PAPERLESS_HOST"]
      secretName: "$TLS_SECRET"
  rules:
    - host: "$PAPERLESS_HOST"
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: paperless
                port:
                  number: 8000
EOF
printf '%s\n' "$PAPERLESS_URL"
```

Continue on the reviewer client whose address is allowed above; it may differ from the cluster-administration shell. Carry the printed `PAPERLESS_URL` and the selected client CA trust to that client. It needs no cluster or provider credentials for this HTTPS check.

```bash
# Wait for Traefik to install both the route and its certificate.
# Each read-only attempt must pass certificate and hostname verification.
curl --fail --silent --show-error --output /dev/null --max-time 10 \
  --retry 30 --retry-delay 2 --retry-max-time 60 --retry-all-errors "$PAPERLESS_URL"
```

If this check fails, retain the error and inspect the address and certificate actually used by the reviewer:

```bash
curl --verbose --output /dev/null --max-time 10 "$PAPERLESS_URL"
```

Have the target administrator compare that address with the observed target ingress. The reviewer's resolver can still cache the predecessor independently of public or cluster DNS; allow the old TTL to expire before retrying the unchanged URL and CA trust. If the address is already correct, the administrator checks the target route and certificate. A default self-signed ingress certificate is not an additional trust root.

Require trusted HTTPS from the reviewer address and HTTP 403 from an independent ordinary source, including a request with a forged `X-Forwarded-For` header naming the reviewer. With no `ipStrategy` configured, the allowlist uses the connection source address. Verify the deployed Middleware and other hostname routes if this fails; do not broaden the allowlist. Ordinary ingress and schedules stay disabled throughout review.

From the allowed address, verify the selected point's expected documents, metadata, grants and the installation's agreed search/workflow behavior. Verify fresh local or selected OIDC login and retained API credentials; [token recovery](#oidc-mfa-and-token-recovery) is available if a consumer needs its existing credential delivered again. Complete the [records review](#records-after-restore) before affected use resumes. Ingest a permitted test document and verify processing/search/download. Review work must remain isolated from production effects; acceptance work does not authorize concurrent production.

Return to the original target-administration terminal, with the target deployment's retained context still selected. The reviewer client needs no Kubernetes credentials. Publish the new work there; keep this administration terminal for the subsequent activation commands:

```bash
REQUEST="manual-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl --context "$KUBE_CONTEXT" -n "$NS" annotate paperlessapplication/paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.backup.request}=$REQUEST" --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=jsonpath='{.status.backup.phase}'=Published --timeout=6h -o json > "$INSTALL_DIR/backup-result.json"
jq -e --arg request "$REQUEST" '.status.backup |
  .request == $request and .phase == "Published" and (.snapshotID | test("^[a-f0-9]{64}$"))' "$INSTALL_DIR/backup-result.json"
```

Require this capture to include the new work. The maintainer's exhaustive synthetic-library fixtures are not required for each recovery; useful restored behavior, new work and a subsequent usable backup are.

Only after acceptance and records approval, restore approved production dependencies and replace the review route with ordinary access. Keep the active deployment, selected point and necessary operating restrictions in the installation record; qualification results belong with the release. Keep source stop intent unchanged. If target writes/effects occurred, do not automatically reactivate the old source.

Delete the operator-owned review route first, then enable the ordinary route and restore the retained schedule. An originally empty schedule remains manual-only:

```bash
BACKUP_SCHEDULE=$(cat "$SOURCE_DIR/backup-schedule-before-operation")
export BACKUP_SCHEDULE
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete ingress/paperless-review --wait=true
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete middleware/paperless-review
yq -i '.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled = true |
  .services[strenv(INSTANCE)].backup.schedule = strenv(BACKUP_SCHEDULE)' "$VALUES"
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values --force-conflicts -f "$VALUES" \
  --set-string deployment="$DEPLOYMENT" --wait=legacy --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json |
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
```

Verify ordinary access and the restored schedule before removing `"$SOURCE_DIR/backup-schedule-before-operation"`. Keep that temporary input independently available while recovery is unfinished; in another shell select the same source-input directory before activation.

If activation is interrupted or its acknowledgement is lost, observe both route objects and the selected deployment before retrying. Confirm that source withdrawal remains enforced. Only the target may serve: the review route alone permits review, the ordinary target ingress permits production, and neither means an outage. Do not infer the active generation from DNS or an earlier command exit. Verify the target's current application UID, PVC identities and a useful document request at the production address, then retain that deployment as active. If it may have accepted production work or caused production effects, do not cancel source withdrawal.

After accepted production activation, retain source diagnostics and the final point, then load the source context and follow [Remove the release](#remove-the-release). This is final disposal, not a prerequisite for target preparation or a cancellation mechanism. Retain or dispose of source PVCs and protected inputs only under the installation's data-retention decision.


## Remove the release

Load retained context, retain needed diagnostics and complete [whole-application stop](#stop). Confirm all dedicated execution has ended and the required recovery point and credentials survive removal. Finalize while the controller remains alive:


```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete paperlessapplication/paperless --wait=true --timeout=10m
helm uninstall "$RELEASE" --kube-context "$KUBE_CONTEXT" -n "$NS" --cascade=foreground --wait --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pvc,secrets
```

Finalization removes owned execution and access, but retains claims, data, Secrets and the original claim-owner annotations. A new application cannot acquire those retired claims; reconstruct on independent storage. Do not clear ownership bindings, bypass finalizers or delete the controller/namespace first. A timeout is not authorization to force deletion.

Recovery after removal uses an independent target and a supported backup, not adoption of old management resources or manual marker removal. Namespace/PVC deletion needs a separate data-disposition decision. Infrastructure and owned DNS cleanup are separate; never delete shared CRDs, external services or backup history as application cleanup.


## OIDC, MFA and token recovery

Use the package configuration rendering and provider preparation above; do not hand-author allauth JSON. Verify an actual fresh browser login, not only an existing session; when provider TOTP is selected for this profile, require it for the intended users and verify it during that login. Paperless retains its own users, groups and object permissions. Deliberately link an existing account through its native profile; do not assume matching email establishes identity. First-login provisioning and permission assignment are native administration, not package startup tests.

A read-only browser group needs `view_document`, `view_uisettings`, `add_uisettings`, `change_uisettings` and `view_savedview`, in addition to its document object grants. Native metadata views may also need `view_tag`, `view_correspondent`, `view_documenttype` and `view_storagepath`. UI-settings permissions do not grant document modification or user administration.

Complete database restore retains DRF API tokens and Django sessions at the selected point. Token reacquisition is not a restore prerequisite. Native session expiry and the independently retained Paperless key still apply. A token revoked or rotated after that point may become valid again after recovery; reconcile subsequent security changes before production access. If a local password account needs its existing token delivered again, use `POST /api/token/`; Paperless-local MFA, when enabled, additionally requires its native `code`. For an SSO-only user, an authorized operator can use the native management command:

```sh
# Treat stdout as a secret; do not put it in general logs.
kubectl --context "$KUBE_CONTEXT" -n "$NS" exec deployment/paperless -c paperless -- \
  uv run --no-project python manage.py drf_create_token USERNAME
```

Omit `--reset`/`-r`: default `get_or_create` returns an existing token without rotation. This does not set a local password or elevate the user's permissions. Deliver the token through the installation's protected credential channel; the authenticated user's `GET /api/profile/` also exposes that user's existing token. The profile's `generate_auth_token` endpoint deliberately rotates tokens and is not this recovery procedure. MFA protects interactive identity login, not every use of a bearer API token. Token issuance, account probes and records review are never ordinary startup dependencies.

## State boundary

The consistent point is one native PostgreSQL custom-format dump plus owned application files, format-2 inventory, hashes, logical identity and source version, published under one complete Restic snapshot. Database and files are captured while all native writers remain stopped: capture closes intake, stops scheduler/consumer, settles worker queues, ends writer descendants and waits for database sessions. A complete dump alone is not a consistent application point. Residual pending/started intake or scratch inputs prevent successful capture; queues are never purged to manufacture success.

| Mutable state | Capture and reconstruction boundary |
| --- | --- |
| PostgreSQL metadata, document versions/relationships, users/passwords/groups/grants, workflow definitions and execution history, task outcomes, settings, social identity and MFA authenticators | Native `pg_dump`/`pg_restore`, then automatic native migrations. All application tables and native timestamp precision are retained. Audit history includes what the source actually recorded; capture does not create missing history. |
| Originals, version files, archive renditions, thumbnails and share-link bundles | Owned media copied under the same stopped-writer boundary; inventory sizes and SHA-256 hashes verified before reconstruction. |
| Consume directory, API/browser scratch inputs and Redis queued/unacknowledged work | Pending inputs persist on owned storage. `PAPERLESS_SCRATCH_DIR` selects `/usr/src/paperless/data/scratch`; native initialization sets permissions and native processing cleans completed inputs. Capture requires settled work and refuses unresolved inputs. A successful point contains completed work; reconstruction uses empty target Redis, not replay of predecessor queues. |
| Search index and derived classifier data | Owned data retained; native migration/reindex completes before target admission. A 3.3.0 point is restored with its matching runtime, then the 3.3.1 native schema 3 → 4 reindex runs automatically. |
| DRF API tokens and Django browser sessions | Retained in the database, subject to native expiry and the original Paperless key. Later revocations, rotations, logout and permission changes require recovery review. |
| Paperless secret key, configuration, TLS, selected OIDC inputs, backup credentials/encryption key | Independently retained inputs, not available solely inside the encrypted point. External services retain their own authority. |
| Capture staging and local binding/transition records | Target-local coordination and publication retry, excluded from reconstructed application state. The package's `bartl_binding` table is excluded from the dump; the target creates its own database/file binding. Replacement never copies predecessor operation records, runtime intent or Kubernetes ownership. |

The profile covers API/browser intake and metadata-assignment workflows. Mail polling, remote OCR/AI, custom scripts, external-effect workflows, shared databases/brokers and optional DB read caching are not implicitly qualified. PostgreSQL and Redis are dedicated owned components. Full database preservation removes export-specific token/session omissions and timestamp truncation; it does not recover changes after the selected point or establish Paperless-local MFA qualification.

## Source retention

Confirm completed ingestion and a readable original. Keep its source until a capture containing it has been published, verified and protected against the failure declared in the retained installation inputs. If that protection requires a secondary, primary publication alone is insufficient; use the backup service's result to establish protection. Paper, email or a device suffices if it survives that failure; otherwise retain a durable holding copy, not a new intake service or receipt ledger.

The result identifies installation, capture boundary, publication/verification completion, exact Restic point and outcome. Publication after upload does not prove inclusion if capture began earlier; check native inventory and original checksums when uncertain. Unsettled ingestion is not covered. Then perform only permitted source-copy cleanup; backup success never authorizes destruction of legally required originals.

After recovery, compare retained sources with the restored library before re-ingesting missing documents. Do not blindly replay or merge records solely because their bytes match.

## Records after restore

A recovery point reflects records and security state at capture, not later deletion, hold, restriction, token revocation or identity changes. Its restored audit history cannot supply missing later changes. After technical recovery in isolation, the responsible person checks independently surviving approvals, disposal records, correspondence or newer evidence and applies corrections through native administration before affected use resumes. This is a records-policy review, not a second technical startup authorization; it applies neither to ordinary restart nor nightly capture.

Where evidence is insufficient, keep affected access/processing closed and resolve the exception with the installation's named records owner. Review cannot reconstruct missing information. Use the independently surviving decision evidence and review responsibilities recorded in the [installation inputs](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md#installation-inputs); retain the review result and unresolved restrictions there, with protected evidence referenced as appropriate. Existing approvals, disposal records and correspondence may suffice; a new decision file is justified only by a demonstrated gap.


## Configuration reference and qualification

The selected archive ships the service interface and static defaults. Inputs under `services.<instance>` include hostname, claims.{storage,database,broker,staging}, configurationSecret, bootstrapSecret, identityProvider or oidc.issuer, optional OIDC clientId/providerId/name, ingress enabled/className/tlsSecret, tls managed/acmeServer and backup repository or endpoint, enabled, readerSecret/writerSecret, schedule/timeZone/drainSeconds. Unknown selected-service fields fail. `running`, `replicas` and native-version overrides are rejected; the selected package determines native code and supported transitions.

Connection rendering exposes HTTPS, OIDC/backup requests, credential bindings and storage claims. Configuration rendering exposes the configuration Secret environment. Protected values are added locally, never to VALUES. Refresh derived bindings after inputs change. Deployment selection validates namespace, Helm release and package version; its sole operational override is static `ingressEnabled`. Runtime intent has no installation-values copy.

Exact-artifact qualification belongs in the existing release record. Earlier candidate results do not qualify changed paths in 0.3.0-dev.7; dev.6's active-ingestion capture failure remains attached to that candidate. Standalone acceptance remains separate from later coordinated multi-application qualification.

## Maintainer procedures and evidence

The README owns operating recipes. Run offline regressions with:

```bash
go test ./...
uv run --no-project --with requests==2.33.0 --with cryptography==50.0.0 python -m unittest discover -s tests -v
node tests/chart.mjs
```

The client-CA regression uses an ephemeral local HTTPS server to check native Requests GET/POST, unchanged default rejection, hostname enforcement and missing/invalid bundles. Its dependency pins match the supported 3.3.1 upstream lock. It does not qualify a running OIDC service; repeat fresh OIDC login against the selected complete bundle using the exact candidate controller/runtime artifacts.


Qualify exact artifacts through every applicable [contract case](https://github.com/bartlapp/bartl-app/blob/main/docs/application-contract.md#supported-configuration-and-catalogue-evidence): both initialization branches, restart without backup access, durable intent under static changes/controller restart, independent component restart, whole stop, consistent capture, independent reconstruction, new work and reconstruction of its next point, native search-schema transition, observation/lookup/integrity/native failures, publication retry, conflicting/stale work, persistent interrupted-transition isolation and independent-target retry. Exercise foreign-state protection and operator authority transfer, stale access, returning-source behavior and interrupted activation. Verify original/version/rendition bytes, metadata, grants, workflows and search, not merely Ready or login. Qualify selected OIDC/MFA where used; local authentication needs no Keycloak.

For the workflow-history regression, ingest a synthetic document titled `Synthetic workflow history`. From the package checkout run preparation against the source, then capture and reconstruct through the package. Run verification against the reconstructed target without changing its workflow history:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" exec -i deployment/paperless -- \
  env WORKFLOW_CHECK=prepare uv run --no-project python manage.py shell < tests/workflow-history.py
# After package reconstruction, select the target's retained context.
kubectl --context "$KUBE_CONTEXT" -n "$NS" exec -i deployment/paperless -- \
  env WORKFLOW_CHECK=verify uv run --no-project python manage.py shell < tests/workflow-history.py
```

For pending uploads, occupy the native worker with known bounded work, accept additional API/browser inputs and retain each returned task ID and original file. Supply `url`, `tokenFile` and `uploads` in a protected JSON file; each upload identifies `task`, `originalFile`, synthetic `title`, expected `owner` and `tags`. Establish that these tasks are pending before interruption, then verify task success, original bytes and metadata after each independent application restart, scale-to-zero cycle and whole stop/start:

```bash
node tests/pending-uploads.mjs pending /protected/pending-inputs.json
# Perform the selected native lifecycle operation.
node tests/pending-uploads.mjs verify /protected/pending-inputs.json
```

Use the supplied CA bundle through `NODE_EXTRA_CA_CERTS` when needed. The verifier waits up to 3,900 seconds by default, allowing native Redis redelivery after an interrupted worker; it neither shortens native visibility timeouts nor republishes tasks. Retain task, broker and scratch diagnostics when work is interrupted. Also initiate capture during known active/pending ingestion: require either completed consistent work or visible refusal with inputs retained. Verify atomic backup plus ordinary stop, no post-capture writer resumption, publication retry without starting the source, stop persistence across controller restart, ordinary explicit start and a new usable point after resumed work.

For the repeatable fixture, start with an empty disposable library and a provisioned non-administrator native user (local or selected OIDC). The preparer creates a reader group, a denied user without document grants, a document-added assignment workflow and a synthetic root with a second file version. It retains originals and native archive PDF renditions separately; it does not alter startup or capture.

```bash
export PAPERLESS_READER=reader-proof  # The actual provisioned native username.
export LIBRARY_WORK="$WORK_DIR/.access/$INSTANCE"
mkdir -p "$LIBRARY_WORK"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_ADMIN=$(cat "$INSTALL_DIR/protected/bootstrap-user")
kubectl --context "$KUBE_CONTEXT" -n "$NS" exec deployment/paperless -c paperless -- \
  uv run --no-project python manage.py drf_create_token "$PAPERLESS_ADMIN" |
  jq -Rer 'select(startswith("Generated token ")) |
    capture("^Generated token (?<token>[0-9a-f]+) for user ").token' > "$LIBRARY_WORK/admin-token"
jq -n --arg url "$PAPERLESS_URL" --arg token "$LIBRARY_WORK/admin-token" \
  --arg reader "$PAPERLESS_READER" --arg output "$LIBRARY_WORK/library" \
  '{url:$url,adminTokenFile:$token,readerUsername:$reader,outputDir:$output}' > "$LIBRARY_WORK/library-setup.json"
```

From the package source checkout, with Node.js 22 and the selected validating CA bundle supplied through `NODE_EXTRA_CA_CERTS` when needed:

```bash
node tests/prepare-library.mjs "$LIBRARY_WORK/library-setup.json"
```

The output directory must be new. An interrupted preparation retains native resource IDs in `creation.json`; inspect those resources before cleanup or retry, rather than rerunning mutations over partial state. The script deliberately refuses existing documents, groups, tags, workflows or reader grants. Return to the selected deployment shell and supply the native API tokens:

```bash
for actor in admin reader denied; do
  if [ "$actor" = admin ]; then
    username=$(cat "$INSTALL_DIR/protected/bootstrap-user")
  else
    username=$(jq -er --arg actor "$actor" '.[$actor]' "$LIBRARY_WORK/library/usernames.json")
  fi
  kubectl --context "$KUBE_CONTEXT" -n "$NS" exec deployment/paperless -c paperless -- \
    uv run --no-project python manage.py drf_create_token "$username" |
    jq -Rer 'select(startswith("Generated token ")) |
      capture("^Generated token (?<token>[0-9a-f]+) for user ").token' > "$LIBRARY_WORK/token"
  jq --arg actor "$actor" --rawfile token "$LIBRARY_WORK/token" \
    '.[$actor] = ($token | rtrimstr("\n"))' "$LIBRARY_WORK/library/tokens.json" > "$LIBRARY_WORK/library/tokens.new.json"
  mv "$LIBRARY_WORK/library/tokens.new.json" "$LIBRARY_WORK/library/tokens.json"
done
rm "$LIBRARY_WORK/token"
```

Use the generated `library/library-inputs.json` for the checker below. Baseline it once after preparation; do not regenerate its expected state merely to pass a transition. After reconstruction, verify using the retained tokens rather than rotating or reissuing them. Keep the original fixture files and expected state for comparison. New work belongs to a subsequent explicitly selected baseline and recovery point.

Synthetic-library checks use:

```bash
node tests/check-library.mjs baseline /protected/library-inputs.json
node tests/check-library.mjs verify /protected/library-inputs.json
```

Only synthetic documents with titles beginning `Synthetic ` are allowed. Inputs contain `url`, `tokensFile` (admin/reader/denied test-role tokens), `expectedFile`, `fixturesDir`, `files` (route/file with optional actor/deniedActors), `searches` (query/ids with optional actor) and `readOnlyDocument`. Include required versions/renditions. Baseline precedes capture; verify follows each transition with recovered credentials. Keep inputs, tokens, expected state and raw output outside Git; retain exact artifacts, concise results and material limits in the existing release/integration record.

On 27 November 2026, exact candidate `0.3.0-dev.9` passed both initialization branches (no repository and configured empty repository), native browser login, complete-state reconstruction and an injected read-only staging failure. The failed capture left the confirmed-intact source usable: existing data verified and a new document was ingested. After removing only the injected filesystem fault, a new atomic backup/stop request published a point and stopped the application without repair or unlock. Ordinary start succeeded without backup credentials; controller/component restarts had not undone the stop. A fresh namespace with independent claims then restored the new point, preserving seven document/version records, fourteen original/archive files, metadata, permissions, search, workflow, retained API tokens and the original browser session. Local checks passed the Go suite, 22 native tests and 15 checks against the exact chart archive.

The same run exercised active-ingestion drain, lost-acknowledgement recovery, stopped publication retry and the native 3.3.0 → 3.3.1 transition on `0.3.0-dev.8`. Those cases were not rerun on `0.3.0-dev.9`. Candidate 8 exposed the intact-source failure-classification defect corrected in candidate 9; retain its evidence as version-specific, not as qualification of the replacement bytes. Exact artifacts, source identities and these limits belong in the respective unpublished draft releases. This run does not complete the full contract matrix or qualify fresh OIDC/MFA, HA or provider-loss recovery.

Historical 0.1.0 runtime tests on 25 October 2026 restored after source-VM deletion, covering originals/versions, relationships, metadata, permissions, token reacquisition, search and another backup restored into fresh database/file/Redis storage. That export-only candidate had millisecond version-added timestamp precision; it does not qualify format-2 fidelity. Other historical package fault scenarios removed source installations/storage and primary repositories on one disposable K3s host; they do not establish host/provider-loss failover or cross-cluster fencing. The target was Debian 13 amd64, K3s v1.36.5+k3s1, cert-manager 1.21.3 and Helm 4.3.0; Podman 5.4.2 built images.

Historical 0.1.0 chart archive SHA-256: `dc87e82d5350a4f31850ef801521f836e4567e8ecf81e3a7e319e7935e48dfa8`; OCI manifest: `ef2bf48e83bb7b919d85d36d18ad6191373e401c74f03c402e88c749d1601c0d`. These identify historical evidence, not a supported flat-values adoption path.

Native observations on 24 October showed queued work surviving tested replacements, but interrupted active work did not settle within the observation window and revocation did not survive worker replacement. Warm shutdown did not independently prove writer/descendant termination. These findings justify settled-work capture, not replay/reconciliation. The experimental supervisor/scripts/chart/reconciliation code retired in `82e4357` is not the current design.

The controller binds native work to application/operation, Pod UID, container ID and execution UUID. Target-local locking, database/file binding and pending-transition markers exclude concurrent or ambiguous restore/capture. The s6 prerequisite runs before migrations/init-complete; upstream custom-init alone logs errors and continues. Capture ends writer descendants and database sessions. Ordinary running intent decides whether writers resume; an admitted backup combined with stopped intent drains through capture/publication before whole-application stop. Publication retries read the retained point without recreating writers. A failed read-only capture is a backup failure, not damaged application state, when native checks confirm the source remains intact. Unknown or unsettled state remains isolated. Ordinary start needs no cancellation operation. Target reconstruction never copies source-local authority or operation state.

## Building and publishing

Source/registry policy and authorization precede remote writes. Never reuse published versions, silently change existing visibility/access or rebuild after qualification. For chart-only changes, select a new chart version and retain the existing pinned runtime/controller images; package once and retain SHA256SUMS plus OCI/image identities with the release. Published 0.2.0 is immutable.

Runtime changes require an authorized Linux amd64 builder with Podman, Skopeo, Helm, yq and sha256sum. Set the new chart version, then:

```bash
OUT=/protected/paperless-candidate
OUT="$OUT" bash build.sh
```

Output contains three OCI image directories, a digest-pinned chart, image-values.yaml, image digests and SHA256SUMS. Retain these exact bytes through the [candidate custody procedure](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md#qualify-the-delivered-path), then qualify them without rebuilding. Candidate upload and stable publication must both be authorized; that authorization may cover the whole sequence.

Before qualification, make the new images retrievable by their pinned digests without publishing the stable chart. With authorized registry access in `REGISTRY_AUTH_FILE`, select an unused candidate tag derived from this build's controller digest:

```bash
RELEASE=$(yq -r '.version' "$OUT/chart/Chart.yaml")
CANDIDATE="candidate-$RELEASE-$(cut -d: -f2 "$OUT/paperless-controller.digest")"
skopeo copy --authfile "$REGISTRY_AUTH_FILE" --preserve-digests \
  "oci:$OUT/paperless-3.3.0" "docker://ghcr.io/bartlapp/bartl-paperless-runtime:3.3.0-$CANDIDATE"
skopeo copy --authfile "$REGISTRY_AUTH_FILE" --preserve-digests \
  "oci:$OUT/paperless-3.3.1" "docker://ghcr.io/bartlapp/bartl-paperless-runtime:3.3.1-$CANDIDATE"
skopeo copy --authfile "$REGISTRY_AUTH_FILE" --preserve-digests \
  "oci:$OUT/paperless-controller" "docker://ghcr.io/bartlapp/bartl-paperless-controller:$CANDIDATE"
```

Verify each registry manifest against its retained `.digest` and retain the chart/checksums and exact source identity in the package's draft release before relying on remote custody. Candidate qualification uses the ordinary operating procedures, with one explicit acquisition difference: at **Select cluster access and obtain the release**, replace only the registry-download block with:

```bash
mkdir -p "$WORK_DIR/packages"
CHART_STAGE=$(mktemp -d "$WORK_DIR/packages/.paperless.XXXXXX")
tar -xzf "$OUT/bartl-paperless-$RELEASE.tgz" -C "$CHART_STAGE"
export PACKAGE_VERSION
PACKAGE_VERSION=$(helm show chart "$CHART_STAGE/bartl-paperless" | yq -er '.version')
```

Continue at **Configure a new deployment**. This is candidate qualification, not public-release acceptance. Exercise the maintainer cases above, including fresh OIDC with the supplied CA bundle. Replacement selects the same retained candidate archive instead of downloading a stable chart; keep its native version transition and all retirement/acceptance checks unchanged. After qualification passes, publish the same images under unused release tags and the unchanged chart:

```bash
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

New package public visibility needs explicit approval. Verify anonymous chart/image acquisition, archive/manifest identities and actual runtime images. Retain exact qualification limits and provider cleanup/budget outcome; a source-only or offline result is not released-path qualification.

## Native sources

- [Exporter](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_exporter.py) and [importer](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/management/commands/document_importer.py).
- [Token endpoint](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/paperless/views.py) and [inherited token acquisition](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/views.py).
- [Native folder preparation](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/docker/rootfs/etc/s6-overlay/s6-rc.d/init-folders/run) and [nonrotating token administration](https://github.com/encode/django-rest-framework/blob/3.18.1/rest_framework/authtoken/management/commands/drf_create_token.py).
- [Paperless's pinned dependencies](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/uv.lock): django-allauth 65.16.1 and Requests 2.33.0. Allauth's [OIDC discovery/userinfo](https://github.com/pennersr/django-allauth/blob/65.16.1/allauth/socialaccount/providers/openid_connect/views.py), [token client](https://github.com/pennersr/django-allauth/blob/65.16.1/allauth/socialaccount/providers/oauth2/client.py) and [session factory](https://github.com/pennersr/django-allauth/blob/65.16.1/allauth/socialaccount/adapter.py) use Requests sessions. Requests' [environment selection](https://github.com/psf/requests/blob/v2.33.0/src/requests/sessions.py) and [TLS adapter](https://github.com/psf/requests/blob/v2.33.0/src/requests/adapters.py) select the supplied bundle instead of default roots and retain certificate/hostname verification; `SSL_CERT_FILE` alone is not the Requests handoff.
- [Native backup/update procedures](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/docs/administration.md), [search schema](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/src/documents/search/_schema.py) and [native startup reindex](https://github.com/paperless-ngx/paperless-ngx/blob/c4d1b0c7325ea8782d87c64b6738ac39d313df2e/docker/rootfs/etc/s6-overlay/s6-rc.d/init-search-index/run).
