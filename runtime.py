#!/usr/bin/env python3
"""One Paperless lifecycle owner. The native image and its source remain untouched."""
import fcntl
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time

from urllib.parse import urlsplit
import psycopg
from psycopg import sql

STATE = Path('/state')
SETTINGS = json.loads(Path('/inputs/settings.json').read_text())
NATIVE_IMAGE = json.loads(Path('/opt/bartl/runtime-version.json').read_text())
NATIVE_PROFILES = json.loads(Path('/opt/bartl/native-profiles.json').read_text())
ALLOCATION = json.loads(Path('/inputs/allocation.json').read_text())
PASSWORD = Path('/secrets/db-password').read_text().strip()
APP_PASSWORD = secrets.token_urlsafe(64)
WRITE_ROLE = 'paperless_writer'
ACCEPTED = False
ACCEPTANCE = None
STOPPING = False
CHILDREN = []
CONNECTION = None
LOCK = None
DRAINING = False
ACTIVE = 0
ACTIVE_LOCK = threading.Lock()
OWNS_WRITER = False


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def emit(state, reason, **details):
    print(json.dumps({'state': state, 'reason': reason, **details}), flush=True)


def db():
    return psycopg.connect(host='paperless-db', dbname='bartl', user='bartl', password=PASSWORD, connect_timeout=5)


def query(statement, parameters=()):
    with CONNECTION.cursor() as cursor:
        cursor.execute(statement, parameters)
        return cursor.fetchall() if cursor.description else []


def native_env():
    env = {key: value for key, value in os.environ.items() if key.startswith('PAPERLESS_') or key in ('PATH', 'HOME', 'S6_READ_ONLY_ROOT')}
    env.update(PAPERLESS_DBUSER=WRITE_ROLE, PAPERLESS_DBPASS=APP_PASSWORD, HOME='/usr/src/paperless', USER_IS_NON_ROOT='1')
    # No superuser password, Kubernetes API token, lifecycle allocation, or authority files in native child.
    env.pop('PAPERLESS_SECRET_KEY_FILE', None)
    provider = {'openid_connect': {'APPS': [{'provider_id': SETTINGS['identity']['provider'], 'name': 'OIDC',
        'client_id': SETTINGS['identity']['client'], 'secret': Path('/secrets/client-secret').read_text().strip(),
        'settings': {'server_url': SETTINGS['identity']['issuer'], 'token_auth_method': 'client_secret_basic'}}]}}
    env['PAPERLESS_SOCIALACCOUNT_PROVIDERS'] = json.dumps(provider)
    return env


def as_native():
    os.setgroups([])
    os.setgid(1000)
    os.setuid(1000)


def native(*args, input=None, timeout=300):
    proc = subprocess.run(args, input=input, text=True, env=native_env(), cwd='/usr/src/paperless/src',
        preexec_fn=as_native, pass_fds=(LOCK.fileno(),), timeout=timeout, check=True)
    return proc
MIGRATION_GRAPH = None


def migration_graph():
    global MIGRATION_GRAPH
    if MIGRATION_GRAPH is None:
        code = ("from django.db.migrations.loader import MigrationLoader; "
                "import json; graph=MigrationLoader(None); disk=set(graph.disk_migrations); "
                "disk.update(item for migration in graph.disk_migrations.values() for item in (migration.replaces or [])); "
                "print('BARTL_MIGRATIONS='+json.dumps(sorted([list(item) for item in disk])))")
        result = subprocess.run(['python3', 'manage.py', 'shell', '-c', code], env=native_env(),
                                cwd='/usr/src/paperless/src', preexec_fn=as_native, pass_fds=(LOCK.fileno(),),
                                capture_output=True, text=True, timeout=60, check=True)
        rows = [line.removeprefix('BARTL_MIGRATIONS=') for line in result.stdout.splitlines()
                if line.startswith('BARTL_MIGRATIONS=')]
        require(len(rows) == 1, 'unreadable-native-migration-graph')
        MIGRATION_GRAPH = {tuple(item) for item in json.loads(rows[0])}
        require(len(MIGRATION_GRAPH) > 50, 'incomplete-native-migration-graph')
    return MIGRATION_GRAPH




def boundary():
    system = str(query('SELECT system_identifier FROM pg_control_system()')[0][0])
    oid, owner = query("SELECT d.oid::text, r.rolname FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba WHERE d.datname=current_database()")[0]
    version = query('SHOW server_version_num')[0][0]
    require(version == '170006' and owner == 'bartl', 'unsupported-database-boundary')
    return {'systemIdentifier': system, 'databaseOid': oid, 'database': 'bartl', 'owner': owner}


