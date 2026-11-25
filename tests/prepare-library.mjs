#!/usr/bin/env node
// Synthetic qualification only; never an application startup dependency.
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const [configPath] = process.argv.slice(2);
assert(configPath, 'Usage: node tests/prepare-library.mjs /protected/library-setup.json');
const config = JSON.parse(await readFile(configPath, 'utf8'));
const url = new URL(config.url);
assert.equal(url.protocol, 'https:');
assert.equal(url.username + url.password + url.search + url.hash, '');
assert.equal(url.pathname, '/');
assert(config.readerUsername, 'Supply the already provisioned native OIDC username');
assert(config.outputDir?.startsWith('/'), 'outputDir must be an absolute protected path outside Git');
const out = resolve(config.outputDir);
const token = (await readFile(config.adminTokenFile, 'utf8')).trim();
assert(token, 'Supply a current native administrator token');
const permissions = ['view_document', 'view_uisettings', 'add_uisettings',
  'change_uisettings', 'view_savedview', 'view_tag', 'view_correspondent',
  'view_documenttype', 'view_storagepath'];
const deniedUsername = 'qualification-denied';
async function request(route, { method = 'GET', body } = {}) {
  const json = body !== undefined && !(body instanceof FormData);
  const response = await fetch(url.origin + route, { method,
    headers: { Authorization: `Token ${token}`, ...(json ? { 'Content-Type': 'application/json' } : {}) },
    body: json ? JSON.stringify(body) : body, signal: AbortSignal.timeout(30000) });
  assert(response.ok, `${method} ${route}: HTTP ${response.status}`);
  return response;
}
async function api(route, options) { return (await request(route, options)).json(); }
const documents = await api('/api/documents/?page_size=1000');
assert.equal(documents.count, 0, 'Preparation requires an empty disposable library');
const users = (await api('/api/users/?page_size=1000')).results;
const matches = users.filter(user => user.username === config.readerUsername);
assert.equal(matches.length, 1, 'Expected the already provisioned OIDC reader');
const reader = matches[0];
assert(reader.is_active && !reader.is_staff && !reader.is_superuser, 'Reader must be active and non-administrative');
assert.equal(reader.groups.length + reader.user_permissions.length, 0, 'Do not replace existing reader grants');
assert(!users.some(user => user.username === deniedUsername), 'Denied fixture user must be absent');
for (const kind of ['groups', 'tags', 'workflows']) {
  assert.equal((await api(`/api/${kind}/?page_size=1000`)).count, 0, `Preparation requires no existing ${kind}`);
}
await mkdir(out, { mode: 0o700 });
await mkdir(join(out, 'fixtures'), { mode: 0o700 });
const state = { url: url.origin, reader: { id: reader.id, username: reader.username } };
// Retain issued resource IDs for reconciliation, not automatic mutation replay.
async function retain() { await writeFile(join(out, 'creation.json'), JSON.stringify(state, null, 2), { mode: 0o600 }); }
await retain();
const group = await api('/api/groups/', { method: 'POST', body: { name: 'Synthetic readers', permissions } });
state.group = group.id; await retain();
await api(`/api/users/${reader.id}/`, { method: 'PATCH', body: { groups: [group.id] } });
const deniedPassword = randomBytes(32).toString('hex');
await writeFile(join(out, 'denied-password'), deniedPassword, { mode: 0o600, flag: 'wx' });
const denied = await api('/api/users/', { method: 'POST', body: {
  username: deniedUsername, password: deniedPassword, is_active: true,
  is_staff: false, is_superuser: false, groups: [], user_permissions: permissions,
} });
assert(!denied.is_staff && !denied.is_superuser);
state.denied = { id: denied.id, username: denied.username }; await retain();
const tag = await api('/api/tags/', { method: 'POST', body: {
  name: 'Synthetic workflow tag', matching_algorithm: 0, is_inbox_tag: false,
} });
state.tag = tag.id; await retain();
const workflow = await api('/api/workflows/', { method: 'POST', body: {
  name: 'Synthetic qualification assignment', enabled: true,
  triggers: [{ type: 2 }],
  actions: [{ type: 1, assign_tags: [tag.id], assign_view_groups: [group.id] }],
} });
state.workflow = workflow.id; await retain();
function pdf(text) {
  const body = `BT /F1 18 Tf 50 750 Td (${text}) Tj ET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(body)} >>\nstream\n${body}\nendstream`];
  let data = '%PDF-1.4\n'; const offsets = [];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(data)); data += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = Buffer.byteLength(data);
  data += 'xref\n0 6\n0000000000 65535 f \n' + offsets.map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  return Buffer.from(data + `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
}
async function consume(route, bytes, name, fields) {
  const form = new FormData(); form.set('document', new Blob([bytes], { type: 'application/pdf' }), name);
  for (const [key, value] of Object.entries(fields)) form.set(key, value);
  const taskId = await api(route, { method: 'POST', body: form });
  assert.equal(typeof taskId, 'string', 'Native upload must return its task UUID');
  state.lastTask = taskId; await retain();
  const deadline = Date.now() + 600000;
  while (Date.now() < deadline) {
    const tasks = await api(`/api/tasks/?task_id=${encodeURIComponent(taskId)}`);
    const task = tasks.results.find(item => item.task_id === taskId);
    if (task?.status === 'success') return task;
    assert(task?.status !== 'failure', `Native consumption failed for ${taskId}; inspect the task before retrying`);
    await delay(2000);
  }
  throw new Error(`Native consumption did not finish for ${taskId}; do not repeat the upload`);
}
const rootBytes = pdf('BARTLROOT synthetic document');
const versionBytes = pdf('BARTLVERSION synthetic document');
await writeFile(join(out, 'fixtures/root-original.pdf'), rootBytes, { mode: 0o600, flag: 'wx' });
await writeFile(join(out, 'fixtures/version-original.pdf'), versionBytes, { mode: 0o600, flag: 'wx' });
const rootTask = await consume('/api/documents/post_document/', rootBytes, 'root.pdf', { title: 'Synthetic versioned record' });
const rootId = rootTask.result_data.document_id;
assert(Number.isInteger(rootId)); state.root = rootId; await retain();
await consume(`/api/documents/${rootId}/update_version/`, versionBytes, 'version.pdf', { version_label: 'Synthetic revised version' });
const root = await api(`/api/documents/${rootId}/?full_perms=true`);
assert.equal(root.title, 'Synthetic versioned record');
assert(root.tags.includes(tag.id), 'The native assignment workflow must have run');
assert.equal(root.versions.length, 2, 'Expected the original and one native file version');
const original = root.versions.find(version => version.is_root);
const revised = root.versions.find(version => !version.is_root);
assert.equal(original.id, rootId);
assert.equal(revised.version_label, 'Synthetic revised version');
state.version = revised.id; await retain();
const files = [];
for (const [label, id, expected] of [['root', original.id, rootBytes], ['version', revised.id, versionBytes]]) {
  const metadata = await api(`/api/documents/${rootId}/metadata/?version=${id}`);
  assert(metadata.has_archive_version && metadata.archive_checksum, 'Archive PDF rendition must exist');
  const originalRoute = `/api/documents/${rootId}/download/?version=${id}&original=true`;
  assert(Buffer.from(await (await request(originalRoute)).arrayBuffer()).equals(expected), 'Original upload bytes changed');
  const archiveRoute = `/api/documents/${rootId}/download/?version=${id}`;
  await writeFile(join(out, `fixtures/${label}-archive.pdf`), Buffer.from(await (await request(archiveRoute)).arrayBuffer()), { mode: 0o600, flag: 'wx' });
  files.push({ route: originalRoute, file: `${label}-original.pdf` }, { route: archiveRoute, file: `${label}-archive.pdf` });
}
await writeFile(join(out, 'usernames.json'), JSON.stringify({ reader: reader.username, denied: denied.username }), { mode: 0o600, flag: 'wx' });
await writeFile(join(out, 'tokens.json'), JSON.stringify({ admin: token }), { mode: 0o600, flag: 'wx' });
await writeFile(join(out, 'library-inputs.json'), JSON.stringify({ url: url.origin,
  tokensFile: join(out, 'tokens.json'), expectedFile: join(out, 'expected.json'),
  fixturesDir: join(out, 'fixtures'), files, searches: [{ query: 'BARTLVERSION', ids: [rootId] }],
  readOnlyDocument: rootId,
}, null, 2), { mode: 0o600, flag: 'wx' });
console.log(JSON.stringify({ prepared: state, inputs: join(out, 'library-inputs.json'),
  next: 'Supply native reader/denied tokens, then run check-library.mjs baseline. This is fixture preparation, not qualification.' }));
