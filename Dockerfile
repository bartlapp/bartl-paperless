ARG PAPERLESS_IMAGE=ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207
FROM docker.io/library/postgres@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3 AS postgres
FROM ${PAPERLESS_IMAGE}
ARG PAPERLESS_IMAGE
ARG PAPERLESS_VERSION
USER root
RUN set -eu; case "$PAPERLESS_VERSION:$PAPERLESS_IMAGE" in \
  3.3.0:ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207|\
  3.3.1:ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4) ;; \
  *) echo 'Unsupported native image/version pair' >&2; exit 1;; esac
COPY --from=postgres /usr/lib/postgresql/17/bin/pg_dump /usr/lib/postgresql/17/bin/pg_dump
COPY --from=postgres /usr/lib/postgresql/17/bin/pg_restore /usr/lib/postgresql/17/bin/pg_restore
COPY --chown=0:0 runtime.py /opt/bartl/runtime.py
COPY --chown=0:0 native-profiles.json /opt/bartl/native-profiles.json
COPY --chown=0:0 records/ /opt/bartl/records/
RUN uv pip install --system --no-cache --no-deps /opt/bartl/records/xml-parser \
    && uv pip check --system \
    && chmod 0555 /opt/bartl/runtime.py && chmod -R a+rX,a-w /opt/bartl/records
RUN printf '{"version":"%s","paperless":"%s","postgres":"%s"}\n' "$PAPERLESS_VERSION" "$PAPERLESS_IMAGE" 'docker.io/library/postgres@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3' > /opt/bartl/runtime-version.json
