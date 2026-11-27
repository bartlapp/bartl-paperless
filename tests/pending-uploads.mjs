#!/usr/bin/env node
// Native integration regression; runs only against explicitly supplied synthetic tasks.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {setTimeout as delay} from 'node:timers/promises';
const [mode, file] = process.argv.slice(2);
assert(['pending', 'verify'].includes(mode) && file,
  'Usage: node tests/pending-uploads.mjs pending|verify /protected/pending-inputs.json');
const config = JSON.parse(await readFile(file, 'utf8'));
assert.equal(new URL(config.url).protocol, 'https:');
assert(config.uploads.length > 0);
const token = (await readFile(config.tokenFile, 'utf8')).trim();
async function request(path) {
  const result = await fetch(config.url + path, {
    headers: {Authorization: `Token ${token}`}, signal: AbortSignal.timeout(30000),
  });
  assert.equal(result.status, 200, `${path}: HTTP ${result.status}`);
  return result;
}
for (const upload of config.uploads) {
  assert(upload.title.startsWith('Synthetic '));
  assert(upload.task && upload.originalFile && Number.isInteger(upload.owner));
  const deadline = Date.now() + (config.timeoutSeconds ?? 3900) * 1000;
  let task;
  do {
    const response = await (await request('/api/tasks/?task_id=' + encodeURIComponent(upload.task))).json();
    task = response.results.find(item => item.task_id === upload.task);
    assert(task, `Accepted task disappeared: ${upload.task}`);
    if (mode === 'pending') {
      assert.equal(task.status, 'pending', 'Establish pending input before interruption, not merely successful upload');
      break;
    }
    assert.notEqual(task.status, 'failure', JSON.stringify(task));
    if (task.status === 'success') break;
    assert(Date.now() < deadline, `Pending task did not complete: ${upload.task}; retain native diagnostics`);
    await delay(2000);
  } while (true);
  if (mode === 'verify') {
    const id = task.result_data.document_id;
    const document = await (await request(`/api/documents/${id}/`)).json();
    assert.equal(document.title, upload.title);
    assert.equal(document.owner, upload.owner);
    assert.deepEqual([...document.tags].sort((a,b) => a-b), [...upload.tags].sort((a,b) => a-b));
    const bytes = Buffer.from(await (await request(`/api/documents/${id}/download/?original=true`)).arrayBuffer());
    assert(bytes.equals(await readFile(upload.originalFile)), 'Accepted document bytes changed');
    console.log(JSON.stringify({task: upload.task, document: id, bytesVerified: true, metadataVerified: true}));
  } else console.log(JSON.stringify({task: upload.task, status: task.status}));
}
