import { defineConfig, type Plugin } from 'vite';
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ORCA FastAPI backend lives next to the UI folder.
const BACKEND_DIR = path.resolve(__dirname, '..', 'ORCA_Backend');
const BACKEND_PORT = 8000;
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/health`;

/**
 * Dev plugin: starts the ORCA multi-agent backend automatically with
 * `npm run dev`, so the whole webapp comes up with ONE command.
 *
 * - Skips spawning when something already answers on :8000 (e.g. you ran
 *   uvicorn yourself), so there are never two servers fighting.
 * - Pipes backend logs into this terminal prefixed with `[orca-be]`.
 * - Kills the whole process tree on exit (Windows-safe via taskkill /T).
 */
function orcaBackendPlugin(): Plugin {
  let proc: ChildProcess | null = null;

  const killTree = () => {
    if (!proc || proc.pid === undefined) return;
    if (process.platform === 'win32') {
      spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      proc.kill('SIGTERM');
    }
    proc = null;
  };

  const isHealthy = async (): Promise<boolean> => {
    try {
      const res = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(1500) });
      return res.ok;
    } catch {
      return false;
    }
  };

  return {
    name: 'orca-auto-backend',
    apply: 'serve',
    async configureServer(server) {
      if (await isHealthy()) {
        server.config.logger.info(
          `[orca-be] backend already running on :${BACKEND_PORT} — not spawning another`,
        );
        return;
      }

      const cmd = process.platform === 'win32' ? 'python' : 'python3';
      proc = spawn(cmd, ['-m', 'uvicorn', 'main:app', '--port', String(BACKEND_PORT)], {
        cwd: BACKEND_DIR,
        env: { ...process.env },
        stdio: ['ignore', 'pipe', 'pipe'],
        shell: false,
      });

      const pipe = (stream: NodeJS.ReadableStream, tag: string) => {
        let buf = '';
        stream.on('data', (chunk: Buffer) => {
          buf += chunk.toString();
          let idx: number;
          while ((idx = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, idx);
            buf = buf.slice(idx + 1);
            if (line.trim()) console.log(`  ${tag} ${line}`);
          }
        });
      };
      pipe(proc.stdout, '[orca-be]');
      pipe(proc.stderr, '[orca-be!]');

      proc.on('exit', (code) => {
        if (proc !== null) {
          console.log(`[orca-be] backend exited (code ${code})`);
          proc = null;
        }
      });

      server.config.logger.info(
        `[orca-be] spawned ORCA backend (pid ${proc.pid}) from ${BACKEND_DIR}`,
      );

      server.httpServer?.once('close', killTree);
      process.once('SIGINT', () => { killTree(); process.exit(0); });
      process.once('SIGTERM', killTree);
      process.once('exit', killTree);
    },
  };
}

export default defineConfig({
  plugins: [orcaBackendPlugin()],
  server: {
    port: 3000,
    open: false,
    host: true,
    proxy: {
      // Same-origin API path for deployments where CORS must stay closed.
      '/api': {
        target: `http://127.0.0.1:${BACKEND_PORT}`,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
