"""Finite Paperless procedures. /init and s6 remain the process supervisor."""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

STATE = Path('/state')
STAGING = Path('/staging')
HOME = Path('/usr/src/paperless')
SOURCE = HOME / 'src'
SERVICES = ('svc-webserver', 'svc-scheduler', 'svc-consumer', 'svc-worker')
VERSIONS = ('3.3.0', '3.3.1')
ID = re.compile(r'^[a-f0-9]{64}$')
OP = re.compile(r'^[a-zA-Z0-9-]{1,100}$')
OWNED_DIRECTORIES = ('data', 'media', 'consume')


def required(name):
    value = os.environ.get(name, '')
    if not value:
        raise RuntimeError(f'Missing {name}')
    return value


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def identity():
    return {'installation': required('BARTL_INSTALLATION'), 'instance': required('BARTL_INSTANCE')}


def version():
    value = required('BARTL_VERSION')
    sys.path.insert(0, str(SOURCE))
    from paperless.version import __full_version_str__
    if value not in VERSIONS or value != __full_version_str__:
        raise RuntimeError('Unsupported or mismatched native image version')
    return value


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def save(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + str(uuid.uuid4()))
    with temporary.open('x') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def result(value):
    value = {**value, 'operation': os.environ.get('BARTL_OPERATION', value.get('operation', '')),
             'applicationUID': required('BARTL_UID')}
    encoded = json.dumps(value, sort_keys=True)
    print(encoded, flush=True)
    if os.environ.get('BARTL_OPERATION'):
        Path('/dev/termination-log').write_text(encoded)
    return value


def command(args, *, timeout=1800, env=None, cwd=SOURCE):
    completed = subprocess.run([str(x) for x in args], cwd=cwd, env=env,
                               text=True, stdout=subprocess.PIPE, stderr=sys.stderr,
                               timeout=timeout, check=True)
    return completed.stdout


def manage(*args, timeout=1800):
    subprocess.run(['uv', 'run', '--no-project', 'python', 'manage.py', *args],
                   cwd=SOURCE, stdout=sys.stderr, stderr=sys.stderr,
                   timeout=timeout, check=True)


@contextlib.contextmanager
def exclusive():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / '.bartl-lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def database():
    import psycopg
    return psycopg.connect(host=required('PAPERLESS_DBHOST'),
                           dbname=os.environ.get('PAPERLESS_DBNAME', 'paperless'),
                           user=os.environ.get('PAPERLESS_DBUSER', 'paperless'),
                           password=required('PAPERLESS_DBPASS'), connect_timeout=10)


def api(path):
    serviceaccount = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    request = urllib.request.Request('https://kubernetes.default.svc' + path,
        headers={'Authorization': 'Bearer ' + (serviceaccount / 'token').read_text().strip()})
    with urllib.request.urlopen(request, context=ssl.create_default_context(
            cafile=str(serviceaccount / 'ca.crt')), timeout=10) as response:
        return json.load(response)


def authority(execution=None, capture_operation=None, publication=None, require_running=True):
    ns, name = required('BARTL_NAMESPACE'), required('BARTL_NAME')
    app = api(f'/apis/paperless.bartl.sh/v1alpha2/namespaces/{ns}/paperlessapplications/{name}')
    if (app['metadata']['uid'] != required('BARTL_UID') or app['metadata'].get('deletionTimestamp')
            or app['spec']['identity'] != identity()
            or app.get('status', {}).get('failure')):
        raise RuntimeError('Running authority withdrawn')
    if capture_operation is not None:
        admitted = app.get('status', {}).get('backup', {})
        if (admitted.get('captureOperation') != capture_operation
                or admitted.get('execution') != execution
                or admitted.get('podUID') != required('BARTL_POD_UID')
                or admitted.get('phase') not in ('Admitting', 'Capturing', 'Captured', 'Publishing', 'Published')):
            raise RuntimeError('Capture authority withdrawn')
    elif publication is not None:
        backup = app.get('status', {}).get('backup', {})
        if (backup.get('captureOperation') != publication or not backup.get('capturedAt')
                or backup.get('phase') != 'Publishing'
                or backup.get('publication', {}).get('id') != required('BARTL_OPERATION')):
            raise RuntimeError('Publication authority withdrawn')
    elif require_running and (app['spec']['running'] is not True or app['spec']['replicas'] != 1):
        raise RuntimeError('Running authority withdrawn')
    for claim in app['spec']['claims'].values():
        pvc = api(f'/api/v1/namespaces/{ns}/persistentvolumeclaims/{claim}')
        if (pvc['metadata'].get('deletionTimestamp') or
                pvc['metadata'].get('annotations', {}).get('paperless.bartl.sh/owner') != app['metadata']['uid']):
            raise RuntimeError('Storage ownership withdrawn')
    pod = api(f'/api/v1/namespaces/{ns}/pods/{required("BARTL_POD_NAME")}')
    if pod['metadata']['uid'] != required('BARTL_POD_UID') or pod['metadata'].get('deletionTimestamp'):
        raise RuntimeError('Pod execution withdrawn')
    if execution is not None and execution != Path('/run/bartl-execution').read_text().strip():
        raise RuntimeError('Container execution changed')
    return app


