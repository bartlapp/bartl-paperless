# Bartlized Paperless

Paperless over HTTPS with PostgreSQL, Redis, automatic initialization/reconstruction, settled-work capture and native forward migration. Compatible external OIDC and HTTPS Restic services suffice; Keycloak and Bartlized Restic are optional independent packages.

New deployment: follow the steps below. Existing deployment: [resume access](#resume-an-existing-deployment), then select an operation. Use workstation Bash, keep tracing off and stop at a failed command. Creation is not a replay or partial-state repair program.

## Package and target

Published **0.2.0** contains Paperless 3.3.0/3.3.1, PostgreSQL 17.6, Redis 8.2.1 and Restic 0.19.1. It reuses the pinned 0.1.0 runtime/controller images. The supported transition is **3.3.0 → 3.3.1**, in place or by same-version import followed by migration. Other versions, downgrades and PostgreSQL major upgrades are unsupported. This rewritten recipe is not renewed live qualification.

Use the [operator tools](https://github.com/bartlapp/bartl-app/blob/main/docs/operator-workstation.md#check-the-workstation) and a Linux amd64 single-node K3s profile with enforced NetworkPolicy, Traefik in kube-system and four ReadWriteOnce claims. Storage must support POSIX permissions, locks, atomic rename and fsync. Native setup needs root; ordinary services use UID 1000. One namespace holds one release named paperless and no unrelated workloads. The supported profile has one container, one Celery worker/thread and local-path storage, not HA or multi-node RWO placement. [Base](https://github.com/bartlapp/base-k3s/blob/main/README.md) supplies this profile.

Supply its existing version-1 installation record, complete cluster/resource references and retained access. Default HTTPS uses cert-manager and public ports 80/443; external TLS is supported. API/browser intake and native metadata-assignment workflows are covered. Mail polling, remote OCR/AI, custom scripts and external-effect workflows need separate qualification. Do not override DJANGO_SETTINGS_MODULE or the controller-owned database/broker/concurrency topology.

Before relying on the service, agree interruption/data loss, source retirement, backup protection/retention, staging headroom and alert ownership. Captures interrupt intake and retain complete exports without automatic pruning. Name the records-review owner and independently surviving evidence of later deletion/hold/access decisions. Export truncates version added timestamps from microseconds to milliseconds; decide whether that fidelity is sufficient. Paperless-local MFA is not qualified; configured provider TOTP needs its own fresh-login check.

## Obtain release 0.2.0

Select the existing installation directory. Restore an independently retained archive at this path or acquire it anonymously:

```bash
set -euo pipefail
umask 077
export WORK_DIR="$HOME/bartl/acme/acme-installation"
export VALUES="$WORK_DIR/installation.yaml"
mkdir -p "$WORK_DIR/packages"
export VERSION=0.2.0
helm pull oci://ghcr.io/bartlapp/bartl-paperless --version "$VERSION" --destination "$WORK_DIR/packages"
CHART="$WORK_DIR/packages/bartl-paperless-$VERSION.tgz"
CHART_SHA256=4c6df6106efb35b2c4a25e4bb77d7ad98765572154dbcd380a9742f20bfac5c9
printf '%s  %s\n' "$CHART_SHA256" "$CHART" | shasum -a 256 --check -
```

Retain exact artifacts, configuration, Paperless key, identity-client inputs and repository credentials independently of the source. Source currently contains an **unreleased** correction to backup connection eligibility; it is not in this archive and requires a new chart release. These commands use explicit backup selection and do not depend on it.

## Configure a new deployment

Choose unused deployment, service and package keys and a fresh namespace. These targeted assignments preserve unrelated installation entries. A replacement must retain the original instance instead.

```bash
export DEPLOYMENT=paperless
export INSTANCE=paperless
export CLUSTER_ID=cluster-1
export NS=paperless-blue
export RELEASE=paperless
export PACKAGE=paperless
export CHART_SHA256
yq -i '
  .deployments[strenv(DEPLOYMENT)] = {
    "instance": strenv(INSTANCE), "cluster": strenv(CLUSTER_ID),
    "namespace": strenv(NS), "release": strenv(RELEASE), "package": strenv(PACKAGE)
  } |
  .services[strenv(INSTANCE)] = {} |
  .packages[strenv(PACKAGE)] = {
    "version": strenv(VERSION), "chart": "oci://ghcr.io/bartlapp/bartl-paperless",
    "chartSha256": strenv(CHART_SHA256)
  }
' "$VALUES"
```

Optional hostname, claim, native-version, TLS and dependency choices belong under services.<instance>. Omitted hostname derives from dns.root; default native version is 3.3.1. Read access and render declarations:

```bash
HELM_INSTANCE=${INSTANCE//./\\.}
KUBE_CONTEXT=$(yq -er '.clusters[strenv(CLUSTER_ID)].kubeconfig.context' "$VALUES")
export KUBECONFIG="$WORK_DIR/clusters/$CLUSTER_ID/base/kubeconfig"
# Replace only with an access file supplied for this selected cluster.
INSTALL_DIR="$WORK_DIR/clusters/$CLUSTER_ID/applications/$INSTANCE"
if [ "$DEPLOYMENT" != "$INSTANCE" ]; then INSTALL_DIR="$INSTALL_DIR/deployments/$DEPLOYMENT"; fi
mkdir -p "$INSTALL_DIR"
INGRESS=$(yq -r '[.services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
mkdir -p "$INSTALL_DIR/protected"
kubectl --context "$KUBE_CONTEXT" get nodes,storageclass
kubectl --context "$KUBE_CONTEXT" create namespace "$NS"
```

Never inherit another target's kubeconfig. Declarations report public endpoints, credential bindings, optional OIDC/backup requests and claims; they neither issue credentials nor create dependencies.

Create the four declared claims. Adjust the capacities once before this block; staging must hold retained exports and failed-publication headroom, not merely one export:

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
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=true" --set-string renderMode=connections \
  --show-only templates/connections.yaml |
  yq -er '.credentials.bindings[strenv(INSTANCE)].tls.secretName')
kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret tls "$TLS_SECRET" \
  --cert="$INSTALL_DIR/tls/fullchain.pem" --key="$INSTALL_DIR/tls/key.pem"
```

This offline lookup asks for the future route's TLS binding; it does not enable ingress or change VALUES. Preserve external ownership on subsequent upgrades. Disabling ingress omits access without disabling managed certificate preparation.

## Optional identity and backup

### External OIDC

For a compatible external provider, select its supplied issuer, then render the exact client/callback requirements:

```bash
export OIDC_ISSUER=https://login.example.org/realms/acme
yq -i '.services[strenv(INSTANCE)].oidc.issuer = strenv(OIDC_ISSUER)' "$VALUES"
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
yq '.oidc.requests[strenv(INSTANCE)]' "$INSTALL_DIR/paperless-connections.yaml"
```

Register that client at the provider and retain its client secret without a newline at INSTALL_DIR/protected/oidc-client-secret. Do not generate a replacement during resumption or recovery. No OIDC choice means no identity-provider dependency. Use the next section instead for composed Keycloak.

### Compose with an existing Keycloak

First install/resume and verify Keycloak through its [own release procedure](https://github.com/bartlapp/bartl-keycloak/blob/main/README.md), including DNS, TLS, credentials and useful login. Do not provision it again here. Supply its current nonsecret declaration file from that procedure; 0.6.1 and the current candidate have different deployment interfaces but expose the issuer declaration used below.

Starting condition: this consumer has no direct `oidc.issuer` override; composition selects the provider through `identityProvider`. Supply an authorized current master-realm administrator at `INSTALL_DIR/protected/keycloak-admin/{username,password}`, with usable `admin-cli` password grant and no interactive required actions. These credentials are preparation-only.

```bash
export KC_DEPLOYMENT=keycloak
export KC_CONNECTIONS="$WORK_DIR/clusters/cluster-1/applications/keycloak/connections.yaml"
KC_INSTANCE=$(yq -er '.deployments[strenv(KC_DEPLOYMENT)].instance' "$VALUES")
export KC_INSTANCE
yq -i '.services[strenv(INSTANCE)].identityProvider = strenv(KC_INSTANCE)' "$VALUES"
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --set-string renderMode=connections \
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

Authenticate and inspect the provider's realms and the declared client specification:

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

Independently retain the client secret. Configure intended users and TOTP through native Keycloak administration; test fresh login and account linking, not matching-email assumptions. This preparation does not create a second provider installation.

### External backup inputs

Use a dedicated initialized HTTPS Restic repository. For fresh initialization it must contain no matching application history; existing history belongs in recovery with the retained Paperless key. [Restic's recipe](https://github.com/bartlapp/bartl-restic/blob/main/README.md#connect-an-application) supplies a compatible endpoint and scoped input files, but any compatible service suffices.

```bash
export REPOSITORY_URL=rest:https://backup.example.org/paperless/
yq -i '.services[strenv(INSTANCE)].backup.repository = strenv(REPOSITORY_URL)' "$VALUES"
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
```

Supply repository/reader/ and repository/writer/ under INSTALL_DIR, each with password (the same repository encryption key), username, restPassword and optional ca.crt. If retained under the older protected/backup layout, restore those files here; do not regenerate them. Reader may manage native locks, not backup contents; writer is append-only. Admin credentials stay with the backup service. Create runtime copies:

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

Render native configuration and add protected inputs without printing the result. This handles local login, external OIDC and composed OIDC through the same package interface:

```bash
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set-string renderMode=configuration --show-only templates/configuration.yaml > "$INSTALL_DIR/configuration.yaml"
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
jq -n --arg name "$CONFIG_SECRET" --arg namespace "$NS" \
  --slurpfile environment "$INSTALL_DIR/protected/environment.json" '{
    apiVersion: "v1", kind: "Secret", type: "Opaque",
    metadata: {name: $name, namespace: $namespace}, stringData: $environment[0]
  }' | kubectl --context "$KUBE_CONTEXT" apply --server-side --field-manager=paperless-preparation -f -
```

For fresh initialization with the default bootstrap binding, create its Secret. If bootstrapSecret was deliberately disabled, skip this block and use the selected native account-creation procedure:

```bash
BOOTSTRAP_SECRET=$(yq -er '.credentials.bindings[strenv(INSTANCE)].bootstrap.secretName' "$INSTALL_DIR/paperless-connections.yaml")
kubectl --context "$KUBE_CONTEXT" -n "$NS" create secret generic "$BOOTSTRAP_SECRET" \
  --from-file=PAPERLESS_ADMIN_USER="$INSTALL_DIR/protected/bootstrap-user" \
  --from-file=PAPERLESS_ADMIN_PASSWORD="$INSTALL_DIR/protected/bootstrap-password"
```

Keep protected files mode 0600, outside Git and independently available. The bootstrap account applies only to an empty installation, never imported state. Do not add controller-owned topology or custom-init/consume scripts to the configuration Secret. Import restores Paperless accounts, not the identity provider; retain that provider and client independently.

## Install and verify

```bash
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm install "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$GENERATION" --timeout=30m
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

Require current-generation Ready and status.version matching the intended native version. Helm only waits for controller infrastructure. Startup observes owned state; absence selects the latest complete matching point, same-version import and supported migration. Lookup/integrity/identity failures never mean empty state. Existing-state restart needs no backup access.

Through real HTTPS, log in locally and, when selected, with fresh OIDC/TOTP. Ingest a synthetic PDF, await OCR/processing, search title/text and download the original. Check used versions/renditions, workflow, reader grants and denied access. [OIDC, MFA and token recovery](#oidc-mfa-and-token-recovery) lists the native reader permissions.

## Resume an existing deployment

In fresh Bash, restore the exact archive and protected files, then select the retained deployment. This block refreshes declarations only; it creates no credentials, claims or cluster resources:

```bash
set -euo pipefail
umask 077
export WORK_DIR="$HOME/bartl/acme/acme-installation"
export VALUES="$WORK_DIR/installation.yaml"
export DEPLOYMENT=paperless
INSTANCE=$(yq -er '.deployments[strenv(DEPLOYMENT)].instance' "$VALUES")
CLUSTER_ID=$(yq -er '.deployments[strenv(DEPLOYMENT)].cluster' "$VALUES")
NS=$(yq -er '.deployments[strenv(DEPLOYMENT)].namespace' "$VALUES")
RELEASE=$(yq -er '.deployments[strenv(DEPLOYMENT)].release' "$VALUES")
PACKAGE=$(yq -er '.deployments[strenv(DEPLOYMENT)].package' "$VALUES")
export INSTANCE CLUSTER_ID PACKAGE
HELM_INSTANCE=${INSTANCE//./\\.}
KUBE_CONTEXT=$(yq -er '.clusters[strenv(CLUSTER_ID)].kubeconfig.context' "$VALUES")
export KUBECONFIG="$WORK_DIR/clusters/$CLUSTER_ID/base/kubeconfig"
# Replace only with an access file supplied for this selected cluster.
VERSION=$(yq -er '.packages[strenv(PACKAGE)].version' "$VALUES")
test "$VERSION" = 0.2.0
CHART="$WORK_DIR/packages/bartl-paperless-$VERSION.tgz"
CHART_SHA256=$(yq -er '.packages[strenv(PACKAGE)].chartSha256' "$VALUES")
printf '%s  %s\n' "$CHART_SHA256" "$CHART" | shasum -a 256 --check -
INSTALL_DIR="$WORK_DIR/clusters/$CLUSTER_ID/applications/$INSTANCE"
if [ "$DEPLOYMENT" != "$INSTANCE" ]; then INSTALL_DIR="$INSTALL_DIR/deployments/$DEPLOYMENT"; fi
mkdir -p "$INSTALL_DIR"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --set-string renderMode=connections \
  --show-only templates/connections.yaml > "$INSTALL_DIR/paperless-connections.yaml"
PAPERLESS_URL=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.url' "$INSTALL_DIR/paperless-connections.yaml")
PAPERLESS_HOST=$(yq -er '.services[strenv(INSTANCE)].endpoints.https.hostname' "$INSTALL_DIR/paperless-connections.yaml")
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o yaml
```

## Capture, publication and retry

Start from a resumed, running application with repository credentials and sufficient staging. Do not stop Paperless first: capture needs its current writer execution. Let the controller drain intake/processing and stop writers around export:

```bash
REQUEST="manual-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl --context "$KUBE_CONTEXT" -n "$NS" annotate paperlessapplication/paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.backup.request}=$REQUEST" --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=jsonpath='{.status.backup.phase}'=Published --timeout=6h
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json > "$INSTALL_DIR/backup-result.json"
jq -e --arg request "$REQUEST" '.status.backup |
  .request == $request and .phase == "Published" and (.snapshotID | test("^[a-f0-9]{64}$"))' "$INSTALL_DIR/backup-result.json"
```

Require this request's Published result; inspect captureOperation, capturedAt, resumed, repositoryID, full snapshotID and publishedAt. BackupFailed is separate from application Ready. Publication restores and byte-checks a candidate before publishing the complete-tag point. The capture boundary is settled work: no active/reserved/scheduled tasks and empty queues, not interrupted-ingestion replay.

A failed publication retains its complete capture. Correct the endpoint/credential/capacity issue and issue a new request; it retries that capture, not newer work. After success, request another capture for later work. Failed/ambiguous capture remains isolated; never purge queues or clear markers. Native Jobs have six-hour outer deadlines, detached capture a one-hour bound; timeout is not proof of termination.

Monitor staging, overdue/failed requests, capture age and required independent replication. Do not prune an active/retry capture or the last usable point. Old capture cleanup needs verified publication/protection and the customer's retention authorization.

## Stop, start and restart

Resume first. Export needed logs before stop: cancellation deletes native Jobs/Pods. Persist intent rather than scaling controller-owned Deployments:

```bash
yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 0' "$VALUES"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Stopped\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Stopped --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Stopped" and .status == "True" and .observedGeneration == $g)'
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pods,jobs,deployments,replicasets
```

Require no application/native-Job Pods, including terminating Pods. PostgreSQL/Redis may remain for diagnosis. A running application can continue through API observation loss; submitted stop intent or unreachability is not retirement.

After a completed nonfailed stop, start the same retained deployment:

```bash
yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 1' "$VALUES"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
```

For an ordinary native restart while running:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" rollout restart deployment/paperless
kubectl --context "$KUBE_CONTEXT" -n "$NS" rollout status deployment/paperless --timeout=10m
```

Verify current-generation Ready and useful service without backup access. Stop/start never clears a failed transition marker.

## Recovery and replacement upgrade

Use this ordered sequence for same-release recovery or the supported 3.3.0 → 3.3.1 replacement. Supply an independent target cluster/namespace, four empty claims, retained Paperless key/client inputs, a usable repository and an authorized recovery point. Source and target share VALUES and logical instance, not storage or deployment intent.

The Base profile uses the administrator-only Traefik review route below, while the package's ordinary ingress remains disabled. Supply a reviewer IPv4/CIDR distinguishable from ordinary clients; shared NAT/proxy addresses are unsuitable. Keep production outbound effects isolated and exclude direct-service or alternate-route bypass. Other environments must supply equivalent verified isolation. Source-provider loss also needs independently enforced retirement, including a returning predecessor; DNS/unreachability alone do not provide it.

### Final capture and source retirement

For a reachable source, resume it, withdraw all intake paths and prevent concurrent publication/configuration changes. Keep its writer execution running for final capture. Disable public ingress and schedules, then capture:

```bash
export SOURCE_DEPLOYMENT="$DEPLOYMENT"
export SOURCE_DIR="$INSTALL_DIR"
BACKUP_SCHEDULE=$(yq -r '.services[strenv(INSTANCE)].backup.schedule // ""' "$VALUES")
export BACKUP_SCHEDULE
yq -i '.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled = false |
  .services[strenv(INSTANCE)].backup.schedule = ""' "$VALUES"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
```

Let already admitted capture/publication finish before continuing. With intake still closed, request a fresh capture below. A publication retry can finish an older export; the capture-operation comparison rejects that result as the final capture. If it rejects an otherwise successful publication, keep intake closed and repeat only this capture block to obtain a new export.

```bash
PREVIOUS_CAPTURE=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json |
  jq -r '.status.backup.captureOperation // ""')
REQUEST="final-$(openssl rand -hex 8)"
kubectl --context "$KUBE_CONTEXT" -n "$NS" annotate paperlessapplication/paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.backup.request}=$REQUEST" --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=jsonpath='{.status.backup.phase}'=Published --timeout=6h
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json > "$INSTALL_DIR/backup-result.json"
jq -e --arg request "$REQUEST" --arg previous "$PREVIOUS_CAPTURE" '.status.backup |
  .request == $request and .phase == "Published" and
  (.captureOperation | length > 0) and .captureOperation != $previous and
  (.snapshotID | test("^[a-f0-9]{64}$"))' "$INSTALL_DIR/backup-result.json"
```

Require final capture inclusion and any required secondary protection. Then stop the source and prevent restart:

```bash
yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 0' "$VALUES"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Stopped\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Stopped --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Stopped" and .status == "True" and .observedGeneration == $g)'
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pods,jobs,deployments,replicasets
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pvc -o json > "$SOURCE_DIR/source-pvc.json"
```

Confirm all application/native workers gone and retirement enforced; preserve source data. For a lost/already retired source, skip these source calls, set SOURCE_DEPLOYMENT and SOURCE_DIR from independently retained records/inputs, and read BACKUP_SCHEDULE from that source instance's retained backup.schedule before target preparation disables it. Enforce retirement independently before target access.

### Prepare the independent target

Choose a fresh deployment/namespace and existing target cluster. Preserve logical identity and service settings. For native replacement upgrade only, set services.<instance>.version to 3.3.1 after source retirement; keep its original value for same-version recovery.

```bash
export DEPLOYMENT=paperless-replacement
export TARGET_CLUSTER=cluster-2
export TARGET_NAMESPACE=paperless-green
export SOURCE_DEPLOYMENT SOURCE_DIR
INSTANCE=$(yq -er '.deployments[strenv(SOURCE_DEPLOYMENT)].instance' "$VALUES")
PACKAGE=$(yq -er '.deployments[strenv(SOURCE_DEPLOYMENT)].package' "$VALUES")
export INSTANCE PACKAGE
yq -i '.deployments[strenv(DEPLOYMENT)] = {
  "instance": strenv(INSTANCE), "cluster": strenv(TARGET_CLUSTER),
  "namespace": strenv(TARGET_NAMESPACE), "release": "paperless", "package": strenv(PACKAGE)
} | .operations.deployments[strenv(DEPLOYMENT)] = {"replicas": 1, "ingressEnabled": false} |
  .services[strenv(INSTANCE)].backup.schedule = ""' "$VALUES"
INSTANCE=$(yq -er '.deployments[strenv(DEPLOYMENT)].instance' "$VALUES")
CLUSTER_ID=$(yq -er '.deployments[strenv(DEPLOYMENT)].cluster' "$VALUES")
NS=$(yq -er '.deployments[strenv(DEPLOYMENT)].namespace' "$VALUES")
RELEASE=$(yq -er '.deployments[strenv(DEPLOYMENT)].release' "$VALUES")
PACKAGE=$(yq -er '.deployments[strenv(DEPLOYMENT)].package' "$VALUES")
export INSTANCE CLUSTER_ID PACKAGE
HELM_INSTANCE=${INSTANCE//./\\.}
KUBE_CONTEXT=$(yq -er '.clusters[strenv(CLUSTER_ID)].kubeconfig.context' "$VALUES")
export KUBECONFIG="$WORK_DIR/clusters/$CLUSTER_ID/base/kubeconfig"
# Replace only with an access file supplied for this selected cluster.
VERSION=$(yq -er '.packages[strenv(PACKAGE)].version' "$VALUES")
test "$VERSION" = 0.2.0
CHART="$WORK_DIR/packages/bartl-paperless-$VERSION.tgz"
CHART_SHA256=$(yq -er '.packages[strenv(PACKAGE)].chartSha256' "$VALUES")
printf '%s  %s\n' "$CHART_SHA256" "$CHART" | shasum -a 256 --check -
INSTALL_DIR="$WORK_DIR/clusters/$CLUSTER_ID/applications/$INSTANCE"
if [ "$DEPLOYMENT" != "$INSTANCE" ]; then INSTALL_DIR="$INSTALL_DIR/deployments/$DEPLOYMENT"; fi
mkdir -p "$INSTALL_DIR"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --set-string renderMode=connections \
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
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --set-string renderMode=connections \
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
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set-string renderMode=configuration --show-only templates/configuration.yaml > "$INSTALL_DIR/configuration.yaml"
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
jq -n --arg name "$CONFIG_SECRET" --arg namespace "$NS" \
  --slurpfile environment "$INSTALL_DIR/protected/environment.json" '{
    apiVersion: "v1", kind: "Secret", type: "Opaque",
    metadata: {name: $name, namespace: $namespace}, stringData: $environment[0]
  }' | kubectl --context "$KUBE_CONTEXT" apply --server-side --field-manager=paperless-preparation -f -
```

Do not create a new bootstrap identity for imported state. For external TLS only, supply its target certificate/key and retain tls.managed: false:

```bash
TLS_SECRET=$(helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=true" --set-string renderMode=connections \
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

The source is retired. Install with target routing still disabled:

```bash
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm install "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$GENERATION" --timeout=30m
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

Inspect status.operation/status.operations and native Job results. Require the authorized repository/full snapshot, expected native version and independent PVC UIDs/backing volumes. Ready with an empty initialization is not recovery of expected history. Failure stays isolated; preserve diagnostics and use another independent empty target, never clear markers or replay an ambiguous import.

For Base's single-node Traefik, preserve the client's source address. This changes the cluster ingress Service, so retain its other settings:

```bash
kubectl --context "$KUBE_CONTEXT" -n kube-system get helmchartconfig traefik \
  --ignore-not-found -o yaml > "$INSTALL_DIR/traefik-config.yaml"
if [ ! -s "$INSTALL_DIR/traefik-config.yaml" ]; then
  yq -n '.apiVersion = "helm.cattle.io/v1" | .kind = "HelmChartConfig" |
    .metadata.name = "traefik" | .metadata.namespace = "kube-system"' > "$INSTALL_DIR/traefik-config.yaml"
fi
TRAEFIK_VALUES=$(yq -r '.spec.valuesContent // "{}"' "$INSTALL_DIR/traefik-config.yaml" |
  yq '.service.spec.externalTrafficPolicy = "Local"')
TRAEFIK_VALUES="$TRAEFIK_VALUES" yq -i '.spec.valuesContent = strenv(TRAEFIK_VALUES)' "$INSTALL_DIR/traefik-config.yaml"
kubectl --context "$KUBE_CONTEXT" apply -f "$INSTALL_DIR/traefik-config.yaml"
kubectl --context "$KUBE_CONTEXT" -n kube-system wait service/traefik \
  --for=jsonpath='{.spec.externalTrafficPolicy}'=Local --timeout=5m
```

Confirm source retirement and no ordinary route for this hostname. Create a separate, operator-owned review Ingress and namespace-local allowlist. Do not edit the controller-owned `paperless` Ingress; it must remain absent. The offline lookup below obtains TLS/class settings without enabling a route:

```bash
export REVIEW_CIDR=203.0.113.10/32  # Replace with the authorized reviewer's actual source CIDR.
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait ingress/paperless --for=delete --timeout=5m
kubectl --context "$KUBE_CONTEXT" get ingress --all-namespaces
helm template "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.ingress.enabled=true" --set-string renderMode=connections \
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
curl --fail --silent --show-error --output /dev/null "$PAPERLESS_URL"
```

Require trusted HTTPS from the reviewer address and HTTP 403 from an independent ordinary source, including a request with a forged `X-Forwarded-For` header naming the reviewer. With no `ipStrategy` configured, the allowlist uses the connection source address. Verify the deployed Middleware and other hostname routes if this fails; do not broaden the allowlist. Ordinary ingress and schedules stay disabled throughout review.

From the allowed address, verify originals/version/rendition bytes, metadata, grants, workflow, search and fresh local/OIDC login. Reacquire API tokens as below without resetting users or assigning an SSO-only user a local password. Complete the records review before affected use resumes. Ingest new synthetic work and publish another usable point:

```bash
REQUEST="manual-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl --context "$KUBE_CONTEXT" -n "$NS" annotate paperlessapplication/paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.backup.request}=$REQUEST" --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=jsonpath='{.status.backup.phase}'=Published --timeout=6h
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json > "$INSTALL_DIR/backup-result.json"
jq -e --arg request "$REQUEST" '.status.backup |
  .request == $request and .phase == "Published" and (.snapshotID | test("^[a-f0-9]{64}$"))' "$INSTALL_DIR/backup-result.json"
```

Only after acceptance and records approval, restore approved production dependencies and replace the review route with ordinary access. Record the active deployment, selected point, recovery time and remaining restrictions in existing installation records. Keep source stop intent unchanged. If target writes/effects occurred, do not automatically reactivate the old source.

Delete the operator-owned review route first, then enable the ordinary route and restore the retained schedule. An originally empty schedule remains manual-only:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete ingress/paperless-review --wait=true
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete middleware/paperless-review
yq -i '.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled = true |
  .services[strenv(INSTANCE)].backup.schedule = strenv(BACKUP_SCHEDULE)' "$VALUES"
INGRESS=true
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" \
  --wait=legacy --timeout=5m
```

## In-place forward upgrade

This retains existing state and does not exercise reconstruction or provide an untouched database fallback. Resume the deployment, configure backup and withdraw production intake through verified environment controls while review access remains possible. Start with no executing native work and prevent concurrent operators. Retain the schedule and suspend scheduled admission before requesting the final export:

```bash
BACKUP_SCHEDULE=$(yq -r '.services[strenv(INSTANCE)].backup.schedule // ""' "$VALUES")
export BACKUP_SCHEDULE
yq -i '.services[strenv(INSTANCE)].backup.schedule = ""' "$VALUES"
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o yaml
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pods,jobs
```

Require current-generation Ready and no executing native operation before capture. Keep `BACKUP_SCHEDULE` through acceptance; if the shell is lost, recover it from the pre-operation installation record, not the temporarily empty setting. Request a fresh capture:

```bash
PREVIOUS_CAPTURE=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json |
  jq -r '.status.backup.captureOperation // ""')
REQUEST="upgrade-$(openssl rand -hex 8)"
kubectl --context "$KUBE_CONTEXT" -n "$NS" annotate paperlessapplication/paperless \
  "paperless.bartl.sh/backup-request=$REQUEST" --overwrite
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.backup.request}=$REQUEST" --timeout=10m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for=jsonpath='{.status.backup.phase}'=Published --timeout=6h
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json > "$INSTALL_DIR/pre-upgrade-backup.json"
jq -e --arg request "$REQUEST" --arg previous "$PREVIOUS_CAPTURE" '.status.backup |
  .request == $request and .phase == "Published" and
  (.captureOperation | length > 0) and .captureOperation != $previous and
  (.snapshotID | test("^[a-f0-9]{64}$"))' "$INSTALL_DIR/pre-upgrade-backup.json"
```

If this only republishes the retained export, the check fails: keep intake closed and repeat only the capture block after publication completes. Once a fresh final capture and any required secondary protection are verified, stop the application:

```bash
yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 0' "$VALUES"
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=0" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Stopped\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Stopped --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pods,jobs
```

Require confirmed drainage and a successful final capture, not an interrupted capture marker. Select the supported native target and restart through the same chart:

```bash
yq -i '.services[strenv(INSTANCE)].version = "3.3.1" |
  .operations.deployments[strenv(DEPLOYMENT)].replicas = 1' "$VALUES"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
```

Verify status.version, useful behavior, new ingestion and another capture before reopening access. Never roll old software back against migrated data.

After acceptance, restore the original schedule; leave an originally manual-only installation manual-only:

```bash
yq -i '.services[strenv(INSTANCE)].backup.schedule = strenv(BACKUP_SCHEDULE)' "$VALUES"
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
```

For a 0.1.0 → 0.2.0 chart adoption, retain the old flat values/artifacts, translate every effective value into services.<instance>, preserve identity/claims/Secrets and immutable images, and register/select the new archive/checksum. Do not use the flat file as a second compatibility layer. Historical 0.1.0 archive SHA-256: dc87e82d5350a4f31850ef801521f836e4567e8ecf81e3a7e319e7935e48dfa8; OCI manifest: ef2bf48e83bb7b919d85d36d18ad6191373e401c74f03c402e88c749d1601c0d. Before any CRD-changing upgrade, review shared compatibility and apply the selected definition; Helm does not update an existing CRD:

```bash
kubectl --context "$KUBE_CONTEXT" apply -f <(helm show crds "$CHART")
```

## Removal and retained-state reinstall

Resume, export diagnostics and obtain current-generation Stopped with no application/native-Job Pods. Keep stop intent and prevent competing reconcilers. Finalize while the controller remains alive:

```bash
yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 0' "$VALUES"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm upgrade "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" --reset-values -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Stopped\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Stopped --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Stopped" and .status == "True" and .observedGeneration == $g)'
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pods,jobs,deployments,replicasets
```

After inspecting complete drainage and authorizing removal:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NS" delete paperlessapplication/paperless --wait=true --timeout=10m
helm uninstall "$RELEASE" --kube-context "$KUBE_CONTEXT" -n "$NS" --wait --timeout=5m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get pvc,secrets
```

Finalization drains dependencies and releases only this CR's claim bindings. Claims/data/Secrets survive. Do not bypass finalizers or delete controller/namespace first. A timeout is not authorization to force deletion.

After successful finalization, with intact retained state and no failed transition marker or competing owner, reinstall without recreating PVCs or credentials:

```bash
yq -i '.operations.deployments[strenv(DEPLOYMENT)].replicas = 1' "$VALUES"
REPLICAS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].replicas, .services[strenv(INSTANCE)].replicas, 1] | map(select(. != null)) | .[0]' "$VALUES")
INGRESS=$(yq -r '[.operations.deployments[strenv(DEPLOYMENT)].ingressEnabled, .services[strenv(INSTANCE)].ingress.enabled, true] | map(select(. != null)) | .[0]' "$VALUES")
helm install "$RELEASE" "$CHART" --kube-context "$KUBE_CONTEXT" -n "$NS" -f "$VALUES" \
  --set-string instance="$INSTANCE" --set-string "services.$HELM_INSTANCE.release=$VERSION" \
  --set "services.$HELM_INSTANCE.replicas=$REPLICAS" --set "services.$HELM_INSTANCE.ingress.enabled=$INGRESS" --wait=legacy --timeout=5m
GENERATION=$(kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o jsonpath='{.metadata.generation}')
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless \
  --for="jsonpath={.status.conditions[?(@.type==\"Ready\")].observedGeneration}=$GENERATION" --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" wait paperlessapplication/paperless --for=condition=Ready --timeout=30m
kubectl --context "$KUBE_CONTEXT" -n "$NS" get paperlessapplication/paperless -o json | \
  jq -e '.metadata.generation as $g | .status.observedGeneration == $g and
    any(.status.conditions[]; .type == "Ready" and .status == "True" and .observedGeneration == $g)'
```

Verify existing identity/library, useful work and another capture. Uninstall cannot repair failed state. Namespace/PVC deletion needs a separate destructive data-disposition decision. Infrastructure and owned DNS cleanup are separate; never delete shared CRDs or external backup history as application cleanup.

## OIDC, MFA and token recovery

Use the package configuration rendering and provider preparation above; do not hand-author allauth JSON. Require TOTP MFA for the intended users at the identity provider and verify an actual fresh browser login, not only an existing session. Paperless retains its own users, groups and object permissions. Deliberately link an existing account through its native profile; do not assume matching email establishes identity. First-login provisioning and permission assignment are native administration, not package startup tests.

A read-only browser group needs `view_document`, `view_uisettings`, `add_uisettings`, `change_uisettings` and `view_savedview`, in addition to its document object grants. Native metadata views may also need `view_tag`, `view_correspondent`, `view_documenttype` and `view_storagepath`. UI-settings permissions do not grant document modification or user administration.

Native import excludes DRF API tokens. Local password accounts can reacquire their token with `POST /api/token/`; Paperless-local MFA, when enabled, additionally requires its native `code`. For a restored SSO-only user, an authorized operator uses the native management command:

```sh
# Treat stdout as a secret; do not put it in general logs.
kubectl --context "$KUBE_CONTEXT" -n "$NS" exec deployment/paperless -c paperless -- \
  uv run --no-project python manage.py drf_create_token USERNAME
```

Omit `--reset`/`-r`: default `get_or_create` returns an existing token without rotation. This does not set a local password or elevate the user's permissions. Deliver the token through the installation's protected credential channel; the authenticated user's `GET /api/profile/` also exposes that user's existing token. The profile's `generate_auth_token` endpoint deliberately rotates tokens and is not this recovery procedure. MFA protects interactive identity login, not every use of a bearer API token. Token issuance, account probes and records review are never ordinary startup dependencies.

## State boundary

Preserve originals and required versions/renditions, metadata, ownership/permissions, users/groups and used workflows/configuration. Native import rebuilds search but excludes DRF tokens. Retain external settings, identity dependencies and later records decisions independently. Keep native export defaults; never discard a rendition under hold.

## Source retention

Confirm completed ingestion and a readable original. Keep its source until a capture containing it has been published, verified and protected against the failure declared in the retained installation inputs. If that protection requires a secondary, primary publication alone is insufficient; use the backup service's result to establish protection. Paper, email or a device suffices if it survives that failure; otherwise retain a durable holding copy, not a new intake service or receipt ledger.

The result identifies installation, capture boundary, publication/verification completion, exact Restic point and outcome. Publication after upload does not prove inclusion if capture began earlier; check native inventory and original checksums when uncertain. Unsettled ingestion is not covered. Then perform only permitted source-copy cleanup; backup success never authorizes destruction of legally required originals.

After recovery, compare retained sources with the restored library before re-ingesting missing documents. Do not blindly replay or merge records solely because their bytes match.

## Records after restore

An export reflects records at capture, not later deletion, hold or restriction decisions. Its restored audit history cannot supply missing later changes. After technical recovery in isolation, the responsible person checks independently surviving approvals, disposal records, correspondence or newer evidence and applies corrections through native administration before affected use resumes. This is a records-policy review, not a second technical startup authorization; it applies neither to ordinary restart nor nightly capture.

Where evidence is insufficient, keep affected access/processing closed and resolve the exception with the installation's named records owner. Review cannot reconstruct missing information. Use the independently surviving decision evidence and review responsibilities recorded in the [installation inputs](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md#installation-inputs); retain the review result and unresolved restrictions there, with protected evidence referenced as appropriate. Existing approvals, disposal records and correspondence may suffice; a new decision file is justified only by a demonstrated gap.


## Configuration reference and qualification

The selected archive ships the service interface and defaults. Supported inputs under services.<instance> include hostname, version, replicas, claims.{storage,database,broker,staging}, configurationSecret, bootstrapSecret, identityProvider or oidc.issuer, optional oidc clientId/providerId/name, ingress enabled/className/tlsSecret, tls managed/acmeServer and backup repository or endpoint, enabled, readerSecret/writerSecret, schedule/timeZone/drainSeconds. Omission restores defaults, lists replace and explicit false/zero remain effective. Unknown selected-service fields fail; unrelated installation entries remain untouched.

Connection rendering exposes HTTPS, OIDC/backup requests, credential requirements/bindings and storage claims. Configuration rendering exposes configuration.<instance>.secretName/environment and whether a client secret is needed. Protected values are added locally, never to VALUES. Refresh derived resolved bindings after source choices change. The 0.2.0 chart accepts instance, not deployment; recipes project retained replicas/ingress intent explicitly.

Historical runtime tests and another namespace on one host do not qualify this revised sequence or provider-loss activation. Exact-artifact results and installation-specific acceptance belong in their existing release/operating records, not this recipe. Maintainer procedures follow below.

## Maintainer procedures and evidence

The README owns operating recipes. Run offline regressions with:

```bash
go test ./...
uv run --no-project python -m unittest discover -s tests -v
node tests/chart.mjs
```

The source-only backup declaration correction makes omission eligible for connection preparation while explicit false opts out. Released 0.2.0 still declares omission ineligible. Neither meaning enables standalone backup without a destination. The correction requires a new chart version and renewed affected qualification; do not repackage it as published 0.2.0.

Qualify exact immutable artifacts through first initialization with no store and an empty external store, ordinary restart without backup access, capture, independent reconstruction, new work/new recoverable point, 3.3.0-to-3.3.1 migration, publication retry, failed-transition isolation, stop and retained-storage reinstall. Inspect full repository/snapshot identities, original/version/rendition bytes, grants, workflow, search and fresh OIDC/TOTP. Browser/MFA and records review are separate from native Job success. Never clear markers to make qualification pass.

Synthetic-library checks use:

```bash
node tests/check-library.mjs baseline /protected/library-inputs.json
node tests/check-library.mjs verify /protected/library-inputs.json
```

Only synthetic documents with titles beginning `Synthetic ` are allowed. Inputs contain `url`, `tokensFile` (admin/reader/denied test-role tokens), `expectedFile`, `fixturesDir`, `files` (route/file with optional actor/deniedActors), `searches` (query/ids with optional actor) and `readOnlyDocument`. Include required versions/renditions. Baseline precedes capture; verify follows each transition with recovered credentials. Keep inputs, tokens, expected state and raw output outside Git; retain exact artifacts, concise results and material limits in the existing release/integration record.

Historical 0.1.0 runtime tests on 25 October 2026 restored after source-VM deletion, covering originals/versions, relationships, metadata, permissions, token reacquisition, search and another backup restored into fresh database/file/Redis storage. The export's millisecond version-added timestamp precision remains a fidelity limit. Other package fault scenarios removed source installations/storage and primary repositories on one disposable K3s host; they do not establish host/provider-loss failover or cross-cluster fencing. The target was Debian 13 amd64, K3s v1.36.5+k3s1, cert-manager 1.21.3 and Helm 4.3.0; Podman 5.4.2 built images.

Native observations on 24 October showed queued work surviving tested replacements, but interrupted active work did not settle within the observation window and revocation did not survive worker replacement. Warm shutdown did not independently prove writer/descendant termination. These findings justify settled-work capture, not replay/reconciliation. The experimental supervisor/scripts/chart/reconciliation code retired in `82e4357` is not the current design.

The current controller binds native work to application/operation, Pod UID, container ID and execution UUID. Target-local locking, database/file binding and pending-transition markers prevent concurrent or ambiguous import/capture. The s6 prerequisite runs before migrations/init-complete; upstream custom-init alone logs errors and continues. Capture requires ended writer descendants and database sessions, preserves native media-lock ownership and retains the marker until same-execution resumption is recorded. Completion after controller loss can authorize publication, never mutation/resumption of a replacement execution. Keep these implementation boundaries distinct from operator instructions.

## Building and publishing

Source/registry policy and authorization precede remote writes. Never reuse published versions, silently change existing visibility/access or rebuild after qualification. For chart-only changes, select a new chart version and retain the existing pinned runtime/controller images; package once and retain SHA256SUMS plus OCI/image identities with the release. Published 0.2.0 is immutable.

Runtime changes require an authorized Linux amd64 builder with Podman, Skopeo, Helm, yq and sha256sum. Set the new chart version, then:

```bash
OUT=/protected/paperless-candidate
OUT="$OUT" bash build.sh
```

Output contains three OCI image directories, a digest-pinned chart, image-values.yaml, image digests and SHA256SUMS. Qualify these exact bytes, retain them independently and publish from the builder without rebuilding. With authorized registry access in `REGISTRY_AUTH_FILE`, publish only absent version tags:

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
