{{- define "bartl.state" -}}
{{- $app := .app -}}
{{- $root := .root -}}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ $app }}-database
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ $app }}-state
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $app }}-db
spec:
  selector: {app: {{ $app }}-db}
  ports: [{port: 5432, targetPort: 5432}]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ $app }}-db
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector:
    matchLabels: {app: {{ $app }}-db}
  template:
    metadata:
      labels: {app: {{ $app }}-db}
    spec:
      containers:
        - name: postgres
          image: {{ $root.Values.images.postgres | quote }}
          env:
            - {name: POSTGRES_USER, value: bartl}
            - {name: POSTGRES_DB, value: bartl}
            - name: POSTGRES_PASSWORD
              valueFrom: {secretKeyRef: {name: paperless-credentials, key: db-password}}
            - {name: PGDATA, value: /var/lib/postgresql/data/pgdata}
          readinessProbe:
            exec: {command: [pg_isready, -U, bartl, -d, bartl]}
            periodSeconds: 2
          volumeMounts:
            - {name: database, mountPath: /var/lib/postgresql/data}
            - {name: state, mountPath: /paperless}
            - {name: recovery, mountPath: /recovery}
      volumes:
        - name: database
          persistentVolumeClaim: {claimName: {{ $app }}-database}
        - name: state
          persistentVolumeClaim: {claimName: {{ $app }}-state}
        - name: recovery
          persistentVolumeClaim: {claimName: {{ $app }}-recovery}
---
{{- if ne $root.Values.phase "state" }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ $app }}-state
spec:
  backoffLimit: 2
  activeDeadlineSeconds: 600
  template:
    metadata:
      labels: {app: {{ $app }}-initializer}
    spec:
      restartPolicy: Never
      containers:
        - name: reconstruct
          image: {{ $root.Values.images.postgres | quote }}
          command: [bash, -ec]
          args:
            - |
              exec 8>/state/lifecycle.lock
              flock -n 8 || { echo 'Exclusive mutation owner exists'; exit 20; }
              if test -f /state/prepared; then
                test "$(cat /state/prepared)" = '{{ $root.Values.generation }}' || exit 21
                echo 'Exact generation already prepared'; exit 0
              fi
              {{- if eq $root.Values.intent "recovery" }}
              test -s /recovery/database.dump || { echo 'Missing verified recovery database'; exit 22; }
              pg_restore --list /recovery/database.dump >/dev/null
              # A clean, isolated target can retry a partially restored database safely.
              dropdb --if-exists --force bartl
              createdb bartl
              pg_restore --exit-on-error --no-owner -d bartl /recovery/database.dump
              {{- if eq $app "paperless" }}
              test -s /recovery/files.tar || exit 23
              tar -tf /recovery/files.tar >/dev/null
              rm -rf /state/data /state/media /state/consume
              tar -C /state -xf /recovery/files.tar
              {{- end }}
              {{- else }}
              test "$(psql -At -d bartl -c 'select count(*) from pg_tables where schemaname = current_schema()')" = 0 || { echo 'Fresh intent refuses unmarked existing database'; exit 24; }
              mkdir -p /state/data /state/media /state/consume
              {{- end }}
              printf '%s' '{{ $root.Values.generation }}' > /state/prepared.tmp
              mv /state/prepared.tmp /state/prepared
          env:
            - {name: PGHOST, value: {{ $app }}-db}
            - {name: PGUSER, value: bartl}
            - name: PGPASSWORD
              valueFrom: {secretKeyRef: {name: paperless-credentials, key: db-password}}
          volumeMounts:
            - {name: state, mountPath: /state}
            - {name: recovery, mountPath: /recovery}
      volumes:
        - name: state
          persistentVolumeClaim: {claimName: {{ $app }}-state}
        - name: recovery
          persistentVolumeClaim: {claimName: {{ $app }}-recovery}
---
{{- end }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ $app }}-recovery
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
---
{{- end -}}