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
  const wf = { status: 'completed', decisions: [], selections: [{ stages: [{ attempts: [{ status: 'passed', assignments: [{ assignment: 'worker-1', dispatch: 'confirmed' }] }] }] }] };
  const checkpoint = { status: 'completed', run_ids: ['run-1'] };
  return { pi, ctx, path, status, save, owners, start, wf, checkpoint, projection, setProof: p => { nativeProof = p; }, verify: () => owners.verify(root, wf, async () => checkpoint) };
}

test('managed rpc subscribes before sending and validates exact version/request', async () => {
  const pi = { events: bus() };
  const off = pi.events.on('subagents:rpc:v1:request', req => pi.events.emit(`subagents:rpc:v1:reply:${req.requestId}`, { version: 1, requestId: req.requestId, success: true, data: { ok: true } }));
  assert.deepEqual(await nativeRequest(pi, 'ping'), { ok: true }); off();
  await assert.rejects(nativeRequest(pi, 'ping', {}, 10), /timeout/);
});

test('managed handoff checks captured live starts, exact public native proof and all assignment ids', async t => {
  const f = fixture(t); await f.owners.ready(); f.pi.events.emit('subagent:async-started', f.start);
  assert.deepEqual(await f.verify(), [proof()]);
  f.checkpoint.run_ids.push('unknown-run'); await assert.rejects(f.verify(), /unknown/);
});

test('empty managed assignments are valid only under the caller acknowledged trust contract', async t => {
  const f = fixture(t); f.wf.selections[0].stages[0].attempts[0].assignments = [];
  assert.deepEqual(await f.verify(), []);
  f.pi.events.emit('subagent:async-started', f.start); await assert.rejects(f.verify(), /missing from workflow/);
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
  ['pending workflow', f => { f.wf.status = 'active'; }],
  ['publication intent', f => { f.wf.selections[0].stages[0].attempts[0].status = 'active'; }],
  ['dispatch intent', f => { f.wf.selections[0].stages[0].attempts[0].assignments[0].dispatch = 'intent'; }],
  ['missing recorded ids', f => { f.checkpoint.run_ids = []; }],
  ['active checkpoint', f => { f.checkpoint.status = 'active'; }],
]) test(`managed handoff refuses ${name}`, async t => {
  const f = fixture(t); f.pi.events.emit('subagent:async-started', f.start); mutate(f); await assert.rejects(f.verify());
});

test('blocked workflow intents require explicit recorded reconciliation, not model booleans', async t => {
  const f = fixture(t); f.pi.events.emit('subagent:async-started', f.start);
  f.wf.status = 'blocked'; const attempt = f.wf.selections[0].stages[0].attempts[0]; attempt.status = 'blocked'; attempt.stopped = true;
  await assert.rejects(f.verify(), /reconciliation/);
  attempt.outcome = 'owners stopped; publication receipt reconciled'; attempt.evidence = ['report']; attempt.decision = 'reconcile-1'; f.wf.decisions.push({ id: 'reconcile-1', kind: 'reconciliation', evidence: ['report'] });
  assert.equal((await f.verify()).length, 1);
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
