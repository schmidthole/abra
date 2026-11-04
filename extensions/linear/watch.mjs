import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { StringDecoder } from 'node:string_decoder';
import { once } from 'node:events';
import * as fs from 'node:fs';
import { join } from 'node:path';
import { configuration, readJson, Store, requireValue } from './core.mjs';

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
            requireValue(event.success === true, 'rpc command failed');
            pending.resolve(event.data);
          } else {
            requireValue(event.type !== 'extension_error', 'pi extension error');
            this.onEvent(event);
          }
        }
      } catch { this.fail(new Error('malformed, failed or uncertain rpc protocol; reconcile child/session owners')); }
    });
    // do not expose model/tool/credential stderr as watch diagnostics; continuously drain it.
    child.stderr.on('data', () => {});
    child.on('error', () => this.fail(new Error('pi child startup/io failed')));
    child.stdin.on('error', () => this.fail(new Error('pi child stdin failed')));
    child.on('close', (code, signal) => {
      this.resolveClose({ code, signal });
      if (!this.ending || code !== 0 || this.buffer || this.decoder.end()) this.fail(new Error('pi child exited without confirmed orderly handoff; reconcile surviving owners'));
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
      const timer = setTimeout(() => this.fail(new Error('rpc command timeout; no automatic retry')), this.timeoutMs);
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
      reject(new Error('pi shutdown timeout; child/native owners may survive; reconcile manually'));
    }, this.timeoutMs); });
    try {
      const result = await Promise.race([this.closed, timeout]);
      requireValue(result.code === 0 && !result.signal && !this.error, 'pi shutdown failed or protocol uncertain; surviving ownership unknown');
    } finally { clearTimeout(timer); }
  }
}

function released(root, config, outcome) {
  const store = new Store(root, config), state = store.load();
  const record = state.records.find(r => r.id === outcome.issue);
  requireValue(!fs.existsSync(store.lock) && state.active === null && record?.session === outcome.session && record.taskId === outcome.task && record.terminal === outcome.outcome && record.releaseEvidence && Array.isArray(record.managedProofs) && record.publications.every(p => p.comment && p.comment !== 'intent' && (!p.stateId || p.state === 'confirmed')), 'handoff disagrees with durable connector/lock/publication receipts');
}

export async function runWatch({ root = process.cwd(), configDirectory = '.pi', pi = 'pi', acknowledge = false, signal, intervalMs = 1000, timeoutMs = 60000, spawnChild = (command, args, options) => spawn(command, args, options), diagnose = event => process.stderr.write(JSON.stringify(event) + '\n') } = {}) {
  requireValue(process.platform !== 'win32', 'foreground watch currently requires posix signal/process-group semantics');
  requireValue(acknowledge, 'explicit trusted managed-work acknowledgment required');
  const config = configuration(readJson(join(root, configDirectory, 'abra-linear.json')));
  requireValue(config.watch?.trustedManagedWork === true, 'configure watch.trustedManagedWork first');
  let stop = signal?.aborted ?? false;
  const interrupt = () => { stop = true; };
  signal?.addEventListener('abort', interrupt);
  try {
    while (!stop) {
      const store = new Store(root, config);
      requireValue(!store.load().active && !fs.existsSync(store.lock), 'existing tracked ownership/lock blocks watch; no automatic recovery');
      const nonce = randomUUID();
      let ready, admitted, outcome, expected, reported, stopDeadline, stopped = false, phase = 'fresh-child-state';
      const child = spawnChild(pi, ['--mode', 'rpc'], { cwd: root, detached: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ABRA_LINEAR_WATCH_NONCE: nonce } });
      const rpc = new RpcChild(child, event => {
        if (event.type === 'extension_ui_request') {
          if (['select', 'confirm', 'input', 'editor'].includes(event.method)) diagnose({ state: 'awaiting-input', note: 'session retained; no automatic dialog approval; interrupt and reconcile manually if needed' });
          return;
        }
        if (event.type !== 'entry_appended' || event.entry?.customType !== 'abra-linear-watch') return;
        const data = event.entry.data;
        requireValue(data?.version === 1 && data.nonce === nonce && data.session === initial.sessionId, 'foreign watch outcome');
        if (data.state === 'ready') {
          requireValue(!ready && data.request === 'start' && data.sessionFile && data.owner, 'duplicate/out-of-order watch ready'); ready = data;
        } else {
          requireValue(ready && data.owner === ready.owner && !outcome, 'out-of-order/duplicate watch outcome');
          if (data.state === 'admitted') {
            requireValue(!admitted && data.request === 'start' && data.issue && data.task === `linear-${data.issue}`, 'invalid/duplicate admission'); admitted = data;
          } else {
            requireValue(data.request === expected && reported !== expected, 'uncorrelated/duplicate watch outcome');
            reported = expected;
            if (data.state === 'uncertain') {
              diagnose({ state: 'uncertain', session: data.session, issue: data.issue, diagnostic: typeof data.diagnostic === 'string' ? data.diagnostic.slice(0, 300) : 'connector/native ownership uncertain' });
              throw new Error('connector state uncertain');
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
        requireValue(initial?.sessionId && initial.messageCount === 0 && initial.pendingMessageCount === 0 && !initial.isStreaming && !initial.isCompacting, 'pi child is not a fresh idle session');
        expected = 'start'; phase = 'extension-start';
        await rpc.command('prompt', { message: `/abra-linear watch-start ${nonce}` });
        requireValue(ready, 'extension did not confirm watch start');
        while (!outcome) {
          phase = stop ? 'interruption-reconciliation' : 'extension-outcome';
          const request = randomUUID(); expected = request;
          const command = stop && !stopped ? 'watch-stop' : 'watch-check';
          if (command === 'watch-stop') { stopped = true; stopDeadline = Date.now() + timeoutMs; }
          await rpc.command('prompt', { message: `/abra-linear ${command} ${nonce} ${request}` });
          requireValue(reported === request, 'command accepted without explicit connector outcome');
          if (stopped && !outcome && Date.now() >= stopDeadline) throw new Error('interrupted with tracked owners; reconcile saved session/workflow/native runs before restart');
          if (!outcome) await Promise.race([new Promise(resolve => setTimeout(resolve, intervalMs)), rpc.failure]);
        }
        phase = 'handoff-session-and-receipts';
        const state = await rpc.command('get_state');
        requireValue(state.sessionId === initial.sessionId && !state.isStreaming && !state.isCompacting && state.pendingMessageCount === 0, 'coordinator resumed or session changed after handoff');
        if (outcome.state === 'handoff') released(root, config, outcome);
        phase = 'child-shutdown';
        await rpc.close();
      } catch (error) {
        diagnose({ state: 'halted', phase, session: initial?.sessionId ?? null, issue: admitted?.issue ?? null, note: 'no restart; preserve connector/session/workflow/checkpoints; surviving native owners are not disproved by child shutdown' });
        try { await rpc.close(); } catch { /* preserve original failure; shutdown is not owner proof. */ }
        throw error;
      }
      if (stopped) stop = true;
    }
    diagnose({ state: 'stopped', note: 'foreground watch ended; no unattended execution promised' });
  } finally { signal?.removeEventListener('abort', interrupt); }
}
