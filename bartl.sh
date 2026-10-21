#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT=$(cd "$(dirname "$0")" && pwd)
[[ $# -ge 3 && $# -le 4 ]] || { echo 'usage: bartl.sh validate|deploy|start|stop|capture|backup|restore|reconcile SETTINGS SECRET_DIR [PAYLOAD_DIR|SNAPSHOT_ID|CURRENT_DECISIONS_JSON]' >&2; exit 2; }
ACTION=$1 SETTINGS=$2 SECRETS=$3 STORE=${4:-} WORK= RESUME=0
fail() { echo "$1" >&2; exit "${2:-4}"; }
case $ACTION in
  validate|deploy) ;;
  start|stop|backup) [[ $# == 3 ]] || fail 'Unexpected argument' 2;;
  capture|restore|reconcile) [[ $# == 4 ]] || fail 'Payload, snapshot or decision input required' 2;;
  *) fail 'Unknown action' 2;;
esac
[[ -f $SETTINGS && -d $SECRETS && ! -L $SECRETS ]] || fail 'Protected settings and secret directory required' 2
NS=$(jq -er '.generation' "$SETTINGS")
[[ $NS =~ ^[a-z][a-z0-9-]{0,40}$ ]] || fail 'Invalid generation' 2
export KUBECONFIG=${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}
exec 8>"$SECRETS/paperless-lifecycle.lock" 9>"/run/lock/bartl-paperless-$NS.lock"
flock -n 8 && flock -n 9 || fail 'Concurrent local lifecycle operation' 7
k() { kubectl -n "$NS" "$@"; }
config() { jq -cS '{generation,intent,identity,initialization,versions:{paperless:.versions.paperless},images:{paperless:.images.paperless,postgres:.images.postgres,redis:.images.redis,tika:.images.tika,gotenberg:.images.gotenberg,runtime:.images.runtime},placement:{identityIP:(.placement.identityIP // null)}}' "$SETTINGS"; }
binding() { { config | jq -cS '{generation,intent,identity,initialization}'; for name in db-password paperless-key client-secret records.json; do sha256sum "$SECRETS/$name" | cut -d' ' -f1; done; } | sha256sum | cut -d' ' -f1; }
check_settings() {
  jq -e '(.intent=="fresh" or .intent=="recovery") and .initialization.database=="postgresql-17" and .initialization.stateFormat==1 and
    (.versions.paperless=="3.3.0" or .versions.paperless=="3.3.1") and
    (.identity.realm as $realm | .identity.issuer | type=="string" and test("^https?://[^/@]+/realms/[A-Za-z0-9_-]+$") and endswith("/realms/" + $realm)) and
    (.identity.paperless|type=="string" and test("^https?://[^/@]+$")) and
    .identity.provider=="keycloak" and (.identity.client|type=="string" and length>0) and
    (.initialization.ocr|type=="string" and length>0) and (.initialization.timezone|type=="string" and length>0) and
    (.images.runtime|type=="string" and test("^[a-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}$"))' "$SETTINGS" >/dev/null || fail 'Unsupported settings or runtime pin' 2
  case "$(jq -r '.versions.paperless+":"+.images.paperless' "$SETTINGS")" in
    3.3.0:ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207|3.3.1:ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4) ;;
    *) fail 'Unsupported Paperless native release/image' 2;;
  esac
  [[ $(jq -r .images.postgres "$SETTINGS") == docker.io/library/postgres@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3 && $(jq -r .images.redis "$SETTINGS") == docker.io/library/redis@sha256:5fa2edb1e408fa8235e6db8fab01d1afaaae96c9403ba67b70feceb8661e8621 ]] || fail 'Unsupported database or broker image' 2
  [[ $(jq -r .images.tika "$SETTINGS") == docker.io/apache/tika@sha256:90b7fa1dc018434075fce9e1d9b88b1e3d0ea6979d0cf86e116c79a8073ae973 && $(jq -r .images.gotenberg "$SETTINGS") == docker.io/gotenberg/gotenberg@sha256:f29984bd1e226bf1b93ba90af06000afa8b315853e99d27b9aaa41b93f15c769 ]] || fail 'Unsupported native converter images' 2
  for name in db-password paperless-key client-secret records.json; do
    [[ -f $SECRETS/$name && ! -L $SECRETS/$name && -s $SECRETS/$name && $(wc -c < "$SECRETS/$name") -le 1048576 ]] || fail "Missing or invalid protected input: $name" 2
  done
  jq -e '.format==1 and .intake.username=="records-intake" and .capture.username=="records-capture" and .admin.username=="records-admin" and all([.intake,.capture,.admin][]; (.password|type=="string" and length>=32) and (.token|type=="string" and test("^[0-9a-f]{40}$")))' "$SECRETS/records.json" >/dev/null || fail 'Invalid records credentials' 2
}
check_payload() {
  [[ -n $STORE && -d $STORE && ! -L $STORE ]] || fail 'Recovery directory required' 6
  local name entry
  for entry in "$STORE"/* "$STORE"/.[!.]*; do
    [[ -e $entry || -L $entry ]] || continue
    name=${entry##*/}
    case $name in database.dump|files.tar|manifest.json|SHA256SUMS) ;; *) fail 'Unexpected recovery member' 6;; esac
    [[ -f $entry && ! -L $entry && ! -x $entry && -s $entry ]] || fail 'Unsafe recovery member' 6
  done
  for name in database.dump files.tar manifest.json SHA256SUMS; do [[ -f $STORE/$name && ! -L $STORE/$name && -s $STORE/$name ]] || fail 'Incomplete recovery point' 6; done
  jq -Rsc 'split("\n")[:-1] as $lines | ($lines|length)==3 and
    all($lines[]; test("^[a-f0-9]{64}  (database[.]dump|files[.]tar|manifest[.]json)$")) and
    ($lines|map(split("  ")[1])|sort==["database.dump","files.tar","manifest.json"])' "$STORE/SHA256SUMS" | jq -e . >/dev/null || fail 'Invalid recovery inventory' 6
  (cd "$STORE" && sha256sum -c SHA256SUMS >/dev/null) || fail 'Recovery checksum mismatch' 6
  jq -e '.format==2 and .stateFormat==1 and .service=="paperless" and (.installation|type=="string" and test("^[0-9a-f]{32}$"))' "$STORE/manifest.json" >/dev/null || fail 'Invalid recovery identity' 6
  [[ $(jq -cS '{identity,initialization}' "$STORE/manifest.json") == "$(jq -cS '{identity,initialization}' "$SETTINGS")" ]] || fail 'Recovery identity mismatch' 6
  case "$(jq -r .version "$STORE/manifest.json"):$(jq -r .versions.paperless "$SETTINGS")" in 3.3.0:3.3.0|3.3.0:3.3.1|3.3.1:3.3.1) ;; *) fail 'Unsupported recovery version' 6;; esac
  [[ $(jq -r .images.postgres "$STORE/manifest.json") == "$(jq -r .images.postgres "$SETTINGS")" && $(jq -r .images.redis "$STORE/manifest.json") == "$(jq -r .images.redis "$SETTINGS")" && $(jq -r .images.tika "$STORE/manifest.json") == "$(jq -r .images.tika "$SETTINGS")" && $(jq -r .images.gotenberg "$STORE/manifest.json") == "$(jq -r .images.gotenberg "$SETTINGS")" ]] || fail 'Recovery dependency image mismatch' 6
  RECOVERY_DIGEST=$(sha256sum "$STORE/SHA256SUMS" | cut -d' ' -f1)
}
get_contract() {
  namespace=$(kubectl get namespace "$NS" --ignore-not-found -o json)
  if [[ -n $namespace ]]; then contract=$(k get configmap paperless-contract --ignore-not-found -o json); else contract=; fi
}
check_owned() {
  get_contract
  if [[ -n $contract ]]; then
    [[ $(jq -r .data.protocol <<< "$contract") == 2 && $(jq -r .data.binding <<< "$contract") == "$(binding)" ]] || fail 'Foreign or obsolete generation contract' 7
    stage=$(jq -er '.data.stage | select(.=="provisioning" or .=="accepted")' <<< "$contract") || fail 'Unknown generation state' 7
    if [[ $(jq -r .data.settings <<< "$contract") != "$(config)" ]]; then
      previous=$(jq -r .data.settings <<< "$contract")
      [[ $ACTION == deploy || $ACTION == start ]] || fail 'Different generation settings' 7
      [[ $(jq -cS 'del(.versions,.images.paperless,.images.runtime)' <<< "$previous") == "$(config | jq -cS 'del(.versions,.images.paperless,.images.runtime)')" ]] || fail 'Different generation settings' 7
      [[ $(jq -r .versions.paperless <<< "$previous"):$(jq -r .versions.paperless "$SETTINGS") == 3.3.0:3.3.1 ]] || fail 'Unsupported runtime replacement or downgrade' 7
    fi
    if [[ -n ${RECOVERY_DIGEST:-} ]]; then [[ $(jq -r .data.recoveryDigest <<< "$contract") == "$RECOVERY_DIGEST" ]] || fail 'Different selected recovery point' 7; fi
  else
    stage=provisioning
    [[ $ACTION == deploy || $ACTION == validate ]] || fail 'No provisioned generation' 7
    if [[ -n $namespace ]]; then
      resources=$(k get deployment,job,pvc,service,secret,configmap -o json)
      [[ $(jq '[.items[] | .metadata.name as $name | select(($name|startswith("paperless")) or ($name|startswith("sh.helm.release.v1.paperless")) or ($name=="redis") or ($name=="documents") or ($name=="tika") or ($name=="gotenberg"))] | length' <<< "$resources") == 0 ]] || fail 'Unowned Paperless resources' 7
    fi
  fi
}
apply_chart() {
  helm upgrade --install paperless "$ROOT/chart" -n "$NS" -f "$SETTINGS" --set-string "phase=$1" --set "replicas=$2" --set "brokerReplicas=$3" --set-string "task=${4:-}" --timeout 600s >&2
  k scale deployment redis --replicas="$3" >&2
  if [[ $1 == runtime || $1 == task ]]; then k scale deployment paperless --replicas="$2" >&2; fi
}
stop_writer() {
  [[ -n $(k get deployment paperless --ignore-not-found -o json) ]] || return 0
  k scale deployment paperless --replicas=0 >&2
  for ((i=0;i<180;i++)); do [[ -z $(k get pod -l app=paperless -o name) ]] && return 0; sleep 1; done
  fail 'Native writers did not stop' 4
}
stop_broker() {
  k scale deployment redis --replicas=0 >&2
  for ((i=0;i<180;i++)); do [[ -z $(k get pod -l app=redis -o name) ]] && return 0; sleep 1; done
  fail 'Broker did not stop' 4
}
drain_writer() {
  local installation
  installation=$(k get configmap paperless-contract -o json | jq -r '.data.allocation|fromjson|.installation')
  k exec deployment/paperless -- sh -c 'kill -USR1 1'
  for ((i=0;i<150;i++)); do
    if [[ $(k exec deployment/paperless -- cat /state/drain-ready 2>/dev/null || true) == "$installation" ]]; then
      stop_writer
      return 0
    fi
    sleep 2
  done
  fail 'In-flight native work did not drain; service remains fenced' 4
}
run_task() {
  local old status
  old=$(k get job paperless-task --ignore-not-found -o json)
  if [[ -n $old ]]; then
    status=$(jq -r '[.status.conditions[]?|select(.status=="True")|.type]|join(",")' <<< "$old")
    [[ $status == *Complete* || $status == *Failed* ]] || fail 'Previous lifecycle task remains active' 7
    k delete job paperless-task --wait=true >&2
  fi
  apply_chart task 0 "$2" "$1"
  for ((i=0;i<300;i++)); do
    status=$(k get job paperless-task -o json | jq -r '[.status.conditions[]?|select(.status=="True")|.type]|join(",")')
    [[ $status != *Complete* ]] || return 0
    if [[ $status == *Failed* ]]; then k logs job/paperless-task >&2 || true; fail 'Lifecycle task refused' 4; fi
    sleep 2
  done
  fail 'Lifecycle task deadline exceeded' 4
}
job_complete() {
  [[ $(k get job paperless-task --ignore-not-found -o json | jq -r '.status.conditions[]?|select(.type=="Complete" and .status=="True")|.type') == Complete ]]
}
bind_empty_target() {
  local target installation
  target=$(k logs job/paperless-task | jq -Rcr 'fromjson? | select(.state=="observed" and .reason=="empty-physical-target") | .target | select((.systemIdentifier|type=="string") and (.databaseOid|type=="string") and .database=="bartl" and .owner=="bartl")') || fail 'No observed empty physical target' 4
  [[ -n $target ]] || fail 'No observed empty physical target' 4
  if [[ $(jq -r .intent "$SETTINGS") == recovery ]]; then installation=$(jq -r .installation "$STORE/manifest.json"); else installation=$(openssl rand -hex 16); fi
  allocation=$(jq -cn --arg generation "$NS" --arg installation "$installation" --argjson target "$target" '{format:1,mode:"authorized",generation:$generation,installation:$installation,target:$target}')
  k patch configmap paperless-contract --type merge -p "$(jq -cn --arg allocation "$allocation" '{data:{allocation:$allocation}}')" >/dev/null
}
publish_bound_target() {
  local complete
  complete=$(k logs job/paperless-task | jq -Rcr --arg generation "$NS" --argjson previous "$allocation" 'fromjson? | select(.state=="provisioned") | .allocation | select(.mode=="bound" and .generation==$generation and .target==$previous.target and .installation==$previous.installation and (.writerOid|type=="string" and test("^[0-9]+$")))') || fail 'No completed bound target identity' 4
  [[ -n $complete ]] || fail 'No completed bound target identity' 4
  allocation=$complete
  k patch configmap paperless-contract --type merge -p "$(jq -cn --arg allocation "$allocation" '{data:{allocation:$allocation}}')" >/dev/null
}
wait_ready() {
  local installation
  installation=$(k get configmap paperless-contract -o json | jq -r '.data.allocation|fromjson|.installation')
  for ((i=0;i<180;i++)); do
    if k get deployment paperless -o json | jq -e --arg image "$(jq -r .images.runtime "$SETTINGS")" '.spec.replicas==1 and .status.readyReplicas==1 and .status.observedGeneration==.metadata.generation and .spec.template.spec.containers[0].image==$image' >/dev/null; then
      if k exec deployment/paperless -- curl --fail --silent --connect-timeout 2 --max-time 4 http://127.0.0.1:8080/__bartl/acceptance 2>/dev/null |
         jq -e --arg generation "$NS" --arg installation "$installation" --arg version "$(jq -r .versions.paperless "$SETTINGS")" '.state=="accepted" and .generation==$generation and .installation==$installation and .version==$version and (.documents|type=="number")' >/dev/null; then
        return 0
      fi
    fi
    sleep 2
  done
  k logs deployment/paperless --tail=40 >&2 || true
  fail 'Native service functional acceptance failed' 4
}
resume() {
  [[ $RESUME == 1 ]] || return 0
  apply_chart runtime 1 1
  wait_ready
  RESUME=0
}
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  if [[ $RESUME == 1 ]]; then resume || code=4; fi
  if [[ -n $WORK ]]; then rm -rf -- "$WORK" || code=9; fi
  exit "$code"
}
prepare_restic() {
  command -v restic >/dev/null || fail 'Restic required' 2
  [[ -n ${RESTIC_REPOSITORY:-} || -n ${RESTIC_REPOSITORY_FILE:-} ]] || fail 'Restic repository required' 2
  [[ -n ${RESTIC_PASSWORD_FILE:-} || -n ${RESTIC_PASSWORD:-} || -n ${RESTIC_PASSWORD_COMMAND:-} ]] || fail 'Restic credential required' 2
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/bartl-paperless.XXXXXXXX")
  trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM
}
r() { restic --no-cache "$@" 2> "$WORK/restic-error"; }
retrieve() {
  local id=$STORE name path
  [[ $id =~ ^[a-f0-9]{64}$ && $(jq -r .intent "$SETTINGS") == recovery ]] || fail 'Exact snapshot and recovery intent required' 2
  prepare_restic
  r snapshots --json "$id" > "$WORK/snapshot.json" || fail 'Snapshot lookup failed' 6
  jq -e --arg id "$id" 'length==1 and .[0].id==$id' "$WORK/snapshot.json" >/dev/null || fail 'Exact snapshot absent' 6
  r ls --json "$id" > "$WORK/inventory.json" || fail 'Snapshot inventory failed' 6
  jq -se '[.[]|select(.struct_type=="node" and .type!="dir")] as $files |
    ($files|length==4) and
    ($files|map(.path|split("/")[-1])|sort==["SHA256SUMS","database.dump","files.tar","manifest.json"]) and
    ($files|map(.path|split("/")[:-1]|join("/"))|unique|length==1) and
    all($files[]; .type=="file" and (.mode|type=="number") and (.mode%2==0) and ((.mode/8|floor)%2==0) and ((.mode/64|floor)%2==0) and (.path|contains("/../")|not))' "$WORK/inventory.json" >/dev/null || fail 'Unsafe or incomplete snapshot inventory' 6
  STORE=$WORK/payload; mkdir -m 700 "$STORE"
  for name in database.dump files.tar manifest.json SHA256SUMS; do
    path=$(jq -r --arg name "$name" 'select(.struct_type=="node" and .type=="file")|select((.path|split("/")[-1])==$name)|.path' "$WORK/inventory.json")
    r dump "$id" "$path" > "$STORE/$name" || fail 'Snapshot retrieval failed' 6
  done
  ACTION=deploy
}
check_settings
RECOVERY_DIGEST=
if [[ $ACTION == restore ]]; then retrieve; fi
if [[ $ACTION == deploy || $ACTION == validate || $ACTION == start ]]; then
  if [[ $(jq -r .intent "$SETTINGS") == recovery ]]; then
    [[ -n $STORE ]] && check_payload || [[ $ACTION == start ]] || fail 'Selected recovery payload required' 6
  else [[ -z $STORE ]] || fail 'Fresh start rejects recovery input' 2; fi
