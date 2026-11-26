#!/usr/bin/env node
// Offline package behavior: no cluster, registry, credentials or installation tooling.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const chart = process.env.PAPERLESS_CHART || fileURLToPath(new URL('../chart', import.meta.url));
const helm = process.env.HELM || 'helm';
const yq = process.env.YQ || 'yq';
function render(values, {mode = 'deployment', release = 'paperless', namespace = 'default', deployment, inspectIngress = false} = {}) {
  const args = ['template', release, chart, '-n', namespace, '-f', '-', '--set-string', `renderMode=${mode}`];
  if (deployment) args.push('--set-string', `deployment=${deployment}`);
  if (inspectIngress) args.push('--set', `operations.deployments.${deployment}.ingressEnabled=true`);
  return spawnSync(helm, args, {
    input: JSON.stringify(values), encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
  });
}
function documents(result) {
  assert.equal(result.status, 0, result.stderr);
  const parsed = spawnSync(yq, ['-o=json', '-I=0', '.'], {input: result.stdout, encoding: 'utf8'});
  assert.equal(parsed.status, 0, parsed.stderr);
  return parsed.stdout.trim().split('\n').filter(Boolean).map(JSON.parse).filter(Boolean);
}
const base = () => ({installation: 'acme', dns: {root: 'acme.example'}, services: {paperless: {}}});
const selected = v => v.services[v.instance || 'paperless'];
function deployment(v) {
  const docs = documents(render(v));
  const app = docs.find(d => d.kind === 'PaperlessApplication');
  assert.ok(app);
  assert.equal(app.apiVersion, 'paperless.bartl.sh/v1alpha2');
  assert.equal(Object.hasOwn(app.spec, 'running'), false);
  assert.equal(Object.hasOwn(app.spec, 'replicas'), false);
  return {spec: app.spec, docs};
}
function declaration(v, options) { return documents(render(v, {mode: 'connections', release: 'offline', ...options}))[0]; }
function configuration(v, options) { return documents(render(v, {mode: 'configuration', release: 'offline', ...options}))[0].configuration[v.instance || v.deployments?.[options?.deployment]?.instance || 'paperless']; }
function rejects(v, options) { assert.notEqual(render(v, options).status, 0, 'invalid inputs rendered successfully'); }
let checks = 0;
function check(name, fn) { fn(); checks++; console.log('PASS ' + name); }

