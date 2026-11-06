import { join } from 'node:path';
import * as fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import { configuration, readJson, Store, LinearClient, Connector, ApiError, connectorDiagnostic, requireValue } from './core.mjs';
import { ManagedOwners, NativeContinuation } from './managed.mjs';
import { ClientCredentials, resolveCredentials } from './auth.mjs';
import { setup } from './setup.mjs';
import { WatchFailure, failureCode, diagnosticText, requireWatch } from './diagnostics.mjs';
import { dedicatedMarker as marker, seedDedicatedSession, verifySavedBootstrap, verifySavedDedicated } from './session.mjs';

const result = message => ({ content: [{ type: 'text', text: message }], details: {} });
export function install(pi, configDirectory = '.pi', dependencies = {}) {
  let connector;
  let dedicated = false;
  let watch;
  let settled = false;
  let settingUp = false;
  let freshHandoff;
  let continuation;
  let reportingRequested = false;
  let aborted = false;
  const setupController = new AbortController();
  const emitWatch = (ctx, request, state, extra = {}) => {
    pi.appendEntry('abra-linear-watch', { version: 1, nonce: watch.nonce, request, session: ctx.sessionManager.getSessionId(), owner: connector.store.owner, state, issue: connector.active?.id ?? null, task: connector.active?.taskId ?? null, ...extra });
  };
  const load = ctx => {
    requireValue(ctx.isProjectTrusted(), 'project trust required before reading connector configuration');
    return configuration(readJson(join(ctx.cwd, configDirectory, 'abra-linear.json')));
  };
  const build = ctx => {
    const config = load(ctx);
    requireValue(!config.auth?.credentialsFile?.startsWith(ctx.cwd + '/'), 'credential files must be outside checkout');
    const store = new Store(ctx.cwd, config);
    const api = dependencies.api ?? new LinearClient(config, config.auth ? new ClientCredentials(config) : process.env[config.tokenEnv]);
    const built = new Connector({ root: ctx.cwd, config, store, api, ...dependencies, host: {
      idle: () => ctx.isIdle() && !ctx.hasPendingMessages(),
      afterControl: () => checkSettled(ctx, true),
      send: async prompt => {
        if (watch) emitWatch(ctx, 'start', 'admitted');
        pi.setSessionName(`abra linear coordinator`); pi.sendUserMessage(prompt);
      },
      cancel: async reason => {
        ctx.abort();
        pi.sendUserMessage(`stop new actions: ${reason}. only reconcile/cancel existing native owners, preserve task/native evidence and report blocked. aborting pi alone does not prove subagents stopped.`, { deliverAs: 'steer' });
      },
      steer: async message => { pi.sendUserMessage(message, { deliverAs: 'steer' }); },
      notify: message => { if (ctx.hasUI) ctx.ui.notify(message, 'warning'); },
    } });
    continuation?.dispose();
    continuation = new NativeContinuation(pi, ctx, dependencies.nativeRequest);
    return built;
  };
  pi.on('session_start', async (event, ctx) => {
    const entries = ctx.sessionManager.getBranch();
    dedicated = entries.some(e => e.type === 'custom' && e.customType === marker);
    // only the exact explicit new-session bootstrap arms polling, never reload/resume.
    if (event.reason === 'new' && dedicated) {
      freshHandoff = verifySavedBootstrap(ctx.sessionManager);
      requireValue(ctx.isIdle() && !ctx.hasPendingMessages(), 'dedicated bootstrap requires idle session');
      if (freshHandoff.source === 'interactive') {
        connector = build(ctx);
        await connector.enable(ctx.sessionManager.getSessionId());
      }
    }
  });
  pi.registerCommand('abra-linear', {
    description: 'local linear setup | start | pause | status | poll | stop | resume | release <stopped-owner evidence> | reconcile <receipt.json>',
    handler: async (args, ctx) => {
      const [command, ...rest] = args.trim().split(/\s+/);
      try {
        requireValue(!settingUp, 'finish or cancel the setup dialog first');
        if (command === 'setup') {
          requireValue(!watch && !connector?.active && (!connector || connector.mode === 'off'), 'stop and reconcile connector ownership before setup');
          settingUp = true;
          try { await setup(ctx, configDirectory, { ...dependencies.setup, signal: setupController.signal }); }
          finally { settingUp = false; }
          return;
        }
        if (command === 'watch-start') {
          const [nonce] = rest;
          const config = load(ctx);
          requireValue(ctx.mode === 'rpc' && config.watch?.trustedManagedWork === true && nonce === process.env.ABRA_LINEAR_WATCH_NONCE && /^[a-f0-9-]{36}$/.test(nonce), 'watch requires rpc launcher and acknowledged trusted managed-work configuration');
          requireValue(!connector && !watch && ctx.isIdle() && !ctx.hasPendingMessages() && !ctx.sessionManager.getBranch().some(e => e.type === 'message' || e.customType === marker), 'watch requires a fresh unused persisted child session');
          const store = new Store(ctx.cwd, config);
          requireValue(!store.load().active && !fs.existsSync(store.lock), 'existing connector/native ownership must be reconciled');
          const handoff = { source: 'watch', token: nonce, previousSession: ctx.sessionManager.getSessionId() };
          // replacement invalidates this pi/ctx; return its promise without old-runtime work.
          return ctx.newSession({ setup: sm => seedDedicatedSession(sm, handoff) });
        }
        if (command === 'watch-arm') {
          const [nonce, previousSession] = rest;
          const config = load(ctx);
          requireValue(ctx.mode === 'rpc' && config.watch?.trustedManagedWork === true && nonce === process.env.ABRA_LINEAR_WATCH_NONCE && freshHandoff?.source === 'watch' && freshHandoff.token === nonce && freshHandoff.previousSession === previousSession, 'watch bootstrap handoff disagrees');
          requireValue(!connector && !watch && ctx.isIdle() && !ctx.hasPendingMessages(), 'watch requires an unused idle bootstrap');
          verifySavedBootstrap(ctx.sessionManager);
          connector = build(ctx);
          requireValue(!connector.active && !fs.existsSync(connector.store.lock), 'existing connector/native ownership must be reconciled');
          watch = { nonce, owners: new ManagedOwners(pi, ctx, dependencies.nativeRequest), stopped: false, handed: false };
          try { await watch.owners.ready(); } catch { throw new WatchFailure('native-ownership-uncertain'); }
          requireValue(ctx.isIdle() && !ctx.hasPendingMessages(), 'watch requires idle bootstrap after native checks');
          verifySavedBootstrap(ctx.sessionManager);
          emitWatch(ctx, 'start', 'ready', { sessionFile: ctx.sessionManager.getSessionFile(), previousSession });
          await connector.enable(ctx.sessionManager.getSessionId());
          requireWatch(!connector.error, connector.status().diagnostic ?? 'connector-check-failed');
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
          requireWatch(active || watch.owners.runs.size === 0, 'native-ownership-uncertain');
          const status = connector.status();
          requireWatch(!connector.error, status.diagnostic ?? 'connector-check-failed');
          requireWatch(!watch.owners.fault, 'native-ownership-uncertain');
          requireWatch(!status.pending.length, 'publication-pending');
          if (active?.terminal && !active.waiting && settled && ctx.isIdle() && !ctx.hasPendingMessages()) {
            const identity = { issue: active.id, task: active.taskId, outcome: active.terminal };
            await connector.release('trusted managed-work handoff: settled coordinator, confirmed reporting receipts and exact native terminal proofs', async () => {
              try { return await watch.owners.verify(); } catch { throw new WatchFailure('native-ownership-uncertain'); }
            });
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
          if (!dependencies.api) {
            if (config.auth) {
              try { resolveCredentials(config.auth); }
              catch { throw new Error('client credential references unavailable; run setup or check private storage locally'); }
            } else requireValue(process.env[config.tokenEnv], 'credential environment reference is not populated');
          }
          const store = new Store(ctx.cwd, config);
          requireValue(!store.load().active && !fs.existsSync(store.lock), 'existing connector/native ownership must be reconciled before start');
          requireValue(ctx.hasUI && await ctx.ui.confirm('start dedicated linear task session?', 'opens a dedicated coordinator session with saved recovery context; polls while pi is alive, admits only one ticket. next ticket needs another explicit /start. configured delegation grants only the saved authority ceiling. no merge/deploy/close.'), 'start not confirmed');
          const handoff = { source: 'interactive', token: randomUUID(), previousSession: ctx.sessionManager.getSessionId() };
          return ctx.newSession({ parentSession: ctx.sessionManager.getSessionFile(), setup: sm => seedDedicatedSession(sm, handoff) });
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
          requireValue(dedicated && (!connector || connector.mode === 'off') && ctx.hasUI, 'resume the original dedicated pi session first; inspect task/native ownership');
          requireValue(await ctx.ui.confirm('resume control polling only?', 'confirm you inspected saved dispatch and surviving native owners. this does not redispatch or replay uncertain mutations. admission stays paused.'), 'resume not confirmed');
          verifySavedDedicated(ctx.sessionManager);
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
        } else throw new Error('usage: /abra-linear setup|start|pause|status|poll|stop|resume|release <evidence>|reconcile <absolute receipt.json>');
        if (ctx.hasUI) ctx.ui.notify(JSON.stringify(connector.status()), 'info');
      } catch (error) {
        const watchCommand = ['watch-start', 'watch-arm', 'watch-check', 'watch-stop'].includes(command);
        const code = error instanceof ApiError ? connectorDiagnostic(error) : failureCode(error) === 'unknown-failure' ? 'connector-check-failed' : failureCode(error);
        const detail = watchCommand ? diagnosticText(code) : command === 'setup' ? 'setup requires trusted idle terminal, valid configuration and reconciled ownership; inspect locally' : error instanceof Error ? error.message.split('\n')[0].slice(0, 300) : 'unknown failure';
        if (watch && connector) emitWatch(ctx, command === 'watch-arm' ? 'start' : rest[1] ?? 'start', 'uncertain', { code });
        else if (['watch-start', 'watch-arm'].includes(command) && ctx.mode === 'rpc' && rest[0] === process.env.ABRA_LINEAR_WATCH_NONCE) {
          pi.appendEntry('abra-linear-watch', { version: 1, nonce: rest[0], request: 'start', session: ctx.sessionManager.getSessionId(), state: 'uncertain', code });
        }
        if (ctx.hasUI) ctx.ui.notify(`linear command blocked/failed: ${connector?.redacted(detail) ?? detail}. no automatic retry or reset`, 'error');
      }
    },
  });
  pi.registerTool({
    name: 'abra_linear_checkpoint', label: 'linear checkpoint',
    description: 'bind the real tasks-axi task and immutable source.json with original requestedDelivery (report or pr) before dispatch, then report concrete approach/progress/checks, completed PR/report for review, or an actual blocker and next action. stable key is immutable; review requires structured delivery evidence; reports never substitute for code delivery. no raw logs/reasoning. summaries <=16000 characters; public report <=12000 bytes.',
    executionMode: 'sequential',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        ...Object.fromEntries(['kind', 'key', 'summary', 'approach', 'checks', 'blocker', 'nextAction', 'task'].map(k => [k, k === 'kind' ? { type: 'string', enum: ['bind', 'approach', 'progress', 'checks', 'waiting', 'blocked', 'review'] } : { type: 'string', maxLength: 16000 }])),
        requestedDelivery: { type: 'string', enum: ['report', 'pr'], description: 'bind only: original requested delivery, independent of authority; code intent requires pr, never report' },
        delivery: {
          type: 'object', additionalProperties: false,
          properties: {
            ...Object.fromEntries(['kind', 'reference', 'candidate', 'baseCommit', 'workerDirectory', 'verifierDirectory', 'verificationReport', 'verifiedCommit', 'prHead', 'prBase', 'ci', 'externalEvidence'].map(k => [k, { type: 'string', maxLength: 16000 }])),
            checks: { type: 'object', additionalProperties: false, properties: Object.fromEntries(['intent', 'tests', 'docs', 'format'].map(k => [k, { type: 'string', enum: ['pass', 'fail', 'blocked', 'not-applicable'] }])), required: ['intent', 'tests', 'docs', 'format'] },
          },
          required: ['kind', 'reference'],
        },
      },
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
  const prevent = () => settingUp || connector?.active ? { cancel: true } : undefined;
  pi.on('session_before_switch', prevent);
  pi.on('session_before_fork', prevent);
  pi.on('session_before_tree', prevent);
  pi.on('agent_start', () => { settled = false; });
  pi.on('tool_execution_start', event => watch?.owners.observeTool(event));
  pi.on('tool_execution_end', event => watch?.owners.observeTool(event));
  pi.on('message_start', event => continuation?.observeMessage(event.message));
  const checkSettled = async (ctx, fromControl = false) => {
    if (!settled || !connector?.active || connector.disposed || connector.active.terminal || connector.active.waiting || connector.active.dispatch !== 'sent' || !ctx.isIdle() || ctx.hasPendingMessages()) return;
    let pending, uncertain = false;
    try { pending = await continuation.pending(); } catch { uncertain = true; }
    if (!settled || !ctx.isIdle() || ctx.hasPendingMessages() || connector.disposed) return;
    if (!aborted && !uncertain && !connector.active.halted) {
      if (pending.running.length) return;
      if (pending.completed.length) {
        // allow the native notifier to deliver first; control polls repair a missing wake once.
        if (!fromControl) return;
        continuation.consume(pending.completed);
        settled = false;
        pi.sendUserMessage(`native work has finished: ${JSON.stringify(pending.completed)}. inspect these exact native results and the saved task, then continue the original request. do not relaunch work whose outcome is uncertain. report actual findings/test results here and on linear; if a run failed or returned empty output, explain the concrete failure and next action rather than claiming the task is impossible.`);
        return;
      }
      if (!reportingRequested) {
        reportingRequested = true; settled = false;
        pi.sendUserMessage('continue the original issue request from the saved task and results. no async work remains pending. finish the requested PR/report and publish kind review with delivery/check evidence, ask a specific question with kind waiting, or publish kind blocked with the actual failure and a useful next action. do not stop with only a chat summary or invent a blocker.');
        return;
      }
    }
    connector.pause();
    const issue = await connector.api.issue(connector.active.id, connector.controller.signal);
    const team = connector.team(issue);
    if (!settled || !ctx.isIdle() || ctx.hasPendingMessages() || connector.disposed) return;
    if (!team || ['completed', 'canceled'].includes(issue.state.type)) return;
    const reason = aborted ? 'the coordinator was interrupted before delivering a PR or report' : uncertain ? 'abra could not confirm the status of its background work' : 'the coordinator stopped without delivering a PR or report, even after a request to finish reporting';
    await connector.publish('settled-without-terminal', `blocked: ${reason}. next action: reopen the saved task and inspect the worker results and any running workers before retrying. no verified delivery is available; this does not mean the requested change is impossible.`, team.blocked, connector.controller.signal);
    connector.active.terminal = 'blocked'; connector.active.waiting = false; connector.persist();
  };
  pi.on('agent_settled', async (event, ctx) => {
    settled = true; aborted = event?.aborted === true;
    await connector?.serial(() => checkSettled(ctx));
  });
  pi.on('session_shutdown', async () => { setupController.abort(); continuation?.dispose(); watch?.owners.dispose(); await connector?.dispose(); });
}
