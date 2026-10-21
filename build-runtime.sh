#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# == 2 ]] || { echo 'Usage: build-runtime.sh 3.3.0|3.3.1 LOCAL_TAG' >&2; exit 2; }
case $1 in
  3.3.0) upstream=ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207;;
  3.3.1) upstream=ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4;;
  *) echo 'Unsupported release' >&2; exit 2;;
esac
[[ $2 =~ ^[a-z0-9]+([._/-]+[a-z0-9]+)*:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || { echo 'Explicit local image tag required' >&2; exit 2; }
root=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/bartl-paperless-build.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
docker buildx build --platform linux/amd64 --load --build-arg "PAPERLESS_IMAGE=$upstream" --build-arg "PAPERLESS_VERSION=$1" --file "$root/Dockerfile" --tag "$2" --iidfile "$work/id" "$root" >&2
image_id=$(<"$work/id")
[[ $image_id =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Invalid derived image identity' >&2; exit 1; }
printf '%s\n' "$image_id"