def qualified_schema(kind=None):
    profile = NATIVE_PROFILES.get('releases', {}).get(SETTINGS['versions']['paperless'], {})
    fresh = profile.get('schemaSha256')
    restored = profile.get('restoredSchemaSha256')
    require(NATIVE_PROFILES.get('format') == 1 and NATIVE_PROFILES.get('postgres') == '17.6'
            and profile.get('paperless') == SETTINGS['images']['paperless']
            and all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                    for value in (fresh, restored)), 'unqualified-native-schema-profile')
    return fresh if kind == 'fresh' else restored if kind == 'restored' else (fresh, restored)


def schema_fingerprint():
    # Named logical PostgreSQL catalogue footprint; never storage slots or live sequence values.
    statements = (
        "SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,cn.nspname,co.collname,pg_get_expr(d.adbin,d.adrelid) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v','m','f') ORDER BY c.relname COLLATE \"C\",a.attname COLLATE \"C\"",
        "SELECT c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.relispartition FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname COLLATE \"C\"",
        "SELECT c.relname,k.conname,pg_get_constraintdef(k.oid),k.convalidated FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname COLLATE \"C\",k.conname COLLATE \"C\"",
        "SELECT c.relname,pg_get_indexdef(i.indexrelid),i.indisvalid,i.indisready FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_index i ON i.indexrelid=c.oid WHERE n.nspname='public' ORDER BY c.relname COLLATE \"C\"",
        "SELECT c.relname,format_type(s.seqtypid,NULL),s.seqstart::text,s.seqincrement::text,s.seqmax::text,s.seqmin::text,s.seqcache::text,s.seqcycle FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_sequence s ON s.seqrelid=c.oid WHERE n.nspname='public' ORDER BY c.relname COLLATE \"C\"",
    )
    unsupported = (
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'",
        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal",
        "SELECT count(*) FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'",
        "SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'",
        "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' AND t.typtype<>'c' AND t.typelem=0",
        "SELECT (SELECT count(*) FROM pg_event_trigger)+(SELECT count(*) FROM pg_foreign_server)+(SELECT count(*) FROM pg_foreign_data_wrapper)+(SELECT count(*) FROM pg_publication)+(SELECT count(*) FROM pg_subscription)+(SELECT count(*) FROM pg_largeobject_metadata)",
    )
    require(all(query(statement)[0][0] == 0 for statement in unsupported), 'unsupported-native-catalogue-objects')
    return hashlib.sha256(json.dumps([query(item) for item in statements], default=str).encode()).hexdigest()




def observation(expected):
    files = [STATE / name for name in ('data', 'media', 'consume')]
    broker = Path('/broker')
    if any(path.is_symlink() or (path.exists() and not path.is_dir()) for path in files) or not broker.is_dir():
        return 'foreign', 'invalid-persistence-directory'
    # A new PostgreSQL database may contain only its standard extension and public schema.
    schemas = query("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE %s AND nspname <> 'information_schema'", ('pg_%',))
    extensions = query('SELECT extname FROM pg_extension')
    objects = query("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f')")
    extra = query("SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'")
    marker = STATE / 'lifecycle.json'
    owned_entries = {'lifecycle.lock', 'data', 'media', 'consume'}
    root_clean = all(entry.name in owned_entries for entry in STATE.iterdir())
    empty = root_clean and schemas == [('public',)] and extensions == [('plpgsql',)] and not objects and not extra
    empty = empty and not marker.exists() and all(not p.exists() or not any(p.iterdir()) for p in files)
    if expected['history'] == 'uninitialized':
        if not empty:
            return 'incomplete', 'unowned-or-partial-native-state'
        if (broker / 'lifecycle.json').exists():
            return 'foreign', 'foreign-broker-identity'
        if not query("SELECT 1 FROM pg_roles WHERE rolname=%s", (WRITE_ROLE,)):
            return 'empty', 'confirmed-owned-target-empty'
        return 'incomplete', 'writer-role-already-created'
    if empty or not marker.is_file() or not all(p.is_dir() for p in files):
        return 'incomplete', 'established-database-or-media-missing'
    consumed = STATE / 'initialization-consumed'
    if consumed.is_symlink() or not consumed.is_file() or consumed.read_text() != expected['installation']:
        return 'incomplete', 'missing-consumed-initialization-authority'
    retained = json.loads(marker.read_text())
    observed_schema = schema_fingerprint()
    if observed_schema not in qualified_schema() or retained.get('schema') != observed_schema:
        return 'incomplete', 'unqualified-or-damaged-native-schema'
    if retained.get('target') != expected['target'] or retained.get('installation') != expected['installation']:
        return 'foreign', 'installation-or-target-mismatch'
    if any(path.is_symlink() or not path.is_dir() or any(path.iterdir())
           for path in (root / ('.bartl-' + expected['installation']) for root in files)):
        return 'incomplete', 'missing-or-foreign-persistence-root'
    source = retained.get('release')
    target = SETTINGS['versions']['paperless']
    if (source, target) not in (('3.3.0', '3.3.0'), ('3.3.0', '3.3.1'), ('3.3.1', '3.3.1')):
        return 'incompatible', 'unsupported-native-release-transition'
    if schemas != [('public',)] or extensions != [('plpgsql',)]:
        return 'foreign', 'foreign-database-scope'
    tables = {row[0] for row in objects}
    if not {'django_migrations', 'documents_document', 'auth_user', 'auth_group'}.issubset(tables):
        return 'incomplete', 'missing-native-schema'
    columns = {row[0] for row in query("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='documents_document'")}
    if not {'id', 'title', 'checksum', 'archive_checksum', 'original_filename'}.issubset(columns):
        return 'incomplete', 'damaged-native-document-model'
    history = {(app, name) for app, name in query('SELECT app,name FROM django_migrations')}
    disk = migration_graph()
    if len(history) < 50 or history != disk:
        return 'incomplete', 'unknown-or-missing-native-migration-history'
    return 'valid', 'known-native-state'


