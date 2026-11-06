import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { StringDecoder } from 'node:string_decoder';
import { once } from 'node:events';
import * as fs from 'node:fs';
import { join } from 'node:path';
import { configuration, readJson, Store, requireValue } from './core.mjs';
import { WatchFailure, failureCode, diagnosticCode, diagnosticText, requireWatch } from './diagnostics.mjs';

// strict lf framing: unicode separators are legal inside json strings.
export class RpcChild {
  constructor(child, onEvent, timeoutMs = 60000) {
    this.child = child; this.onEvent = onEvent; this.timeoutMs = timeoutMs; this.pending = new Map(); this.buffer = ''; this.decoder = new StringDecoder('utf8'); this.ending = false;
    this.closed = new Promise(resolve => { this.resolveClose = resolve; });
    this.failure = new Promise((_, reject) => { this.reject = reject; });
    this.failure.catch(() => {});
    child.stdout.on('data', chunk => {
      try {
        this.buffer += this.decoder.write(chunk);
        requireValue(Buffer.byteLength(this.buffer) <= 4 * 1024 * 1024, 'oversized rpc record');
        let index;
        while ((index = this.buffer.indexOf('\n')) !== -1) {
          const line = this.buffer.slice(0, index).replace(/\r$/, ''); this.buffer = this.buffer.slice(index + 1);
          const event = JSON.parse(line);
          requireValue(event && typeof event.type === 'string', 'malformed rpc object');
          if (event.type === 'response') {
            const pending = this.pending.get(event.id);
            requireValue(pending && pending.type === event.command, 'unknown/duplicate rpc response');
            this.pending.delete(event.id); clearTimeout(pending.timer);
            requireWatch(event.success === true, 'rpc-command-failed');
            pending.resolve(event.data);
          } else {
            requireWatch(event.type !== 'extension_error', 'extension-failed');
            this.onEvent(event);
          }
        }
      } catch (error) { this.fail(error instanceof WatchFailure ? error : new WatchFailure('rpc-protocol-invalid')); }
    });
    // do not expose model/tool/credential stderr as watch diagnostics; continuously drain it.
    child.stderr.on('data', () => {});
    child.on('error', () => this.fail(new WatchFailure('child-start-failed')));
    child.stdin.on('error', () => this.fail(new WatchFailure('child-stdin-failed')));
    child.on('close', (code, signal) => {
      this.resolveClose({ code, signal });
      if (!this.ending || code !== 0 || this.buffer || this.decoder.end()) this.fail(new WatchFailure('child-exited'));
    });
  }
  fail(error) {
    this.error ??= error;
    this.reject(error);
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error); }
    this.pending.clear();
  }
  async command(type, args = {}) {
    const id = randomUUID();
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => this.fail(new WatchFailure('rpc-timeout')), this.timeoutMs);
      this.pending.set(id, { type, resolve, reject, timer });
    });
    reply.catch(() => {});
    if (!this.child.stdin.write(JSON.stringify({ id, type, ...args }) + '\n')) await Promise.race([once(this.child.stdin, 'drain'), this.failure]);
    return Promise.race([reply, this.failure]);
  }
  async close() {
    this.ending = true; this.child.stdin.end();
    let timer;
    const timeout = new Promise((_, reject) => { timer = setTimeout(() => {
      this.child.kill('SIGTERM');
      this.child.unref(); this.child.stdin.destroy(); this.child.stdout.destroy(); this.child.stderr.destroy();
      reject(new WatchFailure('shutdown-timeout'));
    }, this.timeoutMs); });
    try {
      const result = await Promise.race([this.closed, timeout]);
      requireWatch(result.code === 0 && !result.signal && !this.error, 'shutdown-failed');
    } finally { clearTimeout(timer); }
  }
}

function released(root, config, outcome) {
  const store = new Store(root, config), state = store.load();
  const record = state.records.find(r => r.id === outcome.issue);
  requireValue(!fs.existsSync(store.lock) && state.active === null && record?.session === outcome.session && record.bound === true && record.dispatch === 'sent' && (record.terminal !== 'review' || record.delivery) && record.taskId === outcome.task && record.terminal === outcome.outcome && record.releaseEvidence && Array.isArray(record.managedProofs) && record.publications.every(p => p.comment && p.comment !== 'intent' && (!p.stateId || p.state === 'confirmed')), 'handoff disagrees with durable connector/lock/publication receipts');
}