def files_under(path):
    path = Path(path)
    try:
        path.stat()
    except FileNotFoundError:
        return
    # glob/Path.exists suppress filesystem errors on current Python releases.
    # Failed observation must never become permission to initialize empty state.
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                yield from files_under(entry.path)
            else:
                yield Path(entry.path)


def observe():
    if load(STATE / 'transition.json'):
        raise RuntimeError('Interrupted native transition; retain diagnostics and replace the failed target')
    binding = load(STATE / 'binding.json')
    if binding and (binding.get('identity') != identity() or binding.get('version') not in VERSIONS
                    or binding.get('applicationUID') != required('BARTL_UID')):
        raise RuntimeError('Foreign or incompatible local binding')
    with database() as db:
        tables = {row[0] for row in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        if binding:
            if not {'bartl_binding', 'documents_document', 'auth_user'} <= tables:
                raise RuntimeError('Owned database state is missing')
            row = db.execute('SELECT binding FROM bartl_binding WHERE singleton=true').fetchone()
            if not row or row[0] != binding:
                raise RuntimeError('Database and file storage bindings disagree')
            documents = db.execute('SELECT EXISTS(SELECT 1 FROM documents_document)').fetchone()[0]
            if documents and not any(files_under(HOME / 'media/documents/originals')):
                raise RuntimeError('Document state exists but original file storage is absent')
            return {'state': 'Existing', 'version': binding['version']}
        if tables or any(files_under(HOME / 'media')) or any(files_under(HOME / 'consume')):
            raise RuntimeError('Unowned or partial application state is not absence')
        # Native setup may create empty directories, but never business data.
        if any(p.name != 'migration_lock' for p in files_under(HOME / 'data')):
            raise RuntimeError('Unowned data directory is not empty')
        return {'state': 'Empty', 'version': version()}


def restic(*args, cwd=STAGING):
    credentials = Path('/credentials')
    environment = os.environ.copy()
    environment.update(RESTIC_REPOSITORY=required('BARTL_REPOSITORY'),
                       RESTIC_PASSWORD_FILE=str(credentials / 'password'),
                       RESTIC_REST_USERNAME=(credentials / 'username').read_text().strip(),
                       RESTIC_REST_PASSWORD=(credentials / 'restPassword').read_text().strip(),
                       RESTIC_CACHE_DIR='/tmp/restic-cache')
    options = ['restic']
    if (credentials / 'ca.crt').exists():
        options += ['--cacert', str(credentials / 'ca.crt')]
    # Native lock behavior is deliberately untouched. Never --no-lock/unlock.
    return command(options + list(args), env=environment, cwd=cwd, timeout=3600)


def repository_id():
    value = json.loads(restic('cat', 'config'))['id']
    if not ID.fullmatch(value):
        raise RuntimeError('Invalid native repository identity')
    return value


def tags():
    i = identity()
    return ['bartl-paperless', 'installation:' + i['installation'], 'instance:' + i['instance']]


def inventory(directory):
    directory = Path(directory)
    found = {}
    for path in sorted(files_under(directory)):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f'Unexpected nonregular capture member: {path}')
        if path.name == 'bartl-manifest.json' and path.parent == directory:
            continue
        digest = hashlib.sha256()
        size = 0
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
                size += len(block)
        found[str(path.relative_to(directory))] = {'bytes': size, 'sha256': digest.hexdigest()}
    return found


