// Development-only entry. No dev server or authentication override ships in the bundle.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';
import { createServer } from 'vite';
process.chdir(fileURLToPath(new URL('..', import.meta.url)));
const local = process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python';
const python = process.env.POLYSIA_PREVIEW_PYTHON || (existsSync(local) ? local : 'python');
const fixture = spawn(python, ['-u', 'dev/fixture.py'], { stdio: ['ignore', 'pipe', 'inherit'] });
let server;
const close = async () => { fixture.kill(); await server?.close(); };
process.on('SIGINT', () => void close().then(() => process.exit()));
process.on('SIGTERM', () => void close().then(() => process.exit()));
process.on('exit', () => fixture.kill());
try {
  const port = await new Promise((resolve, reject) => {
    const lines = createInterface({ input: fixture.stdout });
    lines.once('line', line => { lines.close(); /^\d+$/.test(line) ? resolve(Number(line)) : reject(Error('Invalid synthetic fixture port')); });
    fixture.once('exit', code => reject(Error(`Synthetic fixture stopped: ${code}`)));
    fixture.once('error', reject);
  });
  server = await createServer({ base: '/', server: { host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api/console/v1': { target: `http://127.0.0.1:${port}`, changeOrigin: true } } } });
  await server.listen();
  console.log('Synthetic preview: http://127.0.0.1:5173/?preview=fresh');
} catch (error) { await close(); throw error; }
