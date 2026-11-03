#!/usr/bin/env bash
set -euo pipefail
# After import, export the same immutable images once, sharing common layers.
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
case ${1:-k3s} in
  k3s) runtime=(k3s ctr) ;;
  containerd) runtime=(ctr -n k8s.io) ;;
  *) printf 'Usage: sudo OUT=/new/directory bash compact.sh [k3s|containerd]\n' >&2; exit 1 ;;
esac
OUT=${OUT:-$ROOT/compact}
mkdir "$OUT"
OUT=$(cd "$OUT" && pwd)
images=()
while IFS=$'\t' read -r archive tagged immutable; do
  images+=("$immutable")
done < images.tsv
[[ ${#images[@]} -gt 0 ]] || { printf 'No declared images\n' >&2; exit 1; }
"${runtime[@]}" images export --platform linux/amd64 "$OUT/images.oci.tar" "${images[@]}"
gzip -9 "$OUT/images.oci.tar"
for image in "${images[@]}"; do
  printf '%s\t%s\t%s\n' images.oci.tar.gz "$image" "$image"
done > "$OUT/images.tsv"
cp -- ./*.tgz image-values.yaml import.sh compact.sh "$OUT/"
(cd "$OUT" && sha256sum -- images.oci.tar.gz *.tgz image-values.yaml images.tsv import.sh compact.sh > SHA256SUMS)
printf 'Compact amd64 bundle: %s\n' "$OUT"