// display only allowlisted descriptions and validated ids, never remote prose or raw streams.
export function createWatchReporter({ write = line => process.stderr.write(line), now = Date.now, heartbeatMs = 60000 } = {}) {
  let previous, lastOutput = 0, interrupted = false, dialog = false;
  return event => {
    const task = typeof event.issue === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(event.issue) ? ` [task linear-${event.issue}]` : '';
    let message;
    switch (event.state) {
      case 'starting': message = 'starting; checking configuration and saved ownership before opening a coordinator. ctrl-c requests a safe stop.'; break;
      case 'starting-session':
        dialog = false;
        message = 'opening a fresh pi session; waiting for saved bootstrap and connector checks. no action needed.'; break;
      case 'ready': message = 'connector ready; checking for eligible delegated linear issues within the configured scope.'; break;
      case 'admitted': message = 'picked up a delegated issue; the coordinator will handle this task within the configured authority. no action needed.'; break;
      case 'no-work': message = 'waiting for an eligible delegated issue; none admitted. checking automatically; no action needed.'; break;
      case 'working': message = 'task in progress; waiting for the coordinator, confirmed reporting and proof that all tracked workers have stopped. no action needed unless input is requested.'; break;
      case 'awaiting-input':
        if (event.reason === 'dialog') dialog = true;
        message = 'action needed: read the clarification on the linear issue and reply there. this session is retained; replies require manual saved-steering and owner reconciliation, not automatic resumption. see docs/linear-polling.md.'; break;
      case 'interrupted':
        interrupted = true;
        message = 'stop requested; no further sessions will open. requesting admission stop and owner reconciliation; please wait. shutdown alone does not prove workers stopped.'; break;
      case 'handoff': message = event.outcome === 'blocked'
        ? 'coordinator reports this task blocked; checking saved reporting, ownership receipts and session shutdown before any handoff. this is not successful delivery.'
        : 'coordinator reports output ready for review; checking saved delivery, reporting and ownership receipts before closing the session. handoff is not yet confirmed.'; break;
      case 'session-closed': message = event.outcome === 'blocked'
        ? 'safe handoff confirmed and coordinator closed; task remains blocked. action needed: inspect the linear blocker and next steps. the issue is not completed.'
        : event.outcome === 'review'
          ? 'safe handoff confirmed and coordinator closed; output awaits review in linear. no merge or issue completion is implied.'
          : 'coordinator closed cleanly after stopping; no new work will start.'; break;
      case 'stopped': message = event.ended
        ? 'watch stopped; no further sessions will open and no unattended execution is promised.'
        : 'connector stopped admission; checking the session is idle before closing it. please wait.'; break;
      case 'uncertain': message = `action needed: ${diagnosticText(event.code)}. connector, reporting or worker ownership is uncertain. halting without retry; preserve the saved session and receipts for manual reconciliation. see docs/linear-polling.md.`; break;
      case 'halted': {
        const phases = new Map(Object.entries({
          'startup': 'checking launcher configuration and saved ownership',
          'fresh-child-state': 'starting the pi session',
          'extension-start': 'starting the connector',
          'extension-outcome': 'checking task status',
          'interruption-reconciliation': 'stopping and reconciling workers',
          'handoff-session-and-receipts': 'validating the handoff receipts and idle session',
          'child-shutdown': 'waiting for the coordinator to close',
        }));
        message = `halted while ${phases.get(event.phase) ?? 'checking watch safety'}: ${diagnosticText(event.code)}. action needed: preserve connector receipts, saved session, task and worker artifacts; reconcile owners before restarting. child shutdown is not proof workers stopped. no automatic retry or lock removal; see docs/linear-polling.md.`;
        break;
      }
      default: return;
    }
    const polling = ['no-work', 'working', 'awaiting-input'].includes(event.state);
    if (polling && dialog) message = 'action needed: a session dialog requested input; watch cannot answer or approve it. if still waiting, use ctrl-c, reconcile owners and reopen the saved pi session manually. no automatic approval; see docs/linear-polling.md.';
    if (polling && interrupted) message = 'stop in progress; waiting for confirmed reporting and stopped-worker evidence. session retained; if shutdown cannot be confirmed, manual reconciliation is required. please wait.';
    const text = message + task, time = now(), unchanged = text === previous;
    if (unchanged && (!polling || time - lastOutput < heartbeatMs)) return;
    write(`[${new Date(time).toISOString().slice(11, 19)} utc] linear watch: ${unchanged ? 'still checking: ' : ''}${text}\n`);
    previous = text; lastOutput = time;
  };
}

