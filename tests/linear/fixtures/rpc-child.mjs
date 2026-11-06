#!/usr/bin/env node
// harmless local rpc boundary fixture; never invokes pi, models or linear.
import * as fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { configuration, readJson, Store } from '../../../extensions/linear/core.mjs';

const scenario = process.env.WATCH_TEST_SCENARIO;
const log = process.env.WATCH_TEST_LOG;
const serial = fs.existsSync(log) ? fs.readFileSync(log, 'utf8').split('\n').filter(Boolean).length + 1 : 1;
fs.appendFileSync(log, `${process.pid}\n`);
const session = randomUUID(), nonce = process.env.ABRA_LINEAR_WATCH_NONCE;
const config = configuration(readJson(join(process.cwd(), '.pi/abra-linear.json')));
const store = new Store(process.cwd(), config), state = store.load();
const issue = `00000000-0000-0000-0000-${String(serial + 100).padStart(12, '0')}`, task = `linear-${issue}`;
let admitted = false, checks = 0;
if (scenario === 'signal-sequence') process.on('SIGINT', () => { fs.appendFileSync(process.env.WATCH_TEST_SIGNAL_LOG, 'child-sigint\n'); process.exitCode = 1; });
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
const event = (request, status, extra = {}) => send({ type: 'entry_appended', entry: { type: 'custom', customType: 'abra-linear-watch', data: { version: 1, nonce, request, session, owner: store.owner, state: status, issue: admitted ? issue : null, task: admitted ? task : null, ...extra } } });
let buffer = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  buffer += chunk;
  let index;
  while ((index = buffer.indexOf('\n')) !== -1) {
    const command = JSON.parse(buffer.slice(0, index)); buffer = buffer.slice(index + 1);
    if (command.type === 'get_state') {
      send({ type: 'response', id: command.id, command: command.type, success: true, data: { sessionId: session, messageCount: admitted ? 3 : 0, pendingMessageCount: scenario === 'pending' && checks > 0 ? 1 : 0, isStreaming: false, isCompacting: false } });
      continue;
    }
    const [, action, , request] = command.message.split(' ');
    if (action === 'watch-start') {
      if (scenario === 'crash') process.exit(0);
      if (scenario === 'malformed') { process.stdout.write('not-json\n'); continue; }
      if (scenario === 'failed-prompt') { send({ type: 'response', id: command.id, command: 'prompt', success: false }); continue; }
      if (scenario === 'timeout') continue;
      store.acquire(session);
      event('start', 'ready', { sessionFile: join(process.cwd(), 'fake-session.jsonl') });
      if (scenario === 'duplicate-ready') event('start', 'ready', { sessionFile: 'fake' });
      if (!['no-work', 'dialog', 'missing-outcome', 'signal-sequence'].includes(scenario) && !(scenario === 'multiple' && serial > 2)) {
        admitted = true;
        state.active = issue;
        state.records.push({ id: issue, session, taskId: task, repo: config.repositories[0].name, fingerprint: 'a'.repeat(64), dispatch: 'sent', bound: true, binding: { requestedDelivery: 'report', source: `data/${task}/source.json`, sourceHash: 'b'.repeat(64) }, halted: null, terminal: null, comments: {}, publications: [{ key: 'terminal', body: 'reviewable public output\u2028safe lf record', stateId: config.teams[0].inReview, comment: 'comment-id', state: 'confirmed' }] });
        store.save(state);
        if (scenario !== 'out-of-order') event('start', 'admitted');
      }
      if (scenario === 'dialog') send({ type: 'extension_ui_request', id: 'dialog', method: 'input', title: 'clarification' });
      if (scenario === 'noisy') {
        process.stderr.write('secret-stderr-canary /home/private/operator\n');
        send({ type: 'message_update', delta: 'secret-model-canary' });
        send({ type: 'tool_execution_end', result: 'secret-tool-canary' });
        send({ type: 'extension_ui_request', method: 'notify', message: 'secret-notification-canary' });
      }
    } else if (action === 'watch-stop' && !admitted) {
      if (scenario === 'signal-sequence') fs.appendFileSync(process.env.WATCH_TEST_SIGNAL_LOG, 'stop-command\n');
      store.release(); event(request, 'stopped');
    } else {
      checks++;
      if (scenario === 'missing-outcome') { /* accepted is not an outcome. */ }
      else if (['uncertain', 'auth-loss', 'unknown-owner'].includes(scenario)) event(request, 'uncertain');
      else if (['clarification', 'interrupt-active'].includes(scenario)) event(request, 'awaiting-input');
      else if (!admitted) event(request, 'no-work');
      else if (scenario === 'working' && checks <= 3) event(request, 'working', { runs: ['private-run-id'] });
      else {
        const outcome = scenario === 'blocked' ? 'blocked' : 'review';
        const record = state.records.at(-1); record.terminal = outcome; record.delivery = { kind: 'report', reference: 'https://example.test/public-report' }; record.releaseEvidence = 'verified fixture boundary'; record.managedProofs = [];
        state.active = null;
        if (scenario === 'missing-delivery') delete record.delivery;
        if (scenario === 'unbound') record.bound = false;
        if (scenario === 'dispatch-intent') record.dispatch = 'intent';
        if (scenario === 'uncertain-publication') record.publications[0].state = 'intent';
        if (scenario === 'unreleased') state.active = issue;
        store.save(state);
        if (scenario !== 'lock-retained') store.release();
        const extra = { outcome, issue, task };
        if (scenario === 'wrong-session') extra.session = 'foreign';
        if (scenario === 'wrong-task') extra.task = 'linear-foreign';
        if (scenario === 'wrong-nonce') extra.nonce = 'foreign';
        if (scenario === 'wrong-request') extra.request = 'foreign';
        event(request, 'handoff', extra);
        if (scenario === 'duplicate-handoff') event(request, 'handoff', extra);
      }
    }
    send({ type: 'response', id: command.id, command: 'prompt', success: true, data: { disposition: 'handled' } });
  }
});
process.stdin.on('end', () => { store.release(); if (scenario === 'close-failure') process.exitCode = 1; });
