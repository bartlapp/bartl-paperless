#!/usr/bin/env bash
set -euo pipefail

# Run on a Linux amd64 builder. This recipe never pushes to a registry.
# Dependencies: podman, skopeo, Helm 3/4, Mike Farah yq 4, sha256sum.
# Import the resulting bundle with: sudo bash import.sh k3s
# Then install the packaged chart with the installation's own values.
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
  printf '%s\n' 'Build on Linux amd64; no local macOS Docker/VM is used.' >&2
  exit 1
}
for tool in podman skopeo helm yq sha256sum; do
  command -v "$tool" >/dev/null || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 1; }
done
[[ $(yq --version) == *'version v4.'* ]] || { printf '%s\n' 'Mike Farah yq v4 is required' >&2; exit 1; }
OUT=${OUT:-$ROOT/dist}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
[[ ! -e $OUT/chart ]] || { printf 'Output chart already exists: %s/chart; choose a fresh OUT\n' "$OUT" >&2; exit 1; }

PAPERLESS_330=ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207
PAPERLESS_331=ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4
POSTGRES=docker.io/library/postgres@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3
REDIS=docker.io/library/redis@sha256:5fa2edb1e408fa8235e6db8fab01d1afaaae96c9403ba67b70feceb8661e8621
RUNTIME_330=localhost/bartl-paperless:3.3.0-0.1.0
RUNTIME_331=localhost/bartl-paperless:3.3.1-0.1.0
CONTROLLER=localhost/bartl-paperless-controller:0.1.0

build_image() {
  local image=$1 dockerfile=$2
  shift 2
  podman build --platform linux/amd64 --format oci -f "$dockerfile" -t "$image" "$@" .
}
archive_local() {
  local image=$1 name=$2
  skopeo copy --preserve-digests --digestfile "$OUT/$name.digest" \
    "containers-storage:$image" "oci-archive:$OUT/$name.oci.tar:$image"
}
archive_dependency() {
  local image=$1 name=$2 tag=$3
  skopeo copy --all --preserve-digests \
    "docker://$image" "oci-archive:$OUT/$name.oci.tar:$tag"
}
build_image "$RUNTIME_330" Dockerfile --build-arg "PAPERLESS_IMAGE=$PAPERLESS_330"
build_image "$RUNTIME_331" Dockerfile --build-arg "PAPERLESS_IMAGE=$PAPERLESS_331"
build_image "$CONTROLLER" Controller.Dockerfile
archive_local "$RUNTIME_330" paperless-3.3.0
archive_local "$RUNTIME_331" paperless-3.3.1
archive_local "$CONTROLLER" paperless-controller
archive_dependency "$POSTGRES" postgres docker.io/library/postgres:17.6
archive_dependency "$REDIS" redis docker.io/library/redis:8.2.1

DIGEST_330=$(< "$OUT/paperless-3.3.0.digest")
DIGEST_331=$(< "$OUT/paperless-3.3.1.digest")
DIGEST_CONTROLLER=$(< "$OUT/paperless-controller.digest")
export IMAGE_330="${RUNTIME_330%:*}@$DIGEST_330"
export IMAGE_331="${RUNTIME_331%:*}@$DIGEST_331"
export IMAGE_CONTROLLER="${CONTROLLER%:*}@$DIGEST_CONTROLLER"
cp -R chart "$OUT/chart"
yq -i '.controller.image = strenv(IMAGE_CONTROLLER) | .images.runtime330 = strenv(IMAGE_330) | .images.runtime331 = strenv(IMAGE_331)' "$OUT/chart/values.yaml"
# The package itself carries the exact built images; this file is also usable
# as a final image override when installing from the source chart.
yq '{"controller": {"image": .controller.image}, "images": .images}' "$OUT/chart/values.yaml" > "$OUT/image-values.yaml"
helm package "$OUT/chart" --destination "$OUT"
cp import.sh compact.sh "$OUT/"
printf '%s\t%s\t%s\n' \
  paperless-3.3.0.oci.tar "$RUNTIME_330" "$IMAGE_330" \
  paperless-3.3.1.oci.tar "$RUNTIME_331" "$IMAGE_331" \
  paperless-controller.oci.tar "$CONTROLLER" "$IMAGE_CONTROLLER" \
  postgres.oci.tar docker.io/library/postgres:17.6 "$POSTGRES" \
  redis.oci.tar docker.io/library/redis:8.2.1 "$REDIS" > "$OUT/images.tsv"
(cd "$OUT" && sha256sum -- *.oci.tar *.tgz image-values.yaml images.tsv import.sh compact.sh > SHA256SUMS)
printf 'Offline artifacts: %s\nImport on every target node with: sudo bash import.sh k3s\n' "$OUT"
printf '%s\n' 'Install: helm install paperless ./bartl-paperless-0.1.0.tgz --namespace paperless --create-namespace -f installation-values.yaml'
