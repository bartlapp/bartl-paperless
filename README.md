# Bartl Paperless service

A local, independently operated Paperless-ngx service package for a bounded single-node Kubernetes proof. It owns Paperless, PostgreSQL, ephemeral Redis, state reconstruction, migrations, document media, access-group permissions and its own capture. It consumes an OIDC issuer endpoint; it does not deploy or manage the identity provider. HTTP, local persistent volumes, root user mapping and one replica are deliberate private-lab constraints, not a production TLS, HA or backup design.

## CLI

```sh
./bartl.sh validate SETTINGS_JSON SECRET_DIR [RECOVERY_DIR]
./bartl.sh deploy SETTINGS_JSON SECRET_DIR [RECOVERY_DIR]
./bartl.sh capture SETTINGS_JSON SECRET_DIR NEW_DIR
./bartl.sh stop SETTINGS_JSON SECRET_DIR
```

Run from any directory on an authorized host with Bash, jq, sha256sum, flock, kubectl and Helm 3, access to a compatible Kubernetes target, a writable `/run/lock`, and access to the pinned image registries. `KUBECONFIG` defaults to `/etc/rancher/k3s/k3s.yaml`. `validate` reads cluster state but creates no resources. `deploy` creates or resumes a generation. `capture` requires an accepted generation and an absent output path; it rejects pending/started Paperless tasks, records drain proof, stops the worker, then dumps PostgreSQL and archives the three Paperless data directories. If an output operation fails after the worker stops, retry into a new path while the stopped/drained contract remains. `stop` fences the Paperless worker without stopping PostgreSQL; it does not establish capture drain proof. Neither command touches a sibling service or predecessor generation. Do not retry `deploy` to restart a stopped accepted generation.

The caller supplies a JSON object like [example-settings.json](example-settings.json). `generation` is a DNS-safe namespace, `intent` is `fresh` or `recovery`, and `identity` supplies `issuer` (realm URL), `paperless` (public URL), `realm`, `client` and `provider`. `initialization` supplies `database: postgresql-17`, `ocr`, `timezone`, and `stateFormat: 1`; `versions.paperless` is `3.3.0` or `3.3.1`; `images.paperless`, `images.postgres`, and `images.redis` are digest-pinned references. Other service settings in a composition JSON are accepted and ignored. `placement.identityIP` is optional for a stable issuer hostname hostAlias; the alias hostname is derived from `identity.issuer`. `phase` is not an input to lifecycle behavior. The client, provider and issuer must match the external OIDC configuration. Consumer-controlled realm/users/documents are not fabricated by this package.

`SECRET_DIR` must contain nonempty bounded files `db-password`, `paperless-key` and `client-secret`. Protect this directory outside Git and retain the exact bytes for re-entry into the same generation and for recovery. The PostgreSQL dump stores documents, users, groups, object permissions and application settings, while `files.tar` stores `data`, `media`, `consume`; both are required to recover exact documents and permissions. The manifest captures `stateFormat: 1`, `service: paperless`, source `generation`, source `version`, `images`, `identity` and `initialization`. `SHA256SUMS` lists exactly `database.dump`, `files.tar`, `manifest.json`. Keys are never archived. Store capture artifacts immutably and securely with the corresponding keys; a checksum proves consistency, not provenance or secrecy. Redis is deliberately ephemeral and reconstructed empty; drain and stop the application before capture. The caller must protect the capture against external mutation and supply the OIDC endpoint before Paperless readiness can pass.

Recovery uses a new namespace and an independently supplied capture directory. `validate` rejects absent, malformed, duplicated or extra inventory entries, missing files, checksum mismatches, changed persistent identity/initialization, and unsupported versions before mutation. Supported transitions are `3.3.0 -> 3.3.0`, `3.3.0 -> 3.3.1`, and `3.3.1 -> 3.3.1`; rollback is not supported. The PostgreSQL image must remain identical. Preserve the application encryption key and OIDC client secret across recovery. The source generation stays fenced; promotion and endpoint routing belong to the caller.

The per-service checkpoint `paperless-contract`, secret `paperless-credentials`, Helm release `paperless` and Kubernetes resources named `paperless*`, `redis`, and `documents` are owned here. The operation fingerprint includes only this service's selected settings, script/chart bytes, secret hashes and recovery checksum inventory; it never stores literal secret values in a fingerprint. State reconstruction is retryable before the prepared marker; migrations use a persistent marker to avoid replay after success. External mutation of owned resources is not authorized by re-entry. There is no automatic repair of incomplete captured directories or lost protected secrets.

The default OIDC group `bartl-users` receives only `documents.add_document`, `documents.view_document` and `documents.view_uisettings`. UISettings View is required for the frontend to load the current user's settings and permissions; it does not grant document access beyond the existing owner/object permissions, administrator privileges or settings-write rights. See [Paperless-ngx v3.3.0 usage permissions](https://github.com/paperless-ngx/paperless-ngx/blob/v3.3.0/docs/usage.md#permissions), [UiSettingsView](https://github.com/paperless-ngx/paperless-ngx/blob/v3.3.0/src/documents/views.py#L4239) and [frontend settings initialization](https://github.com/paperless-ngx/paperless-ngx/blob/v3.3.0/src-ui/src/app/services/settings.service.ts#L357). New generations establish this minimum group policy after restore; they preserve existing user memberships and document object permissions. Already accepted generations do not replay initialization when package bytes change; reconstruct a new generation to adopt a changed package.

Example lifecycle on a disposable target:

```sh
./bartl.sh validate example-settings.json /secure/paperless
./bartl.sh deploy example-settings.json /secure/paperless
./bartl.sh capture example-settings.json /secure/paperless /secure/captures/paperless-001
# Change generation and intent to recovery in a copy of settings, then:
./bartl.sh validate /secure/recovery.json /secure/paperless /secure/captures/paperless-001
./bartl.sh deploy /secure/recovery.json /secure/paperless /secure/captures/paperless-001
```

The source chart was extracted from the internal Bartl proof. The referenced Paperless-ngx, PostgreSQL and Redis container images retain their own upstream licenses; no upstream copyright or license grant for those components is implied here.
