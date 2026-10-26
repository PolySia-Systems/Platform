import { defineConfig } from 'vite';
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
export default defineConfig({
  // RSC boundaries have no meaning in this exclusively static browser bundle.
  plugins: [{ name: 'static-browser-directives', enforce: 'pre', transform(code, id) {
    if (id.includes('/@mantine/') || id.includes('\\@mantine\\')) {
      return code.replace(/^["']use client["'];\s*/, '');
    }
  } }],
  base: '/h1/assets/',
  build: {
    target: 'es2022', outDir: '.build', emptyOutDir: true,
    cssCodeSplit: false, modulePreload: false,
    rollupOptions: { input: 'src/main.tsx', output: {
      entryFileNames: '[name]-[hash].js', assetFileNames: '[name]-[hash][extname]',
    } },
  },
});