def verify_capture(directory):
    manifest = load(Path(directory) / 'bartl-manifest.json')
    if (not manifest or manifest.get('format') != 2 or manifest.get('identity') != identity()
            or manifest.get('version') not in VERSIONS):
        raise RuntimeError('Foreign, incomplete or incompatible capture manifest')
    actual = inventory(directory)
    if (actual != manifest.get('files') or not actual.get('database.dump', {}).get('bytes')
            or any(not (Path(directory) / 'files' / name).is_dir() for name in OWNED_DIRECTORIES)
            or any(name != 'database.dump' and not any(
                name.startswith(f'files/{root}/') for root in OWNED_DIRECTORIES) for name in actual)):
        raise RuntimeError('Capture inventory or content integrity mismatch')
    return manifest


def selected_restore(snapshot, destination):
    paths = snapshot.get('paths', [])
    if len(paths) != 1 or not re.fullmatch(r'/staging/captures/[a-zA-Z0-9-]{1,100}', paths[0]):
        raise RuntimeError('Unexpected snapshot capture path')
    restic('restore', snapshot['id'], '--target', str(destination))
    directory = destination / paths[0].lstrip('/')
    return directory, verify_capture(directory)


def inspect():
    with exclusive():
        authority()
        observed = observe()
        if observed['state'] == 'Existing' or not os.environ.get('BARTL_REPOSITORY'):
            return result(observed)
        repo = repository_id()
        snapshots = []
        for snapshot_id in restic('list', 'snapshots').splitlines():
            if not ID.fullmatch(snapshot_id):
                raise RuntimeError('Unreadable native snapshot inventory')
            snapshot = json.loads(restic('cat', 'snapshot', snapshot_id))
            if set(tags() + ['complete']) <= set(snapshot.get('tags', [])):
                snapshot['id'] = snapshot_id
                snapshots.append(snapshot)
        if not snapshots:
            return result(observed)
        snapshot = max(snapshots, key=lambda s: (s['time'], s['id']))
        destination = STAGING / 'recovery' / required('BARTL_OPERATION')
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        directory, manifest = selected_restore(snapshot, destination)
        if VERSIONS.index(manifest['version']) > VERSIONS.index(version()):
            raise RuntimeError('Backup downgrade refused')
        record = {'state': 'Recovery', 'version': manifest['version'], 'repositoryID': repo,
                  'snapshotID': snapshot['id'], 'path': str(directory), 'identity': identity()}
        save(STAGING / 'recovery.json', record)
        return result({k: v for k, v in record.items() if k not in ('identity', 'path')})


def postgres(*args):
    environment = os.environ.copy()
    environment.update(PGHOST=required('PAPERLESS_DBHOST'),
                       PGPORT=os.environ.get('PAPERLESS_DBPORT', '5432'),
                       PGDATABASE=os.environ.get('PAPERLESS_DBNAME', 'paperless'),
                       PGUSER=os.environ.get('PAPERLESS_DBUSER', 'paperless'),
                       PGPASSWORD=required('PAPERLESS_DBPASS'))
    return command(args, env=environment)


def restore_state(directory):
    directory = Path(directory)
    verify_capture(directory)
    # No native migrations or application tables may precede a full restore.
    with database() as db:
        if db.execute("SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public')").fetchone()[0]:
            raise RuntimeError('Native database restore requires an empty owned database')
    for name in OWNED_DIRECTORIES:
        if any(p.name != 'migration_lock' or name != 'data' for p in files_under(HOME / name)):
            raise RuntimeError('Native file restore requires empty owned directories')
    postgres('pg_restore', '--exit-on-error', '--single-transaction', '--no-owner',
             '--no-privileges', '--dbname', os.environ.get('PAPERLESS_DBNAME', 'paperless'),
             str(directory / 'database.dump'))
    for name in OWNED_DIRECTORIES:
        source, destination = directory / 'files' / name, HOME / name
        shutil.copytree(source, destination, dirs_exist_ok=True)
        restored = inventory(destination)
        expected = inventory(source)
        # /init may already own its empty migration lock on the target.
        if name == 'data' and 'migration_lock' not in expected:
            restored.pop('migration_lock', None)
        if restored != expected:
            raise RuntimeError('Restored native file inventory mismatch')


