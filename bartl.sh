#!/usr/bin/env bash
# Paperless lifecycle. Local secrets and captured state are supplied by the caller.
set -Eeuo pipefail
umask 077
ROOT=$(cd "$(dirname "$0")" && pwd)
export KUBECONFIG=${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}
[[ $# -ge 3 && $# -le 4 ]] || { echo 'usage: bartl.sh validate|deploy|capture|stop SETTINGS_JSON SECRET_DIR [RECOVERY_DIR]' >&2; exit 2; }
ACTION=$1 SETTINGS=$2 SECRETS=$3 STORE=${4:-}
case $ACTION in validate|deploy|capture|stop) ;; *) echo 'Unknown action' >&2; exit 2;; esac
NS=$(jq -er '.generation | select(type=="string")' "$SETTINGS")
[[ $NS =~ ^[a-z][a-z0-9-]{0,40}$ ]] || { echo 'Invalid generation' >&2; exit 2; }
test -d "$SECRETS" || { echo 'Protected secret directory missing' >&2; exit 5; }
# Lock both the protected key set and this service's generation. Never share the
# namespace lock with another independently operated service.
if [[ ${BARTL_PAPERLESS_LOCKED:-} != 1 ]]; then
  exec env BARTL_PAPERLESS_LOCKED=1 flock -n -o "$SECRETS/paperless.lock" flock -n -o "/run/lock/bartl-paperless-$NS.lock" "$0" "$@"