fi
check_owned
case $ACTION in
validate)
  helm template paperless "$ROOT/chart" -f "$SETTINGS" --set-string phase=runtime --set replicas=1 >/dev/null
  echo 'Input, selected recovery and ownership preflight passed';;
stop)
  [[ $stage == accepted ]] || fail 'Stop requires accepted state' 7
  stop_writer;;
reconcile)
  [[ $stage == accepted ]] || fail 'Reconciliation requires accepted state' 7
  [[ -f $STORE && ! -L $STORE && -s $STORE && $(stat -c %a "$STORE") == 600 && $(stat -c %u "$STORE") == "$EUID" ]] || fail 'Protected owned decision file required' 2
  jq -e --arg issuer "$(jq -r .identity.issuer "$SETTINGS")" --arg paperless "$(jq -r .identity.paperless "$SETTINGS")" '.format==1 and .issuer==$issuer and .paperless==$paperless' "$STORE" >/dev/null || fail 'Decision identity mismatch' 2
  replicas=$(k get deployment paperless -o jsonpath='{.spec.replicas}')
  case $replicas in 1) drain_writer;; 0) ;; *) fail 'Unsupported native replica count' 7;; esac
  pod=$(k get pod -l app=paperless-db -o jsonpath='{.items[0].metadata.name}')
  if ! k exec "$pod" -- test -e /recovery/records-decisions.json; then
    k exec -i "$pod" -- sh -c 'umask 077; cat > /recovery/records-decisions.json' < "$STORE"
  fi
  decision_digest=$(sha256sum "$STORE" | cut -d' ' -f1)
  [[ $(k exec "$pod" -- sha256sum /recovery/records-decisions.json | cut -d' ' -f1) == "$decision_digest" ]] || fail 'Staged decisions differ from approved input' 6
  run_task reconcile 1
  k logs job/paperless-task | jq -Rce --arg digest "$decision_digest" 'fromjson? | select(.state=="reconciled" and .decisionsDigest==$digest and .receipt.decisionsDigest==$digest)'
  k exec "$pod" -- rm /recovery/records-decisions.json
  if [[ $replicas == 1 ]]; then RESUME=1; resume; else stop_broker; fi;;
