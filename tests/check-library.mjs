#!/usr/bin/env node
// Optional synthetic qualification, never an application startup dependency.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';

const [mode, configPath] = process.argv.slice(2);
assert(['baseline', 'verify'].includes(mode) && configPath,
  'Usage: node tests/check-library.mjs baseline|verify /protected/library-inputs.json');
const config = JSON.parse(await readFile(configPath, 'utf8'));
assert.equal(new URL(config.url).protocol, 'https:');
const tokens = JSON.parse(await readFile(config.tokensFile, 'utf8'));
async function request(route, actor = 'admin', options = {}) {
  assert(tokens[actor], `Missing ${actor} credential`);
  return fetch(config.url + route, {...options, headers: {
    Authorization: `Token ${tokens[actor]}`, ...options.headers,
  }, signal: AbortSignal.timeout(30000)});
}
async function json(route, actor = 'admin') {
  const response = await request(route, actor);
  assert.equal(response.status, 200, `${route}: HTTP ${response.status}`);
  return response.json();
}
function select(object, fields) {
  return Object.fromEntries(fields.filter(field => field in object).map(field => [field, object[field]]));
}
const documents = (await json('/api/documents/?full_perms=true&page_size=1000')).results;
assert(documents.every(document => document.title.startsWith('Synthetic ')),
  'Refusing permission probes against a nonsynthetic library');
const observed = {
  documents: documents.map(document => {
    const selected = select(document, ['id', 'title', 'content', 'owner', 'permissions', 'tags',
      'archive_serial_number', 'root_document', 'versions', 'created', 'correspondent',
      'document_type', 'storage_path', 'custom_fields']);
    for (const version of selected.versions) version.added = new Date(version.added).toISOString();
    return selected;
  }).sort((a, b) => a.id - b.id),
  users: (await json('/api/users/?page_size=1000')).results.map(user => select(user,
    ['id', 'username', 'is_staff', 'is_superuser', 'groups', 'user_permissions', 'is_active']
  )).sort((a, b) => a.id - b.id),
  groups: (await json('/api/groups/?page_size=1000')).results,
  workflows: (await json('/api/workflows/?page_size=1000')).results.map(workflow => ({
    ...select(workflow, ['id', 'name', 'order', 'enabled']),
    triggers: workflow.triggers.map(trigger => select(trigger, ['type', 'filter_filename', 'sources'])),
    actions: workflow.actions.map(action => select(action, ['type', 'assign_tags', 'assign_view_groups'])),
  })),
};
if (mode === 'verify') {
  assert.deepEqual(observed, JSON.parse(await readFile(config.expectedFile, 'utf8')),
    'Recovered metadata, version relationships, identity, grants or used workflow changed');
}
const files = [];
for (const file of config.files) {
  const response = await request(file.route, file.actor || 'reader');
  assert.equal(response.status, 200, `${file.file}: download`);
  const actual = Buffer.from(await response.arrayBuffer());
  assert(actual.equals(await readFile(path.join(config.fixturesDir, file.file))),
    `${file.file}: original/version/rendition bytes changed`);
  for (const denied of file.deniedActors || ['denied']) {
    assert.equal((await request(file.route, denied)).status, 403, `${file.file}: denied ${denied}`);
  }
  files.push({file: file.file, sha256: createHash('sha256').update(actual).digest('hex')});
}
assert.equal((await json('/api/documents/', 'denied')).count, 0);
assert.equal((await request('/api/users/', 'reader')).status, 403);
assert.equal((await request(`/api/documents/${config.readOnlyDocument}/`, 'reader', {
  method: 'PATCH', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({title: 'Synthetic unauthorized modification'}),
})).status, 403);
for (const search of config.searches) {
  assert.deepEqual((await json('/api/documents/?query=' + encodeURIComponent(search.query),
    search.actor || 'reader')).results.map(document => document.id).sort((a, b) => a - b), search.ids);
  assert.equal((await json('/api/documents/?query=' + encodeURIComponent(search.query), 'denied')).count, 0);
}
assert.equal((await json('/api/documents/?query=UNSEENNEEDLE', 'reader')).count, 0);
if (mode === 'baseline') {
  await writeFile(config.expectedFile, JSON.stringify(observed, null, 2), {mode: 0o600});
}
console.log(JSON.stringify({mode, files, metadata: true, permissions: true,
  search: true, workflow: true, versionTimestampPrecision: 'native milliseconds'}));
