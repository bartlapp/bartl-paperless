#!/usr/bin/env bash
set -euo pipefail

# Build a candidate once on Linux amd64; qualification and publication reuse it.
# Dependencies: podman, skopeo, Helm 3/4, Mike Farah yq 4, sha256sum.
# OCI directories are remote build retention, not an offline installation product.
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
mkdir "$OUT"
OUT=$(cd "$OUT" && pwd)
RELEASE=$(yq -r '.version' chart/Chart.yaml)

PAPERLESS_330=ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207
PAPERLESS_331=ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4
RUNTIME_330=ghcr.io/bartlapp/bartl-paperless-runtime:3.3.0-$RELEASE
RUNTIME_331=ghcr.io/bartlapp/bartl-paperless-runtime:3.3.1-$RELEASE
CONTROLLER=ghcr.io/bartlapp/bartl-paperless-controller:$RELEASE

build_image() {
  local image=$1 dockerfile=$2
  shift 2
  podman build --platform linux/amd64 --format oci -f "$dockerfile" -t "$image" "$@" .
}
retain_image() {
  local image=$1 name=$2
  skopeo copy --preserve-digests --digestfile "$OUT/$name.digest" \
    "containers-storage:$image" "oci:$OUT/$name:$image"
}
build_image "$RUNTIME_330" Dockerfile --build-arg "PAPERLESS_IMAGE=$PAPERLESS_330"
build_image "$RUNTIME_331" Dockerfile --build-arg "PAPERLESS_IMAGE=$PAPERLESS_331"
build_image "$CONTROLLER" Controller.Dockerfile
retain_image "$RUNTIME_330" paperless-3.3.0
retain_image "$RUNTIME_331" paperless-3.3.1
retain_image "$CONTROLLER" paperless-controller

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
(cd "$OUT" && sha256sum -- *.tgz *.digest image-values.yaml > SHA256SUMS)
printf 'Retained release candidate: %s\n' "$OUT"
printf '%s\n' 'Qualify this chart and these OCI images; publish the same bytes without rebuilding.'
