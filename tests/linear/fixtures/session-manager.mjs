import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

// exercise installed pi storage, not a persistence mock; fail if unavailable.
const packageRoot = process.env.PI_CODING_AGENT_PACKAGE ?? join(dirname(process.execPath), '../lib/node_modules/@earendil-works/pi-coding-agent');
export const { SessionManager } = await import(pathToFileURL(join(packageRoot, 'dist/core/session-manager.js')).href);
export const installedRuntime = () => import(pathToFileURL(join(packageRoot, 'dist/core/agent-session-runtime.js')).href);