export async function runWatch({ root = process.cwd(), configDirectory = '.pi', pi = 'pi', acknowledge = false, signal, intervalMs = 1000, timeoutMs = 60000, spawnChild = (command, args, options) => spawn(command, args, options), diagnose = createWatchReporter() } = {}) {
  diagnose({ state: 'starting' });
  let phase = 'startup', halted = false;
  try {
    requireWatch(process.platform !== 'win32', 'platform-unsupported');
    requireWatch(acknowledge, 'acknowledgment-required');
    let config;
    try { config = configuration(readJson(join(root, configDirectory, 'abra-linear.json'))); }
    catch { throw new WatchFailure('configuration-invalid'); }
    requireWatch(config.watch?.trustedManagedWork === true, 'watch-opt-in-required');
    let stop = signal?.aborted ?? false;
    const interrupt = () => { if (!stop) diagnose({ state: 'interrupted' }); stop = true; };
    signal?.addEventListener('abort', interrupt);
    try {
      while (!stop) {
        phase = 'startup';
        const store = new Store(root, config);
        let saved;
        try { saved = store.load(); } catch { throw new WatchFailure('journal-invalid'); }
        requireWatch(!saved.active && !fs.existsSync(store.lock), 'ownership-unresolved');
        const nonce = randomUUID();
        let ready, admitted, outcome, expected, reported, stopDeadline, bootstrapped, stopped = false;
        phase = 'fresh-child-state';
        diagnose({ state: 'starting-session' });
        let child;
        try { child = spawnChild(pi, ['--mode', 'rpc'], { cwd: root, detached: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ABRA_LINEAR_WATCH_NONCE: nonce } }); }
        catch { throw new WatchFailure('child-start-failed'); }
        const rpc = new RpcChild(child, event => {
          if (event.type === 'extension_ui_request') {
            if (['select', 'confirm', 'input', 'editor'].includes(event.method)) diagnose({ state: 'awaiting-input', reason: 'dialog', note: 'session retained; no automatic dialog approval; interrupt and reconcile manually if needed' });
            return;
          }
          if (event.type !== 'entry_appended' || event.entry?.customType !== 'abra-linear-watch') return;
          const data = event.entry.data;
          requireValue(data?.version === 1 && data.nonce === nonce && data.session === (bootstrapped?.sessionId ?? initial.sessionId), 'foreign watch outcome');
          if (data.state === 'ready') {
            requireValue(!ready && expected === 'start' && data.request === 'start' && bootstrapped && data.sessionFile === bootstrapped.sessionFile && data.previousSession === initial.sessionId && data.owner, 'duplicate/out-of-order watch ready'); ready = data;
            diagnose({ state: 'ready', session: data.session });
          } else {
            // a failed start can report uncertainty, never readiness or stopped ownership.
            if (!ready && data.state === 'uncertain' && expected === 'start' && data.request === 'start' && !admitted) throw new WatchFailure(diagnosticCode(data.code));
            requireValue(ready && data.owner === ready.owner && !outcome, 'out-of-order/duplicate watch outcome');
            if (data.state === 'admitted') {
              requireValue(!admitted && data.request === 'start' && data.issue && data.task === `linear-${data.issue}`, 'invalid/duplicate admission'); admitted = data;
              diagnose({ state: 'admitted', session: data.session, issue: data.issue });
            } else {
              requireValue(data.request === expected && reported !== expected, 'uncorrelated/duplicate watch outcome');
              reported = expected;
              if (data.state === 'uncertain') {
                diagnose({ state: 'uncertain', session: data.session, issue: data.issue, code: diagnosticCode(data.code) });
                throw new WatchFailure(diagnosticCode(data.code));
              }
              requireValue(['no-work', 'working', 'awaiting-input', 'handoff', 'stopped'].includes(data.state), 'unknown watch state');
              if (data.state === 'handoff') {
                requireValue(admitted && data.issue === admitted.issue && data.task === admitted.task && ['review', 'blocked'].includes(data.outcome), 'wrong task handoff'); outcome = data;
              } else if (data.state === 'stopped') {
                requireValue(stopped && !admitted, 'invalid stopped outcome'); outcome = data;
              } else requireValue(data.state === 'no-work' ? !admitted && !data.issue : admitted && data.issue === admitted.issue && data.task === admitted.task, 'watch task correlation changed');
              diagnose({ state: data.state, session: data.session, issue: data.issue, outcome: data.outcome, runs: data.runs });
            }
          }
        }, timeoutMs);
        let initial;
        try {
          initial = await rpc.command('get_state');
          requireWatch(initial?.sessionId && initial.messageCount === 0 && initial.pendingMessageCount === 0 && !initial.isStreaming && !initial.isCompacting, 'session-not-idle');
          expected = 'start'; phase = 'extension-start';
          await rpc.command('prompt', { message: `/abra-linear watch-start ${nonce}` });
          bootstrapped = await rpc.command('get_state');
          requireWatch(bootstrapped?.sessionId && bootstrapped.sessionId !== initial.sessionId && bootstrapped.sessionFile && bootstrapped.messageCount === 1 && bootstrapped.pendingMessageCount === 0 && !bootstrapped.isStreaming && !bootstrapped.isCompacting, 'session-not-idle');
          await rpc.command('prompt', { message: `/abra-linear watch-arm ${nonce} ${initial.sessionId}` });
          requireWatch(ready, 'outcome-missing');
          while (!outcome) {
            phase = stop ? 'interruption-reconciliation' : 'extension-outcome';
            const request = randomUUID(); expected = request;
            const command = stop && !stopped ? 'watch-stop' : 'watch-check';
            if (command === 'watch-stop') { stopped = true; stopDeadline = Date.now() + timeoutMs; }
            await rpc.command('prompt', { message: `/abra-linear ${command} ${nonce} ${request}` });
            requireWatch(reported === request, 'outcome-missing');
            if (stopped && !outcome && Date.now() >= stopDeadline) throw new WatchFailure('stop-unresolved');
            if (!outcome) await Promise.race([new Promise(resolve => setTimeout(resolve, intervalMs)), rpc.failure]);
          }
          phase = 'handoff-session-and-receipts';
          const state = await rpc.command('get_state');
          requireWatch(state.sessionId === ready.session && !state.isStreaming && !state.isCompacting && state.pendingMessageCount === 0, 'session-not-idle');
          if (outcome.state === 'handoff') {
            try { released(root, config, outcome); } catch { throw new WatchFailure('handoff-invalid'); }
          }
          phase = 'child-shutdown';
          await rpc.close();
          diagnose({ state: 'session-closed', issue: admitted?.issue, outcome: outcome.outcome });
        } catch (error) {
          halted = true;
          diagnose({ state: 'halted', phase, code: failureCode(error), session: initial?.sessionId ?? null, issue: admitted?.issue ?? null, note: 'no restart; preserve connector/session/task/native artifacts; surviving native owners are not disproved by child shutdown' });
          try { await rpc.close(); } catch { /* preserve original failure; shutdown is not owner proof. */ }
          throw error;
        }
        if (stopped) stop = true;
      }
      diagnose({ state: 'stopped', ended: true, note: 'foreground watch ended; no unattended execution promised' });
    } finally { signal?.removeEventListener('abort', interrupt); }
  } catch (error) {
    if (!halted) diagnose({ state: 'halted', phase, code: failureCode(error) });
    throw error;
  }
}