def bind():
    from psycopg.types.json import Jsonb
    previous = load(STATE / 'binding.json')
    binding = {'identity': identity(), 'version': version(), 'applicationUID': required('BARTL_UID'),
               'storageID': previous['storageID'] if previous else str(uuid.uuid4())}
    with database() as db:
        db.execute('CREATE TABLE IF NOT EXISTS bartl_binding (singleton boolean PRIMARY KEY CHECK(singleton), binding jsonb NOT NULL)')
        db.execute('INSERT INTO bartl_binding VALUES (true,%s) ON CONFLICT(singleton) DO UPDATE SET binding=EXCLUDED.binding', (Jsonb(binding),))
    save(STATE / 'binding.json', binding)


def prepare(migration=False):
    with exclusive():
        authority()
        observed = observe()
        mode = 'Existing' if migration else required('BARTL_PREPARE_MODE')
        if mode == 'Existing':
            if observed['state'] != 'Existing':
                raise RuntimeError('Existing preparation requires owned state')
            if (observed['version'], version()) not in (('3.3.0','3.3.0'), ('3.3.0','3.3.1'), ('3.3.1','3.3.1')):
                raise RuntimeError('Unsupported transition or downgrade')
        elif mode not in ('Empty', 'Recovery') or observed['state'] != 'Empty':
            raise RuntimeError('Initialization/reconstruction requires confirmed absence')
        if mode == 'Existing' and observed['version'] == version():
            return result({'state': 'Prepared', 'version': version()})
        recovery = None
        if mode == 'Recovery':
            recovery = load(STAGING / 'recovery.json')
            if not recovery or recovery['identity'] != identity() or recovery['version'] != version():
                raise RuntimeError('Missing same-version bound recovery selection')
            verify_capture(recovery['path'])
        save(STATE / 'transition.json', {'operation': required('BARTL_OPERATION'), 'kind': mode,
                                       'version': version(), 'startedAt': now()})
        if recovery:
            authority()
            restore_state(recovery['path'])
        # Reuse the native directory initializer after restoring owned state.
        subprocess.run(['/usr/bin/bash', '/etc/s6-overlay/s6-rc.d/init-folders/run'],
                       cwd=SOURCE, stdout=sys.stderr, stderr=sys.stderr,
                       timeout=1800, check=True)
        # These are the same native compatibility check/migrations used by init-migrations.
        manage('check', '--tag', 'compatibility', 'paperless')
        manage('migrate', '--skip-checks', '--no-input')
        if mode == 'Empty' and os.environ.get('PAPERLESS_ADMIN_USER'):
            os.environ.update(DJANGO_SUPERUSER_USERNAME=required('PAPERLESS_ADMIN_USER'),
                              DJANGO_SUPERUSER_PASSWORD=required('PAPERLESS_ADMIN_PASSWORD'),
                              DJANGO_SUPERUSER_EMAIL=os.environ.get('PAPERLESS_ADMIN_MAIL', ''))
            manage('createsuperuser', '--noinput')
        # /init's init-search-index performs this conditional native rebuild.
        # 3.3.1 changes search schema v3 -> v4 (root documents only), despite
        # having no new Django migrations. Complete it before binding the target.
        manage('document_index', 'reindex', '--if-needed', '--no-progress-bar')
        # Finite Jobs run as root to protect staging; native services run as UID 1000.
        for name in ('data', 'media', 'consume'):
            root = HOME / name
            root.mkdir(parents=True, exist_ok=True)
            for path in (root, *root.rglob('*')):
                os.chown(path, 1000, 1000, follow_symlinks=False)
        bind()
        authority()
        (STATE / 'transition.json').unlink()
        return result({'state': 'Prepared', 'version': version()})


