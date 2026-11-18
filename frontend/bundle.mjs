import { readFile } from 'node:fs/promises';

export function bundleOptions(outdir, development = false) {
  return {
    entryPoints: ['src/main.tsx'], outdir, bundle: true,
    format: 'esm', target: 'es2022', jsx: 'automatic', minify: !development,
    entryNames: development ? 'console' : 'console-[hash]', assetNames: '[name]-[hash]',
    publicPath: '/assets', legalComments: 'none',
    define: { 'import.meta.env.DEV': String(development) },
    loader: { '.svg': 'file', '.png': 'file', '.woff2': 'file' },
    plugins: [{ name: 'static-browser-directives', setup(build) {
      build.onLoad({ filter: /\.mjs$/ }, async ({ path }) => {
        if (!path.replaceAll('\\', '/').includes('/node_modules/@mantine/')) return;
        const source = await readFile(path, 'utf8');
        return { contents: source.replace(/^[\"']use client[\"'];\s*/, ''), loader: 'js' };
      });
    } }],
  };
}

// Custody hashes exact bytes. Git checks these source inputs out with LF;
// refuse a local CRLF build rather than publish a hash CI cannot reproduce.
export function assertCanonicalSource(path, bytes) {
  if (/(\.(?:ts|tsx|css|json|mjs|py|txt)|\/(?:\.npmrc|\.node-version))$/.test(path.replaceAll('\\', '/'))
      && bytes.includes(Buffer.from('\r\n'))) {
    throw Error(`Noncanonical CRLF source input: ${path}; restore LF before building Console assets`);
  }
}
// Preserve exact template values while keeping generated files valid under git's
// whitespace gate. Tagged templates observe raw bytes, so refuse that case.
export function escapeTemplateWhitespace(code, ast) {
  const edits = [];
  const visit = (node, parent) => {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'TemplateLiteral') {
      for (const part of node.quasis) {
        const raw = part.value.raw;
        const escaped = raw.replace(/[ \t]+(?=\r?\n)/g, (value, offset) => {
          const slashes = raw.slice(0,offset).match(/\\+$/)?.[0].length ?? 0;
          if (slashes % 2) throw Error('Escaped template whitespace needs explicit review');
          return [...value].map(c => c === ' ' ? '\\x20' : '\\t').join('');
        });
        if (raw !== escaped) {
          if (parent?.type === 'TaggedTemplateExpression') throw Error('Tagged raw whitespace needs explicit review');
          const start = code.indexOf(raw, part.start);
          if (start < part.start || start + raw.length > part.end) throw Error('Template range differs');
          edits.push({ start, end: start + raw.length, escaped });
        }
      }
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === 'parent') continue;
      if (Array.isArray(value)) value.forEach(child => visit(child, node));
      else if (value && typeof value === 'object') visit(value, node);
    }
  };
  visit(ast, null);
  for (const edit of edits.sort((a,b) => b.start-a.start)) code = code.slice(0,edit.start) + edit.escaped + code.slice(edit.end);
  return code;
}