capture|backup)
  [[ $stage == accepted ]] || fail 'Capture requires accepted state' 7
  if [[ $ACTION == backup ]]; then prepare_restic; STORE=$WORK/payload; fi
  [[ -n $STORE && ! -e $STORE && ! -L $STORE ]] || fail 'New capture directory required' 2
  replicas=$(k get deployment paperless -o jsonpath='{.spec.replicas}')
  case $replicas in 1) drain_writer;; 0) ;; *) fail 'Unsupported native replica count' 7;; esac
  if [[ $replicas == 0 ]]; then apply_chart state 0 1; k rollout status deployment/redis --timeout=180s >&2; fi
  # No native worker, scheduler, consumer, or web remains. Refuse any queued broker state.
  k exec deployment/redis -- redis-cli EVAL "local ks=redis.call('keys','*'); for _,key in ipairs(ks) do local t=redis.call('type',key)['ok']; local cache=(t=='string' and redis.call('ttl',key)>0 and (string.find(key,'^:1:django%.contrib%.sessions%.cached_db') or string.find(key,'^:1:jwt:iss=') or string.match(key,'^:1:doc_%d+_thumbnail_modified$'))); if not ((t=='set' and string.sub(key,1,15)=='_kombu.binding.') or (t=='string' and (string.sub(key,1,17)=='celery-task-meta-' or key==':1:treenode_list' or key==':1:treenode_dict')) or cache) then return 0 end end; return 1" 0 | jq -e '.==1' >/dev/null || fail 'Broker contains unsettled or unknown work' 4
  stop_broker
  run_task capture 0
  pod=$(k get pod -l app=paperless-db -o jsonpath='{.items[0].metadata.name}')
  mkdir -m 700 "$STORE"
  for name in database.dump files.tar manifest.json SHA256SUMS; do k exec "$pod" -- cat "/recovery/capture/$name" > "$STORE/$name"; done
  check_payload
  k exec "$pod" -- rm -rf /recovery/capture
  if [[ $ACTION == capture ]]; then echo 'Sealed capture; source remains stopped'; else
    if [[ $replicas == 1 ]]; then RESUME=1; resume || fail 'Source resume failed' 4; fi
    r backup --json "$STORE/database.dump" "$STORE/files.tar" "$STORE/manifest.json" "$STORE/SHA256SUMS" > "$WORK/backup.json" || fail 'Restic upload failed' 9
    snapshot=$(jq -ser '[.[]|select(.message_type=="summary")|.snapshot_id]|select(length==1)|.[0]|select(test("^[a-f0-9]{64}$"))' "$WORK/backup.json") || fail 'No exact snapshot result' 9
    printf '{"snapshot_id":"%s"}\n' "$snapshot"
  fi;;
