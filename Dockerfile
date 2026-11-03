# The build recipe overrides this with the pinned 3.3.0 image for that runtime.
ARG PAPERLESS_IMAGE=ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4
FROM docker.io/restic/restic:0.19.1@sha256:08916bcda4a4435f9d9828ebb4e91bb7ada3d2c8a53699788930e0ae1bd4fa67 AS restic
FROM ${PAPERLESS_IMAGE}
COPY --from=restic /usr/bin/restic /usr/bin/restic
COPY runtime/native.py /opt/bartl/native.py
COPY runtime/https_settings.py /usr/src/paperless/src/bartl_https_settings.py
ENV DJANGO_SETTINGS_MODULE=bartl_https_settings
# A failed finite gate prevents native migrations and every ordinary service.
# Upstream /init, all native initialization and all four services remain intact.
RUN set -eu; \
    gate=/etc/s6-overlay/s6-rc.d/init-bartl-gate; \
    mkdir -p "$gate/dependencies.d"; \
    printf 'oneshot\n' > "$gate/type"; \
    printf '/etc/s6-overlay/s6-rc.d/init-bartl-gate/run\n' > "$gate/up"; \
    printf '#!/command/with-contenv /bin/sh\nset -eu\ncd /usr/src/paperless/src\nexec uv run --no-project python /opt/bartl/native.py gate\n' > "$gate/run"; \
    chmod 0755 "$gate/run"; \
    touch "$gate/dependencies.d/init-folders" \
          "$gate/dependencies.d/init-wait-for-db" \
          "$gate/dependencies.d/init-wait-for-redis" \
          /etc/s6-overlay/s6-rc.d/init-migrations/dependencies.d/init-bartl-gate \
          /etc/s6-overlay/s6-rc.d/init-complete/dependencies.d/init-bartl-gate
