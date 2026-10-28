import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { runInNewContext } from 'node:vm';
import { parseAst } from 'rolldown/parseAst';
import { escapeTemplateWhitespace } from '../vite.config.mjs';
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