deploy|start)
  if [[ -z $contract ]]; then
    [[ $ACTION == deploy ]] || fail 'Unprovisioned start' 7
    kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - >&2
    k create configmap paperless-contract --from-literal=protocol=2 --from-literal="binding=$(binding)" --from-literal=stage=provisioning --from-literal="recoveryDigest=$RECOVERY_DIGEST" --from-literal="settings=$(config)" --from-literal="allocation=$(jq -cn --arg generation "$NS" '{format:1,mode:"new",generation:$generation}')" >&2
  else
    deployment=$(k get deployment paperless --ignore-not-found -o json)
    if [[ $ACTION == deploy && $stage == accepted && -n $deployment && $(jq -r .spec.replicas <<< "$deployment") == 0 ]]; then fail 'Explicit start required for stopped service' 7; fi
    stop_writer
    k patch configmap paperless-contract --type merge -p "$(jq -cn --arg settings "$(config)" '{data:{settings:$settings}}')" >/dev/null
    k patch configmap paperless-contract --type merge -p '{"data":{"stage":"provisioning"}}' >/dev/null
  fi
  k create secret generic paperless-inputs --from-file="$SECRETS/db-password" --from-file="$SECRETS/paperless-key" --from-file="$SECRETS/client-secret" --from-file="$SECRETS/records.json" --dry-run=client -o yaml | k apply -f - >&2
  allocation=$(k get configmap paperless-contract -o json | jq -r .data.allocation)
  if job_complete; then
    case $(jq -r .mode <<< "$allocation") in
      new) bind_empty_target;;
      authorized) if k logs job/paperless-task | jq -Rce 'fromjson? | select(.state=="provisioned")' >/dev/null; then publish_bound_target; fi;;
    esac
  fi
  apply_chart state 0 0
  k rollout status deployment/paperless-db --timeout=300s >&2
  allocation=$(k get configmap paperless-contract -o json | jq -r .data.allocation)
  if [[ $(jq -r .mode <<< "$allocation") == new ]]; then
    run_task observe "$([[ $(jq -r .intent "$SETTINGS") == fresh ]] && echo 1 || echo 0)"
    bind_empty_target
  fi
  if [[ $(jq -r .mode <<< "$allocation") == authorized ]]; then
    if [[ $(jq -r .intent "$SETTINGS") == recovery ]]; then
      pod=$(k get pod -l app=paperless-db -o jsonpath='{.items[0].metadata.name}')
      k exec "$pod" -- mkdir -p /recovery/payload
      for name in database.dump files.tar manifest.json SHA256SUMS; do k exec -i "$pod" -- sh -c "cat > /recovery/payload/$name" < "$STORE/$name"; done
      task=restore
    else task=provision; fi
    run_task "$task" "$([[ $task == provision ]] && echo 1 || echo 0)"
    publish_bound_target
  fi
  apply_chart runtime 1 1
  wait_ready
  k patch configmap paperless-contract --type merge -p '{"data":{"stage":"accepted"}}' >/dev/null
  echo "Paperless generation $NS functionally accepted";;
esac
