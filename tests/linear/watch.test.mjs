import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { runWatch, createWatchReporter } from '../../extensions/linear/watch.mjs';
import { configuration, readJson, Store } from '../../extensions/linear/core.mjs';
import { WatchFailure, failureCode, diagnosticText } from '../../extensions/linear/diagnostics.mjs';

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

for (const scenario of ['crash', 'malformed', 'failed-prompt', 'timeout', 'duplicate-ready', 'duplicate-handoff', 'out-of-order', 'wrong-session', 'wrong-task', 'wrong-nonce', 'wrong-request', 'missing-outcome', 'uncertain', 'auth-loss', 'unknown-owner', 'uncertain-publication', 'lock-retained', 'unreleased', 'pending', 'missing-delivery', 'unbound', 'dispatch-intent']) {
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
  await assert.rejects(runWatch(f.options), /ownership-unresolved/); assert.equal(f.spawned(), 0);
  assert.equal(readJson(join(store.lock, 'owner.json')).session, 'foreign-owner'); store.release();
  await assert.rejects(runWatch({ ...f.options, spawnChild: (_cmd, _args, options) => spawn(join(f.path, 'does-not-exist'), [], options) }), /child-start-failed/);
});

test('terminal ctrl-c reaches foreground watch before its separately grouped tracked rpc child', { skip: process.platform === 'win32' }, async t => {
  const f = fixture(t, 'no-work'), signalLog = join(f.path, 'signals.log');
  const child = spawn(join(root, 'bin/linear-watch'), ['--trusted-managed-work', '--pi', join(root, 'tests/linear/fixtures/rpc-child.mjs')], { cwd: f.path, detached: true, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, WATCH_TEST_SCENARIO: 'signal-sequence', WATCH_TEST_LOG: f.log, WATCH_TEST_SIGNAL_LOG: signalLog } });
  let interrupted = false, stderr = '';
  child.stderr.on('data', chunk => {
    stderr += chunk.toString();
    if (!interrupted && stderr.includes('waiting for an eligible delegated issue')) { interrupted = true; process.kill(-child.pid, 'SIGINT'); }
  });
  const timer = setTimeout(() => child.kill('SIGTERM'), 5000);
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); }); clearTimeout(timer);
  assert.equal(code, 0, stderr); assert.equal(interrupted, true);
  assert.equal(fs.readFileSync(signalLog, 'utf8'), 'stop-command\n');
  assert.ok(!fs.existsSync(join(f.path, 'data/linear/owner.lock')));
});

const issue = '00000000-0000-0000-0000-000000000101';
function reporterFixture() {
  let time = 0;
  const lines = [], diagnose = createWatchReporter({ write: line => lines.push(line), now: () => time });
  return { lines, diagnose, advance: ms => { time += ms; } };
}

test('watch reporter explains lifecycle without treating reported handoff as confirmed delivery', () => {
  const f = reporterFixture();
  for (const state of ['starting', 'starting-session', 'ready', 'no-work', 'admitted', 'working', 'awaiting-input']) f.diagnose({ state, issue: ['admitted', 'working', 'awaiting-input'].includes(state) ? issue : null });
  assert.match(f.lines[0], /checking configuration.*ctrl-c/);
  assert.match(f.lines[1], /fresh saved pi session.*no action needed/);
  assert.match(f.lines[2], /eligible delegated linear issues/);
  assert.match(f.lines[3], /none admitted.*no action needed/);
  assert.match(f.lines[4], new RegExp(`picked up.*task linear-${issue}`));
  assert.match(f.lines[5], /task in progress.*proof.*workers have stopped/);
  assert.match(f.lines[6], /action needed.*reply there.*not automatic resumption/);
  f.diagnose({ state: 'handoff', outcome: 'review', issue });
  assert.match(f.lines.at(-1), /reports output ready for review.*not yet confirmed/);
  f.diagnose({ state: 'session-closed', outcome: 'review', issue });
  assert.match(f.lines.at(-1), /safe handoff confirmed.*awaits review.*no merge or issue completion/);
  f.diagnose({ state: 'stopped', ended: true });
  assert.match(f.lines.at(-1), /watch stopped.*no unattended execution/);
  assert.ok(f.lines.every(line => line.startsWith('[00:00:00 utc] linear watch: ') && line === line.toLowerCase()));
});