def gate():
    with exclusive():
        authority()
        # Recreate orders upgrades, but not replacement after ordinary Pod deletion.
        # RWO permits both Pods on this node; a terminating predecessor may still write.
        selector = urllib.parse.urlencode({'labelSelector':
            f'paperless.bartl.sh/uid={required("BARTL_UID")},paperless.bartl.sh/role=app'})
        pods = api(f'/api/v1/namespaces/{required("BARTL_NAMESPACE")}/pods?{selector}')
        if any(p['metadata']['uid'] != required('BARTL_POD_UID') for p in pods['items']):
            raise BlockingIOError('Previous application Pod has not retired; retry native admission')
        marker = load(STATE / 'transition.json')
        captured = load(STATE / 'capture.json')
        binding = load(STATE / 'binding.json', {}) if marker else {}
        if (marker and marker.get('state') == 'Capturing' and captured
                and binding.get('applicationUID') == required('BARTL_UID')
                and binding.get('identity') == identity()
                and captured.get('operation') == marker.get('operation')
                and captured.get('execution') == marker.get('execution')):
            if (captured.get('state') == 'Captured'
                    and captured.get('path') == str(STAGING / 'captures' / captured['operation'])):
                verify_capture(captured['path'])
                (STATE / 'transition.json').unlink()
            elif captured.get('state') == 'Failed' and captured.get('sourceIntact'):
                (STATE / 'transition.json').unlink()
        observed = observe()
        if observed != {'state': 'Existing', 'version': version()}:
            raise RuntimeError('Native startup requires successful current-version preparation')
        execution = str(uuid.uuid4())
        Path('/run/bartl-execution').write_text(execution)
        print(json.dumps({'state': 'Admitted', 'execution': execution}), flush=True)


def status():
    execution = Path('/run/bartl-execution')
    failure = load(STATE / 'transition.json') or load('/run/bartl-gate-error.json')
    capture = load(STATE / 'capture.json', {})
    return result({'execution': execution.read_text().strip() if execution.exists() else '',
                   'ready': failure is None and execution.exists(),
                   'failure': json.dumps(failure) if failure else '',
                   'capture': capture})


def s6(up, services):
    command(['s6-rc', '-t', '120000', '-u' if up else '-d', 'change', *services], timeout=130)


def process_identity(pid):
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
        return stat.rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def native_processes():
    found = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            uid_line = next(line for line in (path / 'status').read_text().splitlines() if line.startswith('Uid:'))
            if int(uid_line.split()[1]) == 1000:
                started = process_identity(path.name)
                if started is not None:
                    found[path.name] = started
        except (FileNotFoundError, ProcessLookupError):
            pass
    return found


def broker_empty():
    import redis
    broker = redis.Redis.from_url(required('PAPERLESS_REDIS'), socket_timeout=5, socket_connect_timeout=5)
    # Kombu's Redis priority queues use four list keys; inspect all queue lists.
    for key in broker.scan_iter():
        kind = broker.type(key)
        if kind == b'list' and broker.llen(key):
            return False
        if key == b'unacked_index' and kind == b'zset' and broker.zcard(key):
            return False
        if key == b'unacked' and kind == b'hash' and broker.hlen(key):
            return False
    return True


def settled():
    sys.path.insert(0, str(SOURCE))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'paperless.settings')
    # Inspection replies can contain pickled native model arguments for active
    # or reserved work. Load their model registry before decoding those replies.
    import django
    django.setup()
    from paperless.celery import app
    inspector = app.control.inspect(timeout=5)
    for method in ('active', 'reserved', 'scheduled'):
        replies = getattr(inspector, method)()
        if not replies:
            return False
        if len(replies) != 1:
            raise RuntimeError('Supported capture requires exactly one native worker')
        if any(replies.values()):
            return False
    return broker_empty() and not any(files_under(HOME / 'consume'))


def assert_settled_state():
    # Empty broker/worker replies alone can hide a task whose process died.
    # Retain ambiguous inputs for diagnosis; do not invent a replay procedure.
    import django
    django.setup()
    from django.conf import settings
    from documents.models import PaperlessTask
    if PaperlessTask.objects.filter(status__in=('pending', 'started')).exists():
        raise RuntimeError('Unresolved native task state; complete capture refused')
    if any(files_under(settings.SCRATCH_DIR)):
        raise RuntimeError('Unresolved native scratch files; complete capture refused')
    # The native command only renders findings and exits successfully even
    # for missing originals. Use its same native API and enforce its errors.
    from documents.sanity_checker import check_sanity
    messages = check_sanity()
    messages.log_messages()
    if messages.has_error:
        raise RuntimeError('Native document sanity check failed; complete capture refused')