fi
k() { kubectl -n "$NS" "$@"; }
selected() { jq -cS '{generation,intent,identity,initialization,placement:{identityIP:.placement.identityIP},version:.versions.paperless,images:{paperless:.images.paperless,postgres:.images.postgres,redis:.images.redis}}' "$SETTINGS"; }
release() { jq -cS '{identity,initialization,placement:{identityIP:.placement.identityIP},version:.versions.paperless,images:{paperless:.images.paperless,postgres:.images.postgres,redis:.images.redis}}' "$SETTINGS"; }
operation() {
  { selected
    sha256sum "$ROOT/bartl.sh" "$ROOT/chart/Chart.yaml" "$ROOT/chart/templates/_state.tpl" "$ROOT/chart/templates/state.yaml" "$ROOT/chart/templates/runtime.yaml" | cut -d' ' -f1
    for name in db-password paperless-key client-secret; do sha256sum "$SECRETS/$name" | cut -d' ' -f1; done
    if [[ $(jq -r .intent "$SETTINGS") == recovery ]]; then sha256sum "$STORE/SHA256SUMS" | cut -d' ' -f1; fi
  } | sha256sum | cut -d' ' -f1
}
checkpoint() {
  k patch configmap paperless-contract --type merge -p "{\"data\":{\"stage\":\"$1\"}}" >/dev/null
  stage=$1
}
# Kubernetes API errors must not be interpreted as absence.
object() { k get "$1" "$2" --ignore-not-found -o json; }
wait_job() {
  local attempt status
  for ((attempt=0; attempt<300; attempt++)); do
    status=$(k get job "$1" -o json | jq -r '[.status.conditions[]? | select(.status=="True") | .type] | join(" ")')
    [[ $status != *Complete* ]] || return 0
    [[ $status != *Failed* ]] || break
    sleep 2
  done
  k logs "job/$1" --all-containers --tail=40 || true
  echo "Job $1 failed or timed out; generation is not ready" >&2
  exit 4
}
retry_job() {
  local job
  job=$(object job "$1")
  if [[ -n $job ]] && jq -e '.status.conditions[]? | select(.type=="Failed" and .status=="True")' <<< "$job" >/dev/null; then
    k delete job "$1" --wait=true
    k wait --for=delete pod -l "job-name=$1" --timeout=180s
  fi
}
check_recovery() {
  [[ -n $STORE && -d $STORE && ! -L $STORE ]] || { echo 'Recovery directory missing' >&2; exit 6; }
  local member listed expected digest file
  expected=$(printf '%s\n' database.dump files.tar manifest.json | LC_ALL=C sort)
  listed=''
  [[ -f $STORE/SHA256SUMS && ! -L $STORE/SHA256SUMS ]] || { echo 'Recovery checksums missing' >&2; exit 6; }
  while IFS= read -r entry || [[ -n $entry ]]; do
    [[ $entry =~ ^[a-f0-9]{64}\ \ (database\.dump|files\.tar|manifest\.json)$ ]] || { echo 'Invalid checksum record' >&2; exit 6; }
    member=${BASH_REMATCH[1]}
    listed+="$member"$'\n'
  done < "$STORE/SHA256SUMS"
  [[ $(printf '%s' "$listed" | LC_ALL=C sort) == "$expected" ]] || { echo 'Incomplete or repeated recovery inventory' >&2; exit 6; }
  for member in database.dump files.tar manifest.json; do
    [[ -f $STORE/$member && ! -L $STORE/$member && -s $STORE/$member ]] || { echo "Missing recovery member: $member" >&2; exit 6; }
  done
  (cd "$STORE" && sha256sum --status -c SHA256SUMS) || { echo 'Recovery integrity failed' >&2; exit 6; }
  jq -e '.stateFormat == 1 and .service == "paperless" and (.version | type == "string") and (.generation | type == "string") and (.images | type == "object") and (.identity | type == "object") and (.initialization | type == "object")' "$STORE/manifest.json" >/dev/null || { echo 'Invalid recovery manifest' >&2; exit 6; }
  [[ $(jq -cS '{identity,initialization}' "$SETTINGS") == $(jq -cS '{identity,initialization}' "$STORE/manifest.json") ]] || { echo 'Persistent identity or initialization mismatch' >&2; exit 7; }
  local old new
  old=$(jq -r .version "$STORE/manifest.json")
  new=$(jq -r .versions.paperless "$SETTINGS")
  case "$old:$new" in 3.3.0:3.3.0|3.3.0:3.3.1|3.3.1:3.3.1) ;; *) echo "Unsupported Paperless transition $old -> $new" >&2; exit 8;; esac
  local expected_old
  case $old in
    3.3.0) expected_old='ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207';;
    3.3.1) expected_old='ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4';;
  esac
  [[ $(jq -r .images.paperless "$STORE/manifest.json") == "$expected_old" && $(jq -r .images.postgres "$STORE/manifest.json") == "$(jq -r .images.postgres "$SETTINGS")" ]] || { echo 'Unsupported recovery image set' >&2; exit 8; }
}
preflight() {
  jq -e '(.intent == "fresh" or .intent == "recovery") and (.identity.issuer | type == "string" and startswith("http://") and contains("/realms/")) and (.identity.paperless | type == "string" and startswith("http://")) and (.identity.realm | type == "string" and length > 0) and (.identity.client | type == "string" and length > 0) and (.identity.provider | type == "string" and length > 0) and .initialization.database == "postgresql-17" and .initialization.stateFormat == 1 and (.initialization.ocr | type == "string" and length > 0) and (.initialization.timezone | type == "string" and length > 0) and (.versions.paperless == "3.3.0" or .versions.paperless == "3.3.1") and ([.images.paperless,.images.postgres,.images.redis] | all(type == "string" and test("@sha256:[a-f0-9]{64}$"))) and (.placement.identityIP == null or (.placement.identityIP | type == "string" and length > 0))' "$SETTINGS" >/dev/null || { echo 'Unsupported Paperless settings' >&2; exit 7; }
  # Only the exercised, exact image set is supported.
  local version image expected
  version=$(jq -r .versions.paperless "$SETTINGS")
  case $version in
    3.3.0) expected='ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207';;
    3.3.1) expected='ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4';;
  esac
  [[ $(jq -r .images.paperless "$SETTINGS") == "$expected" && $(jq -r .images.postgres "$SETTINGS") == 'docker.io/library/postgres@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3' && $(jq -r .images.redis "$SETTINGS") == 'docker.io/library/redis@sha256:5fa2edb1e408fa8235e6db8fab01d1afaaae96c9403ba67b70feceb8661e8621' ]] || { echo 'Unsupported image digest' >&2; exit 8; }
  local name size contract namespace resources current wanted previous
  for name in db-password paperless-key client-secret; do
    [[ -f $SECRETS/$name && ! -L $SECRETS/$name ]] || { echo "Missing secret $name" >&2; exit 5; }
    size=$(wc -c < "$SECRETS/$name")
    (( size >= 16 && size <= 4096 )) || { echo "Invalid secret size $name" >&2; exit 5; }
  done
  if [[ $ACTION == validate || $ACTION == deploy ]]; then
    if [[ $(jq -r .intent "$SETTINGS") == recovery ]]; then check_recovery; else [[ -z $STORE ]] || { echo 'Fresh install does not accept recovery input' >&2; exit 7; }; fi
  fi
  namespace=$(kubectl get namespace "$NS" --ignore-not-found -o json)
  stage=state
  [[ -n $namespace ]] || return 0
  contract=$(object configmap paperless-contract)
  if [[ -n $contract ]]; then
    stage=$(jq -er '.data.stage' <<< "$contract") || { echo 'Retained checkpoint missing' >&2; exit 7; }
    case $stage in state|initialize|migrate|runtime|accepted) ;; *) echo 'Unknown retained stage' >&2; exit 7;; esac
    [[ $(jq -r .data.release <<< "$contract") == "$(release)" ]] || { echo 'Existing generation release differs' >&2; exit 7; }
    if [[ $ACTION == validate || $ACTION == deploy ]]; then
      [[ $(jq -r .data.operation <<< "$contract") == "$(operation)" ]] || { echo 'Existing generation operation differs' >&2; exit 7; }
    fi
    for name in db-password paperless-key client-secret; do
      credential=$(object secret paperless-credentials)
      if [[ -z $credential && $stage == state && ( $ACTION == deploy || $ACTION == validate ) ]]; then break; fi
      current=$(jq -er --arg name "$name" '.data[$name]' <<< "$credential" | base64 -d | sha256sum | cut -d' ' -f1)
      wanted=$(sha256sum "$SECRETS/$name" | cut -d' ' -f1)
      [[ $current == "$wanted" ]] || { echo "Existing secret differs: $name" >&2; exit 7; }
    done
  else
    for resources in 'secret paperless-credentials' 'deployment paperless' 'deployment paperless-db' 'deployment redis' 'job paperless-state' 'job paperless-migrate' 'pvc paperless-database' 'pvc paperless-state' 'pvc paperless-recovery' 'service paperless-db' 'service redis' 'service documents'; do
      read -r kind name <<< "$resources"
      [[ -z $(object "$kind" "$name") ]] || { echo "Unowned Paperless resource: $resources" >&2; exit 7; }
    done
    [[ $(k get secret -l owner=helm,name=paperless -o json | jq '.items | length') == 0 ]] || { echo 'Unowned Paperless release' >&2; exit 7; }
  fi
}
stop_writers() {
  local deployment
  deployment=$(object deployment paperless)
  [[ -n $deployment ]] || { echo 'Paperless deployment missing' >&2; exit 7; }
  k scale deployment paperless --replicas=0
  local pods
  pods=$(k get pod -l app=paperless -o json)
  if jq -e '.items | length > 0' <<< "$pods" >/dev/null; then
    k wait --for=delete pod -l app=paperless --timeout=180s
  fi
  k patch configmap paperless-contract --type merge -p '{"data":{"stopped":"true"}}' >/dev/null
}
case $ACTION in
validate) preflight;;
deploy)
  preflight
  if [[ $stage == accepted ]]; then
    [[ -z $(jq -r '.data.stopped // empty' <<< "$(object configmap paperless-contract)") ]] || { echo 'Stopped generation requires a new capture and generation' >&2; exit 7; }
  else
    kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
    k create configmap paperless-contract --from-literal="release=$(release)" --from-literal="operation=$(operation)" --from-literal="stage=$stage" --dry-run=client -o yaml | k apply -f -
    k create secret generic paperless-credentials --from-file="$SECRETS/db-password" --from-file="$SECRETS/paperless-key" --from-file="$SECRETS/client-secret" --dry-run=client -o yaml | k apply -f -
    if [[ $stage == state ]]; then
      helm upgrade --install paperless "$ROOT/chart" -n "$NS" -f "$SETTINGS" --set phase=state --wait --timeout 600s
      if [[ $(jq -r .intent "$SETTINGS") == recovery ]]; then
        pod=$(k get pod -l app=paperless-db -o jsonpath='{.items[0].metadata.name}')
        k exec -i "$pod" -- sh -c 'cat > /recovery/database.dump' < "$STORE/database.dump"
        k exec -i "$pod" -- sh -c 'cat > /recovery/files.tar' < "$STORE/files.tar"
      fi
      checkpoint initialize
    fi
    if [[ $stage == initialize ]]; then
      retry_job paperless-state
      helm upgrade paperless "$ROOT/chart" -n "$NS" -f "$SETTINGS" --set phase=initialize
      wait_job paperless-state
      checkpoint migrate
    fi
    if [[ $stage == migrate ]]; then
      retry_job paperless-migrate
      helm upgrade paperless "$ROOT/chart" -n "$NS" -f "$SETTINGS" --set phase=migrate
      wait_job paperless-migrate
      checkpoint runtime
    fi
    if [[ $stage == runtime ]]; then
      helm upgrade paperless "$ROOT/chart" -n "$NS" -f "$SETTINGS" --set phase=runtime
    fi
  fi
  k rollout status deployment/paperless --timeout=600s
  [[ $(k get deployment paperless -o jsonpath='{.spec.replicas}') == 1 && $(k get deployment paperless -o jsonpath='{.status.readyReplicas}') == 1 ]] || { echo 'Stopped or unready Paperless generation' >&2; exit 4; }
  wait_job paperless-state
  wait_job paperless-migrate
  [[ $stage == accepted ]] || checkpoint accepted
  echo "Paperless generation $NS ready";;
