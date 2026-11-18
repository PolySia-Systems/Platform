// Development-only entry. The Python fixture owns the loopback listener.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { context } from 'esbuild';
import { bundleOptions } from '../bundle.mjs';

process.chdir(fileURLToPath(new URL('..', import.meta.url)));
const local = process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python';
const python = process.env.POLYSIA_PREVIEW_PYTHON || (existsSync(local) ? local : 'python');
const output = mkdtempSync(join(tmpdir(), 'polysia-console-preview-'));
let build;
let fixture;
try {
  build = await context(bundleOptions(output, true));
  await build.rebuild();
  await build.watch();
  fixture = spawn(python, ['-u', 'dev/fixture.py', output], { stdio: 'inherit' });
  const stop = () => fixture.kill();
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  process.exitCode = await new Promise((resolve, reject) => {
    fixture.once('exit', code => resolve(code ?? 0));
    fixture.once('error', reject);
  });
} finally {
  await build?.dispose();
  rmSync(output, { recursive: true, force: true });
}
