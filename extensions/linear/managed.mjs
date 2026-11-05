import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { realpathSync } from 'node:fs';
import { requireValue, safePath, readJson } from './core.mjs';

const terminal = new Set(['complete', 'failed', 'partial', 'paused', 'stopped', 'rejected']);
const nonempty = value => typeof value === 'string' && value.length > 0;

// public pi-subagents event-bus rpc only; never accept model-supplied proof paths.
export function nativeRequest(pi, method, params = {}, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const requestId = randomUUID();
    const dispose = pi.events.on(`subagents:rpc:v1:reply:${requestId}`, reply => {
      clearTimeout(timer); dispose();
      if (reply?.version !== 1 || reply.requestId !== requestId || reply.success !== true) reject(new Error('managed native rpc unavailable or failed'));
      else resolve(reply.data);
    });
    const timer = setTimeout(() => { dispose(); reject(new Error('managed native rpc timeout; reconcile owners')); }, timeoutMs);
    pi.events.emit('subagents:rpc:v1:request', { version: 1, requestId, method, params });
  });
}

export function validateProcessTerminal(proof, runId) {
  requireValue(proof?.version === 1 && proof.state === 'observed' && proof.runId === runId && proof.childIndex === undefined && nonempty(proof.runnerProcessInstanceId) && Number.isFinite(proof.observedAt) && proof.observedAt >= 0, 'missing exact observed managed runner proof');
  requireValue(Array.isArray(proof.instances) && proof.instances.length === 1, 'unsupported writer/process inventory');
  const runner = proof.instances[0];
  requireValue(runner.kind === 'runner' && runner.processInstanceId === proof.runnerProcessInstanceId && Number.isFinite(runner.closeObservedAt) && runner.closeObservedAt >= 0 && runner.closeObservedAt <= proof.observedAt && (runner.exitCode === null || Number.isInteger(runner.exitCode)) && (runner.signal === null || typeof runner.signal === 'string'), 'runner close not observed');
  if (proof.canonicalSession) requireValue(nonempty(proof.canonicalSession.canonicalSessionId) && proof.canonicalSession.freeAtObservation === true && ['released', 'not-held'].includes(proof.canonicalSession.leaseDisposition), 'canonical session lease unresolved');
  return proof;
}

export class ManagedOwners {
  constructor(pi, ctx, request = (method, params) => nativeRequest(pi, method, params)) {
    this.ctx = ctx; this.request = request; this.runs = new Map(); this.calls = new Set(); this.fault = null;
    this.unsubscribe = pi.events.on('subagent:async-started', event => {
      try {
        requireValue(event?.lifecycleArtifactVersion === 3 && nonempty(event.id) && [ctx.sessionManager.getSessionId(), ctx.sessionManager.getSessionFile()].includes(event.sessionId), 'foreign or malformed managed start');
        requireValue(event.mode === 'single' && !event.parentWorkflowRunId && !this.runs.has(event.id), 'unsupported or duplicate managed run type');
        requireValue(nonempty(event.asyncDir), 'missing native-owned artifact directory');
        // canonicalize the native-owned temp root once (macos /var may be a symlink).
        const asyncDir = realpathSync(event.asyncDir);
        safePath(asyncDir);
        this.runs.set(event.id, { sessionId: event.sessionId, asyncDir });
        pi.appendEntry('abra-linear-managed-start', { runId: event.id, sessionId: event.sessionId });
      } catch { this.fault = 'unknown/unsupported managed owner; manual reconciliation required'; }
    });
  }
  async ready() {
    const ping = await this.request('ping');
    requireValue(ping?.version === 1 && ping.capabilities?.processTerminalProof?.version === 1 && ping.capabilities.processTerminalProof.lifecycleArtifactVersion === 3 && ping.session?.sessionId === this.ctx.sessionManager.getSessionId(), 'compatible managed native proof capability required');
    await this.quiet();
  }
  async quiet() {
    const data = await this.request('status', {});
    const snapshot = data?.asyncSnapshot;
    requireValue(data?.fleet?.version === 1 && data.fleet.totalActive === 0 && data.fleet.omitted === 0 && snapshot?.kind === 'pi-subagents.async-status-snapshot' && snapshot.version === 1 && snapshot.omitted?.runs === 0 && snapshot.omitted.children === 0 && snapshot.omitted.byteLimitExceeded === false && Array.isArray(snapshot.runs) && snapshot.runs.every(r => this.runs.has(r.id)), 'unknown, active or omitted native ownership projection');
  }
  observeTool(event) {
    if (event.toolName !== 'subagent') return;
    if (event.args) {
      if (!event.args.action || event.args.action === 'resume') this.calls.add(event.toolCallId);
      return;
    }
    if (!this.calls.delete(event.toolCallId)) return;
    const details = event.result?.details;
    if (event.isError || !details?.asyncId || !this.runs.has(details.asyncId)) this.fault = 'unsupported, failed or unobserved native launch; reconcile manually';
  }
  async verify() {
    requireValue(!this.fault, this.fault);
    const runIds = [...this.runs.keys()];
    const proofs = [];
    for (const [runId, start] of this.runs) {
      const data = await this.request('status', { id: runId });
      // status.json is a documented lifecycle artifact, rooted only in a live native start.
      const status = readJson(join(start.asyncDir, 'status.json'));
      requireValue(data?.details?.runId === runId && status.runId === runId && status.sessionId === start.sessionId && status.lifecycleArtifactVersion === 3 && status.mode === 'single' && terminal.has(status.state), 'missing, foreign or nonterminal targeted native status');
      requireValue(status.steps?.length === 1 && !status.steps[0].runner && !status.steps[0].externalJob && !status.steps[0].externalProcess && !status.steps[0].children?.length && !status.isNested && !status.parentWorkflowRunId && !status.revivedFrom && !status.scheduleOrigin && !status.launcher && !status.children?.length && !status.nestedChildren?.length && !status.nestedWarnings?.length && !status.pendingAppends && !status.hostSteps?.length, 'unsupported external/nested/pending managed work');
      const proof = validateProcessTerminal(data.details.lifecycleStatus?.processTerminal, runId);
      requireValue(status.processTerminal?.runnerProcessInstanceId === proof.runnerProcessInstanceId, 'foreign runner instance');
      proofs.push(proof);
    }
    await this.quiet();
    requireValue(!this.fault && runIds.length === this.runs.size && this.calls.size === 0, 'managed ownership changed during handoff');
    return proofs;
  }
  dispose() { this.unsubscribe(); }
}