test('watch reporter suppresses unchanged polls and emits minute heartbeats without resetting on quiet polls', () => {
  for (const state of ['no-work', 'working', 'awaiting-input']) {
    const f = reporterFixture();
    const event = { state, issue: state === 'no-work' ? null : issue };
    f.diagnose(event);
    for (let i = 0; i < 59; i++) { f.advance(1000); f.diagnose({ ...event, session: `ignored-${i}`, runs: ['not-an-active-worker-count'] }); }
    assert.equal(f.lines.length, 1);
    f.advance(1000); f.diagnose(event);
    assert.equal(f.lines.length, 2);
    assert.match(f.lines[1], /^\[00:01:00 utc\] linear watch: still checking:/);
    f.advance(1000); f.diagnose(event); assert.equal(f.lines.length, 2);
    f.diagnose({ state: state === 'working' ? 'awaiting-input' : 'working', issue });
    assert.equal(f.lines.length, 3);
    f.diagnose({ state: 'working', issue: '00000000-0000-0000-0000-000000000102' });
    assert.equal(f.lines.length, 4);
  }
});

test('watch reporter keeps dialog and interruption guidance visible across unchanged connector polls', () => {
  const f = reporterFixture();
  f.diagnose({ state: 'awaiting-input', reason: 'dialog' });
  assert.match(f.lines.at(-1), /action needed.*cannot answer or approve.*reopen the saved pi session/);
  f.diagnose({ state: 'no-work' });
  assert.equal(f.lines.length, 1);
  f.advance(60000); f.diagnose({ state: 'working' });
  assert.match(f.lines.at(-1), /still checking:.*session dialog/);
  f.diagnose({ state: 'interrupted' });
  assert.match(f.lines.at(-1), /stop requested.*please wait.*does not prove workers stopped/);
  f.diagnose({ state: 'working', issue });
  assert.match(f.lines.at(-1), /stop in progress.*manual reconciliation/);
  assert.doesNotMatch(f.lines.at(-1), /no action needed/);
});

test('watch reporter distinguishes blocked handoff and fails closed without rendering raw diagnostic fields', () => {
  const f = reporterFixture();
  f.diagnose({ state: 'handoff', outcome: 'blocked', issue });
  assert.match(f.lines.at(-1), /blocked.*checking saved reporting.*not successful delivery/);
  f.diagnose({ state: 'session-closed', outcome: 'blocked', issue });
  assert.match(f.lines.at(-1), /task remains blocked.*action needed/);
  for (const state of ['uncertain', 'halted']) f.diagnose({ state, issue: '\x1b[31msecret-id\n', phase: 'private-phase', diagnostic: 'secret-token', note: '/home/private', session: 'secret-session', runs: ['secret-run'] });
  assert.match(f.lines.at(-1), /halted while checking watch safety.*reconcile owners.*no automatic retry or lock removal/);
  f.diagnose({ state: 'halted', phase: 'child-shutdown', issue });
  assert.match(f.lines.at(-1), /waiting for the coordinator to close/);
  const text = f.lines.join('');
  assert.doesNotMatch(text, /secret|private|\x1b|private-phase/);
});

test('watch work events remain injectable on every poll while terminal output stays quiet', async t => {
  const f = fixture(t, 'working'), output = reporterFixture(), capture = f.options.diagnose;
  await runWatch({ ...f.options, diagnose: event => { output.diagnose(event); capture(event); } });
  assert.equal(f.diagnostics.filter(event => event.state === 'working').length, 3);
  assert.equal(output.lines.filter(line => line.includes('task in progress')).length, 1);
  assert.ok(f.diagnostics.findIndex(event => event.state === 'admitted') < f.diagnostics.findIndex(event => event.state === 'working'));
  assert.ok(f.diagnostics.findIndex(event => event.state === 'handoff') < f.diagnostics.findIndex(event => event.state === 'session-closed'));
});

for (const scenario of ['lock-retained', 'pending', 'missing-delivery', 'close-failure']) {
  test(`watch reporter never confirms handoff when ${scenario} fails verification`, async t => {
    const f = fixture(t, scenario), output = reporterFixture(), capture = f.options.diagnose;
    await assert.rejects(runWatch({ ...f.options, diagnose: event => { output.diagnose(event); capture(event); } }));
    assert.match(output.lines.join(''), /handoff is not yet confirmed/);
    assert.ok(output.lines.some(line => line.includes(scenario === 'close-failure' ? 'halted while waiting for the coordinator to close' : 'halted while validating the handoff')));
    assert.ok(!output.lines.some(line => line.includes('safe handoff confirmed')));
    assert.ok(!f.diagnostics.some(event => event.state === 'session-closed'));
  });
}