stop)
  preflight
  [[ $stage == accepted ]] || { echo 'Only accepted generation can be stopped' >&2; exit 7; }
  stop_writers;;
capture)
  preflight
  [[ $stage == accepted ]] || { echo 'Only accepted generation can be captured' >&2; exit 7; }
  [[ -n $STORE && ! -e $STORE && ! -L $STORE ]] || { echo 'New capture destination required' >&2; exit 9; }
  contract=$(object configmap paperless-contract)
  [[ $(jq -r '.data.stopped // empty' <<< "$contract") != true || $(jq -r '.data.drained // empty' <<< "$contract") == true ]] || { echo 'Stopped without capture drain proof' >&2; exit 7; }
  if [[ $(k get deployment paperless -o jsonpath='{.spec.replicas}') == 0 ]]; then
    [[ $(jq -r '.data.drained // empty' <<< "$contract") == true ]] || { echo 'Stopped without capture drain proof' >&2; exit 7; }
    stop_writers
  elif [[ $(jq -r '.data.stopped // empty' <<< "$contract") != true ]]; then
    k exec deployment/paperless -- python3 manage.py shell -c 'from documents.models import PaperlessTask; pending=PaperlessTask.objects.filter(status__in=[PaperlessTask.Status.PENDING,PaperlessTask.Status.STARTED]); assert not pending.exists(), "Unfinished work; drain or resolve before capture"'
    k patch configmap paperless-contract --type merge -p '{"data":{"drained":"true"}}' >/dev/null
    stop_writers
  else
    echo 'Stopped contract has running Paperless worker' >&2; exit 7
  fi
  mkdir -m 700 "$STORE"
  pod=$(k get pod -l app=paperless-db -o jsonpath='{.items[0].metadata.name}')
  k exec "$pod" -- pg_dump -U bartl -d bartl -Fc > "$STORE/database.dump"
  k exec "$pod" -- tar -C /paperless -cf - data media consume > "$STORE/files.tar"
  jq '{stateFormat:1,service:"paperless",generation,version:.versions.paperless,images:{paperless:.images.paperless,postgres:.images.postgres,redis:.images.redis},identity,initialization}' "$SETTINGS" > "$STORE/manifest.json"
  (cd "$STORE" && sha256sum database.dump files.tar manifest.json > SHA256SUMS && sha256sum --status -c SHA256SUMS)
  echo 'Captured stopped Paperless source; retain immutable files and keys' ;;
esac
