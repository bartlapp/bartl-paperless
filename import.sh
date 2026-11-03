#!/usr/bin/env bash
set -euo pipefail
# Packaging only: import verified artifacts, never initialize application state.
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
case ${1:-k3s} in
  k3s) runtime=(k3s ctr) ;;
  containerd) runtime=(ctr -n k8s.io) ;;
  *) printf 'Usage: bash import.sh [k3s|containerd]\n' >&2; exit 1 ;;
esac
sha256sum -c SHA256SUMS
previous_archive=
while IFS=$'\t' read -r archive tagged immutable; do
  if [[ $archive != "$previous_archive" ]]; then
    case "$archive" in
      *.gz) gzip -dc "$archive" | "${runtime[@]}" images import --digests - ;;
      *) "${runtime[@]}" images import --digests "$archive" ;;
    esac
    previous_archive=$archive
  fi
  # OCI transport indexes have their own digest. Register the actual image
  # manifest/index identity used by the chart, not the transport wrapper.
  if [[ $tagged != "$immutable" ]]; then
    "${runtime[@]}" images tag --force "$tagged" "$immutable"
  fi
done < images.tsv