def capture(operation, execution, seconds):
    with exclusive():
        current = load(STATE / 'capture.json')
        if (not current or current.get('state') != 'Capturing'
                or current['operation'] != operation or current['execution'] != execution):
            raise RuntimeError('Capture admission changed')
        quiesced = False
        try:
            authority(execution, operation)
            s6(False, SERVICES[:3])
            deadline = time.monotonic() + seconds
            while not settled():
                authority(execution, operation)
                if time.monotonic() >= deadline:
                    raise RuntimeError('Drain deadline exceeded; queues were not purged')
                time.sleep(1)
            writers = native_processes()
            s6(False, ('svc-worker',))
            if native_processes() or any(process_identity(pid) == start for pid, start in writers.items()):
                raise RuntimeError('Native writer/descendant termination not established')
            if not broker_empty():
                raise RuntimeError('Broker became nonempty after worker stop')
            # A disconnected client can leave PostgreSQL executing its query.
            # Wait for server-side application sessions, not just local PIDs.
            from django.db import connections
            connections.close_all()
            while True:
                with database() as db:
                    clients = db.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                        "WHERE datname=current_database() AND pid<>pg_backend_pid() "
                        "AND backend_type='client backend')").fetchone()[0]
                if not clients:
                    break
                authority(execution, operation)
                if time.monotonic() >= deadline:
                    raise RuntimeError('Drain deadline exceeded with PostgreSQL sessions still present')
                time.sleep(1)
            authority(execution, operation)
            assert_settled_state()
            quiesced = True
            directory = STAGING / 'captures' / operation
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            current['capturedAt'] = now()
            postgres('pg_dump', '--format=custom', '--no-owner', '--no-privileges',
                     '--exclude-table=public.bartl_binding', '--file', str(directory / 'database.dump'))
            # The same stopped-writer boundary covers database and every owned
            # native file, including versions, classifier and search data.
            for name in OWNED_DIRECTORIES:
                source = HOME / name
                source_files = inventory(source)  # Refuse symlinks/special files.
                destination = directory / 'files' / name
                shutil.copytree(source, destination)
                if inventory(destination) != source_files:
                    raise RuntimeError('Native capture file copy integrity mismatch')
            # Complete receipts must not outlive unflushed dump/copied bytes.
            for root, _, names in os.walk(directory, topdown=False):
                for name in names:
                    with (Path(root) / name).open('rb') as stream:
                        os.fsync(stream.fileno())
                fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            manifest = {'format': 2, 'identity': identity(), 'version': version(),
                        'operation': operation, 'execution': execution, 'capturedAt': current['capturedAt'],
                        'files': inventory(directory)}
            save(directory / 'bartl-manifest.json', manifest)
            verify_capture(directory)
            current.update(state='Captured', path=str(directory), resumed=False)
            save(STATE / 'capture.json', current)
            # Capture did not mutate application data. Once the complete point
            # is verified, ordinary startup must not require an unlock procedure.
            (STATE / 'transition.json').unlink()
            try:
                app = authority(execution, require_running=False)
                if app['spec']['running'] is True and app['spec']['replicas'] == 1:
                    s6(True, SERVICES)
                    current['resumed'] = True
            except Exception as error:
                current['resumptionError'] = str(error)
            save(STATE / 'capture.json', current)
        except Exception as error:
            if current.get('state') == 'Captured':
                # Losing completion bookkeeping does not undo a verified point.
                current['resumptionError'] = str(error)
                save(STATE / 'capture.json', current)
                raise
            intact = False
            if quiesced:
                try:
                    # Snapshot work only reads the source. Recheck native state
                    # after its failure before allowing ordinary operation.
                    assert_settled_state()
                    intact = True
                except Exception:
                    pass
            current.update(state='Failed', error=str(error), sourceIntact=intact)
            save(STATE / 'capture.json', current)
            if intact:
                (STATE / 'transition.json').unlink()
                try:
                    app = authority(execution, require_running=False)
                    if app['spec']['running'] is True and app['spec']['replicas'] == 1:
                        s6(True, SERVICES)
                        current['resumed'] = True
                except Exception as resume_error:
                    current['resumptionError'] = str(resume_error)
                save(STATE / 'capture.json', current)
            raise


