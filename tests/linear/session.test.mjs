import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { install } from '../../extensions/linear/pi.mjs';
import { configuration, readJson, Store } from '../../extensions/linear/core.mjs';
import { dedicatedMarker, seedDedicatedSession, verifySavedBootstrap } from '../../extensions/linear/session.mjs';
import { SessionManager, installedRuntime } from './fixtures/session-manager.mjs';

const root = resolve('.');
const { AgentSessionRuntime } = await installedRuntime();
function temporary(t) {
  const parent = join(root, '.cache/session-tests'); fs.mkdirSync(parent, { recursive: true });
  const path = fs.mkdtempSync(join(parent, 'trial-'));
  t.after(() => fs.rmSync(path, { recursive: true, force: true }));
  return path;
}

test('installed pi custom entries and allocated paths do not persist until a real user message', t => {
  const path = temporary(t), sm = SessionManager.create(path, join(path, 'sessions'));
  sm.appendCustomEntry(dedicatedMarker, { watch: randomUUID() });
  assert.ok(sm.getSessionFile()); assert.equal(fs.existsSync(sm.getSessionFile()), false);
  assert.throws(() => verifySavedBootstrap(sm));
  const saved = SessionManager.create(path, join(path, 'sessions'));
  seedDedicatedSession(saved, { source: 'watch', token: randomUUID(), previousSession: sm.getSessionId() });
  const reopened = SessionManager.open(saved.getSessionFile());
  assert.equal(reopened.getSessionId(), saved.getSessionId());
  assert.deepEqual(reopened.getBranch(), saved.getBranch());
  assert.equal(reopened.getBranch().filter(e => e.type === 'message').length, 1);
  assert.equal(reopened.getBranch().find(e => e.type === 'message').message.role, 'user');
  verifySavedBootstrap(reopened);
});

async function fixture(t, { failPickup = false, setupFailure = false } = {}) {
  let runtime;
  t.after(async () => { await runtime?.dispose(); });
  const path = temporary(t), cfg = readJson(join(root, 'docs/linear.example.json'));
  const nonce = randomUUID(), previousNonce = process.env.ABRA_LINEAR_WATCH_NONCE;
  process.env.ABRA_LINEAR_WATCH_NONCE = nonce;
  t.after(() => { if (previousNonce === undefined) delete process.env.ABRA_LINEAR_WATCH_NONCE; else process.env.ABRA_LINEAR_WATCH_NONCE = previousNonce; });
  fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(cfg));
  const config = configuration(cfg), calls = [], sent = [], events = [];
  const issue = { id: randomUUID(), title: 'offline report request', description: 'report only', identifier: 'test-1', delegate: { id: cfg.personaId }, team: { id: cfg.teams[0].id }, state: { id: randomUUID(), type: 'unstarted' }, labels: { nodes: [{ id: cfg.repositories[0].labelId }], pageInfo: { hasNextPage: false } } };
  const api = {
    validate: async () => { verifySavedBootstrapOrRecovery(); calls.push('validate'); },
    discover: async () => { calls.push('discover'); return [structuredClone(issue)]; },
    issue: async () => structuredClone(issue), comments: async () => [],
    comment: async () => { calls.push('pickup'); if (failPickup) throw new Error('offline failure before dispatch'); return randomUUID(); },
    status: async () => { calls.push('status'); },
  };
  function verifySavedBootstrapOrRecovery() {
    const sm = runtime.session.sessionManager;
    const reopened = SessionManager.open(sm.getSessionFile());
    assert.equal(reopened.getSessionId(), sm.getSessionId());
    assert.ok(reopened.getBranch().some(e => e.customType === dedicatedMarker));
  }
  const createSession = (sm, startEvent) => {
    const handlers = {}, commands = {}, notifications = [];
    let disposed = false;
    const live = () => assert.equal(disposed, false, 'old session context must not be reused');
    const ctx = { cwd: path, mode: 'rpc', hasUI: true, isProjectTrusted: () => true, isIdle: () => true, hasPendingMessages: () => false,
      get sessionManager() { live(); return sm; }, ui: { confirm: async () => true, notify: message => { live(); notifications.push(message); } },
      newSession: options => runtime.newSession({ ...options, setup: async manager => {
        if (setupFailure) fs.mkdirSync(manager.getSessionFile());
        await options.setup(manager);
      } }),
    };
    const pi = { on: (name, handler) => handlers[name] = handler, registerCommand: (name, command) => commands[name] = command, registerTool: () => {},
      appendEntry: (customType, data) => { live(); sm.appendCustomEntry(customType, data); events.push(data); },
      sendUserMessage: message => { live(); sent.push(message); }, setSessionName: () => live(), events: { on: () => () => {} },
    };
    install(pi, '.pi', { api, nativeRequest: async method => {
      if (method === 'ping') return { version: 1, capabilities: { processTerminalProof: { version: 1, lifecycleArtifactVersion: 3 } }, session: { sessionId: sm.getSessionId() } };
      return { fleet: { version: 1, totalActive: 0, omitted: 0 }, asyncSnapshot: { kind: 'pi-subagents.async-status-snapshot', version: 1, omitted: { runs: 0, children: 0, byteLimitExceeded: false }, runs: [] } };
    } });
    return { sessionManager: sm, sessionFile: sm.getSessionFile(), handlers, ctx, notifications, startEvent,
      extensionRunner: { hasHandlers: name => !!handlers[name], emit: event => handlers[event.type]?.(event, ctx) },
      abort: async () => {}, dispose: () => { disposed = true; }, refreshContext: () => {},
      command: args => commands['abra-linear'].handler(args, ctx),
    };
  };
  const services = { cwd: path };
  const initial = createSession(SessionManager.create(path, join(path, 'sessions')), { reason: 'startup' });
  runtime = new AgentSessionRuntime(initial, services, async ({ sessionManager, sessionStartEvent }) => ({ session: createSession(sessionManager, sessionStartEvent), services, diagnostics: [] }));
  runtime.setRebindSession(async session => { await session.handlers.session_start(session.startEvent, session.ctx); });
  await initial.handlers.session_start(initial.startEvent, initial.ctx);
  return { path, nonce, config, calls, sent, events, runtime, initial, createSession,
    store: () => new Store(path, config),
    bootstrap: () => initial.command(`watch-start ${nonce}`),
    arm: (token = nonce, previous = initial.sessionManager.getSessionId()) => runtime.session.command(`watch-arm ${token} ${previous}`),
  };
}

