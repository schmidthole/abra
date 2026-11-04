import { join } from 'node:path';
import * as fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import { configuration, readJson, Store, LinearClient, Connector, requireValue } from './core.mjs';
import { ManagedOwners } from './managed.mjs';

const marker = 'abra-linear-dedicated';
const result = message => ({ content: [{ type: 'text', text: message }], details: {} });
export function install(pi, configDirectory = '.pi', dependencies = {}) {
  let connector;
  let dedicated = false;
  let watch;
  let settled = false;
  const emitWatch = (ctx, request, state, extra = {}) => {
    pi.appendEntry('abra-linear-watch', { version: 1, nonce: watch.nonce, request, session: ctx.sessionManager.getSessionId(), owner: connector.store.owner, state, issue: connector.active?.id ?? null, task: connector.active?.taskId ?? null, ...extra });
  };
  const load = ctx => {
    requireValue(ctx.isProjectTrusted(), 'project trust required before reading connector configuration');
    return configuration(readJson(join(ctx.cwd, configDirectory, 'abra-linear.json')));
  };
  const build = ctx => {
    const config = load(ctx);
    const store = new Store(ctx.cwd, config);
    const api = dependencies.api ?? new LinearClient(config, process.env[config.tokenEnv]);
    return new Connector({ root: ctx.cwd, config, store, api, ...dependencies, host: {
      idle: () => ctx.isIdle() && !ctx.hasPendingMessages(),
      send: async prompt => {
        if (watch) emitWatch(ctx, 'start', 'admitted');
        pi.setSessionName(`abra linear coordinator`); pi.sendUserMessage(prompt);
      },
      cancel: async reason => {
        ctx.abort();
        pi.sendUserMessage(`stop new actions: ${reason}. only reconcile/cancel existing native owners, preserve task/manifest evidence and report blocked. aborting pi alone does not prove subagents stopped.`, { deliverAs: 'steer' });
      },
      steer: async message => { pi.sendUserMessage(message, { deliverAs: 'steer' }); },
      notify: message => { if (ctx.hasUI) ctx.ui.notify(message, 'warning'); },
    } });
  };
  pi.on('session_start', async (event, ctx) => {
    const entries = ctx.sessionManager.getBranch();
    dedicated = entries.some(e => e.type === 'custom' && e.customType === marker);
    // only the explicit /start new-session handoff arms polling, never reload/resume.
    if (event.reason === 'new' && dedicated && !entries.some(e => e.type === 'message')) {
      connector = build(ctx);
      await connector.enable(ctx.sessionManager.getSessionId());
    }
  });
  pi.registerCommand('abra-linear', {
    description: 'local linear start | pause | status | poll | stop | resume | release <stopped-owner evidence> | reconcile <receipt.json>',
    handler: async (args, ctx) => {
      const [command, ...rest] = args.trim().split(/\s+/);
      try {
        if (command === 'watch-start') {
          const [nonce] = rest;
          const config = load(ctx);
          requireValue(ctx.mode === 'rpc' && config.watch?.trustedManagedWork === true && nonce === process.env.ABRA_LINEAR_WATCH_NONCE && /^[a-f0-9-]{36}$/.test(nonce), 'watch requires rpc launcher and acknowledged trusted managed-work configuration');
          requireValue(!connector && !watch && ctx.isIdle() && !ctx.hasPendingMessages() && !ctx.sessionManager.getBranch().some(e => e.type === 'message' || e.customType === marker), 'watch requires a fresh unused persisted child session');
          connector = build(ctx);
          requireValue(!connector.active && !fs.existsSync(connector.store.lock), 'existing connector/native ownership must be reconciled');
          dedicated = true;
          watch = { nonce, owners: new ManagedOwners(pi, ctx, dependencies.nativeRequest), stopped: false, handed: false };
          pi.appendEntry(marker, { watch: nonce });
          await watch.owners.ready();
          emitWatch(ctx, 'start', 'ready', { sessionFile: ctx.sessionManager.getSessionFile() });
          await connector.enable(ctx.sessionManager.getSessionId());
          requireValue(!connector.error, 'watch admission failed; inspect connector receipts');
          return;
        }
        if (command === 'watch-check' || command === 'watch-stop') {
          const [nonce, request] = rest;
          requireValue(watch && nonce === watch.nonce && /^[a-f0-9-]{36}$/.test(request) && !watch.handed, 'foreign, repeated or invalid watch control');
          if (command === 'watch-stop') {
            watch.stopped = true;
            await connector.stop();
          }
          const active = connector.active;
          requireValue(active || watch.owners.runs.size === 0, 'managed owner without an admitted task; reconcile manually');
          requireValue(!connector.error && !watch.owners.fault && !connector.status().pending.length, 'uncertain connector/native/publication state; reconcile manually');
          if (active?.terminal && !active.waiting && settled && ctx.isIdle() && !ctx.hasPendingMessages()) {
            const identity = { issue: active.id, task: active.taskId, outcome: active.terminal };
            await connector.release('trusted managed-work handoff: settled coordinator, reconciled workflow and exact native terminal proofs', wf => watch.owners.verify(ctx.cwd, wf, dependencies.readCheckpoint));
            watch.handed = true;
            emitWatch(ctx, request, 'handoff', identity);
          } else if (watch.stopped && !active && ctx.isIdle() && !ctx.hasPendingMessages()) {
            await connector.dispose(); watch.handed = true;
            emitWatch(ctx, request, 'stopped');
          } else emitWatch(ctx, request, active?.waiting ? 'awaiting-input' : active ? 'working' : 'no-work', { runs: [...watch.owners.runs.keys()] });
          return;
        }
        if (command === 'start') {
          requireValue(ctx.isIdle() && !ctx.hasPendingMessages(), 'wait for current work and queued messages; never inject into a busy session');
          const config = load(ctx);
          requireValue(process.env[config.tokenEnv] || dependencies.api, 'credential environment reference is not populated');
          const store = new Store(ctx.cwd, config);
          requireValue(!store.load().active && !fs.existsSync(store.lock), 'existing connector/native ownership must be reconciled before start');
          requireValue(ctx.hasUI && await ctx.ui.confirm('start dedicated linear task session?', 'saves this session and opens a clean coordinator session; polls while pi is alive, admits only one ticket. next ticket needs another explicit /start. configured delegation grants only the saved authority ceiling. no merge/deploy/close.'), 'start not confirmed');
          await ctx.newSession({ parentSession: ctx.sessionManager.getSessionFile(), setup: async sm => { sm.appendCustomEntry(marker, { start: randomUUID() }); } });
          return;
        }
        if (command === 'status') {
          const status = connector?.status() ?? { mode: 'off', note: 'disabled; configure and explicitly start; reload/restart never auto-dispatches' };
          if (!connector) {
            try { const config = load(ctx); const state = new Store(ctx.cwd, config).load(); status.unresolvedIssue = state.active; } catch { status.configuration = 'absent, invalid or inaccessible'; }
          }
          if (ctx.hasUI) ctx.ui.notify(JSON.stringify(status), 'info');
          return;
        }
        if (command === 'resume') {
          requireValue(dedicated && (!connector || connector.mode === 'off') && ctx.hasUI, 'resume the original dedicated pi session first; inspect task/manifest/native ownership');
          requireValue(await ctx.ui.confirm('resume control polling only?', 'confirm you inspected saved dispatch and surviving native owners. this does not redispatch or replay uncertain mutations. admission stays paused.'), 'resume not confirmed');
          await connector?.dispose();
          connector = build(ctx);
          await connector.enable(ctx.sessionManager.getSessionId(), true);
          return;
        }
        requireValue(connector, 'explicit start/resume required; no network activity while off');
        if (command === 'pause') connector.pause();
        else if (command === 'poll') await connector.poll();
        else if (command === 'stop') await connector.stop();
        else if (command === 'release') {
          requireValue(ctx.hasUI && await ctx.ui.confirm('release native ownership?', 'only confirm after inspecting and stopping/reconciling every coordinator, subprocess and subagent, plus all publication receipts. timestamps, pi idle or a blocked status are not proof.'), 'release not confirmed');
          await connector.release(rest.join(' '));
        } else if (command === 'reconcile') {
          requireValue(ctx.hasUI && await ctx.ui.confirm('apply explicit publication reconciliation?', 'inspect remote comments/status and any in-flight requests first. not-applied permits a later explicit retry; never assert this from a missing comment alone.'), 'reconciliation not confirmed');
          await connector.reconcile(readJson(rest.join(' ')));
        } else throw new Error('usage: /abra-linear start|pause|status|poll|stop|resume|release <evidence>|reconcile <absolute receipt.json>');
        if (ctx.hasUI) ctx.ui.notify(JSON.stringify(connector.status()), 'info');
      } catch (error) {
        const detail = error instanceof Error ? error.message.split('\n')[0].slice(0, 300) : 'unknown failure';
        if (watch && connector) emitWatch(ctx, rest[1] ?? 'start', 'uncertain', { diagnostic: connector.redacted(detail) });
        if (ctx.hasUI) ctx.ui.notify(`linear command blocked/failed: ${connector?.redacted(detail) ?? detail}. no automatic retry or reset`, 'error');
      }
    },
  });
  pi.registerTool({
    name: 'abra_linear_checkpoint', label: 'linear checkpoint',
    description: 'bind the existing task workflow, then report redacted approach/progress/checks or evidence-backed review/blocked. stable key is immutable; report is a workflow delivery reference. no raw logs/reasoning. summaries <=16000 characters; public report <=12000 bytes.',
    executionMode: 'sequential',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: Object.fromEntries(['kind', 'key', 'summary', 'approach', 'checks', 'blocker', 'nextAction', 'report'].map(k => [k, k === 'kind' ? { type: 'string', enum: ['bind', 'approach', 'progress', 'checks', 'waiting', 'blocked', 'review'] } : { type: 'string', maxLength: 16000 }])),
      required: ['kind', 'key', 'summary', 'nextAction'],
    },
    async execute(_id, params, _signal, _onUpdate, ctx) {
      requireValue(connector && connector.active?.session === ctx.sessionManager.getSessionId(), 'checkpoint only available to owning dedicated session');
      return result(await connector.checkpoint(params, _signal));
    },
  });
  pi.on('input', (event, ctx) => {
    if (dedicated && event.source !== 'extension') {
      if (ctx.hasUI) ctx.ui.notify('dedicated linear session: use issue comments or /abra-linear controls; unrelated prompts are not admitted', 'warning');
      return { action: 'handled' };
    }
  });
  const prevent = () => connector?.active ? { cancel: true } : undefined;
  pi.on('session_before_switch', prevent);
  pi.on('session_before_fork', prevent);
  pi.on('session_before_tree', prevent);
  pi.on('agent_start', () => { settled = false; });
  pi.on('tool_execution_start', event => watch?.owners.observeTool(event));
  pi.on('tool_execution_end', event => watch?.owners.observeTool(event));
  pi.on('agent_settled', async () => {
    settled = true;
    if (!connector?.active || connector.disposed || connector.active.terminal || connector.active.waiting || connector.active.dispatch !== 'sent') return;
    // settle proves neither delivery nor stopped subagents; publish a truthful fallback.
    await connector.serial(async () => {
      connector.pause();
      const issue = await connector.api.issue(connector.active.id, connector.controller.signal);
      const team = connector.team(issue);
      if (!team || ['completed', 'canceled'].includes(issue.state.type)) return;
      await connector.publish('settled-without-terminal', 'blocked: coordinator settled without an evidence-backed terminal checkpoint. next action: inspect task, manifest, checks, delivery receipts and surviving native owners; no verified success inferred.', team.blocked, connector.controller.signal);
      connector.active.terminal = 'blocked'; connector.persist();
    });
  });
  pi.on('session_shutdown', async () => { watch?.owners.dispose(); await connector?.dispose(); });
}
