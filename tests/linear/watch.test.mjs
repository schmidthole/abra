import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { runWatch } from '../../extensions/linear/watch.mjs';
import { configuration, readJson, Store } from '../../extensions/linear/core.mjs';

const root = resolve('.');
function fixture(t, scenario, stopAfter = 1) {
  fs.mkdirSync(join(root, '.cache/watch-tests'), { recursive: true });
  const path = fs.mkdtempSync(join(root, '.cache/watch-tests/trial-'));
  fs.mkdirSync(join(path, '.pi'));
  const cfg = readJson(join(root, 'docs/linear.example.json')); cfg.watch = { trustedManagedWork: true };
  fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(cfg));
  const controller = new AbortController(), diagnostics = [], log = join(path, 'children.log');
  let count = 0, spawned = 0;
  const options = { root: path, acknowledge: true, signal: controller.signal, timeoutMs: 300, intervalMs: 1,
    spawnChild: (_command, args, options) => {
      spawned++; assert.deepEqual(args, ['--mode', 'rpc']);
      return spawn(process.execPath, [join(root, 'tests/linear/fixtures/rpc-child.mjs')], { ...options, env: { ...options.env, WATCH_TEST_SCENARIO: scenario, WATCH_TEST_LOG: log } });
    },
    diagnose: event => {
      diagnostics.push(event);
      if (['no-work', 'awaiting-input'].includes(event.state) && ++count >= stopAfter) controller.abort();
      if (event.state === 'handoff' && scenario !== 'multiple') controller.abort();
    },
  };
  t.after(() => fs.rmSync(path, { recursive: true, force: true }));
  return { path, options, diagnostics, controller, spawned: () => spawned, cfg: configuration(cfg), log };
}

test('watch uses fresh persisted rpc children only after confirmed review handoffs', async t => {
  const f = fixture(t, 'multiple', 3);
  await runWatch(f.options);
  assert.equal(f.spawned(), 3);
  assert.equal(new Set(fs.readFileSync(f.log, 'utf8').trim().split('\n')).size, 3);
  assert.equal(f.diagnostics.filter(d => d.state === 'handoff').length, 2);
  assert.equal(new Store(f.path, f.cfg).load().records.length, 2);
});

test('no work retains one child across polls and interruption closes without restart', async t => {
  const f = fixture(t, 'no-work', 4); await runWatch(f.options);
  assert.equal(f.spawned(), 1); assert.equal(f.diagnostics.filter(d => d.state === 'no-work').length, 4);
  assert.ok(!fs.existsSync(join(f.path, 'data/linear/owner.lock')));
});

test('blocked safe handoff can advance but does not claim review success', async t => {
  const f = fixture(t, 'blocked'); await runWatch(f.options);
  assert.equal(f.spawned(), 1); assert.equal(f.diagnostics.find(d => d.state === 'handoff').outcome, 'blocked');
});

test('clarification retains the active session, then interruption reports unresolved owners', async t => {
  const f = fixture(t, 'clarification', 3);
  await assert.rejects(runWatch(f.options), /tracked owners/);
  assert.equal(f.spawned(), 1); assert.ok(f.diagnostics.filter(d => d.state === 'awaiting-input').length >= 3);
  assert.ok(new Store(f.path, f.cfg).load().active);
});

test('rpc dialog is never automatically approved and retains its child', async t => {
  const f = fixture(t, 'dialog', 2); await runWatch(f.options);
  assert.equal(f.spawned(), 1); assert.ok(f.diagnostics.some(d => d.state === 'awaiting-input'));
});

for (const scenario of ['crash', 'malformed', 'failed-prompt', 'timeout', 'duplicate-ready', 'duplicate-handoff', 'out-of-order', 'wrong-session', 'wrong-task', 'wrong-nonce', 'wrong-request', 'missing-outcome', 'uncertain', 'auth-loss', 'unknown-owner', 'uncertain-publication', 'lock-retained', 'unreleased', 'pending']) {
  test(`watch halts without restart on ${scenario}`, async t => {
    const f = fixture(t, scenario);
    await assert.rejects(runWatch(f.options));
    assert.equal(f.spawned(), 1);
    assert.ok(f.diagnostics.some(d => d.state === 'halted'));
  });
}

test('watch startup failure, missing trust and preexisting locks never retry', async t => {
  const f = fixture(t, 'no-work');
  await assert.rejects(runWatch({ ...f.options, acknowledge: false }), /acknowledgment/); assert.equal(f.spawned(), 0);
  const store = new Store(f.path, f.cfg); store.acquire('foreign-owner');
  await assert.rejects(runWatch(f.options), /ownership\/lock/); assert.equal(f.spawned(), 0);
  assert.equal(readJson(join(store.lock, 'owner.json')).session, 'foreign-owner'); store.release();
  await assert.rejects(runWatch({ ...f.options, spawnChild: (_cmd, _args, options) => spawn(join(f.path, 'does-not-exist'), [], options) }), /startup\/io/);
});

test('terminal ctrl-c reaches foreground watch before its separately grouped tracked rpc child', { skip: process.platform === 'win32' }, async t => {
  const f = fixture(t, 'no-work'), signalLog = join(f.path, 'signals.log');
  const child = spawn(join(root, 'bin/linear-watch'), ['--trusted-managed-work', '--pi', join(root, 'tests/linear/fixtures/rpc-child.mjs')], { cwd: f.path, detached: true, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, WATCH_TEST_SCENARIO: 'signal-sequence', WATCH_TEST_LOG: f.log, WATCH_TEST_SIGNAL_LOG: signalLog } });
  let interrupted = false, stderr = '';
  child.stderr.on('data', chunk => {
    stderr += chunk.toString();
    if (!interrupted && stderr.includes('"state":"no-work"')) { interrupted = true; process.kill(-child.pid, 'SIGINT'); }
  });
  const timer = setTimeout(() => child.kill('SIGTERM'), 5000);
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); }); clearTimeout(timer);
  assert.equal(code, 0, stderr); assert.equal(interrupted, true);
  assert.equal(fs.readFileSync(signalLog, 'utf8'), 'stop-command\n');
  assert.ok(!fs.existsSync(join(f.path, 'data/linear/owner.lock')));
});