test('default cli output is plain language and omits raw model, tool, notification and stderr streams', async t => {
  const f = fixture(t, 'noisy');
  const child = spawn(join(root, 'bin/linear-watch'), ['--trusted-managed-work', '--pi', join(root, 'tests/linear/fixtures/rpc-child.mjs')], { cwd: f.path, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, WATCH_TEST_SCENARIO: 'noisy', WATCH_TEST_LOG: f.log } });
  let stdout = '', stderr = '', interrupted = false;
  child.stdout.on('data', chunk => { stdout += chunk; });
  child.stderr.on('data', chunk => {
    stderr += chunk;
    if (!interrupted && stderr.includes('coordinator reports output ready for review')) { interrupted = true; child.kill('SIGINT'); }
  });
  const timer = setTimeout(() => child.kill('SIGTERM'), 5000);
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); }); clearTimeout(timer);
  assert.equal(code, 0, stderr);
  assert.equal(stdout, '');
  assert.match(stderr, /checking configuration/);
  assert.match(stderr, /picked up a delegated issue/);
  assert.match(stderr, /safe handoff confirmed/);
  assert.match(stderr, /watch stopped/);
  assert.doesNotMatch(stderr, /secret-|private|"state"|"type"|"session"/);
});

test('cli configuration and argument failures give safe actionable guidance with nonzero exit', async t => {
  const f = fixture(t, 'no-work');
  for (const args of [[], ['--unknown-secret-option']]) {
    const child = spawn(join(root, 'bin/linear-watch'), args, { cwd: f.path, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
    const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    assert.equal(code, 1); assert.equal(stdout, '');
    assert.match(stderr, /action needed.*--help.*abra-linear.json.*reconcile.*no automatic retry/);
    assert.doesNotMatch(stderr, /unknown-secret-option|"state"/);
  }
  assert.equal(f.spawned(), 0);
});

for (const [scenario, code] of [
  ['failed-check', 'rpc-command-failed'], ['malformed-check', 'rpc-protocol-invalid'],
  ['timeout-check', 'rpc-timeout'], ['extension-error-check', 'extension-failed'],
  ['auth-loss', 'connector-auth-failed'], ['unknown-owner', 'native-ownership-uncertain'],
  ['private-uncertain', 'unknown-failure'], ['missing-outcome', 'outcome-missing'],
]) {
  test(`task-status failure ${scenario} reports a bounded cause and phase without leaking payloads`, async t => {
    const f = fixture(t, scenario), output = reporterFixture(), capture = f.options.diagnose;
    await assert.rejects(runWatch({ ...f.options, diagnose: event => { output.diagnose(event); capture(event); } }), error => error.code === code);
    assert.equal(f.spawned(), 1);
    const halted = f.diagnostics.find(event => event.state === 'halted');
    assert.equal(halted.phase, 'extension-outcome'); assert.equal(halted.code, code);
    assert.match(output.lines.join(''), new RegExp(`halted while checking task status: \\[${code}\\]`));
    assert.doesNotMatch(JSON.stringify(f.diagnostics) + output.lines.join(''), /secret-|ticket-description|credential-file|stack-canary/);
    assert.ok(!f.diagnostics.some(event => event.state === 'session-closed'));
    if (scenario !== 'missing-outcome') assert.ok(new Store(f.path, f.cfg).load().active);
  });
}

test('reporter accepts only exact diagnostic codes and phases, including inherited property names', () => {
  const f = reporterFixture();
  for (const code of ['constructor', '__proto__', 'secret-canary\n/private/path', { message: 'secret-canary' }]) {
    f.diagnose({ state: 'halted', code, phase: 'constructor' });
    assert.match(f.lines.at(-1), /checking watch safety: \[unknown-failure\]/);
  }
  assert.doesNotMatch(f.lines.join(''), /secret-canary|private|function Object/);
});

async function cliResult(path, args, env = {}) {
  const child = spawn(join(root, 'bin/linear-watch'), args, { cwd: path, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, ...env } });
  let stdout = '', stderr = '';
  child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
  const timer = setTimeout(() => child.kill('SIGTERM'), 5000);
  try {
    const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    return { code, stdout, stderr };
  } finally { clearTimeout(timer); }
}

test('launcher distinguishes options, configuration, opt-in, journal, ownership and executable failures safely', async t => {
  const f = fixture(t, 'no-work');
  const args = ['--trusted-managed-work'];
  const cases = [
    { args: ['--private-secret-option'], code: 'options-invalid' },
    { args: ['--pi'], code: 'options-invalid' },
    { args: ['ticket-description'], code: 'options-invalid' },
    { args: [], code: 'acknowledgment-required' },
    { prepare: () => fs.writeFileSync(join(f.path, '.pi/abra-linear.json'), '{secret-token'), code: 'configuration-invalid' },
    { prepare: () => { const cfg = readJson(join(f.path, '.pi/abra-linear.json')); delete cfg.watch; fs.writeFileSync(join(f.path, '.pi/abra-linear.json'), JSON.stringify(cfg)); }, code: 'watch-opt-in-required' },
    { prepare: () => { const store = new Store(f.path, f.cfg); store.load(); fs.writeFileSync(store.path, '{secret-journal'); }, code: 'journal-invalid' },
    { prepare: () => { const store = new Store(f.path, f.cfg); store.acquire('secret-owner'); }, code: 'ownership-unresolved' },
    { args: [...args, '--pi', join(f.path, 'secret-private-executable')], code: 'child-start-failed' },
  ];
  for (const trial of cases) {
    fs.writeFileSync(join(f.path, '.pi/abra-linear.json'), JSON.stringify(f.cfg));
    fs.rmSync(join(f.path, 'data'), { recursive: true, force: true });
    trial.prepare?.();
    const result = await cliResult(f.path, trial.args ?? args);
    assert.equal(result.code, 1, result.stderr); assert.equal(result.stdout, '');
    assert.ok(result.stderr.includes(`[${trial.code}]`), result.stderr);
    assert.match(result.stderr, /action needed:.*no automatic retry or lock removal/);
    assert.doesNotMatch(result.stderr, /secret-|ticket-description|stack|\/Users\/|\/private\//);
    if (trial.code === 'journal-invalid') assert.equal(fs.readFileSync(join(f.path, 'data/linear/connector.json'), 'utf8'), '{secret-journal');
    if (trial.code === 'ownership-unresolved') assert.equal(readJson(join(f.path, 'data/linear/owner.lock/owner.json')).session, 'secret-owner');
  }
  assert.equal(f.spawned(), 0);
});

test('launcher task-status failure prints safe cause and phase, never raw rpc errors or stderr', async t => {
  const f = fixture(t, 'failed-check');
  const result = await cliResult(f.path, ['--trusted-managed-work', '--pi', join(root, 'tests/linear/fixtures/rpc-child.mjs')], { WATCH_TEST_SCENARIO: 'failed-check', WATCH_TEST_LOG: f.log });
  assert.equal(result.code, 1); assert.equal(result.stdout, '');
  assert.match(result.stderr, /halted while checking task status: \[rpc-command-failed\].*pi rejected a control command/);
  assert.doesNotMatch(result.stderr, /secret-|ticket-description|credential-file|stack-canary/);
  assert.equal(fs.readFileSync(f.log, 'utf8').trim().split('\n').length, 1);
});

test('correlated startup uncertainty reports its safe cause without admitting work or retrying', async t => {
  const f = fixture(t, 'start-uncertain');
  await assert.rejects(runWatch(f.options), error => error.code === 'native-ownership-uncertain');
  const halted = f.diagnostics.find(event => event.state === 'halted');
  assert.equal(halted.phase, 'extension-start'); assert.equal(halted.code, 'native-ownership-uncertain');
  assert.equal(f.spawned(), 1); assert.ok(!f.diagnostics.some(event => ['ready', 'admitted', 'session-closed'].includes(event.state)));
  assert.doesNotMatch(JSON.stringify(f.diagnostics), /secret-start-canary/);
});

test('untyped exceptions and forged codes cannot supply terminal diagnostic text', () => {
  const payload = 'secret-exception-canary /private/path ticket-description\nstack-canary';
  for (const error of [new Error(payload), { code: 'connector-auth-failed', message: payload }, payload, null]) {
    assert.equal(failureCode(error), 'unknown-failure');
    assert.doesNotMatch(diagnosticText(failureCode(error)), /secret-|private|ticket-description|stack-canary/);
  }
  assert.equal(failureCode(new WatchFailure('rpc-timeout')), 'rpc-timeout');
  assert.equal(failureCode(new WatchFailure(payload)), 'unknown-failure');
});