test('installed newSession lifecycle saves watch bootstrap before ready, ownership and pickup; pre-dispatch failure reopens same owner paused', async t => {
  const f = await fixture(t, { failPickup: true });
  await f.bootstrap();
  assert.notEqual(f.runtime.session.sessionManager.getSessionId(), f.initial.sessionManager.getSessionId());
  verifySavedBootstrap(f.runtime.session.sessionManager);
  assert.deepEqual(f.calls, []); assert.deepEqual(f.events, []); assert.deepEqual(f.sent, []);
  assert.equal(fs.existsSync(f.store().lock), false);
  await f.arm();
  assert.equal(f.events[0].state, 'ready'); assert.equal(f.events.at(-1).state, 'uncertain');
  assert.deepEqual(f.calls, ['validate', 'discover', 'pickup']); assert.deepEqual(f.sent, []);
  const record = f.store().load().records[0], file = f.runtime.session.sessionFile;
  assert.equal(record.dispatch, 'reserved'); assert.equal(record.session, f.runtime.session.sessionManager.getSessionId());
  await f.runtime.dispose();
  const recovered = f.createSession(SessionManager.open(file), { reason: 'resume' });
  await recovered.handlers.session_start({ reason: 'resume' }, recovered.ctx);
  assert.deepEqual(f.calls, ['validate', 'discover', 'pickup']);
  await recovered.command('resume');
  await recovered.command('status');
  assert.match(recovered.notifications.at(-1), /"mode":"paused"/);
  assert.equal(f.calls.filter(c => c === 'pickup').length, 1); assert.deepEqual(f.sent, []);
  await recovered.handlers.session_shutdown();
});

test('interactive start uses installed replacement lifecycle and saves context before first pickup', async t => {
  const f = await fixture(t, { failPickup: true });
  await f.initial.command('start');
  verifySavedBootstrap(f.runtime.session.sessionManager);
  assert.deepEqual(f.calls, ['validate', 'discover', 'pickup']); assert.deepEqual(f.sent, []);
  const record = f.store().load().records[0];
  assert.equal(record.session, SessionManager.open(f.runtime.session.sessionFile).getSessionId());
  assert.equal(record.dispatch, 'reserved');
});

