import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { validate } from '../src/validation.ts';
import { m } from '../src/messages.ts';
const fixture = JSON.parse(readFileSync(new URL('./producer.json', import.meta.url)));
test('empty history guidance makes no request acceptance claim', () => {
  assert.doesNotMatch(m.requested, /request recorded|request accepted|success/i);
});
test('the real producer/gateway fixture validates without numeric conversion', () => {
  const snapshot = validate('Snapshot', fixture);
  assert.equal(snapshot.financial.cash.value, fixture.financial.cash.value);
  assert.equal(typeof snapshot.financial.cash.value, 'string');
});
test('unknown enums, missing identity, malformed decimals and compatibility reject', () => {
  for (const mutate of [s => { s.api = 'console/v99'; }, s => { delete s.release; },
    s => { s.financial.cash.value = 1.02; }, s => { s.financial.cash.value = 'NaN'; },
    s => { s.context.observed_mode = 'ARMED'; }, s => { delete s.context.scope; },
    s => { s.financial.cash.value = '1.00;alert(1)'; },
    s => { s.server_time = '2026-02-30T00:00:00Z'; }]) {
    const data = structuredClone(fixture); mutate(data);
    assert.throws(() => validate('Snapshot', data), /incompatible_contract/);
  }
});
