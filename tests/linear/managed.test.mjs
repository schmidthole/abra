import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join, resolve } from 'node:path';
import { EventEmitter } from 'node:events';
import { ManagedOwners, nativeRequest, validateProcessTerminal } from '../../extensions/linear/managed.mjs';

const root = resolve('.');
const bus = () => { const emitter = new EventEmitter(); return { on: (name, fn) => { emitter.on(name, fn); return () => emitter.off(name, fn); }, emit: (...args) => emitter.emit(...args) }; };
const proof = () => ({ version: 1, state: 'observed', runId: 'run-1', runnerProcessInstanceId: 'runner-1', observedAt: 20, instances: [{ kind: 'runner', processInstanceId: 'runner-1', closeObservedAt: 20, exitCode: 0, signal: null }] });
function fixture(t) {
  fs.mkdirSync(join(root, '.cache/managed-tests'), { recursive: true });
  const path = fs.mkdtempSync(join(root, '.cache/managed-tests/trial-'));
  t.after(() => fs.rmSync(path, { recursive: true, force: true }));
  const pi = { events: bus(), appendEntry: () => {} }, ctx = { sessionManager: { getSessionId: () => 'session-1', getSessionFile: () => 'session-file' } };
  let nativeProof = proof();
  const status = { lifecycleArtifactVersion: 3, runId: 'run-1', mode: 'single', state: 'complete', sessionId: 'session-file', steps: [{ status: 'completed' }], processTerminal: { runnerProcessInstanceId: 'runner-1' } };
  const save = () => fs.writeFileSync(join(path, 'status.json'), JSON.stringify(status)); save();
  const projection = { fleet: { version: 1, totalActive: 0, omitted: 0 }, asyncSnapshot: { kind: 'pi-subagents.async-status-snapshot', version: 1, omitted: { runs: 0, children: 0, byteLimitExceeded: false }, runs: [] } };
  const request = async (method, params) => method === 'ping' ? { version: 1, capabilities: { processTerminalProof: { version: 1, lifecycleArtifactVersion: 3 } }, session: { sessionId: 'session-1' } } : params?.id ? { details: { runId: 'run-1', lifecycleStatus: { processTerminal: nativeProof } } } : projection;
  const owners = new ManagedOwners(pi, ctx, request); t.after(() => owners.dispose());
  const start = { id: 'run-1', lifecycleArtifactVersion: 3, mode: 'single', sessionId: 'session-file', asyncDir: path };
  return { pi, ctx, path, status, save, owners, start, projection, setProof: p => { nativeProof = p; }, verify: () => owners.verify() };
}

test('managed rpc subscribes before sending and validates exact version/request', async () => {
  const pi = { events: bus() };
  const off = pi.events.on('subagents:rpc:v1:request', req => pi.events.emit(`subagents:rpc:v1:reply:${req.requestId}`, { version: 1, requestId: req.requestId, success: true, data: { ok: true } }));
  assert.deepEqual(await nativeRequest(pi, 'ping'), { ok: true }); off();
  await assert.rejects(nativeRequest(pi, 'ping', {}, 10), /timeout/);
});

test('managed handoff checks every captured live start against exact public native proof', async t => {
  const f = fixture(t); await f.owners.ready(); f.pi.events.emit('subagent:async-started', f.start);
  assert.deepEqual(await f.verify(), [proof()]);
});

test('coordinator-only managed reports need no assignment graph or native run', async t => {
  const f = fixture(t);
  assert.deepEqual(await f.verify(), []);
});

for (const [name, mutate] of [
  ['pending proof', f => f.setProof({ ...proof(), state: 'pending' })],
  ['foreign run proof', f => f.setProof({ ...proof(), runId: 'foreign' })],
  ['foreign instance', f => { f.status.processTerminal.runnerProcessInstanceId = 'foreign'; f.save(); }],
  ['missing close', f => { const p = proof(); p.instances = []; f.setProof(p); }],
  ['active lease', f => { const p = proof(); p.canonicalSession = { canonicalSessionId: 'canonical', leaseDisposition: 'released', freeAtObservation: false }; f.setProof(p); }],
  ['external runner', f => { f.status.steps[0].runner = { type: 'external-job' }; f.save(); }],
  ['unknown runner', f => { f.status.steps[0].runner = { type: 'future-runner' }; f.save(); }],
  ['foreign status', f => { f.status.sessionId = 'foreign'; f.save(); }],
  ['nested owner', f => { f.status.nestedChildren = [{}]; f.save(); }],
  ['nonterminal runner', f => { f.status.state = 'running'; f.save(); }],
  ['missing status', f => fs.unlinkSync(join(f.path, 'status.json'))],
  ['malformed status', f => fs.writeFileSync(join(f.path, 'status.json'), '{broken')],
]) test(`managed handoff refuses ${name}`, async t => {
  const f = fixture(t); f.pi.events.emit('subagent:async-started', f.start); mutate(f); await assert.rejects(f.verify());
});

