import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { runInNewContext } from 'node:vm';
import { parseAst } from 'rolldown/parseAst';
import { assertCanonicalSource, escapeTemplateWhitespace } from '../vite.config.mjs';

test('custody refuses noncanonical text while preserving reviewed binary artwork', () => {
  assert.doesNotThrow(() => assertCanonicalSource('src/App.tsx', Buffer.from('source\n')));
  assert.throws(() => assertCanonicalSource('src/App.tsx', Buffer.from('source\r\n')), /restore LF/);
  assert.throws(() => assertCanonicalSource('C:\\repo\\frontend\\package.json', Buffer.from('{}\r\n')), /restore LF/);
  assert.doesNotThrow(() => assertCanonicalSource('brand/master.svg', Buffer.from('<svg/>\r\n')));
  assert.doesNotThrow(() => assertCanonicalSource('font.woff2', Buffer.from([13, 10])));
});
test('generated template whitespace keeps exact runtime string values', () => {
  const code = 'const x="parameter"; `css {  \n \t\n value:${x} \n}`';
  const transformed = escapeTemplateWhitespace(code, parseAst(code));
  assert.equal(runInNewContext(transformed), runInNewContext(code));
  assert.doesNotMatch(transformed, /[ \t]+\n/);
});
test('tagged raw template bytes cannot be silently changed', () => {
  const code = 'String.raw`raw  \n`';
  assert.throws(() => escapeTemplateWhitespace(code, parseAst(code)), /explicit review/);
  const escaped = '`value\\ \n`';
  assert.throws(() => escapeTemplateWhitespace(escaped, parseAst(escaped)), /explicit review/);
});