def begin_capture(operation, execution, seconds):
    if not OP.fullmatch(operation) or not 1 <= seconds <= 86400:
        raise RuntimeError('Invalid capture request or deadline')
    with exclusive():
        app = authority(execution, operation)
        admitted = app.get('status', {}).get('backup', {})
        if admitted.get('captureOperation') != operation or admitted.get('execution') != execution:
            raise RuntimeError('Capture operation no longer has current admission')
        existing = load(STATE / 'capture.json')
        if existing and existing['operation'] == operation:
            return result(existing)
        observe()
        if existing and not (existing['state'] == 'Captured'
                             or (existing['state'] == 'Failed' and existing.get('sourceIntact'))):
            raise RuntimeError('Conflicting or unresolved capture')
        current = {'operation': operation, 'execution': execution, 'state': 'Capturing',
                   'startedAt': now(), 'resumed': False}
        save(STATE / 'transition.json', current)
        save(STATE / 'capture.json', current)
    # Admission is durable before handoff. The child must not race our flock.
    logpath = STAGING / ('capture-' + operation + '.log')
    with logpath.open('x') as log:
        os.chmod(logpath, 0o600)
        subprocess.Popen(['uv', 'run', '--no-project', 'python', __file__,
                          'capture', operation, execution, str(seconds)],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True, close_fds=True, cwd=SOURCE)
    return result(current)


def publish(operation):
    if not OP.fullmatch(operation):
        raise RuntimeError('Invalid capture operation')
    authority(publication=operation)
    directory = STAGING / 'captures' / operation
    manifest = verify_capture(directory)
    repo = repository_id()
    flags = [item for tag in tags() for item in ('--tag', tag)]
    def backup(label):
        output = restic('backup', '--json', *flags, '--tag', label, str(directory))
        summaries = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
        summary = next(x for x in summaries if x.get('message_type') == 'summary')
        snapshot_id = summary['snapshot_id']
        if not ID.fullmatch(snapshot_id):
            raise RuntimeError('Backup did not return a full snapshot identity')
        snapshot = json.loads(restic('cat', 'snapshot', snapshot_id))
        snapshot['id'] = snapshot_id
        return snapshot
    candidate = backup('candidate')
    # Full native readback proves bytes before any complete-tag point exists.
    verify_dir = Path('/tmp') / ('verify-' + str(uuid.uuid4()))
    verify_dir.mkdir(mode=0o700)
    selected_restore(candidate, verify_dir)
    authority(publication=operation)
    complete = backup('complete')
    if complete['tree'] != candidate['tree']:
        raise RuntimeError('Publication changed the verified capture tree')
    return result({'state': 'Published', 'operation': operation, 'repositoryID': repo,
                   'snapshotID': complete['id'], 'capturedAt': manifest['capturedAt'], 'publishedAt': now()})


def main():
    os.umask(0o077)
    name = sys.argv[1]
    if name == 'inspect':
        inspect()
    elif name in ('prepare', 'migrate'):
        prepare(name == 'migrate')
    elif name == 'gate':
        gate()
    elif name == 'status':
        status()
    elif name in ('begin-capture', 'capture'):
        fn = begin_capture if name == 'begin-capture' else capture
        fn(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    elif name == 'publish':
        publish(sys.argv[2])
    else:
        raise RuntimeError('Unknown finite native procedure')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr, flush=True)
        failure = {'state': 'Failed', 'error': str(error),
                   'operation': os.environ.get('BARTL_OPERATION', ''),
                   'applicationUID': os.environ.get('BARTL_UID', '')}
        if len(sys.argv) > 1 and sys.argv[1] == 'gate':
            failure['sticky'] = isinstance(error, (RuntimeError, json.JSONDecodeError)) or bool(load(STATE / 'transition.json'))
            save('/run/bartl-gate-error.json', failure)
        if os.environ.get('BARTL_OPERATION') or (len(sys.argv) > 1 and sys.argv[1] == 'gate'):
            Path('/dev/termination-log').write_text(json.dumps(failure))
        sys.exit(1)