test('unresolved native launch calls block handoff without a replacement manifest', async t => {
  const f = fixture(t);
  f.owners.observeTool({ toolName: 'subagent', toolCallId: 'pending', args: { agent: 'worker', async: true } });
  await assert.rejects(f.verify(), /ownership changed/);
});

test('unsupported, duplicated or foreign native launch events cannot be ignored', async t => {
  for (const mutate of [e => e.mode = 'workflow', e => e.sessionId = 'foreign', e => e.parentWorkflowRunId = 'parent', e => e.lifecycleArtifactVersion = 2]) {
    const f = fixture(t); const event = { ...f.start }; mutate(event); f.pi.events.emit('subagent:async-started', event); await assert.rejects(f.verify(), /unsupported/);
  }
  const f = fixture(t); f.pi.events.emit('subagent:async-started', f.start); f.pi.events.emit('subagent:async-started', f.start); await assert.rejects(f.verify());
});

test('unsupported foreground tool result and failed launch create durable-in-session halt', async t => {
  const f = fixture(t); f.owners.observeTool({ toolName: 'subagent', toolCallId: 'call-1', args: { agent: 'worker', async: false } });
  f.owners.observeTool({ toolName: 'subagent', toolCallId: 'call-1', result: { details: { mode: 'single', runId: 'foreground' } } });
  await assert.rejects(f.verify(), /unsupported/);
  assert.throws(() => validateProcessTerminal({ ...proof(), state: 'unknown' }, 'run-1'));
});

test('native projections detect known unknown/active/omitted owners without claiming arbitrary descendant coverage', async t => {
  for (const mutate of [p => p.fleet.totalActive = 1, p => p.fleet.omitted = 1, p => p.asyncSnapshot.runs.push({ id: 'foreign' }), p => p.asyncSnapshot.omitted.children = 1, p => p.asyncSnapshot.omitted.byteLimitExceeded = true]) {
    const f = fixture(t); mutate(f.projection); await assert.rejects(f.owners.ready(), /ownership projection/);
  }
});

test('every captured start is checked even without model-supplied run ids', async t => {
  const f = fixture(t); f.pi.events.emit('subagent:async-started', f.start);
  f.pi.events.emit('subagent:async-started', { ...f.start, id: 'run-2' });
  await assert.rejects(f.verify(), /foreign/);
});

test('a native start during final ownership recheck prevents handoff', async t => {
  const f = fixture(t), request = f.owners.request;
  f.owners.request = async (method, params) => {
    const value = await request(method, params);
    if (method === 'status' && !params?.id) f.pi.events.emit('subagent:async-started', f.start);
    return value;
  };
  await assert.rejects(f.verify(), /ownership changed/);
});

for (const state of ['queued', 'running', 'complete', 'failed', 'paused', 'stopped']) test(`native continuation observes ${state} without inferring task success`, async t => {
  const { NativeContinuation } = await import('../../extensions/linear/managed.mjs');
  const f = fixture(t), continuation = new NativeContinuation(f.pi, f.ctx, f.owners.request); t.after(() => continuation.dispose());
  f.status.state = state; f.save(); f.pi.events.emit('subagent:async-started', f.start);
  const pending = await continuation.pending();
  if (['queued', 'running'].includes(state)) assert.deepEqual(pending, { running: ['run-1'], completed: [] });
  else {
    assert.deepEqual(pending, { running: [], completed: [{ id: 'run-1', state }] });
    continuation.observeMessage({ customType: 'subagent-notify', details: { runs: [{ runId: 'foreign' }] } });
    assert.deepEqual(await continuation.pending(), pending);
    continuation.observeMessage({ customType: 'subagent-notify', details: { runs: [{ runId: 'run-1' }] } });
    assert.deepEqual(await continuation.pending(), { running: [], completed: [] });
  }
});

test('native continuation fails closed on unknown or missing status and foreign starts', async t => {
  const { NativeContinuation } = await import('../../extensions/linear/managed.mjs');
  const f = fixture(t), continuation = new NativeContinuation(f.pi, f.ctx, f.owners.request); t.after(() => continuation.dispose());
  f.pi.events.emit('subagent:async-started', f.start);
  f.status.state = 'future-state'; f.save(); await assert.rejects(continuation.pending(), /unknown async state/);
  fs.unlinkSync(join(f.path, 'status.json')); await assert.rejects(continuation.pending());
  f.pi.events.emit('subagent:async-started', { ...f.start, id: 'foreign', sessionId: 'foreign' });
  await assert.rejects(continuation.pending(), /ownership could not be confirmed/);
});