for (const command of ['start', 'watch-start']) test(`${command} persistence failure blocks every ownership acquisition and pickup`, async t => {
  const f = await fixture(t, { setupFailure: true });
  await assert.rejects(f.initial.command(command === 'start' ? 'start' : `watch-start ${f.nonce}`));
  assert.deepEqual(f.calls, []); assert.deepEqual(f.events, []); assert.deepEqual(f.sent, []);
  assert.equal(fs.existsSync(f.store().lock), false); assert.equal(f.store().load().active, null);
  await f.arm(); assert.deepEqual(f.calls, []); assert.equal(fs.existsSync(f.store().lock), false);
});

for (const failure of ['foreign-nonce', 'foreign-parent', 'extra-message', 'pending', 'busy', 'missing-file', 'wrong-header', 'wrong-cwd', 'missing-marker', 'reload']) test(`watch bootstrap refuses ${failure} without pickup`, async t => {
  const f = await fixture(t); await f.bootstrap();
  const session = f.runtime.session, sm = session.sessionManager;
  if (failure === 'extra-message') sm.appendMessage({ role: 'user', content: 'not fresh', timestamp: Date.now() });
  if (failure === 'pending') session.ctx.hasPendingMessages = () => true;
  if (failure === 'busy') session.ctx.isIdle = () => false;
  if (failure === 'missing-file') fs.unlinkSync(sm.getSessionFile());
  if (['wrong-header', 'wrong-cwd', 'missing-marker'].includes(failure)) {
    const entries = fs.readFileSync(sm.getSessionFile(), 'utf8').trim().split('\n').map(JSON.parse);
    if (failure === 'wrong-header') entries[0].id = randomUUID();
    else if (failure === 'wrong-cwd') entries[0].cwd = '/foreign-session-directory';
    else entries.splice(entries.findIndex(e => e.customType === dedicatedMarker), 1);
    fs.writeFileSync(sm.getSessionFile(), entries.map(e => JSON.stringify(e) + '\n').join(''));
  }
  if (failure === 'reload') {
    const replacement = f.createSession(SessionManager.open(sm.getSessionFile()), { reason: 'reload' });
    await replacement.handlers.session_start({ reason: 'reload' }, replacement.ctx);
    await replacement.command(`watch-arm ${f.nonce} ${f.initial.sessionManager.getSessionId()}`);
  } else await f.arm(failure === 'foreign-nonce' ? randomUUID() : f.nonce, failure === 'foreign-parent' ? randomUUID() : f.initial.sessionManager.getSessionId());
  assert.deepEqual(f.calls, []); assert.deepEqual(f.sent, []);
  assert.ok(!f.events.some(e => e.state === 'ready'));
  assert.equal(fs.existsSync(f.store().lock), false); assert.equal(f.store().load().active, null);
});

test('ephemeral dedicated bootstrap cannot acquire ownership', t => {
  const path = temporary(t), sm = SessionManager.inMemory(path);
  assert.throws(() => seedDedicatedSession(sm, { source: 'interactive', token: randomUUID(), previousSession: 'previous' }), /persistent storage/);
});

test('a different saved dedicated session cannot take over pre-dispatch ownership', async t => {
  const f = await fixture(t, { failPickup: true }); await f.bootstrap(); await f.arm();
  const owner = f.store().load().records[0].session;
  await f.runtime.dispose();
  const sm = SessionManager.create(f.path, join(f.path, 'sessions'));
  seedDedicatedSession(sm, { source: 'interactive', token: randomUUID(), previousSession: 'previous' });
  const foreign = f.createSession(sm, { reason: 'resume' });
  await foreign.handlers.session_start({ reason: 'resume' }, foreign.ctx);
  const before = [...f.calls]; await foreign.command('resume');
  assert.match(foreign.notifications.at(-1), /recorded owning pi session/);
  assert.deepEqual(f.calls, before); assert.deepEqual(f.sent, []);
  assert.equal(fs.existsSync(f.store().lock), false); assert.equal(f.store().load().records[0].session, owner);
  await foreign.handlers.session_shutdown();
});
