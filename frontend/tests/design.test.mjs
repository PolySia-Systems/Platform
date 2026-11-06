import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync, readdirSync } from 'node:fs';
import { statusTone } from '../src/design/status.ts';
test('unrecognized and structural availability codes never imply financial success', () => {
  for (const code of ['AVAILABLE', 'ACCEPTED', 'PAPER', 'NEW_STATE', 'NOT_AUTHORIZED']) assert.equal(statusTone(code), 'neutral');
  assert.equal(statusTone('OBSERVED'), 'good');
  assert.equal(statusTone('BLOCKED'), 'danger');
  assert.equal(statusTone('STALE'), 'bad');
});
test('presentation styles consume semantic colors; foundations cannot call the gateway', () => {
  for (const file of ['global.css', 'Console.module.css']) assert.doesNotMatch(readFileSync(new URL('../src/'+file, import.meta.url), 'utf8'), /#[0-9a-f]{3,8}\b/i);
  for (const file of readdirSync(new URL('../src/design/', import.meta.url)).filter(f=>/\.tsx?$/.test(f))) {
    assert.doesNotMatch(readFileSync(new URL('../src/design/'+file,import.meta.url),'utf8'), /from ['"].*(client|App|Workspaces)['"]/);
  }
});

test('selected source assets match the reviewed provenance record', () => {
 const base = new URL('../src/assets/', import.meta.url);
 const provenance = JSON.parse(readFileSync(new URL('provenance.json',base),'utf8'));
 for (const [name, expected] of Object.entries(provenance.sha256)) assert.equal(createHash('sha256').update(readFileSync(new URL(name,base))).digest('hex'), expected);
});