def broker_quiescent():
    import redis
    client = redis.Redis.from_url(os.environ['PAPERLESS_REDIS'], socket_timeout=5)
    for name in client.scan_iter('*'):
        kind = client.type(name)
        if kind == b'set' and name.startswith(b'_kombu.binding.'):
            continue
        if kind == b'string' and name.startswith(b'celery-task-meta-'):
            continue
        if kind == b'string' and name in (b':1:treenode_list', b':1:treenode_dict'):
            continue
        if kind == b'string' and client.ttl(name) > 0 and (
                name.startswith(b':1:django.contrib.sessions.cached_db') or
                name.startswith(b':1:jwt:iss=') or
                re.fullmatch(rb':1:doc_[0-9]+_thumbnail_modified', name)):
            continue
        raise RuntimeError('broker-has-unsettled-or-unknown-work')
    require(not query("SELECT 1 FROM documents_paperlesstask WHERE status IN ('pending','started') LIMIT 1"),
            'native-tasks-unsettled-before-start')


def save_identity(target, installation):
    schema = schema_fingerprint()
    if ALLOCATION['mode'] == 'authorized':
        expected = qualified_schema('restored' if SETTINGS['intent'] == 'recovery' else 'fresh')
        require(schema == expected, 'native-schema-not-qualified')
    else:
        require(schema in qualified_schema(), 'native-schema-not-qualified')
    value = {'format': 2, 'target': target, 'installation': installation,
             'release': SETTINGS['versions']['paperless'], 'schema': schema}
    path = STATE / 'lifecycle.json'
    temp = STATE / ('lifecycle.' + secrets.token_hex(8))
    with temp.open('x') as handle:
        json.dump(value, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    directory = os.open(STATE, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def lock_owner():
    global LOCK, CONNECTION
    LOCK = (STATE / 'lifecycle.lock').open('a+')
    fcntl.flock(LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
    CONNECTION = db()
    CONNECTION.autocommit = True
    require(query('SELECT pg_try_advisory_lock(17490,72402)')[0][0], 'another-database-owner')


def fence_writer():
    roles = query('SELECT oid::text, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=%s', (WRITE_ROLE,))
    if not roles:
        require(ALLOCATION['mode'] == 'authorized', 'missing-independent-initialization-binding')
        query(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(
            sql.Identifier(WRITE_ROLE), sql.Literal(APP_PASSWORD)))
        query(sql.SQL('GRANT CONNECT ON DATABASE bartl TO {}').format(sql.Identifier(WRITE_ROLE)))
        query(sql.SQL('GRANT USAGE, CREATE ON SCHEMA public TO {}').format(sql.Identifier(WRITE_ROLE)))
        query(sql.SQL('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(WRITE_ROLE)))
        query(sql.SQL('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(WRITE_ROLE)))
        query(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE bartl IN SCHEMA public GRANT ALL ON TABLES TO {}').format(sql.Identifier(WRITE_ROLE)))
        query(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE bartl IN SCHEMA public GRANT ALL ON SEQUENCES TO {}').format(sql.Identifier(WRITE_ROLE)))
        roles = query('SELECT oid::text, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=%s', (WRITE_ROLE,))
    oid, _, superuser, createdb, createrole = roles[0]
    require(not (superuser or createdb or createrole) and
            (ALLOCATION['mode'] == 'authorized' or ALLOCATION.get('writerOid') == oid), 'foreign-writer-role')
    query(sql.SQL('ALTER ROLE {} NOLOGIN').format(sql.Identifier(WRITE_ROLE)))
    query('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename=%s AND pid<>pg_backend_pid()', (WRITE_ROLE,))
    require(query('SELECT count(*) FROM pg_stat_activity WHERE usename=%s', (WRITE_ROLE,))[0][0] == 0, 'previous-native-writer-active')
    return oid


def enable_writer():
    query(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(WRITE_ROLE), sql.Literal(APP_PASSWORD)))


def migrate():
    native('python3', 'manage.py', 'migrate', '--noinput', timeout=600)
    for name in ('index', 'scratch'):
        directory = STATE / 'data' / name
        directory.mkdir(exist_ok=True)
        os.chown(directory, 1000, 1000)
    native('python3', 'manage.py', 'document_index', 'reindex', '--if-needed', timeout=600)


def records(action):
    env = native_env()
    path = Path('/tmp/records-' + secrets.token_hex(12))
    path.write_bytes(Path('/secrets/records.json').read_bytes())
    os.chown(path, 1000, 1000)
    path.chmod(0o400)
    env.update(BARTL_RECORDS_ACTION=action, BARTL_RECORDS_SECRET=str(path))
    try:
        with open('/opt/bartl/records/profile.py') as source:
            subprocess.run(['python3', 'manage.py', 'shell'], stdin=source, env=env,
                           cwd='/usr/src/paperless/src', preexec_fn=as_native, pass_fds=(LOCK.fileno(),), timeout=300, check=True)
    finally:
        path.unlink()


def reconcile():
    env = native_env()
    secret = Path('/tmp/records-' + secrets.token_hex(12))
    secret.write_bytes(Path('/secrets/records.json').read_bytes())
    os.chown(secret, 1000, 1000)
    secret.chmod(0o400)
    state = STATE / 'data' / 'records-operations'
    require(not any(path.is_symlink() for path in (state, *state.parents)), 'invalid-records-operation-storage')
    state.mkdir(mode=0o700, exist_ok=True)
    os.chown(state, 1000, 1000)
    state.chmod(0o700)
    decisions = Path('/recovery/records-decisions.json')
    os.chown(decisions, 1000, 1000)
    decisions.chmod(0o400)
    env.update(BARTL_RECORDS_DECISIONS=str(decisions), BARTL_RECORDS_SECRET=str(secret),
               BARTL_RECORDS_STATE=str(state), BARTL_RECORDS_INSTALLATION=ALLOCATION['installation'])
    diagnostics = state / ('failure-' + secrets.token_hex(12))
    stdout_path = diagnostics.with_suffix('.stdout')
    stderr_path = diagnostics.with_suffix('.stderr')
    try:
        with stdout_path.open('x') as stdout, stderr_path.open('x') as stderr:
            stdout_path.chmod(0o600)
            stderr_path.chmod(0o600)
            with open('/opt/bartl/records/reconcile.py') as source:
                result = subprocess.run(['python3', 'manage.py', 'shell'], stdin=source, env=env,
                    cwd='/usr/src/paperless/src', preexec_fn=as_native, pass_fds=(LOCK.fileno(),),
                    stdout=stdout, stderr=stderr, text=True, check=False, timeout=600)
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
        require(result.returncode == 0,
                f'records-helper-failed:exit={result.returncode}:protected-diagnostics={diagnostics}')
        rows = [line for line in stdout_path.read_text().splitlines() if line.strip()]
        require(rows, 'missing-records-reconciliation-receipt')
        receipt = json.loads(rows[-1])
        require(receipt.get('state') == 'records-reconciled' and
                receipt.get('installation') == ALLOCATION['installation'] and
                receipt.get('decisionsDigest') == digest_file(decisions) and
                receipt.get('residueVerified') is True, 'invalid-records-reconciliation-receipt')
        sanity()
        emit('reconciled', 'approved-native-records-operations', generation=SETTINGS['generation'],
             installation=ALLOCATION['installation'], settingsDigest=digest_file(Path('/inputs/settings.json')),
             decisionsDigest=digest_file(decisions), receipt=receipt)
        stdout_path.unlink()
        stderr_path.unlink()
    finally:
        secret.unlink()



def sanity():
    native('python3', 'manage.py', 'check')
    native('python3', 'manage.py', 'document_llmindex', 'migrate')
    native('python3', 'manage.py', 'shell', '-c',
           'from documents.sanity_checker import check_sanity; result=check_sanity(); '
           'assert not result.has_error and not result.has_warning, "native-document-file-consistency-refused"', timeout=600)
    native('python3', 'manage.py', 'document_index', 'reindex', '--if-needed', timeout=600)
    records('check')


def acceptance():
    import urllib.request
    issuer = SETTINGS['identity']['issuer']
    with urllib.request.urlopen(issuer + '/.well-known/openid-configuration', timeout=5) as response:
        require(json.load(response).get('issuer') == issuer, 'foreign-oidc-issuer')
    for endpoint in ('http://tika:9998/version', 'http://gotenberg:3000/health'):
        with urllib.request.urlopen(endpoint, timeout=5) as response:
            require(response.status == 200, 'native-converter-unavailable')
    count = query('SELECT count(*) FROM documents_document')[0][0]
    credentials = json.loads(Path('/secrets/records.json').read_text())
    origin = urlsplit(SETTINGS['identity']['paperless'])
    for role in ('intake', 'capture', 'admin'):
        conn = http.client.HTTPConnection('127.0.0.1', 8000, timeout=3)
        try:
            conn.request('GET', '/api/documents/?page_size=1', headers={'Host': origin.netloc,
                         'X-Forwarded-Proto': origin.scheme,
                         'Authorization': 'Token ' + credentials[role]['token']})
            response = conn.getresponse()
            body = response.read()
            require(response.status == 200, 'native-authenticated-' + role + '-unavailable')
            result = json.loads(body)
            require(isinstance(result.get('count'), int) and isinstance(result.get('results'), list),
                    'native-documents-api-invalid')
        finally:
            conn.close()
    global ACCEPTANCE
    ACCEPTANCE = {'state': 'accepted', 'generation': SETTINGS['generation'],
                  'installation': ALLOCATION['installation'],
                  'version': SETTINGS['versions']['paperless'], 'documents': count}
    emit('accepted', 'native-authenticated-service-and-records-check', **{key: value for key, value in ACCEPTANCE.items() if key != 'state'})


class Gate(http.server.BaseHTTPRequestHandler):

    def do_request(self):
        global ACTIVE
        with ACTIVE_LOCK:
            if not ACCEPTED or STOPPING:
                self.send_error(503, 'Intake fenced')
                return
            if self.path == '/__bartl/acceptance':
                if self.client_address[0] != '127.0.0.1' or self.command != 'GET':
                    self.send_error(404)
                    return
                body = json.dumps(ACCEPTANCE).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            ACTIVE += 1
        try:
            if not self.path.startswith('/') or self.path.startswith('//') or len(self.headers.get_all('Content-Length', [])) > 1:
                self.send_error(400, 'Ambiguous request target or framing')
                return
            if self.headers.get('Transfer-Encoding'):
                self.send_error(501, 'Chunked request bodies are not supported')
                return
            length_text = self.headers.get('Content-Length')
            if length_text is None and self.command in ('POST', 'PUT', 'PATCH'):
                self.send_error(411, 'Content-Length required')
                return
            if length_text is not None and (not length_text.isdecimal() or int(length_text) < 0):
                self.send_error(400, 'Invalid Content-Length')
                return
            remaining = int(length_text or 0)
            external = urlsplit(SETTINGS['identity']['paperless'])
            hop = {'host', 'forwarded', 'x-forwarded-proto', 'x-forwarded-host', 'x-forwarded-port',
                   'x-forwarded-for', 'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
                   'te', 'trailer', 'transfer-encoding', 'upgrade'}
            hop.update(token.strip().lower() for value in self.headers.get_all('Connection', []) for token in value.split(','))
            headers = {key: value for key, value in self.headers.items() if key.lower() not in hop}
            headers.update(Host=external.netloc, **{'X-Forwarded-Proto': external.scheme,
                'X-Forwarded-Host': external.netloc,
                'X-Forwarded-Port': str(external.port or (443 if external.scheme == 'https' else 80)),
                'X-Forwarded-For': self.client_address[0]})
            conn = http.client.HTTPConnection('127.0.0.1', 8000, timeout=60)
            try:
                conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
                for key, value in headers.items():
                    conn.putheader(key, value)
                conn.endheaders()
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    require(chunk, 'short-request-body')
                    conn.send(chunk)
                    remaining -= len(chunk)
                response = conn.getresponse()
                self.send_response(response.status)
                response_hop = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}
                response_hop.update(token.strip().lower() for token in (response.getheader('Connection') or '').split(','))
                for key, value in response.getheaders():
                    if key.lower() not in response_hop:
                        self.send_header(key, value)
                self.end_headers()
                while chunk := response.read(65536):
                    self.wfile.write(chunk)
            finally:
                conn.close()
        finally:
            with ACTIVE_LOCK:
                ACTIVE -= 1

    do_GET = do_HEAD = do_OPTIONS = do_POST = do_PUT = do_PATCH = do_DELETE = do_request

    def log_message(self, *_):
        pass


def stop_native():
    for child in CHILDREN:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 30
    for child in CHILDREN:
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            continue
        os.killpg(child.pid, signal.SIGKILL)
        raise RuntimeError('native-process-group-survived-stop')


def serve():
    global ACCEPTED, STOPPING, DRAINING
    def terminate(*_):
        global STOPPING, ACCEPTED
        STOPPING = True
        ACCEPTED = False
        for child in CHILDREN:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    def drain(*_):
        global ACCEPTED, DRAINING
        ACCEPTED = False
        DRAINING = True
        Path('/state/drain-ready').unlink(missing_ok=True)
    signal.signal(signal.SIGUSR1, drain)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    sanity()
    base = native_env()
    web = dict(base, GRANIAN_HOST='127.0.0.1', GRANIAN_PORT='8000', GRANIAN_WORKERS='1')
    commands = (
        ('/usr/local/bin/granian', '--interface', 'asginl', '--ws', '--loop', 'uvloop', 'paperless.asgi:application'),
        ('/usr/local/bin/celery', '--app', 'paperless', 'worker', '--loglevel', 'INFO', '--without-mingle', '--without-gossip'),
        ('/usr/local/bin/celery', '--app', 'paperless', 'beat', '--loglevel', 'INFO'),
        ('python3', 'manage.py', 'document_consumer'),
    )
    server = None
    try:
        for index, command in enumerate(commands):
            CHILDREN.append(subprocess.Popen(command, env=web if index == 0 else base,
                cwd='/usr/src/paperless/src', preexec_fn=as_native, pass_fds=(LOCK.fileno(),), start_new_session=True))
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            require(not STOPPING and all(child.poll() is None for child in CHILDREN), 'native-process-exited')
            try:
                acceptance()
                break
            except (OSError, ConnectionError):
                time.sleep(2)
        else:
            raise RuntimeError('native-service-acceptance-timeout')
        server = http.server.ThreadingHTTPServer(('0.0.0.0', 8080), Gate)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        ACCEPTED = True
        while not STOPPING and all(child.poll() is None for child in CHILDREN):
            query('SELECT 1')
            if DRAINING and ACTIVE == 0 and not query(
                "SELECT 1 FROM documents_paperlesstask WHERE status IN ('pending','started') LIMIT 1"):
                Path('/state/drain-ready').write_text(ALLOCATION['installation'])
            time.sleep(2)
        require(STOPPING, 'native-process-exited-unexpectedly')
    finally:
        STOPPING = True
        ACCEPTED = False
        if server:
            server.shutdown()
        stop_native()


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def payload():
    root = Path('/recovery/payload')
    required = ('database.dump', 'files.tar', 'manifest.json', 'SHA256SUMS')
    require(root.is_dir() and all((root / name).is_file() for name in required), 'missing-recovery-inventory')
    lines = (root / 'SHA256SUMS').read_text().splitlines()
    require(len(lines) == 3, 'invalid-recovery-inventory')
    names = []
    for line in lines:
        digest, separator, name = line.partition('  ')
        require(separator and name in required[:-1] and len(digest) == 64 and
                digest_file(root / name) == digest, 'invalid-recovery-checksum')
        names.append(name)
    require(set(names) == set(required[:-1]), 'incomplete-recovery-inventory')
    manifest = json.loads((root / 'manifest.json').read_text())
    require(manifest['format'] == 2 and manifest['service'] == 'paperless' and
            manifest['identity'] == SETTINGS['identity'] and manifest['initialization'] == SETTINGS['initialization'],
            'foreign-recovery-identity')
    require((manifest['version'], SETTINGS['versions']['paperless']) in
            (('3.3.0', '3.3.0'), ('3.3.0', '3.3.1'), ('3.3.1', '3.3.1')), 'unsupported-recovery-transition')
    require(manifest['images']['postgres'] == SETTINGS['images']['postgres'] and
            manifest['images']['redis'] == SETTINGS['images']['redis'] and
            manifest['images']['paperless'] in (
                'ghcr.io/paperless-ngx/paperless-ngx@sha256:6b94799bc769a063b3340cc5847402e626d4d91d29a295a8e747f8e9bead4207',
                'ghcr.io/paperless-ngx/paperless-ngx@sha256:cb91bfb468e63025a9d10c01b54c33665113668eee61b490db96de19b860b9c4'),
            'foreign-recovery-image-set')
    return root, manifest


def restore(target, oid):
    import tarfile
    root, manifest = payload()
    installation = manifest['installation']
    require(installation == ALLOCATION['installation'], 'selected-installation-identity-mismatch')
    with tarfile.open(root / 'files.tar') as archive:
        entries = archive.getmembers()
        require(entries and all(not member.issym() and not member.islnk() and not member.isdev() and
                member.name.split('/')[0] in ('data', 'media', 'consume', 'broker') and
                '..' not in Path(member.name).parts for member in entries), 'unsafe-files-inventory')
        require({member.name for member in entries if member.isdir() and '/' not in member.name.rstrip('/')} == {'data', 'media', 'consume', 'broker'}, 'incomplete-files-roots')
        stage = STATE / 'restore-staging'
        stage.mkdir(mode=0o700)
        archive.extractall(stage, filter='data')
        # The data extraction filter intentionally ignores directory modes.
        # Reapply only ordinary archived permission bits after validating paths.
        for member in entries:
            if member.isdir():
                (stage / member.name).chmod(member.mode & 0o777)
        # A failed restore is deliberately not automatically overwritten. The target remains isolated.
        enable_writer()
        env = {'PGHOST': 'paperless-db', 'PGDATABASE': 'bartl', 'PGUSER': WRITE_ROLE,
               'PGPASSWORD': APP_PASSWORD, 'PATH': os.environ['PATH']}
        subprocess.run(['/usr/lib/postgresql/17/bin/pg_restore', '--list', str(root / 'database.dump')],
                       stdout=subprocess.DEVNULL, env=env, pass_fds=(LOCK.fileno(),), check=True, timeout=60)
        subprocess.run(['/usr/lib/postgresql/17/bin/pg_restore', '--single-transaction', '--exit-on-error', '--no-owner',
                        '--no-acl', '-d', 'bartl', str(root / 'database.dump')], env=env, pass_fds=(LOCK.fileno(),), check=True, timeout=600)
        require(schema_fingerprint() == qualified_schema('restored'), 'foreign-restored-native-schema')
        require({(app, name) for app, name in query('SELECT app,name FROM django_migrations')} == migration_graph(),
                'foreign-or-incomplete-restored-migration-history')
        import shutil
        for name in ('data', 'media', 'consume'):
            shutil.copytree(stage / name, STATE / name, dirs_exist_ok=True)
        (stage / 'broker').replace(STATE / 'broker')
        shutil.rmtree(stage)
    require((STATE / 'broker').is_dir() and not any(Path('/broker').iterdir()), 'invalid-recovered-broker-state')
    for item in (STATE / 'broker').iterdir():
        if item.is_dir():
            shutil.copytree(item, Path('/broker') / item.name)
        else:
            shutil.copy2(item, Path('/broker') / item.name)
    shutil.rmtree(STATE / 'broker')
    for parent, directories, files in os.walk('/broker'):
        os.chown(parent, 999, 999)
        for entry in files:
            os.chown(Path(parent) / entry, 999, 999)
    for name in ('data', 'media', 'consume'):
        root_dir = STATE / name
        require(root_dir.is_dir(), 'missing-restored-media-directory')
        for parent, directories, files in os.walk(root_dir):
            os.chown(parent, 1000, 1000)
            for entry in files:
                os.chown(Path(parent) / entry, 1000, 1000)
    require({(app, name) for app, name in query('SELECT app,name FROM django_migrations')} == migration_graph(),
            'foreign-or-incomplete-restored-migration-history')
    sanity()
    require({(app, name) for app, name in query('SELECT app,name FROM django_migrations')} == migration_graph(),
            'restored-native-migrations-incomplete')
    save_identity(target, installation)
    emit('provisioned', 'selected-native-restore-complete', allocation={'format': 1, 'mode': 'bound',
         'generation': SETTINGS['generation'], 'target': target, 'writerOid': oid,
         'installation': installation})


def capture():
    import tarfile
    require(ALLOCATION['mode'] == 'bound', 'unbound-capture')
    require(not query("SELECT 1 FROM documents_paperlesstask WHERE status IN ('pending','started') LIMIT 1"),
            'unsettled-native-task')
    root = Path('/recovery/capture')
    root.mkdir(mode=0o700)
    require(not any(root.iterdir()), 'capture-destination-not-empty')
    env = {'PGHOST': 'paperless-db', 'PGDATABASE': 'bartl', 'PGUSER': 'bartl',
           'PGPASSWORD': PASSWORD, 'PATH': os.environ['PATH']}
    with (root / 'database.dump').open('xb') as target:
        subprocess.run(['/usr/lib/postgresql/17/bin/pg_dump', '-Fc', '-d', 'bartl'],
                       env=env, stdout=target, pass_fds=(LOCK.fileno(),), check=True, timeout=600)
    with tarfile.open(root / 'files.tar', 'w') as archive:
        for name in ('data', 'media', 'consume'):
            archive.add(STATE / name, arcname=name)
        archive.add(Path('/broker'), arcname='broker')
    manifest = {'format': 2, 'stateFormat': 1, 'service': 'paperless',
                'version': SETTINGS['versions']['paperless'], 'images': SETTINGS['images'],
                'generation': SETTINGS['generation'], 'installation': ALLOCATION['installation'],
                'identity': SETTINGS['identity'], 'initialization': SETTINGS['initialization']}
    (root / 'manifest.json').write_text(json.dumps(manifest) + '\n')
    with (root / 'SHA256SUMS').open('x') as inventory:
        for name in ('database.dump', 'files.tar', 'manifest.json'):
            inventory.write(f'{digest_file(root / name)}  {name}\n')
    emit('captured', 'sealed-native-state', installation=ALLOCATION['installation'])


def main():
    global OWNS_WRITER
    require(SETTINGS['intent'] in ('fresh', 'recovery'), 'invalid-authority')
    require(ALLOCATION['format'] == 1 and ALLOCATION['generation'] == SETTINGS['generation'], 'invalid-allocation')
    require(NATIVE_IMAGE == {'version': SETTINGS['versions']['paperless'],
            'paperless': SETTINGS['images']['paperless'], 'postgres': SETTINGS['images']['postgres']},
            'derived-native-image-mismatch')
    qualified_schema()
    mode = ALLOCATION['mode']
    require(mode in ('new', 'authorized', 'bound'), 'invalid-target-authority')
    lock_owner()
    actual = boundary()
    if mode == 'new':
        require(not ALLOCATION.get('target') and sys.argv[1:] == ['observe'], 'target-not-yet-authorized')
    else:
        require(ALLOCATION.get('target') == actual, 'foreign-physical-target')
        require(isinstance(ALLOCATION.get('installation'), str) and
                len(ALLOCATION['installation']) == 32, 'missing-independent-installation-identity')
    state, reason = observation({'target': actual, 'history': 'established' if mode == 'bound' else 'uninitialized',
                                 'installation': ALLOCATION.get('installation')})
    emit(state, reason, target=actual)
    if mode == 'new':
        require(state == 'empty', 'fresh-target-not-empty')
        if SETTINGS['intent'] == 'fresh':
            import redis
            require(redis.Redis.from_url(os.environ['PAPERLESS_REDIS']).dbsize() == 0,
                    'new-broker-contains-work')
        else:
            require(not any(Path('/broker').iterdir()), 'recovery-broker-not-empty')
        emit('observed', 'empty-physical-target', target=actual)
        return
    if mode == 'authorized':
        require(state == 'empty', f'initialization-refused:{reason}')
        if SETTINGS['intent'] == 'fresh':
            import redis
            require(redis.Redis.from_url(os.environ['PAPERLESS_REDIS']).dbsize() == 0,
                    'new-broker-contains-work')
            require(sys.argv[1:] == ['provision'], 'fresh-provision-only')
        else:
            require(not any(Path('/broker').iterdir()) and sys.argv[1:] == ['restore'],
                    'restore-requires-empty-broker-and-selected-payload')
            payload()
        with (STATE / "initialization-consumed").open("x") as consumed:
            consumed.write(ALLOCATION["installation"])
            consumed.flush()
            os.fsync(consumed.fileno())
        directory = os.open(STATE, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        oid = fence_writer()
        OWNS_WRITER = True
        if SETTINGS['intent'] == 'recovery':
            restore(actual, oid)
            return
        for name in ('data', 'media', 'consume'):
            path = STATE / name
            path.mkdir(exist_ok=True)
            os.chown(path, 1000, 1000)
        for relative in ('media/documents', 'media/documents/originals', 'media/documents/thumbnails'):
            directory = STATE / relative
            directory.mkdir(exist_ok=True)
            os.chown(directory, 1000, 1000)
        enable_writer()
        migrate()
        records('initialize')
        installation = ALLOCATION['installation']
        for root in (STATE / name for name in ('data', 'media', 'consume')):
            identity = root / ('.bartl-' + installation)
            identity.mkdir(mode=0o700)
            os.chown(identity, 1000, 1000)
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        Path('/broker/lifecycle.json').write_text(json.dumps({'installation': installation}))
        save_identity(actual, installation)
        emit('provisioned', 'native-initialization-complete', allocation={'format': 1, 'mode': 'bound',
             'generation': SETTINGS['generation'], 'target': actual, 'writerOid': oid,
             'installation': installation})
        return
    require(state == 'valid', f'state-refused:{reason}')
    broker_identity = Path('/broker/lifecycle.json')
    require(broker_identity.is_file() and
            json.loads(broker_identity.read_text()) == {'installation': ALLOCATION['installation']},
            'missing-or-foreign-broker-history')
    if sys.argv[1:] == ['serve']:
        broker_quiescent()
    oid = fence_writer()
    OWNS_WRITER = True
    require(ALLOCATION['writerOid'] == oid, 'writer-identity-mismatch')
    if sys.argv[1:] == ['capture']:
        enable_writer()
        sanity()
        capture()
        return
    if sys.argv[1:] == ["reconcile"]:
        enable_writer()
        reconcile()
        return
    require(sys.argv[1:] == ['serve'], 'unsupported-transition')
    enable_writer()
    source = json.loads((STATE / 'lifecycle.json').read_text())['release']
    if source != SETTINGS['versions']['paperless']:
        sanity()
        require({(app, name) for app, name in query('SELECT app,name FROM django_migrations')} == migration_graph(),
                'native-migration-incomplete')
        save_identity(actual, ALLOCATION['installation'])
    records('check')
    serve()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        emit('refused', str(error))
        sys.exit(4)
    finally:
        shutdown_error = None
        if CONNECTION:
            try:
                if OWNS_WRITER:
                    query(sql.SQL('ALTER ROLE {} NOLOGIN').format(sql.Identifier(WRITE_ROLE)))
                    query('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename=%s AND pid<>pg_backend_pid()', (WRITE_ROLE,))
                    require(query('SELECT count(*) FROM pg_stat_activity WHERE usename=%s', (WRITE_ROLE,))[0][0] == 0,
                            'native-writer-still-active')
            except Exception as error:
                shutdown_error = str(error)
            finally:
                CONNECTION.close()
        if LOCK:
            LOCK.close()
        if shutdown_error:
            emit('refused', 'shutdown-writer-fence-failed', detail=shutdown_error)
            raise SystemExit(4)
