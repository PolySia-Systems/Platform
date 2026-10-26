// One asset custody recipe. Production consumes these bytes without Node/npm.
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { resolve, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseAst } from 'rolldown/parseAst';
import { escapeTemplateWhitespace } from './vite.config.mjs';
process.chdir(fileURLToPath(new URL('.', import.meta.url)));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const root = resolve('..');
const output = resolve('../src/polysia/monitoring/human_console_assets');
if (!output.startsWith(resolve(root, 'src/polysia/monitoring') + sep)) throw Error('Asset target outside workspace');
const walk = dir => readdirSync(dir, { withFileTypes: true }).flatMap(e =>
  e.isDirectory() ? walk(resolve(dir, e.name)) : [resolve(dir, e.name)]);
const sources = [...walk('src'), ...walk('tests'), ...walk('licenses'), ...['package.json', 'package-lock.json',
  'tsconfig.json', 'vite.config.mjs', 'build.mjs', '.npmrc', '.node-version'].map(p => resolve(p)),
  resolve('../src/polysia/monitoring/console_contract.py')].sort((a,b) => {
    const x = relative(root,a).replaceAll('\\','/'), y = relative(root,b).replaceAll('\\','/');
    return x < y ? -1 : x > y ? 1 : 0;
  });
const sourceHash = createHash('sha256');
for (const path of sources) {
  sourceHash.update(relative(root,path).replaceAll('\\','/')); sourceHash.update(Buffer.from(hash(readFileSync(path)), 'hex'));
}
const source = sourceHash.digest('hex');
if (process.argv.includes('--check')) {
  const manifest = JSON.parse(readFileSync(resolve(output,'manifest.json')));
  if (manifest.source !== source) throw Error('Stale Console source manifest');
  for (const [name, digest] of Object.entries(manifest.files)) {
    if (hash(readFileSync(resolve(output,name))) !== digest) throw Error('Stale asset: '+name);
  }
} else {
  rmSync(output, { recursive: true, force: true }); mkdirSync(output, { recursive: true });
  const files = {};
  if (walk('.build').filter(p => p.endsWith('.js')).length !== 1) throw Error('Review asset custody before introducing split chunks');
  for (const path of walk('.build')) {
    let name = relative(resolve('.build'),path).replaceAll('\\','/');
    let bytes = readFileSync(path);
    if (name.endsWith('.js')) {
      const code = bytes.toString('utf8');
      bytes = Buffer.from(escapeTemplateWhitespace(code, parseAst(code)));
      name = `main-${hash(bytes).slice(0,12)}.js`;
    }
    writeFileSync(resolve(output,name),bytes); files[name] = hash(bytes);
  }
  let notices = 'PolySia Console third-party software notices\n\n';
  const lock = JSON.parse(readFileSync('package-lock.json'));
  for (const [path, entry] of Object.entries(lock.packages).sort()) {
    if (!path || entry.dev) continue;
    const info = JSON.parse(readFileSync(resolve(path, 'package.json')));
    const licenses = readdirSync(path).filter(name => /^(license|copying)([.-]|$)/i.test(name));
    const paths = licenses.length ? licenses.map(name => resolve(path,name)) : [resolve('licenses', `${info.name}-${info.version}.txt`)];
    notices += `${info.name}@${info.version} (${info.license})\n${paths.map(p => readFileSync(p, 'utf8')).join('\n')}\n\n`;
  }
  notices = notices.replaceAll('\r\n', '\n').trimEnd() + '\n';
  writeFileSync(resolve(output,'notices.txt'), notices); files['notices.txt'] = hash(notices);
  const script = Object.keys(files).find(p => p.endsWith('.js'));
  const css = Object.keys(files).find(p => p.endsWith('.css'));
  if (!script || !css) throw Error('Missing Console entry');
  const html = `<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="style-nonce" content="{{nonce}}"><title>PolySia Console</title><link rel="stylesheet" href="/h1/assets/${css}"><script type="module" src="/h1/assets/${script}"></script></head><body><div id="root"></div></body></html>\n`;
  const document = html.replace('<title>', `<meta name="bundle-source" content="${source}"><title>`);
  writeFileSync(resolve(output,'index.html'),document); files['index.html'] = hash(document);
  writeFileSync(resolve(output,'manifest.json'), JSON.stringify({
    version: 1, api: 'console/v1', release: '0.4.0', source, files,
  }, null, 2)+'\n');
}
