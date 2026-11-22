# Repository instructions

Before changing package configuration, lifecycle behavior, installation procedures or qualification, read this repository's README and both governing documents:

- [Bartl application contract](https://github.com/bartlapp/bartl-app/blob/main/docs/application-contract.md), including Standalone operation and Supported configuration and catalogue evidence.
- [How to bartlize](https://github.com/bartlapp/bartl-app/blob/main/docs/how-to-bartlize.md), including the applicable package interface and qualification procedure.

Read the documents before implementation; listing them as future reading is insufficient. They govern implementation and acceptance. For coordinated local work, use the bartl-app checkout carrying the approved contract changes; in bartl-app itself, read docs/application-contract.md and docs/how-to-bartlize.md. Otherwise use the canonical public documents linked above. Identify the source revision used. Resolve conflicting governing versions before implementation rather than silently choosing one.

Preserve the contract's standalone operating path. Company-specific installation tooling may compose packages but must not become necessary to operate them. The contract, not this instruction file, owns the detailed requirements.

Before declaring affected package behavior or operating procedures complete, provide the standalone qualification evidence required by the contract, tied to the exact delivered artifacts, in the existing package qualification or release record. Existing evidence may be reused only where it still covers the behavior and applicable artifacts. Passing installation-generator tests is not a substitute. If required verification cannot be performed, report implementation progress and the outstanding acceptance requirement; do not declare the behavior complete. Documentation-only changes require document verification, not an unrelated deployment exercise.

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