check('one shared file selects only the independent Paperless release', () => {
  const v = base(); v.services.keycloak = {foreign: ['ignored']}; v.infrastructure = {anything: true};
  v.resolved = {oidc: {bindings: {keycloak: 'ignored'}}};
  const {spec, docs} = deployment(v);
  assert.deepEqual(spec.identity, {installation: 'acme', instance: 'paperless'});
  assert.deepEqual(spec.backup, {});
  assert.equal(spec.ingress.host, 'paperless.acme.example');
  assert.equal(spec.ingress.enabled, true);
  assert.equal(docs.some(d => d.kind === 'Secret'), false);
});
check('optional client CA binding is separate from environment configuration', () => {
  const v = base();
  for (const secretName of ['paperless-configuration', 'selected-config']) {
    if (secretName !== 'paperless-configuration') selected(v).configurationSecret = secretName;
    const d = declaration(v);
    assert.deepEqual(d.credentials.bindings.paperless.clientCA, {secretName: `${secretName}-client-ca`, key: 'ca-bundle.pem'});
    assert.deepEqual(d.credentials.requirements.paperless.clientCA, {sources: ['external', 'recovered'], keys: ['ca-bundle.pem'], requiredFor: ['customClientTrust']});
    assert.equal(deployment(v).spec.configurationSecret, secretName);
    const config = configuration(v);
    assert.equal(config.secretName, secretName);
    assert.equal('REQUESTS_CA_BUNDLE' in config.environment, false);
    assert.equal('ca-bundle.pem' in config.environment, false);
  }
});
check('custom instance and static map overrides preserve explicit false', () => {
  const v = base(); v.instance = 'records'; v.services = {paperless: 'unselected', records: {claims: {storage: 'records-data'}, ingress: {enabled: false}, images: {redis: 'example.org/redis@sha256:abc'}, controller: {imagePullPolicy: 'Always'}}};
  const {spec, docs} = deployment(v);
  assert.equal(spec.identity.instance, 'records');
  assert.equal(spec.claims.storage, 'records-data'); assert.equal(spec.claims.database, 'paperless-db');
  assert.equal(spec.images.redis, 'example.org/redis@sha256:abc'); assert.ok(spec.images.postgres);
  assert.equal(docs.find(d => d.kind === 'Deployment').spec.template.spec.containers[0].imagePullPolicy, 'Always');
  assert.equal(spec.ingress.enabled, false);
  assert.equal(configuration(v).environment.PAPERLESS_URL, 'https://paperless.acme.example');
});
check('all modes derive current hostname and honor explicit override', () => {
  const v = base(); selected(v).hostname = 'records.example'; v.dns.root = 'new.example';
  for (const hostname of ['records.example', 'paperless.new.example']) {
    assert.equal(deployment(v).spec.ingress.host, hostname);
    assert.equal(declaration(v).services.paperless.endpoints.https.url, `https://${hostname}`);
    assert.equal(configuration(v).environment.PAPERLESS_URL, `https://${hostname}`);
    delete selected(v).hostname;
  }
  delete v.dns; rejects(v); selected(v).hostname = 'records.example'; deployment(v);
});
check('managed TLS remains when ingress is disabled and external TLS opts out', () => {
  const v = base(); selected(v).ingress = {enabled: false, className: 'edge', tlsSecret: 'records-tls'};
  selected(v).tls = {acmeServer: 'https://acme-staging-v02.api.letsencrypt.org/directory'};
  const {docs} = deployment(v);
  const cert = docs.find(d => d.kind === 'Certificate'); const issuer = docs.find(d => d.kind === 'Issuer');
  assert.deepEqual(cert.spec.dnsNames, ['paperless.acme.example']); assert.equal(cert.spec.secretName, 'records-tls');
  assert.equal(cert.spec.issuerRef.name, issuer.metadata.name);
  assert.equal(issuer.spec.acme.solvers[0].http01.ingress.ingressClassName, 'edge');
  assert.equal(issuer.spec.acme.server, selected(v).tls.acmeServer);
  assert.deepEqual(declaration(v).credentials.requirements.paperless.tls.sources, ['cert-manager']);
  selected(v).tls.managed = false;
  assert.equal(deployment(v).docs.some(d => ['Certificate', 'Issuer'].includes(d.kind)), false);
  selected(v).ingress.enabled = true;
  assert.deepEqual(declaration(v).credentials.requirements.paperless.tls.sources, ['external', 'recovered']);
  selected(v).ingress.tlsSecret = ''; rejects(v);
  selected(v).ingress.enabled = false; deployment(v);
  selected(v).tls.managed = true; rejects(v);
});
check('offline declarations expose unresolved provider requirements and no resources', () => {
  const v = base(); selected(v).identityProvider = 'accounts'; selected(v).backup = {endpoint: 'archive'};
  const docs = documents(render(v, {mode: 'connections', release: 'offline'})); assert.equal(docs.length, 1);
  const d = docs[0]; assert.equal(d.kind, undefined);
  assert.deepEqual(d.oidc.requests.paperless.redirectUris, ['https://paperless.acme.example/accounts/oidc/keycloak/login/callback/']);
  assert.deepEqual(d.oidc.requests.paperless.webOrigins, ['https://paperless.acme.example']);
  assert.equal(d.oidc.requests.paperless.provider, 'accounts'); assert.equal(d.oidc.requests.paperless.clientId, 'paperless');
  assert.equal(d.backup.requests.paperless.endpoint, 'archive');
  assert.equal(d.credentials.bindings.paperless.oidc.secretName, 'paperless-configuration');
  assert.equal(d.storage.claims.paperless.staging.claimName, 'paperless-staging');
  rejects(v); rejects(v, {mode: 'configuration'});
});
check('resolved provider and standalone external OIDC map to native nonsecret configuration', () => {
  const v = base(); selected(v).identityProvider = 'accounts';
  v.resolved = {oidc: {bindings: {paperless: {provider: 'accounts', issuer: 'https://login.example/realms/acme'}, other: 'ignored'}}};
  deployment(v);
  let config = configuration(v); assert.equal(config.secretName, 'paperless-configuration');
  const native = JSON.parse(config.environment.PAPERLESS_SOCIALACCOUNT_PROVIDERS).openid_connect;
  assert.deepEqual(native.SCOPE, ['openid', 'profile', 'email']); assert.equal(native.OAUTH_PKCE_ENABLED, true);
  assert.deepEqual(native.APPS, [{provider_id: 'keycloak', name: 'Keycloak', client_id: 'paperless', settings: {server_url: 'https://login.example/realms/acme'}}]);
  assert.equal(config.environment.PAPERLESS_APPS, 'allauth.socialaccount.providers.openid_connect');
  assert.equal(config.oidc.clientSecretRequired, true); assert.equal('secret' in native.APPS[0], false);
  delete selected(v).identityProvider; delete v.resolved;
  selected(v).oidc = {issuer: 'https://external.example/issuer', clientId: 'documents', providerId: 'external', name: 'External Identity'};
  config = configuration(v); const app = JSON.parse(config.environment.PAPERLESS_SOCIALACCOUNT_PROVIDERS).openid_connect.APPS[0];
  assert.equal(app.client_id, 'documents'); assert.equal(app.provider_id, 'external'); assert.equal(app.name, 'External Identity');
  assert.equal(app.settings.server_url, 'https://external.example/issuer'); deployment(v);
  assert.deepEqual(declaration(v).oidc.requests.paperless.redirectUris, ['https://paperless.acme.example/accounts/oidc/external/login/callback/']);
});
check('OIDC provider mismatch, missing issuer and plaintext credential inputs fail', () => {
  const v = base(); selected(v).identityProvider = 'accounts';
  v.resolved = {oidc: {bindings: {paperless: {provider: 'wrong', issuer: 'https://login.example/realm'}}}};
  rejects(v); rejects(v, {mode: 'configuration'});
  v.resolved.oidc.bindings.paperless.provider = 'accounts'; v.resolved.oidc.bindings.paperless.clientId = 'wrong'; rejects(v);
  delete v.resolved.oidc.bindings.paperless.clientId; v.resolved.oidc.bindings.paperless.clientSecretFile = '/protected/secret'; rejects(v);
  delete selected(v).identityProvider; delete v.resolved; selected(v).oidc = {}; rejects(v, {mode: 'connections'});
  selected(v).oidc = {issuer: 'https://issuer.example', secret: 'plaintext'}; rejects(v);
});
check('backup eligibility does not activate an unbound deployment and explicit opt-out wins', () => {
  const v = base();
  const eligible = declaration(v);
  assert.equal(eligible.backup.requests.paperless.enabled, true);
  assert.equal(eligible.backup.requests.paperless.repository, undefined);
  assert.deepEqual(eligible.credentials.requirements.paperless.backupReader.keys, ['password', 'username', 'restPassword']);
  assert.deepEqual(deployment(v).spec.backup, {});
  selected(v).backup = {enabled: false};
  v.resolved = {backup: {bindings: {paperless: {repository: 'rest:https://old.example/paperless/'}}}};
  const disabled = declaration(v);
  assert.deepEqual(disabled.backup.requests.paperless, {enabled: false});
  assert.equal(disabled.credentials.bindings.paperless.backupReader, undefined);
  assert.equal(disabled.credentials.requirements.paperless.backupWriter, undefined);
  assert.deepEqual(deployment(v).spec.backup, {});
});
check('external and resolved backup map unchanged controller API and disabled backup is empty', () => {
  const v = base(); selected(v).backup = {repository: 'rest:https://backup.example/paperless/', schedule: '0 3 * * *', timeZone: 'Europe/Berlin', drainSeconds: 600};
  let backup = deployment(v).spec.backup;
  assert.deepEqual(backup, {repository: 'rest:https://backup.example/paperless/', readerSecret: 'paperless-backup-reader', writerSecret: 'paperless-backup-writer', schedule: '0 3 * * *', timeZone: 'Europe/Berlin', drainSeconds: 600});
  configuration(v);
  selected(v).backup = {endpoint: 'archive'};
  v.resolved = {backup: {bindings: {paperless: {endpoint: 'archive', repository: 'rest:https://archive.example/paperless/', readerSecret: 'rest-reader', writerSecret: 'rest-writer'}, other: 'ignored'}}};
  backup = deployment(v).spec.backup; assert.equal(backup.repository, 'rest:https://archive.example/paperless/');
  assert.equal(backup.readerSecret, 'rest-reader'); assert.equal(backup.schedule, ''); assert.equal(backup.enabled, undefined); assert.equal(backup.endpoint, undefined);
  selected(v).backup.readerSecret = 'custom-reader'; assert.equal(deployment(v).spec.backup.readerSecret, 'custom-reader');
  selected(v).backup.enabled = false; assert.deepEqual(deployment(v).spec.backup, {});
  assert.equal(declaration(v).backup.requests.paperless.enabled, false);
  assert.equal(declaration(v).credentials.requirements.paperless.backupReader, undefined);
  delete selected(v).backup; v.resolved.backup.bindings.paperless = {enabled: false}; assert.deepEqual(deployment(v).spec.backup, {});
});
check('unresolved, conflicting and unsafe backup inputs fail at rendering boundary', () => {
  const v = base(); selected(v).backup = {endpoint: 'archive'}; rejects(v);
  v.resolved = {backup: {bindings: {paperless: {endpoint: 'different', repository: 'rest:https://backup.example/paperless/'}}}}; rejects(v);
  v.resolved.backup.bindings.paperless.endpoint = 'archive'; delete v.resolved.backup.bindings.paperless.repository; rejects(v);
  selected(v).backup = {enabled: true}; delete v.resolved; rejects(v);
  selected(v).backup = {repository: 'rest:https://user:password@backup.example/paperless/'}; rejects(v);
  selected(v).backup = {repository: 'rest:https://backup.example/paperless/', endpoint: 'archive'}; rejects(v, {mode: 'connections'});
});
check('release name guard applies only to deployment and selected chart release is enforced', () => {
  const v = base(); selected(v).release = '0.3.0-dev.1'; deployment(v); declaration(v); configuration(v);
  rejects(v, {release: 'other'});
  selected(v).release = '0.2.0'; for (const mode of ['deployment', 'connections', 'configuration']) rejects(v, {mode});
});
check('selected deployments apply only their own static routing without runtime intent', () => {
  const v = base();
  v.services = {paperless: {ingress: {enabled: true}}, records: {
    ingress: {enabled: false}, oidc: {issuer: 'https://id.example/realms/acme'},
    backup: {repository: 'rest:https://backup.example/records/'}}
  };
  v.deployments = {
    source: {instance: 'records', cluster: 'cluster-1', namespace: 'blue', release: 'paperless', package: 'records'},
    target: {instance: 'records', cluster: 'cluster-2', namespace: 'green', release: 'paperless', package: 'records'},
    other: {instance: 'paperless', cluster: 'cluster-3', namespace: 'other', release: 'paperless', package: 'other'}
  };
  v.packages = {records: {version: '0.3.0-dev.1', chart: 'oci://ghcr.io/bartlapp/bartl-paperless'}, other: {version: '0.1.0', chart: 'irrelevant'}};
  v.operations = {deployments: {source: {ingressEnabled: false}, target: {ingressEnabled: true}, other: {foreign: 'ignored'}}};
  for (const [id, namespace, ingressEnabled] of [['source', 'blue', false], ['target', 'green', true]]) {
    const options = {namespace, deployment: id};
    const docs = documents(render(v, options));
    const app = docs.find(d => d.kind === 'PaperlessApplication');
    assert.deepEqual(app.spec.identity, {installation: 'acme', instance: 'records'});
    assert.equal(app.apiVersion, 'paperless.bartl.sh/v1alpha2');
    assert.equal(app.spec.version, '3.3.1');
    assert.equal(Object.hasOwn(app.spec, 'running'), false);
    assert.equal(Object.hasOwn(app.spec, 'replicas'), false);
    assert.equal(app.spec.ingress.enabled, ingressEnabled);
    const connections = declaration(v, {...options, release: 'paperless'});
    assert.equal(connections.services.records.endpoints.https.ingressEnabled, ingressEnabled);
    assert.equal(connections.oidc.requests.records.clientId, 'records');
    assert.equal(connections.backup.requests.records.repository, 'rest:https://backup.example/records/');
    assert.equal(configuration(v, {...options, release: 'paperless'}).environment.PAPERLESS_URL, 'https://paperless.acme.example');
  }
  v.operations.deployments.source = {};
  assert.equal(declaration(v, {namespace: 'blue', release: 'paperless', deployment: 'source'}).services.records.endpoints.https.ingressEnabled, false);
  const inspection = documents(render(v, {mode: 'connections', namespace: 'blue', deployment: 'source', inspectIngress: true}))[0];
  assert.equal(inspection.services.records.endpoints.https.ingressEnabled, true);
  assert.equal(declaration(v, {namespace: 'blue', release: 'paperless', deployment: 'source'}).services.records.endpoints.https.ingressEnabled, false);
});
check('deployment selection rejects wrong target, version, conflict and invalid selected intent', () => {
  const v = base();
  v.deployments = {blue: {instance: 'paperless', cluster: 'cluster-1', namespace: 'blue', release: 'paperless', package: 'paperless'}};
  v.packages = {paperless: {version: '0.3.0-dev.1', chart: 'oci://ghcr.io/bartlapp/bartl-paperless'}};
  const options = {namespace: 'blue', deployment: 'blue'};
  for (const mode of ['deployment', 'connections', 'configuration']) documents(render(v, {...options, mode}));
  for (const mode of ['deployment', 'connections', 'configuration']) {
    rejects(v, {...options, mode, namespace: 'wrong'});
    rejects(v, {...options, mode, release: 'wrong'});
    v.packages.paperless.version = '0.2.0'; rejects(v, {...options, mode});
    v.packages.paperless.version = '0.3.0-dev.1';
  }
  v.packages.paperless.version = '0.3.0-dev.1'; v.instance = 'other'; rejects(v, options);
  delete v.instance;
  for (const intent of [{running: true}, {running: false}, {replicas: 0}, {replicas: 1}, {version: '3.3.0'}, {version: '3.3.1'}]) {
    v.operations = {deployments: {blue: intent}};
    for (const mode of ['deployment', 'connections', 'configuration']) rejects(v, {...options, mode});
  }
  v.operations.deployments.blue = {ingressEnabled: 'false'}; rejects(v, options);
  v.operations.deployments.blue = {version: '3.4.0'}; rejects(v, options);
  v.operations.deployments.blue = {}; v.deployments.blue.instance = 'missing'; rejects(v, options);
  v.deployments.blue.instance = 'paperless'; delete v.packages.paperless; rejects(v, options);
  delete v.deployments.blue; rejects(v, options);
});
check('strict selected interface rejects flat legacy inputs, unknown fields and invalid values', () => {
  for (const [key, value] of Object.entries({identity: {}, running: false, replicas: 1, version: '3.3.1', images: {}, controller: {}, claims: {}, configurationSecret: 'secret', bootstrapSecret: '', ingress: {}, backup: {repository: 'rest:https://backup.example/paperless/'}})) {
    const v = base(); v[key] = value; rejects(v);
  }
  for (const service of [false, [], 'invalid', {unknown: true}, {running: true}, {running: false}, {replicas: 0}, {replicas: 1}, {replicas: 2}, {replicas: 0.5}, {version: '3.3.0'}, {version: '3.3.1'}, {version: '3.4.0'}, {ingress: {enabled: 'false'}}, {claims: {database: 'paperless-data'}}, {controller: {imagePullPolicy: 'Sometimes'}}, {backup: {drainSeconds: 0}}, {hostname: 'https://host.example'}]) {
    const v = base(); v.services.paperless = service;
    for (const mode of ['deployment', 'connections', 'configuration']) rejects(v, {mode});
  }
  const v = base(); v.services.other = {unknown: true, replicas: 'invalid'}; v.backup = {endpoints: {external: {foreign: true}}}; declaration(v); configuration(v); deployment(v);
});
console.log(`PASS ${checks} chart behavior checks`);
