import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { readJson } from '../../../extensions/linear/core.mjs';
import { SCOPES } from '../../../extensions/linear/auth.mjs';
import { install } from '../../../extensions/linear/pi.mjs';
import { SessionManager } from './session-manager.mjs';

// fresh foreground-child boundary: real extension construction, fake network/native api.
const root = process.argv[2], config = readJson(join(root, '.pi/abra-linear.json'));
const session = randomUUID(), nonce = randomUUID(), handlers = {}, commands = {}, entries = [];
let acquisitions = 0, scans = 0;
process.env.ABRA_LINEAR_WATCH_NONCE = nonce;
globalThis.fetch = async (url, options) => {
  let data;
  if (url.endsWith('/oauth/token')) {
    const form = new URLSearchParams(options.body);
    assert.equal(form.get('grant_type'), 'client_credentials');
    assert.ok(form.get('client_secret')); acquisitions++;
    return { ok: true, status: 200, json: async () => ({ access_token: 'fake-child-token', token_type: 'Bearer', expires_in: 1000, scope: SCOPES.join(' ') }) };
  }
  const { query } = JSON.parse(options.body);
  assert.equal(options.headers.Authorization, 'Bearer fake-child-token');
  if (query.includes('AbraIdentity')) data = { viewer: { id: config.personaId }, organization: { id: config.workspaceId } };
  else if (query.includes('AbraStates')) data = { workflowStates: { nodes: Object.entries(config.teams[0]).filter(([key]) => key !== 'id').map(([key, id]) => ({ id, type: key === 'working' ? 'started' : 'unstarted', team: { id: config.teams[0].id } })), pageInfo: { hasNextPage: false } } };
  else { assert.ok(query.includes('AbraDelegated')); scans++; data = { issues: { nodes: [], pageInfo: { hasNextPage: false } } }; }
  return { ok: true, status: 200, headers: new Headers(), json: async () => ({ data }) };
};
const ctx = { cwd: root, mode: 'rpc', hasUI: true, isProjectTrusted: () => true, isIdle: () => true, hasPendingMessages: () => false, sessionManager: { getSessionId: () => session, getBranch: () => [], getSessionFile: () => '/fake/session' }, ui: { notify: () => {} } };
const pi = { on: (name, handler) => handlers[name] = handler, registerCommand: (name, command) => commands[name] = command, registerTool: () => {}, appendEntry: (customType, data) => entries.push({ customType, data }), events: { on: () => () => {} } };
const dependencies = { nativeRequest: async method => {
  if (method === 'ping') return { version: 1, capabilities: { processTerminalProof: { version: 1, lifecycleArtifactVersion: 3 } }, session: { sessionId: ctx.sessionManager.getSessionId() } };
  return { fleet: { version: 1, totalActive: 0, omitted: 0 }, asyncSnapshot: { kind: 'pi-subagents.async-status-snapshot', version: 1, omitted: { runs: 0, children: 0, byteLimitExceeded: false }, runs: [] } };
} };
install(pi, '.pi', dependencies);
ctx.newSession = async options => {
  await handlers.session_shutdown();
  ctx.sessionManager = SessionManager.create(root, join(root, 'sessions'));
  await options.setup(ctx.sessionManager);
  install(pi, '.pi', dependencies);
  await handlers.session_start({ reason: 'new' }, ctx);
  return { cancelled: false };
};
try {
  await handlers.session_start({ reason: 'startup' }, ctx);
  assert.equal(acquisitions, 0);
  await commands['abra-linear'].handler(`watch-start ${nonce}`, ctx);
  assert.equal(acquisitions, 0);
  await commands['abra-linear'].handler(`watch-arm ${nonce} ${session}`, ctx);
  assert.equal(entries.at(-1).data.state, 'ready');
  assert.equal(acquisitions, 1); assert.equal(scans, 1);
} finally { await handlers.session_shutdown(); }
process.stdout.write('fresh child authenticated without inherited credentials\n');
