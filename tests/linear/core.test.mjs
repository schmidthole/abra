import { test } from 'node:test';
import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join, resolve } from 'node:path';
import { configuration, Store, LinearClient, ApiError, Connector, coordinatorPrompt } from '../../extensions/linear/core.mjs';
import { install } from '../../extensions/linear/pi.mjs';
import { seedDedicatedSession } from '../../extensions/linear/session.mjs';
import { SessionManager, installedAgentSession } from './fixtures/session-manager.mjs';

const root = resolve('.');
const id = n => `00000000-0000-0000-0000-${String(n).padStart(12, '0')}`;
const clone = value => structuredClone(value);
const config = () => configuration({ version: 1, authority: { mode: 'report' }, tokenEnv: 'LINEAR_TOKEN', workspaceId: id(1), personaId: id(2), teams: [{ id: id(3), working: id(4), inReview: id(5), blocked: id(6) }], repositories: [{ name: 'abra', path: root, labelId: id(7), teamId: id(3), remote: 'https://github.com/example/abra', base: 'main' }], pollMs: 1000, controlMs: 1000, timeoutMs: 100 });
const issue = (n = 8) => ({ id: id(n), identifier: `ABRA-${n}`, title: 'review request', description: 'original intent and acceptance', url: 'https://linear.app/example/issue/ABRA-8', delegate: { id: id(2) }, team: { id: id(3) }, state: { id: id(9), type: 'unstarted' }, labels: { nodes: [{ id: id(7) }], pageInfo: { hasNextPage: false } } });
const resources = new WeakMap();
function temporary(t) {
  fs.mkdirSync(join(root, '.cache/linear-tests'), { recursive: true });
  const path = fs.mkdtempSync(join(root, '.cache/linear-tests/trial-'));
  t.after(async () => { for (const resource of resources.get(t) ?? []) await resource.dispose(); fs.rmSync(path, { recursive: true, force: true }); });
  return path;
}
class FakeApi {
  constructor() { this.token = 'secret-test-token'; this.issues = [issue()]; this.thread = []; this.calls = []; this.failComment = null; this.failState = null; }
  async validate() { this.calls.push('validate'); }
  async discover() { this.calls.push('discover'); return clone(this.issues); }
  async issue(id) { this.calls.push('issue'); const found = this.issues.find(i => i.id === id); if (!found) throw new Error('access revoked'); return clone(found); }
  async comments() { this.calls.push('comments'); return clone(this.thread); }
  async comment(id, body) {
    this.calls.push('comment');
    if (this.failComment === 'before') throw new Error('network timeout');
    const comment = { id: id + '-' + this.thread.length, body, user: { id: config().personaId }, updatedAt: 'now' };
    this.thread.push(comment);
    if (this.failComment === 'after') throw new Error('response lost');
    return comment.id;
  }
  async attachPR(id, url) {
    this.calls.push('attachPR');
    if (this.failAttachment) throw new Error('attachment unavailable');
    this.attached = { id, url }; return 'attachment-id';
  }
  async unassign(id, clearAssignee) {
    this.calls.push('unassign');
    if (this.failUnassign === 'before') throw new Error('network timeout');
    const issue = this.issues.find(i => i.id === id);
    issue.delegate = null;
    if (clearAssignee) issue.assignee = null;
    if (this.failUnassign === 'after') throw new Error('response lost');
  }
  async status(id, stateId) {
    this.calls.push('status');
    if (this.failState === 'before') throw new Error('network timeout');
    this.issues.find(i => i.id === id).state = { id: stateId, type: 'started' };
    if (this.failState === 'after') throw new Error('response lost');
  }
}
function fixture(t, extra = {}) {
  const path = temporary(t), cfg = config(), api = new FakeApi(), sent = [], cancellations = [], steering = [];
  const store = new Store(path, cfg);
  const taskId = `linear-${id(8)}`;
  const host = { idle: () => true, send: async p => sent.push(p), cancel: async r => cancellations.push(r), steer: async p => steering.push(p) };
  const connector = new Connector({ root: path, config: cfg, store, api, host, random: () => 0, ...extra });
  resources.set(t, [...resources.get(t) ?? [], connector]);
  return { connector, path, cfg, api, store, sent, cancellations, steering, host };
}
const checkpoint = (kind, key = kind) => ({ kind, key, summary: 'concise public summary', approach: 'bounded investigation', checks: 'focused tests passed', nextAction: 'independent review', blocker: 'publication authority unavailable', task: `linear-${id(8)}` });
function saveTask(f, requestedDelivery = 'report', overrides = {}) {
  const task = `linear-${id(8)}`, source = `data/${task}/source.json`;
  const body = `original source and acceptance: ${source}\nrequested delivery: ${requestedDelivery}\ncurrent next action: inspect original acceptance`;
  const detail = { id: task, repo: 'abra', body, ...overrides };
  fs.mkdirSync(join(f.path, 'data', task), { recursive: true });
  fs.writeFileSync(join(f.path, source), JSON.stringify(f.api.issues[0]));
  fs.writeFileSync(join(f.path, 'data/backlog.md'), `## In flight\n- [ ] ${detail.id} - original request (repo: ${detail.repo})\n${detail.body.split('\n').map(line => `  ${line}`).join('\n')}\n`);
  // fake tasks-axi boundary with the observed 0.2.5 full-detail scalar format.
  const output = `task:\n${Object.entries(detail).map(([name, value]) => `  ${name}: ${JSON.stringify(value)}`).join('\n')}\n`;
  fs.mkdirSync(join(f.path, 'bin'), { recursive: true });
  fs.writeFileSync(join(f.path, 'bin/tasks'), `#!${process.execPath}\nimport assert from 'node:assert/strict';\nassert.deepEqual(process.argv.slice(2), ${JSON.stringify(['show', task, '--full', '--backend', 'markdown', '--file', join(f.path, 'data/backlog.md')])});\nprocess.stdout.write(${JSON.stringify(output)});\n`, { mode: 0o700 });
}
async function bind(f, requestedDelivery = 'report') { saveTask(f, requestedDelivery); await f.connector.checkpoint({ ...checkpoint('bind'), requestedDelivery }); }

test('graphql blocked ownership updates preserve human assignees and attach PRs by issue and url', async () => {
  const calls = [], cfg = config();
  const api = new LinearClient(cfg, 'test-token', async (_url, options) => {
    const { query, variables } = JSON.parse(options.body); calls.push({ query, variables });
    const data = query.includes('AbraUnassign') ? { issueUpdate: { success: true, issue: { id: id(8), delegate: null, assignee: variables.input.assigneeId === null ? null : { id: id(70) } } } } : { attachmentCreate: { success: true, attachment: { id: 'attachment-id', url: variables.input.url } } };
    return { ok: true, status: 200, headers: new Headers(), json: async () => ({ data }) };
  });
  await api.unassign(id(8), false);
  assert.deepEqual(calls.at(-1).variables.input, { delegateId: null });
  await api.unassign(id(8), true);
  assert.deepEqual(calls.at(-1).variables.input, { delegateId: null, assigneeId: null });
  const url = 'https://github.com/example/abra/pull/1';
  assert.equal(await api.attachPR(id(8), url), 'attachment-id');
  assert.deepEqual(calls.at(-1).variables.input, { issueId: id(8), title: 'pull request', url });
});

test('configuration defaults to pr delivery without size limits and allows explicit report-only authority', () => {
  const cfg = config(); assert.equal(cfg.authority.mode, 'report');
  const defaults = clone(cfg); delete defaults.authority;
  assert.deepEqual(configuration(defaults).authority, { mode: 'pr' });
  assert.deepEqual(configuration({ ...cfg, authority: { mode: 'pr' } }).authority, { mode: 'pr' });
  for (const mutate of [c => c.token = 'secret', c => c.teams[0].blocked = c.teams[0].working, c => c.teams[0].blocked = '', c => c.repositories[0].path = '../repo', c => c.repositories[0].base = '--output=unexpected', c => c.authority = { mode: 'merge' }, c => c.authority = { mode: 'unknown' }, c => c.repositories.push(c.repositories[0])]) {
    const value = clone(cfg); mutate(value); assert.throws(() => configuration(value));
  }
});

test('discovery dedupes duplicate scans and admits one task into dedicated context', async t => {
  const f = fixture(t); f.api.issues.push(issue(10));
  assert.equal(f.connector.status().mode, 'off'); assert.equal(f.api.calls.length, 0);
  await f.connector.enable('session-1'); await f.connector.poll(); await f.connector.poll();
  assert.equal(f.sent.length, 1); assert.equal(f.connector.active.dispatch, 'sent');
  assert.equal(f.api.thread.length, 1); assert.equal(f.api.issues[0].state.id, id(4));
  assert.equal(f.connector.state.records.length, 1);
  assert.match(f.sent[0], /original intent and acceptance/);
});

test('unconfigured team/repository, ambiguous labels, terminal and undelegated issues are not eligible', async t => {
  const f = fixture(t);
  for (const mutate of [i => i.delegate = null, i => i.team.id = id(77), i => i.labels.nodes = [], i => i.labels.pageInfo.hasNextPage = true, i => i.state.type = 'completed']) {
    const i = issue(); mutate(i); assert.equal(f.connector.eligible(i), null);
  }
  f.api.issues[0].delegate = null; await f.connector.enable('session-1'); assert.equal(f.sent.length, 0);
});

test('exclusive lock refuses second host; stale lock is never auto-stolen', async t => {
  const f = fixture(t); await f.connector.enable('session-1');
  const second = new Store(f.path, f.cfg);
  assert.throws(() => second.acquire('session-2'), /EEXIST/);
  assert.equal(JSON.parse(fs.readFileSync(join(second.lock, 'owner.json'))).session, 'session-1');
});

test('reload off: correlation survives, resume wrong session fails and correct session never redispatches', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await f.connector.dispose();
  const recovered = new Connector({ root: f.path, config: f.cfg, store: new Store(f.path, f.cfg), api: f.api, host: f.host });
  resources.set(t, [...resources.get(t), recovered]);
  assert.equal(recovered.mode, 'off');
  await assert.rejects(recovered.enable('session-2', true), /recorded owning/);
  await assert.rejects(recovered.enable('new-session'), /unresolved ownership/);
  await recovered.enable('session-1', true); assert.equal(recovered.mode, 'paused'); assert.equal(f.sent.length, 1);
});

test('launch uncertainty never automatically redispatches', async t => {
  const f = fixture(t, { host: { idle: () => true, send: async () => { throw new Error('possibly accepted'); }, cancel: async () => {}, steer: async () => {} } });
  await f.connector.enable('session-1'); assert.equal(f.connector.active.dispatch, 'intent');
  await f.connector.poll(); assert.equal(f.connector.active.dispatch, 'intent'); assert.ok(f.connector.active);
});

test('no overlapping graphql polls even with simultaneous operator polls', async t => {
  const f = fixture(t); let running = 0, maximum = 0;
  const discover = f.api.discover.bind(f.api);
  f.api.issues = [];
  f.api.discover = async () => { running++; maximum = Math.max(maximum, running); await new Promise(r => setTimeout(r, 10)); const data = await discover(); running--; return data; };
  await f.connector.enable('session-1'); await Promise.all([f.connector.poll(), f.connector.poll(), f.connector.poll()]);
  assert.equal(maximum, 1);
});

for (const read of ['issue', 'comments']) {
  test(`pause during pre-admission ${read} read prevents reservation, pickup and dispatch`, async t => {
    const f = fixture(t), reading = Promise.withResolvers(), release = Promise.withResolvers();
    const original = f.api[read].bind(f.api);
    f.api[read] = async (...args) => { reading.resolve(); await release.promise; return original(...args); };
    const enabling = f.connector.enable('session-1');
    await reading.promise;
    f.connector.pause(); release.resolve();
    await enabling; await f.connector.poll();
    assert.equal(f.connector.mode, 'paused'); assert.equal(f.connector.error, null);
    assert.equal(f.connector.state.active, null); assert.deepEqual(f.connector.state.records, []);
    assert.equal(f.connector.used, false); assert.equal(fs.existsSync(f.store.path), false);
    assert.equal(f.api.calls.includes('comment'), false); assert.equal(f.api.calls.includes('status'), false);
    assert.equal(f.api.thread.length, 0); assert.equal(f.api.issues[0].state.id, id(9));
    assert.equal(f.sent.length, 0); assert.equal(f.cancellations.length, 0);
  });
}

test('pause during already-admitted pickup still dispatches and polls active control', async t => {
  const f = fixture(t), publishing = Promise.withResolvers(), release = Promise.withResolvers();
  const comment = f.api.comment.bind(f.api);
  f.api.comment = async (...args) => { publishing.resolve(); await release.promise; return comment(...args); };
  const enabling = f.connector.enable('session-1');
  await publishing.promise;
  assert.equal(f.connector.active.dispatch, 'reserved'); assert.equal(f.connector.used, true);
  f.connector.pause(); release.resolve();
  await enabling;
  assert.equal(f.connector.mode, 'paused'); assert.equal(f.connector.error, null);
  assert.equal(f.connector.active.dispatch, 'sent'); assert.equal(f.sent.length, 1);
  assert.equal(f.api.thread.length, 1); assert.equal(f.api.issues[0].state.id, id(4));
  const reads = f.api.calls.filter(c => c === 'issue').length;
  await f.connector.poll();
  assert.equal(f.api.calls.filter(c => c === 'issue').length, reads + 1);
  assert.equal(f.cancellations.length, 0); assert.equal(f.sent.length, 1);
});

test('pause prevents admissions but polls active control; stop cancels and retains ownership', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); f.connector.pause();
  await f.connector.stop();
  assert.equal(f.cancellations.length, 1); assert.ok(f.connector.active); assert.equal(f.api.issues[0].state.id, id(6));
  assert.match(f.api.thread.at(-1).body, /next action/);
});

test('active issue queried independently; undelegation halts without redispatch', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); f.api.issues[0].delegate = null;
  await f.connector.poll(); assert.equal(f.cancellations.length, 1); assert.match(f.connector.active.halted, /delegation/); assert.equal(f.sent.length, 1);
});

test('source edit and human comments halt, ingestion dedupes and own comments never loop', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await f.connector.poll(); assert.equal(f.steering.length, 0);
  f.api.thread.push({ id: 'human-1', body: '/abra stop', user: { id: id(99) }, updatedAt: 'now' });
  await f.connector.poll(); await f.connector.poll(); assert.equal(f.steering.length, 1); assert.equal(f.cancellations.length, 1);
  assert.equal(f.connector.active.comments['human-1'].length, 64);
  const g = fixture(t); await g.connector.enable('session-2'); g.api.issues[0].description += ' changed'; await g.connector.poll(); assert.match(g.connector.active.halted, /material issue edit/);
});

test('comment lost response is reconciled without duplicate publication', async t => {
  const f = fixture(t); f.api.failComment = 'after'; await f.connector.enable('session-1');
  assert.equal(f.sent.length, 0); assert.equal(f.connector.active.publications[0].comment, 'intent');
  await f.connector.poll(); assert.notEqual(f.connector.active.publications[0].comment, 'intent'); assert.equal(f.api.thread.length, 1); assert.equal(f.sent.length, 0);
});

test('unconfirmed comment is not retried by polling, even when remote listing is empty', async t => {
  const f = fixture(t); f.api.failComment = 'before'; await f.connector.enable('session-1'); await f.connector.poll();
  assert.equal(f.api.calls.filter(c => c === 'comment').length, 1); assert.equal(f.connector.status().pending[0], 'pickup');
});

test('status lost response reconciles while preserving confirmed comment', async t => {
  const f = fixture(t); f.api.failState = 'after'; await f.connector.enable('session-1'); await f.connector.poll();
  assert.equal(f.connector.active.publications[0].state, 'confirmed'); assert.equal(f.api.calls.filter(c => c === 'status').length, 1); assert.equal(f.api.thread.length, 1);
});

test('structured checkpoints bind tasks-axi and require actual terminal delivery not prose', async t => {
  const f = fixture(t); await f.connector.enable('session-1');
  await assert.rejects(f.connector.checkpoint(checkpoint('review')), /bind task/);
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('bind'), task: 'foreign' }), /task id/);
  await bind(f); await f.connector.checkpoint(checkpoint('approach'));
  await assert.rejects(f.connector.checkpoint(checkpoint('review')), /invalid configuration/);
  assert.equal(f.api.issues[0].state.id, id(4));
  await f.connector.checkpoint(checkpoint('blocked')); assert.equal(f.api.issues[0].state.id, id(6)); assert.ok(f.connector.active);
  await f.connector.release('operator confirmed all native owners stopped and task continuity saved');
  assert.equal(f.connector.active, undefined);
});

test('public report content is visible in linear; private path alone never counts', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  const report = join(f.path, 'data', f.connector.active.taskId, 'public.md'); fs.mkdirSync(join(report, '..'), { recursive: true }); fs.writeFileSync(report, 'full public findings with test evidence');
  await f.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'report', reference: report } });
  assert.equal(f.api.issues[0].state.id, id(5)); assert.match(f.api.thread.at(-1).body, /full public findings with test evidence/);
  assert.ok(!f.api.thread.at(-1).body.includes(report));
  assert.deepEqual(f.connector.active.delivery, { kind: 'report', reference: report });
  await f.connector.release('confirmed native owners stopped; delivery receipts inspected'); assert.equal(f.connector.active, undefined);
  await assert.rejects(f.connector.enable('session-1'), /session already used/);
});

test('code delivery cannot use report-only authority or inaccessible local commit', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'local-commit', reference: 'abc' } }), /local commit/);
  const g = fixture(t); await g.connector.enable('session-2'); await bind(g, 'pr');
  await assert.rejects(g.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'pr', reference: 'https://github.com/example/abra/pull/1' } }), /no configured code publication authority/);
});

test('terminal partial failure requires same immutable key and no execution rerun', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f); f.api.failState = 'before';
  await assert.rejects(f.connector.checkpoint(checkpoint('blocked')));
  assert.equal(f.connector.active.terminal, null); assert.equal(f.connector.status().pending[0], 'blocked');
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('blocked'), summary: 'changed' }), /different content/);
  await assert.rejects(f.connector.checkpoint(checkpoint('blocked')), /status outcome uncertain/);
  f.api.failState = null;
  await f.connector.reconcile({ key: 'blocked', state: 'not-applied', evidence: 'operator confirmed original request finished without applying status' });
  await f.connector.checkpoint(checkpoint('blocked'));
  assert.equal(f.api.thread.length, 2); assert.equal(f.sent.length, 1); assert.equal(f.connector.active.terminal, 'blocked');
});

test('redaction removes known credential, authorization patterns and private home paths', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  await f.connector.checkpoint({ ...checkpoint('progress'), summary: 'secret-test-token Bearer xyz token=abc /Users/private/report.md' });
  const body = f.api.thread.at(-1).body; assert.ok(!body.includes('secret-test-token')); assert.ok(!body.includes('xyz')); assert.ok(!body.includes('/Users/private')); assert.ok(!body.includes('token=abc'));
});

test('auth errors pause, retry-after/backoff is respected; shutdown clears timer', async t => {
  const f = fixture(t); f.api.discover = async () => { throw new ApiError('linear http 429', { retryMs: 90000 }); };
  await f.connector.enable('session-1'); assert.ok(f.connector.nextPoll >= Date.now() + 89000);
  f.api.discover = async () => { throw new ApiError('linear http 401', { auth: true }); };
  await f.connector.poll(); assert.equal(f.connector.mode, 'paused');
  await f.connector.dispose(); assert.equal(f.connector.nextPoll, null); assert.equal(f.connector.store.held, false);
});

test('missing active issue preserves ownership and reports failure instead of success', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); f.api.issues = []; await f.connector.poll(); assert.ok(f.connector.active); assert.ok(f.connector.error); assert.equal(f.sent.length, 1);
});

test('malformed/foreign metadata and symlinks are preserved and rejected', t => {
  const path = temporary(t), store = new Store(path, config()); store.acquire('s');
  fs.writeFileSync(store.path, '{malformed'); assert.throws(() => store.load()); assert.equal(fs.readFileSync(store.path, 'utf8'), '{malformed');
  fs.unlinkSync(store.path); const target = join(path, 'target'); fs.writeFileSync(target, '{}'); fs.symlinkSync(target, store.path); assert.throws(() => store.load(), /unsafe/); store.release();
});

const response = data => ({ ok: true, headers: new Headers(), json: async () => ({ data }) });
test('graphql boundary paginates discovery/comments/states and never commits a partial page', async () => {
  const calls = [];
  const client = new LinearClient(config(), 'credential', async (url, init) => {
    calls.push(JSON.parse(init.body)); assert.equal(url, 'https://api.linear.app/graphql'); assert.equal(init.redirect, 'error');
    const { query, variables } = calls.at(-1);
    if (query.includes('AbraIdentity')) return response({ viewer: { id: id(2) }, organization: { id: id(1) } });
    const field = query.includes('AbraStates') ? 'workflowStates' : 'issues';
    return response({ [field]: { nodes: field === 'workflowStates' ? [{ id: variables.after ? id(5) : id(4), type: 'started', team: { id: id(3) } }, ...(variables.after ? [{ id: id(6), type: 'unstarted', team: { id: id(3) } }] : [])] : [issue(variables.after ? 11 : 8)], pageInfo: { hasNextPage: !variables.after, endCursor: 'page-2' } } });
  });
  await client.validate(); const issues = await client.discover(); assert.equal(issues.length, 2); assert.equal(calls.at(-1).variables.after, 'page-2');
  client.fetcher = async () => response({ issue: { comments: { nodes: [{ id: 'c' }], pageInfo: { hasNextPage: false } } } }); assert.equal((await client.comments(id(8))).length, 1);
  client.fetcher = async () => response({ issues: { nodes: [], pageInfo: { hasNextPage: true, endCursor: 'same' } } }); await assert.rejects(client.discover(), /pagination/);
});

test('identity and terminal/wrong-team status mapping validation fails closed', async () => {
  const client = new LinearClient(config(), 'credential', async () => response({ viewer: { id: id(99) }, organization: { id: id(1) } }));
  await assert.rejects(client.validate(), /not configured/);
  client.fetcher = async (_url, init) => JSON.parse(init.body).query.includes('AbraIdentity') ? response({ viewer: { id: id(2) }, organization: { id: id(1) } }) : response({ workflowStates: { nodes: [{ id: id(4), type: 'completed', team: { id: id(3) } }], pageInfo: { hasNextPage: false } } });
  await assert.rejects(client.validate(), /status mapping/);
});

test('graphql timeout/cancellation and http errors do not leak credentials or server bodies', async () => {
  const client = new LinearClient(config(), 'credential', async (_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true })));
  const controller = new AbortController(); const request = client.query('query', {}, controller.signal); controller.abort(); await assert.rejects(request);
  client.fetcher = async () => ({ ok: false, status: 429, headers: new Headers({ 'retry-after': '45' }) });
  await assert.rejects(client.query('query'), e => e.retryMs === 45000 && !e.message.includes('credential'));
  client.fetcher = async () => ({ ok: true, headers: new Headers(), json: async () => ({ errors: [{ message: 'private body credential' }] }) });
  await assert.rejects(client.query('query'), e => !e.message.includes('private body'));
});

test('prompt preserves policy, exact-candidate review, authority and terminal discipline', () => {
  const prompt = coordinatorPrompt(issue(), config().repositories[0], config());
  for (const required of ['original intent', 'AGENTS.md', 'bin/tasks', 'native owners', 'dispatch intent', 'exact-candidate', 'make format', 'make test', 'report is not code delivery', 'no merge/deploy', 'raw reasoning', 'in linear', 'kind blocked', 'implementation is authorized under pr authority', 'push the verified branch', 'in review using kind review', 'explicit re-delegation permits another attempt']) assert.ok(prompt.includes(required), required);
});

function fakePi() {
  const handlers = {}, commands = {}, tools = {}, sent = [], entries = [], deferred = [], emitter = new EventEmitter();
  const events = { on: (name, fn) => { emitter.on(name, fn); return () => emitter.off(name, fn); }, emit: (...args) => emitter.emit(...args) };
  return { handlers, commands, tools, sent, events, entries, appendEntry: (customType, data) => entries.push({ customType, data }), on: (event, fn) => handlers[event] = fn, registerCommand: (name, cmd) => commands[name] = cmd, registerTool: tool => tools[tool.name] = tool, sendUserMessage: (...args) => {
    if (args[1]?.expandPromptTemplates && args[0].startsWith('/abra-linear settled ')) deferred.push(args[0]);
    else sent.push(args);
  }, drainSettled: async ctx => { while (deferred.length) await commands['abra-linear'].handler(deferred.shift().slice('/abra-linear '.length), ctx); }, setSessionName: () => {} };
}
async function settleAndPoll(pi, ctx, event = {}) {
  await pi.handlers.agent_settled(event, ctx);
  await pi.drainSettled(ctx);
  await pi.commands['abra-linear'].handler('poll', ctx);
}
function context(path, entries = []) {
  const notifications = [];
  return { cwd: path, notifications, hasUI: true, isProjectTrusted: () => true, isIdle: () => true, hasPendingMessages: () => false, abort: async () => {}, sessionManager: { getBranch: () => entries, getSessionId: () => 'pi-session', getSessionFile: () => 'old-session' }, ui: { notify: m => notifications.push(m), confirm: async () => true } };
}
test('pi factory/reload never auto-enables and commands only create new sessions on explicit start', async t => {
  const path = temporary(t), cfg = config(), api = new FakeApi(), pi = fakePi(); fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(cfg));
  install(pi, '.pi', { api }); const ctx = context(path);
  await pi.handlers.session_start({ reason: 'startup' }, ctx); assert.equal(api.calls.length, 0);
  let setup;
  ctx.newSession = async options => { setup = options; await options.setup(SessionManager.create(path, join(path, 'sessions'))); return { cancelled: false }; };
  await pi.commands['abra-linear'].handler('start', ctx); assert.ok(setup); assert.equal(api.calls.length, 0);
  await pi.handlers.session_start({ reason: 'reload' }, context(path, [{ type: 'custom', customType: 'abra-linear-dedicated' }])); assert.equal(api.calls.length, 0);
  const input = pi.handlers.input({ source: 'interactive' }, ctx); assert.equal(input.action, 'handled');
});

test('pi idle without delivery gets one reporting continuation before readable blocked handoff', async t => {
  const path = temporary(t), api = new FakeApi(), pi = fakePi(); fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(config()));
  install(pi, '.pi', { api }); const ctx = context(path);
  ctx.sessionManager = SessionManager.create(path, join(path, 'sessions'));
  seedDedicatedSession(ctx.sessionManager, { source: 'interactive', token: randomUUID(), previousSession: 'old-session' });
  await pi.handlers.session_start({ reason: 'new' }, ctx); assert.equal(pi.sent.length, 1); assert.deepEqual(pi.handlers.session_before_switch(), { cancel: true });
  await settleAndPoll(pi, ctx); assert.equal(api.issues[0].state.id, id(4)); assert.equal(pi.sent.length, 2);
  await settleAndPoll(pi, ctx); assert.equal(api.issues[0].state.id, id(6)); assert.match(api.thread.at(-1).body, /coordinator stopped without delivering/);
  assert.equal(api.issues[0].delegate, null);
  await pi.handlers.session_shutdown(); assert.ok(!fs.existsSync(join(path, 'data/linear/owner.lock')));
});

test('explicit not-sent reconciliation recovers admission only after proven no dispatch', async t => {
  const f = fixture(t); f.api.failComment = 'before'; await f.connector.enable('session-1');
  // legacy marker receipts must remain retryable after upgrading the extension.
  f.connector.active.publications[0].body = f.connector.active.publications[0].body.replace(':session-1:pickup', ':pickup');
  f.connector.persist();
  f.api.failComment = null;
  await f.connector.reconcile({ key: 'pickup', comment: 'not-applied', dispatch: 'not-sent', evidence: 'operator inspected pi session and native owners: no dispatch occurred; original request ended without comment' });
  assert.equal(f.sent.length, 1); assert.equal(f.connector.active.dispatch, 'sent');
  await assert.rejects(f.connector.reconcile({ key: 'pickup', dispatch: 'not-sent', evidence: 'try again' }), /already have executed/);
});

test('checkpoint rechecks source and refuses in-review after delegation changes', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f); f.api.issues[0].delegate = null;
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/report' } }), /unchanged delegation/);
  assert.equal(f.api.issues[0].state.id, id(4)); assert.equal(f.cancellations.length, 1);
});

test('shutdown aborts an in-flight poll before releasing the host lock', async t => {
  const f = fixture(t); f.api.issues = []; await f.connector.enable('session-1');
  let aborted = false;
  f.api.discover = signal => new Promise((_resolve, reject) => signal.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')); }, { once: true }));
  const poll = f.connector.poll(); await new Promise(r => setImmediate(r)); await f.connector.dispose(); await poll;
  assert.equal(aborted, true); assert.equal(f.store.held, false);
});

test('pr evidence gates exact clean candidate, independent detached review, repository and base without size limits', async t => {
  const { execFileSync } = await import('node:child_process');
  const f = fixture(t); const directory = join(f.path, 'candidate'); fs.mkdirSync(directory);
  const git = args => execFileSync('git', ['-C', directory, ...args], { encoding: 'utf8' }).trim();
  git(['init', '-q', '-b', 'main']); git(['config', 'user.name', 'local test']); git(['config', 'user.email', 'test@example.invalid']); git(['remote', 'add', 'origin', 'https://github.com/example/abra.git']);
  fs.writeFileSync(join(directory, 'file.md'), 'base\n'); git(['add', '.']); git(['commit', '-qm', 'base']); const baseCommit = git(['rev-parse', 'HEAD']);
  git(['checkout', '-qb', 'candidate']);
  fs.appendFileSync(join(directory, 'file.md'), 'changed\n'.repeat(10001));
  for (let index = 0; index < 101; index++) fs.writeFileSync(join(directory, `added-${index}.md`), 'new file\n');
  fs.writeFileSync(join(directory, 'asset.bin'), Buffer.from([0, 1, 2, 3]));
  git(['add', '.']); git(['commit', '-qm', 'candidate']);
  const candidate = git(['rev-parse', 'HEAD']), verifierDirectory = join(f.path, 'detached-verifier'), verificationReport = join(f.path, 'review.md');
  git(['worktree', 'add', '--detach', verifierDirectory, candidate]); fs.writeFileSync(verificationReport, 'independent review: pass with command evidence');
  f.cfg.authority = { mode: 'pr' };
  const delivery = { kind: 'pr', reference: 'https://github.com/example/abra/pull/1', candidate, baseCommit, workerDirectory: directory, verifierDirectory, verificationReport, verifiedCommit: candidate, checks: { intent: 'pass', tests: 'pass', docs: 'not-applicable', format: 'pass' }, prHead: candidate, prBase: 'main', ci: 'passed', externalEvidence: 'coordinator checked authorized pr target/head and required ci through gh-axi' };
  const repo = { ...f.cfg.repositories[0], path: directory }; await f.connector.codeDelivery(delivery, repo);
  f.cfg.repositories[0].path = directory;
  await f.connector.enable('session-1'); await bind(f, 'pr');
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery: { ...delivery, reference: 'https://github.com/foreign/repo/pull/1' } }), /configured repository/);
  f.api.failAttachment = true;
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery }), /attachment unavailable/);
  assert.equal(f.api.issues[0].state.id, id(4)); assert.equal(f.connector.active.terminal, null);
  f.api.failAttachment = false;
  await f.connector.checkpoint({ ...checkpoint('review'), delivery });
  assert.deepEqual(f.api.attached, { id: id(8), url: delivery.reference });
  assert.equal(f.api.issues[0].state.id, id(5));
  assert.equal(f.api.thread.filter(c => c.body.includes('reviewable pr:')).length, 1);
  assert.equal(f.connector.active.terminal, 'review');
  assert.deepEqual(f.store.load().records[0].delivery, delivery);
  await f.connector.codeDelivery({ ...delivery, ci: 'not-required', externalEvidence: 'gh-axi confirmed no required checks; ci did not run' }, repo);

  for (const [field, value, pattern] of [['verifiedCommit', 'a'.repeat(40), /exact candidate/], ['baseCommit', candidate, /base changed/], ['ci', 'pending', /required ci/], ['prHead', baseCommit, /pr head/], ['prBase', 'other', /pr head/], ['externalEvidence', '', /external evidence/], ['verifierDirectory', directory, /independent verifier/]]) {
    await assert.rejects(f.connector.codeDelivery({ ...delivery, [field]: value }, repo), pattern);
  }
  await assert.rejects(f.connector.codeDelivery({ ...delivery, checks: { ...delivery.checks, tests: 'blocked' } }, repo), /checks must pass/);
  await assert.rejects(f.connector.codeDelivery(delivery, { ...repo, remote: 'https://github.com/foreign/repo' }), /repository differs/);
  fs.appendFileSync(join(verifierDirectory, 'file.md'), 'dirty\n'); await assert.rejects(f.connector.codeDelivery(delivery, repo), /dirty/);
  fs.writeFileSync(join(verifierDirectory, 'file.md'), 'base\n' + 'changed\n'.repeat(10001));
  fs.appendFileSync(join(directory, 'file.md'), 'dirty\n'); await assert.rejects(f.connector.codeDelivery(delivery, repo), /dirty/);
  git(['worktree', 'remove', verifierDirectory]);
});

test('request deadline cancels hanging graphql, with no retry side effects', async () => {
  const client = new LinearClient(config(), 'credential', async (_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true })));
  const keepAlive = setTimeout(() => {}, 500);
  try { await assert.rejects(client.query('query'), error => error.name === 'TimeoutError'); } finally { clearTimeout(keepAlive); }
});

test('shutdown of active control poll never injects new work or cancellation messages', async t => {
  const f = fixture(t); await f.connector.enable('session-1');
  f.api.issue = (_id, signal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }));
  const poll = f.connector.poll(); await new Promise(r => setImmediate(r)); await f.connector.dispose(); await poll;
  assert.equal(f.cancellations.length, 0); assert.equal(f.sent.length, 1); assert.equal(f.store.held, false);
});

test('leftover temporary blocks fresh metadata initialization without deleting evidence', t => {
  const path = temporary(t), store = new Store(path, config()); store.load();
  const leftover = `${store.path}.previous-owner.tmp`; fs.writeFileSync(leftover, 'possibly published before interruption');
  assert.throws(() => store.load(), /leftover connector temporary/); assert.ok(fs.existsSync(leftover));
});

async function watchFixture(t, configure = () => {}, nativeRequest) {
  const path = temporary(t), cfg = config(), api = new FakeApi(), pi = fakePi(), nonce = randomUUID();
  cfg.watch = { trustedManagedWork: true }; fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(cfg));
  const old = process.env.ABRA_LINEAR_WATCH_NONCE; process.env.ABRA_LINEAR_WATCH_NONCE = nonce;
  t.after(() => { if (old === undefined) delete process.env.ABRA_LINEAR_WATCH_NONCE; else process.env.ABRA_LINEAR_WATCH_NONCE = old; });
  const ctx = context(path); ctx.mode = 'rpc';
  const dependencies = { api, nativeRequest: nativeRequest ? (method, params) => nativeRequest(method, params, ctx) : (async method => {
    if (method === 'ping') return { version: 1, capabilities: { processTerminalProof: { version: 1, lifecycleArtifactVersion: 3 } }, session: { sessionId: ctx.sessionManager.getSessionId() } };
    return { fleet: { version: 1, totalActive: 0, omitted: 0 }, asyncSnapshot: { kind: 'pi-subagents.async-status-snapshot', version: 1, omitted: { runs: 0, children: 0, byteLimitExceeded: false }, runs: [] } };
  }) };
  install(pi, '.pi', dependencies);
  ctx.newSession = async options => {
    await pi.handlers.session_shutdown();
    ctx.sessionManager = SessionManager.create(path, join(path, 'sessions'));
    await options.setup(ctx.sessionManager);
    install(pi, '.pi', dependencies);
    await pi.handlers.session_start({ reason: 'new' }, ctx);
    return { cancelled: false };
  };
  resources.set(t, [{ dispose: () => pi.handlers.session_shutdown() }]);
  const command = args => pi.commands['abra-linear'].handler(args, ctx);
  configure(api);
  await command(`watch-start ${nonce}`);
  assert.equal(api.calls.length, 0); assert.equal(pi.sent.length, 0);
  await command(`watch-arm ${nonce} pi-session`);
  const f = { path, cfg, api, pi, nonce, ctx, command };
  saveTask(f);
  return f;
}

test('extension watch binds nonce/session/task, confirmed linear delivery and settled coordinator before release', async t => {
  const f = await watchFixture(t);
  assert.deepEqual(f.pi.entries.filter(e => e.customType === 'abra-linear-watch').map(e => e.data.state), ['ready', 'admitted']);
  await f.pi.tools.abra_linear_checkpoint.execute('bind', { ...checkpoint('bind'), requestedDelivery: 'report' }, null, null, f.ctx);
  await f.pi.tools.abra_linear_checkpoint.execute('review', { ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/report' } }, null, null, f.ctx);
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`); assert.equal(f.pi.entries.at(-1).data.state, 'working');
  await settleAndPoll(f.pi, f.ctx);
  f.ctx.hasPendingMessages = () => true;
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`); assert.equal(f.pi.entries.at(-1).data.state, 'working');
  f.ctx.hasPendingMessages = () => false;
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`);
  const handoff = f.pi.entries.at(-1).data; assert.equal(handoff.state, 'handoff'); assert.equal(handoff.outcome, 'review'); assert.equal(handoff.task, `linear-${id(8)}`);
  const saved = new Store(f.path, f.cfg).load(); assert.equal(saved.active, null); assert.deepEqual(saved.records[0].managedProofs, []);
  assert.ok(!fs.existsSync(join(f.path, 'data/linear/owner.lock')));
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`); assert.equal(f.pi.entries.at(-1).data.state, 'uncertain');
});

test('waiting checkpoint retains clarification session without false blocked fallback or handoff', async t => {
  const f = await watchFixture(t);
  await f.pi.tools.abra_linear_checkpoint.execute('bind', { ...checkpoint('bind'), requestedDelivery: 'report' }, null, null, f.ctx);
  await f.pi.tools.abra_linear_checkpoint.execute('wait', checkpoint('waiting'), null, null, f.ctx);
  await settleAndPoll(f.pi, f.ctx);
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`);
  assert.equal(f.pi.entries.at(-1).data.state, 'awaiting-input'); assert.equal(f.api.issues[0].state.id, id(4));
  assert.ok(new Store(f.path, f.cfg).load().active);
});

test('watch never releases terminal blocked while native launch intent is unresolved', async t => {
  const f = await watchFixture(t);
  await f.pi.tools.abra_linear_checkpoint.execute('bind', { ...checkpoint('bind'), requestedDelivery: 'report' }, null, null, f.ctx);
  await f.pi.tools.abra_linear_checkpoint.execute('blocked', checkpoint('blocked'), null, null, f.ctx);
  await settleAndPoll(f.pi, f.ctx);
  f.pi.handlers.tool_execution_start({ toolName: 'subagent', toolCallId: 'unresolved', args: { agent: 'worker', async: true } });
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`);
  assert.equal(f.pi.entries.at(-1).data.state, 'uncertain'); assert.ok(new Store(f.path, f.cfg).load().active);
  assert.ok(fs.existsSync(join(f.path, 'data/linear/owner.lock')));
});

test('old workflow-backed journal is rejected without migration or deletion', t => {
  const path = temporary(t), store = new Store(path, config()); store.load();
  const old = JSON.stringify({ version: 1, identity: store.identity, records: [], active: null });
  fs.writeFileSync(store.path, old);
  assert.throws(() => store.load(), /incompatible/);
  assert.equal(fs.readFileSync(store.path, 'utf8'), old);
});

test('report review refuses missing, empty, oversized, outside and symlink artifacts and credential URLs', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  const directory = join(f.path, 'data', f.connector.active.taskId); fs.mkdirSync(directory, { recursive: true });
  const empty = join(directory, 'empty.md'), large = join(directory, 'large.md'), link = join(directory, 'link.md');
  fs.writeFileSync(empty, ''); fs.writeFileSync(large, 'x'.repeat(12001)); fs.symlinkSync(large, link);
  for (const reference of [empty, large, link, join(directory, 'missing.md'), join(f.path, 'outside.md'), 'https://user:password@example.test/report']) {
    await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'report', reference } }));
    assert.equal(f.connector.active.terminal, null);
    assert.equal(f.api.issues[0].state.id, id(4));
  }
});

test('review receipt is durable and immutable across uncertain status publication', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f); f.api.failState = 'before';
  const delivery = { kind: 'report', reference: 'https://example.test/public-report' };
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery }));
  assert.deepEqual(new Store(f.path, f.cfg).load().records[0].delivery, delivery);
  await assert.rejects(f.connector.release('all owners stopped'), /terminal checkpoint/);
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery: { ...delivery, reference: 'https://example.test/different-report' } }), /delivery receipt already bound/);
  f.api.failState = null;
  await f.connector.reconcile({ key: 'review', state: 'not-applied', evidence: 'operator inspected and confirmed original request finished without applying status' });
  await f.connector.checkpoint({ ...checkpoint('review'), delivery });
  assert.equal(f.connector.active.terminal, 'review'); assert.equal(f.api.thread.length, 2);
});

test('taskBinding rejects absent backlog/helper, missing or foreign task and unsupported full detail', async t => {
  const f = fixture(t); await f.connector.enable('session-1');
  const input = { ...checkpoint('bind'), requestedDelivery: 'report' };
  await assert.rejects(f.connector.checkpoint(input));
  assert.equal(f.connector.active.bound, false);
  saveTask(f);
  await assert.rejects(f.connector.checkpoint(checkpoint('bind')), /original requested delivery/);
  for (const overrides of [{ id: 'foreign-task' }, { repo: 'foreign-repo' }, { body: 'no original source or requested delivery' }, { body: `original source and acceptance: data/foreign/source.json\nrequested delivery: report` }, { body: `original source and acceptance: data/linear-${id(8)}/source.json\nrequested delivery: pr` }, { body: `original source and acceptance: data/linear-${id(8)}/source.json\nrequested delivery: report\nrequested delivery: pr` }]) {
    saveTask(f, 'report', overrides);
    await assert.rejects(f.connector.checkpoint(input), /foreign|source\/acceptance|requested delivery/);
    assert.equal(f.connector.active.bound, false);
  }
  saveTask(f);
  fs.writeFileSync(join(f.path, 'bin/tasks'), '#!/bin/sh\nexit 1\n');
  await assert.rejects(f.connector.checkpoint(input));
  fs.writeFileSync(join(f.path, 'bin/tasks'), '#!/bin/sh\nprintf "unsupported detail\\n"\n');
  await assert.rejects(f.connector.checkpoint(input), /unsupported tasks-axi/);
  fs.unlinkSync(join(f.path, 'bin/tasks'));
  await assert.rejects(f.connector.checkpoint(input));
  assert.equal(f.connector.active.bound, false); assert.equal(f.api.issues[0].state.id, id(4));
});

test('taskBinding rejects missing, foreign, edited and symlink original source snapshots', async t => {
  const f = fixture(t); await f.connector.enable('session-1');
  const input = { ...checkpoint('bind'), requestedDelivery: 'report' }, source = join(f.path, 'data', input.task, 'source.json');
  for (const snapshot of [{ ...issue(), id: id(10) }, { ...issue(), description: 'substituted acceptance' }]) {
    saveTask(f); fs.writeFileSync(source, JSON.stringify(snapshot));
    await assert.rejects(f.connector.checkpoint(input), /original source\/acceptance/);
    assert.equal(f.connector.active.bound, false);
  }
  saveTask(f); fs.unlinkSync(source);
  await assert.rejects(f.connector.checkpoint(input));
  fs.symlinkSync(join(f.path, 'data/backlog.md'), source);
  await assert.rejects(f.connector.checkpoint(input), /unsafe/);
  assert.equal(f.connector.active.bound, false);
});

for (const mode of ['report', 'pr']) {
  test(`bound code intent cannot become terminal report under ${mode} authority; blocked remains available`, async t => {
    const f = fixture(t); f.cfg.authority = { mode };
    f.api.issues[0].title = 'implement the login fix and deliver a pull request';
    f.api.issues[0].description = 'product code, independent review and actual pr required; report is not delivery';
    await f.connector.enable('session-1'); await bind(f, 'pr');
    const original = clone(f.connector.active.binding);
    await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/analysis-only' } }), /publication authority|bound requested delivery/);
    await assert.rejects(f.connector.checkpoint({ ...checkpoint('bind'), requestedDelivery: 'report' }), /already confirmed/);
    assert.equal(f.connector.active.terminal, null); assert.equal(f.api.issues[0].state.id, id(4));
    assert.equal(f.connector.active.delivery, undefined);
    assert.deepEqual(f.store.load().records[0].binding, original);
    if (mode === 'report') await assert.rejects(f.connector.checkpoint(checkpoint('approach')), /publication authority/);
    await f.connector.checkpoint(checkpoint('blocked'));
    assert.equal(f.connector.active.terminal, 'blocked'); assert.equal(f.api.issues[0].state.id, id(6));
    await f.connector.release('coordinator-only blocked work; inspected owners and receipts', async () => []);
    assert.equal(f.store.load().active, null);
  });
}

test('bound report review rechecks task/source assertion without pinning routine task continuity', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  const original = clone(f.connector.active.binding), input = { ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/genuine-report' } };
  const source = join(f.path, original.source), raw = fs.readFileSync(source, 'utf8');
  saveTask(f, 'pr');
  await assert.rejects(f.connector.checkpoint(input), /requested delivery differs/);
  saveTask(f); fs.writeFileSync(source, JSON.stringify({ ...issue(), description: 'changed acceptance' }));
  await assert.rejects(f.connector.checkpoint(input), /changed original source/);
  fs.writeFileSync(source, raw + '\n');
  await assert.rejects(f.connector.checkpoint(input), /bound original source\/acceptance changed/);
  fs.writeFileSync(source, raw);
  saveTask(f, 'report', { body: `original source and acceptance: ${original.source}\nrequested delivery: report\nprogress: investigation completed, public findings prepared` });
  fs.writeFileSync(source, raw);
  await f.connector.checkpoint(input);
  assert.equal(f.connector.active.terminal, 'review'); assert.equal(f.api.issues[0].state.id, id(5));
  assert.deepEqual(f.store.load().records[0].binding, original);
  assert.deepEqual(f.store.load().records[0].delivery, input.delivery);
});

test('old unqualified bound journal and mismatched review receipt reject without changing evidence', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f, 'pr');
  const state = f.store.load();
  delete state.records[0].binding;
  fs.writeFileSync(f.store.path, JSON.stringify(state)); const old = fs.readFileSync(f.store.path, 'utf8');
  assert.throws(() => f.store.load(), /incompatible task binding/);
  assert.equal(fs.readFileSync(f.store.path, 'utf8'), old);
  state.records[0].binding = clone(f.connector.active.binding);
  state.records[0].terminal = 'review'; state.records[0].delivery = { kind: 'report', reference: 'https://example.test/substitute' };
  fs.writeFileSync(f.store.path, JSON.stringify(state)); const mismatched = fs.readFileSync(f.store.path, 'utf8');
  assert.throws(() => f.store.load(), /bound requested delivery/);
  assert.equal(fs.readFileSync(f.store.path, 'utf8'), mismatched);
});

test('bound task disappearance blocks report review but not truthful blocked reporting', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  fs.unlinkSync(join(f.path, 'data/backlog.md'));
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/report' } }));
  assert.equal(f.connector.active.terminal, null); assert.equal(f.api.issues[0].state.id, id(4));
  await f.connector.checkpoint({ ...checkpoint('blocked'), blocker: 'original task/source unavailable; preserve and reconcile before any review' });
  assert.equal(f.connector.active.terminal, 'blocked'); assert.equal(f.api.issues[0].state.id, id(6));
});

for (const [error, code] of [
  [new ApiError('secret-auth-canary /private/path ticket-description', { auth: true }), 'connector-auth-failed'],
  [new ApiError('secret-request-canary /private/path ticket-description'), 'connector-request-failed'],
  [new DOMException('secret-timeout-canary', 'TimeoutError'), 'connector-request-failed'],
  [new Error('secret-operation-canary /private/path ticket-description'), 'connector-operation-failed'],
]) {
  test(`connector status and watch-check expose only typed ${code} diagnostics`, async t => {
    const f = await watchFixture(t);
    f.api.issue = async () => { throw error; };
    await f.command('poll');
    await f.command(`watch-check ${f.nonce} ${randomUUID()}`);
    const outcome = f.pi.entries.at(-1).data;
    assert.equal(outcome.state, 'uncertain'); assert.equal(outcome.code, code);
    assert.equal(outcome.diagnostic, undefined);
    assert.doesNotMatch(JSON.stringify(outcome) + f.ctx.notifications.join(''), /secret-|\/private\/path|ticket-description/);
    await f.command('status');
    const status = JSON.parse(f.ctx.notifications.at(-1));
    assert.equal(status.diagnostic, code); assert.ok(status.error.includes(`[${code}]`));
    assert.ok(new Store(f.path, f.cfg).load().active);
    assert.ok(fs.existsSync(join(f.path, 'data/linear/owner.lock')));
  });
}

test('connector diagnostic clears after a successful explicit poll', async t => {
  const f = fixture(t), discover = f.api.discover.bind(f.api);
  f.api.discover = async () => { throw new ApiError('secret-canary'); };
  await f.connector.enable('session-1'); assert.equal(f.connector.status().diagnostic, 'connector-request-failed');
  f.api.discover = discover;
  await f.connector.poll(); assert.equal(f.connector.status().diagnostic, null); assert.equal(f.connector.error, null);
});

test('watch-check distinguishes pending publication from native ownership faults', async t => {
  const f = await watchFixture(t);
  await f.pi.tools.abra_linear_checkpoint.execute('bind', { ...checkpoint('bind'), requestedDelivery: 'report' }, null, null, f.ctx);
  f.api.failState = 'after';
  await assert.rejects(f.pi.tools.abra_linear_checkpoint.execute('blocked', checkpoint('blocked'), null, null, f.ctx));
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`);
  assert.equal(f.pi.entries.at(-1).data.code, 'publication-pending');
  f.pi.handlers.tool_execution_start({ toolName: 'subagent', toolCallId: 'unknown', args: { async: true } });
  f.pi.handlers.tool_execution_end({ toolName: 'subagent', toolCallId: 'unknown', result: { details: {} } });
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`);
  assert.equal(f.pi.entries.at(-1).data.code, 'native-ownership-uncertain');
  assert.ok(new Store(f.path, f.cfg).load().active);
});

test('watch-start reports authentication failure as a correlated typed uncertainty', async t => {
  const f = await watchFixture(t, api => { api.validate = async () => { throw new ApiError('secret-startup-canary /private/path', { auth: true }); }; });
  const outcome = f.pi.entries.at(-1).data;
  assert.equal(outcome.state, 'uncertain'); assert.equal(outcome.request, 'start'); assert.equal(outcome.nonce, f.nonce);
  assert.equal(outcome.code, 'connector-auth-failed');
  assert.doesNotMatch(JSON.stringify(outcome) + f.ctx.notifications.join(''), /secret-startup-canary|\/private\/path/);
  assert.ok(!f.pi.entries.some(entry => entry.data.state === 'admitted'));
});

test('blocked handoff comments, returns to todo, removes only abra ownership and admits a re-delegated issue', async t => {
  const f = fixture(t); f.api.issues[0].assignee = { id: id(70) };
  await f.connector.enable('first'); await bind(f);
  await f.connector.checkpoint(checkpoint('blocked'));
  assert.equal(f.api.issues[0].state.id, f.cfg.teams[0].blocked);
  assert.equal(f.api.issues[0].delegate, null);
  assert.equal(f.api.issues[0].assignee.id, id(70));
  assert.ok(f.api.calls.lastIndexOf('comment') < f.api.calls.lastIndexOf('status'));
  assert.ok(f.api.calls.lastIndexOf('status') < f.api.calls.lastIndexOf('unassign'));
  await f.connector.poll(); assert.equal(f.cancellations.length, 0);
  await f.connector.release('all owners inspected and stopped', async () => []);
  const next = new Connector({ root: f.path, config: f.cfg, store: new Store(f.path, f.cfg), api: f.api, host: f.host });
  resources.set(t, [...resources.get(t), next]);
  await next.enable('second'); assert.equal(next.active, undefined);
  f.api.issues[0].delegate = { id: id(2) };
  await next.poll(); assert.equal(next.active.id, id(8));
  assert.equal(f.sent.length, 2); assert.equal(next.state.records.length, 1);
  assert.equal(next.active.halted, null); assert.equal(next.active.bound, false);
  assert.equal(f.api.thread.filter(c => c.body.includes('picked up ABRA-8:')).length, 2);
  assert.match(f.sent[1], /reuse the existing task and source snapshot/);
});

for (const failure of ['before', 'after']) {
  test(`uncertain unassignment (${failure}) retains receipts and never releases or blindly retries`, async t => {
    const f = fixture(t); f.api.issues[0].assignee = { id: id(2) };
    await f.connector.enable('first'); await bind(f);
    f.api.failUnassign = failure;
    await assert.rejects(f.connector.checkpoint(checkpoint('blocked')), /timeout|lost/);
    assert.equal(f.connector.status().pending.includes('blocked'), true);
    await assert.rejects(f.connector.release('not enough evidence'), /terminal checkpoint/);
    f.api.failUnassign = null;
    if (failure === 'before') {
      await assert.rejects(f.connector.checkpoint(checkpoint('blocked')), /unassignment outcome uncertain/);
      await assert.rejects(f.connector.checkpoint(checkpoint('blocked', 'fallback-blocked')), /unassignment outcome uncertain/);
      assert.equal(f.api.calls.filter(c => c === 'unassign').length, 1);
      await f.connector.reconcile({ key: 'blocked', unassign: 'not-applied', evidence: 'original request finished without applying; owners stopped' });
    }
    await f.connector.checkpoint(checkpoint('blocked'));
    assert.equal(f.api.issues[0].delegate, null); assert.equal(f.api.issues[0].assignee, null);
    assert.equal(f.connector.active.terminal, 'blocked'); assert.deepEqual(f.connector.status().pending, []);
    assert.equal(f.api.thread.length, failure === 'before' ? 3 : 2);
  });
}

test('a blocked record without stopped-owner release remains protected against duplicate execution', async t => {
  const f = fixture(t); await f.connector.enable('first'); await bind(f);
  await f.connector.checkpoint(checkpoint('blocked'));
  await f.connector.dispose();
  const next = new Connector({ root: f.path, config: f.cfg, store: new Store(f.path, f.cfg), api: f.api, host: f.host });
  resources.set(t, [...resources.get(t), next]);
  f.api.issues[0].delegate = { id: id(2) };
  await assert.rejects(next.enable('second'), /unresolved ownership/);
  assert.equal(f.sent.length, 1);
});

test('explicit authority changes preserve a released journal but cannot bypass ownership or change scope', async t => {
  const f = fixture(t); await f.connector.enable('first'); await bind(f);
  const cfg = { ...f.cfg, authority: { mode: 'pr' } };
  assert.throws(() => f.store.reconfigureAuthority(cfg), /reconcile native ownership/);
  await f.connector.checkpoint(checkpoint('blocked'));
  await f.connector.release('all owners stopped');
  f.store.acquire('configuration');
  assert.throws(() => f.store.reconfigureAuthority({ ...cfg, personaId: id(90) }), /only authority/);
  f.store.reconfigureAuthority(cfg); f.store.release();
  const state = new Store(f.path, cfg).load();
  assert.equal(state.records[0].terminal, 'blocked'); assert.ok(state.records[0].releaseEvidence);
});

test('discovery queries assignment or delegation, and pickup rejects a different delegate', async t => {
  const f = fixture(t), assigned = issue(); assigned.delegate = null; assigned.assignee = { id: id(2) };
  assert.ok(f.connector.eligible(assigned));
  assigned.delegate = { id: id(90) }; assert.equal(f.connector.eligible(assigned), null);
  assigned.delegate = null; f.api.issues = [assigned];
  await f.connector.enable('assigned-session'); assert.equal(f.sent.length, 1);
  let query;
  const api = new LinearClient(config(), 'test-token', async (_url, options) => {
    query = JSON.parse(options.body).query;
    return { ok: true, status: 200, headers: new Headers(), json: async () => ({ data: { issues: { nodes: [], pageInfo: { hasNextPage: false } } } }) };
  });
  await api.discover();
  assert.match(query, /or: \[\{delegate:.*\{assignee:/);
});

for (const assignee of [2, 70]) test(`review removes abra ownership and ${assignee === 2 ? 'clears app assignee' : 'preserves human assignee'}`, async t => {
  const f = fixture(t); f.api.issues[0].assignee = { id: id(assignee) };
  await f.connector.enable('session-1'); await bind(f);
  await f.connector.checkpoint({ ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/report' } });
  assert.equal(f.api.issues[0].delegate, null);
  assert.deepEqual(f.api.issues[0].assignee, assignee === 2 ? null : { id: id(70) });
  assert.equal(f.api.issues[0].state.id, id(5));
  await f.connector.poll(); assert.equal(f.cancellations.length, 0);
});

for (const lost of ['comment', 'status', 'unassign']) test(`review reconciles lost ${lost} response without replay or self-unassignment halt`, async t => {
  const f = fixture(t); f.api.issues[0].assignee = { id: id(70) };
  await f.connector.enable('session-1'); await bind(f);
  const input = { ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/report' } };
  const field = { comment: 'failComment', status: 'failState', unassign: 'failUnassign' }[lost];
  f.api[field] = 'after'; await assert.rejects(f.connector.checkpoint(input), /lost/); f.api[field] = null;
  await f.connector.poll();
  assert.equal(f.cancellations.length, 0);
  await f.connector.checkpoint(input);
  assert.equal(f.connector.active.terminal, 'review'); assert.equal(f.connector.active.halted, null);
  assert.equal(f.api.calls.filter(c => c === 'unassign').length, 1);
  assert.equal(f.api.thread.length, 2); assert.equal(f.api.issues[0].assignee.id, id(70));
  assert.deepEqual(f.connector.status().pending, []);
  await f.connector.release('all owners inspected and stopped');
});

for (const changed of ['source', 'delegate']) test(`lost review unassignment does not permit mutations after changed ${changed}`, async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  const input = { ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/report' } };
  f.api.failUnassign = 'after'; await assert.rejects(f.connector.checkpoint(input));
  if (changed === 'source') f.api.issues[0].description += ' new acceptance';
  else f.api.issues[0].delegate = { id: id(90) };
  const writes = f.api.calls.filter(c => ['comment', 'status', 'unassign'].includes(c)).length;
  await assert.rejects(f.connector.checkpoint(input), /unchanged delegation/);
  assert.equal(f.api.calls.filter(c => ['comment', 'status', 'unassign'].includes(c)).length, writes);
});

test('uncertain unapplied review unassignment requires explicit reconciliation before retry', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  const input = { ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/report' } };
  f.api.failUnassign = 'before'; await assert.rejects(f.connector.checkpoint(input)); f.api.failUnassign = null;
  await f.connector.poll(); await assert.rejects(f.connector.checkpoint(input), /unassignment outcome uncertain/);
  assert.equal(f.api.calls.filter(c => c === 'unassign').length, 1);
  await f.connector.reconcile({ key: 'review', unassign: 'not-applied', evidence: 'original request finished without applying; operator inspected remote issue' });
  await f.connector.checkpoint(input); assert.equal(f.connector.active.terminal, 'review');
});

test('public comments omit placeholder sections and describe pickup, milestones, checks and review', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  for (const [kind, summary] of [['approach', 'trace the token renewal path'], ['progress', 'found the stale token cache'], ['checks', 'renewal regression passes']]) {
    await f.connector.checkpoint({ kind, key: kind, summary, nextAction: 'review the renewal fix' });
  }
  await f.connector.checkpoint({ kind: 'review', key: 'review', summary: 'token renewal investigation is ready', nextAction: 'review the findings', delivery: { kind: 'report', reference: 'https://example.test/findings' } });
  const body = f.api.thread.map(c => c.body).join('\n');
  for (const expected of ['picked up ABRA-8: review request', 'trace the token renewal path', 'found the stale token cache', 'renewal regression passes', 'ready for review', 'https://example.test/findings']) assert.ok(body.includes(expected));
  assert.doesNotMatch(body, /not changed|not run|evidence-backed terminal|approach: undefined|checks\/tests: undefined/);
});

for (const mode of ['manual', 'watch']) for (const outcome of ['complete', 'failed']) test(`${mode} async yield stays working until real ${outcome} result is reported`, async t => {
  const path = temporary(t), pi = fakePi(), api = new FakeApi();
  const nativeDir = join(path, 'native'); fs.mkdirSync(nativeDir);
  let status, ctx, command, f;
  const request = async (method, params, ownerCtx = ctx) => {
    if (method === 'ping') return { version: 1, capabilities: { processTerminalProof: { version: 1, lifecycleArtifactVersion: 3 } }, session: { sessionId: ownerCtx.sessionManager.getSessionId() } };
    if (params?.id) return { details: { runId: 'scout-1' } };
    return { fleet: { version: 1, totalActive: 0, omitted: 0 }, asyncSnapshot: { kind: 'pi-subagents.async-status-snapshot', version: 1, omitted: { runs: 0, children: 0, byteLimitExceeded: false }, runs: [] } };
  };
  if (mode === 'watch') {
    f = await watchFixture(t, () => {}, request); ctx = f.ctx; command = f.command;
  } else {
    fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(config()));
    install(pi, '.pi', { api, nativeRequest: request }); ctx = context(path);
    ctx.sessionManager = SessionManager.create(path, join(path, 'sessions'));
    seedDedicatedSession(ctx.sessionManager, { source: 'interactive', token: randomUUID(), previousSession: 'old-session' });
    await pi.handlers.session_start({ reason: 'new' }, ctx);
    command = args => pi.commands['abra-linear'].handler(args, ctx); f = { path, pi, api, ctx }; saveTask(f);
    resources.set(t, [{ dispose: () => pi.handlers.session_shutdown() }]);
  }
  const activePi = f.pi;
  await activePi.tools.abra_linear_checkpoint.execute('bind', { ...checkpoint('bind'), requestedDelivery: 'report' }, null, null, ctx);
  status = { lifecycleArtifactVersion: 3, runId: 'scout-1', sessionId: ctx.sessionManager.getSessionFile(), mode: 'single', state: 'running' };
  const save = () => fs.writeFileSync(join(nativeDir, 'status.json'), JSON.stringify(status)); save();
  activePi.events.emit('subagent:async-started', { lifecycleArtifactVersion: 3, id: 'scout-1', sessionId: status.sessionId, mode: 'single', asyncDir: nativeDir });
  await settleAndPoll(activePi, ctx); await command('poll');
  assert.equal(f.api.issues[0].state.id, id(4)); assert.equal(activePi.sent.length, 1); assert.equal(f.api.thread.length, 1);
  status.state = outcome; save();
  // terminal artifact can precede its grouped completion notice; settle must still wait.
  await activePi.handlers.agent_settled({}, ctx); await activePi.drainSettled(ctx); assert.equal(activePi.sent.length, 1);
  activePi.handlers.message_start({ message: { role: 'custom', customType: 'subagent-notify', details: { runs: [{ runId: 'scout-1', status: outcome === 'complete' ? 'completed' : 'failed' }] } } });
  activePi.handlers.agent_start();
  const input = outcome === 'complete' ? { ...checkpoint('review'), summary: 'scout located the renewal bug', delivery: { kind: 'report', reference: 'https://example.test/scout-report' } } : { ...checkpoint('blocked'), summary: 'scout returned no findings', blocker: 'scout failed with an empty response; no code was changed', nextAction: 'check the scout model configuration and retry the investigation' };
  await activePi.tools.abra_linear_checkpoint.execute('terminal', input, null, null, ctx);
  await settleAndPoll(activePi, ctx);
  assert.equal(f.api.issues[0].state.id, outcome === 'complete' ? id(5) : id(6)); assert.equal(f.api.issues[0].delegate, null);
  assert.doesNotMatch(f.api.thread.at(-1).body, /evidence-backed terminal|not changed|not run/);
  if (outcome === 'failed') assert.match(f.api.thread.at(-1).body, /empty response/);
});

test('a missing native completion notice gets one result-inspection wake, not a false blocker or relaunch', async t => {
  const path = temporary(t), api = new FakeApi(), pi = fakePi(), ctx = context(path);
  const nativeDir = join(path, 'native'); fs.mkdirSync(nativeDir);
  fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(config()));
  install(pi, '.pi', { api, nativeRequest: async () => ({ details: { runId: 'scout-1' } }) });
  resources.set(t, [{ dispose: () => pi.handlers.session_shutdown() }]);
  ctx.sessionManager = SessionManager.create(path, join(path, 'sessions'));
  seedDedicatedSession(ctx.sessionManager, { source: 'interactive', token: randomUUID(), previousSession: 'old-session' });
  await pi.handlers.session_start({ reason: 'new' }, ctx);
  const status = { lifecycleArtifactVersion: 3, runId: 'scout-1', sessionId: ctx.sessionManager.getSessionFile(), mode: 'single', state: 'failed' };
  fs.writeFileSync(join(nativeDir, 'status.json'), JSON.stringify(status));
  pi.events.emit('subagent:async-started', { lifecycleArtifactVersion: 3, id: 'scout-1', sessionId: status.sessionId, mode: 'single', asyncDir: nativeDir });
  await pi.handlers.agent_settled({}, ctx); await pi.drainSettled(ctx); assert.equal(pi.sent.length, 1);
  await pi.commands['abra-linear'].handler('poll', ctx); assert.equal(pi.sent.length, 2); assert.match(pi.sent.at(-1)[0], /inspect these exact native results/);
  await pi.commands['abra-linear'].handler('poll', ctx); assert.equal(pi.sent.length, 2);
  assert.equal(api.issues[0].state.id, id(4));
  await settleAndPoll(pi, ctx); assert.equal(pi.sent.length, 3);
  await settleAndPoll(pi, ctx); assert.equal(api.issues[0].state.id, id(6));
  assert.match(api.thread.at(-1).body, /stopped without delivering/);
});

test('a native completion wake during status inspection cannot publish a stale settled blocker', async t => {
  const path = temporary(t), api = new FakeApi(), pi = fakePi(), ctx = context(path);
  const nativeDir = join(path, 'native'); fs.mkdirSync(nativeDir);
  fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(config()));
  let wake = false;
  install(pi, '.pi', { api, nativeRequest: async () => {
    if (wake) pi.handlers.agent_start();
    return { details: { runId: 'scout-1' } };
  } });
  resources.set(t, [{ dispose: () => pi.handlers.session_shutdown() }]);
  ctx.sessionManager = SessionManager.create(path, join(path, 'sessions'));
  seedDedicatedSession(ctx.sessionManager, { source: 'interactive', token: randomUUID(), previousSession: 'old-session' });
  await pi.handlers.session_start({ reason: 'new' }, ctx);
  // use the single reporting reminder so a stale second settle would otherwise block.
  await settleAndPoll(pi, ctx); assert.equal(pi.sent.length, 2);
  const status = { lifecycleArtifactVersion: 3, runId: 'scout-1', sessionId: ctx.sessionManager.getSessionFile(), mode: 'single', state: 'complete' };
  fs.writeFileSync(join(nativeDir, 'status.json'), JSON.stringify(status));
  pi.events.emit('subagent:async-started', { lifecycleArtifactVersion: 3, id: 'scout-1', sessionId: status.sessionId, mode: 'single', asyncDir: nativeDir });
  wake = true;
  await settleAndPoll(pi, ctx);
  assert.equal(api.issues[0].state.id, id(4)); assert.equal(pi.sent.length, 2);
  assert.equal(api.thread.length, 1);
});

for (const scenario of ['aborted', 'unknown-native']) test(`${scenario} gives a readable blocked handoff without freeing ownership`, async t => {
  const f = await watchFixture(t);
  if (scenario === 'unknown-native') f.pi.events.emit('subagent:async-started', { id: 'foreign', sessionId: 'foreign' });
  await settleAndPoll(f.pi, f.ctx, { aborted: scenario === 'aborted' });
  assert.equal(f.api.issues[0].state.id, id(6)); assert.equal(f.api.issues[0].delegate, null);
  assert.match(f.api.thread.at(-1).body, scenario === 'aborted' ? /interrupted/ : /could not confirm the status/);
  assert.ok(new Store(f.path, f.cfg).load().active);
  assert.ok(fs.existsSync(join(f.path, 'data/linear/owner.lock')));
});

async function fallbackFixture(t) {
  const path = temporary(t), api = new FakeApi(), pi = fakePi(), ctx = context(path), cfg = config();
  fs.mkdirSync(join(path, '.pi')); fs.writeFileSync(join(path, '.pi/abra-linear.json'), JSON.stringify(cfg));
  install(pi, '.pi', { api });
  resources.set(t, [{ dispose: () => pi.handlers.session_shutdown() }]);
  ctx.sessionManager = SessionManager.create(path, join(path, 'sessions'));
  seedDedicatedSession(ctx.sessionManager, { source: 'interactive', token: randomUUID(), previousSession: 'old-session' });
  await pi.handlers.session_start({ reason: 'new' }, ctx);
  await settleAndPoll(pi, ctx); assert.equal(pi.sent.length, 2);
  const poll = () => pi.commands['abra-linear'].handler('poll', ctx);
  const state = () => new Store(path, cfg).load().records[0];
  return { path, api, pi, ctx, cfg, poll, state };
}

for (const activity of ['wake', 'queued']) test(`late ${activity} during fallback comments read leaves no blocker or empty receipt`, async t => {
  const f = await fallbackFixture(t), comments = f.api.comments.bind(f.api);
  let reads = 0, interrupted = false;
  f.api.comments = async (...args) => {
    // first is normal control; second is the fallback publish read from the review probe.
    if (++reads === 2) {
      interrupted = true;
      if (activity === 'wake') { f.pi.handlers.agent_start(); f.ctx.isIdle = () => false; }
      else f.ctx.hasPendingMessages = () => true;
    }
    return comments(...args);
  };
  await f.pi.handlers.agent_settled({}, f.ctx);
  assert.equal(f.api.thread.length, 1);
  await f.pi.drainSettled(f.ctx); await f.poll();
  assert.equal(interrupted, true);
  assert.equal(f.api.issues[0].state.id, id(4)); assert.notEqual(f.api.issues[0].delegate, null);
  assert.equal(f.api.thread.length, 1);
  assert.deepEqual(f.state().publications.map(p => p.key), ['pickup']);
  assert.equal(f.state().terminal, null); assert.equal(f.state().halted, null);
});

for (const boundary of ['publication-issue', 'status-read', 'unassignment-read', 'comment-response', 'status-response', 'unassignment-response']) test(`fallback wake at ${boundary} stops later mutations and terminal marking, preserving issued receipts`, async t => {
  const f = await fallbackFixture(t);
  let interrupted = false, issues = 0;
  const wake = () => { interrupted = true; f.pi.handlers.agent_start(); f.ctx.isIdle = () => false; };
  const readTarget = { 'publication-issue': 3, 'status-read': 4, 'unassignment-read': 5 }[boundary];
  if (readTarget) {
    const issue = f.api.issue.bind(f.api);
    f.api.issue = async (...args) => { const value = await issue(...args); if (++issues === readTarget) wake(); return value; };
  } else {
    const method = { 'comment-response': 'comment', 'status-response': 'status', 'unassignment-response': 'unassign' }[boundary];
    const original = f.api[method].bind(f.api);
    f.api[method] = async (...args) => { const value = await original(...args); wake(); return value; };
  }
  const writesBefore = f.api.calls.filter(c => ['comment', 'status', 'unassign'].includes(c)).length;
  await settleAndPoll(f.pi, f.ctx);
  assert.equal(interrupted, true);
  const writes = f.api.calls.filter(c => ['comment', 'status', 'unassign'].includes(c)).slice(writesBefore);
  const expected = ['publication-issue'].includes(boundary) ? [] : ['status-read', 'comment-response'].includes(boundary) ? ['comment'] : ['unassignment-read', 'status-response'].includes(boundary) ? ['comment', 'status'] : ['comment', 'status', 'unassign'];
  assert.deepEqual(writes, expected);
  const state = f.state(), receipt = state.publications.find(p => p.key === 'settled-without-terminal');
  assert.equal(state.terminal, null); assert.equal(state.halted, null); assert.equal(state.releaseEvidence, undefined);
  if (!expected.length) assert.equal(receipt, undefined);
  else {
    assert.ok(receipt.comment && receipt.comment !== 'intent');
    assert.equal(receipt.state, expected.includes('status') ? 'confirmed' : null);
    assert.equal(receipt.unassign, expected.includes('unassign') ? 'confirmed' : undefined);
  }
});

for (const applied of [false, true]) test(`wake aborts in-flight fallback comment and retains uncertain receipt (applied=${applied})`, async t => {
  const f = await fallbackFixture(t), comment = f.api.comment.bind(f.api);
  let cancellationObserved = false;
  f.api.comment = async (issue, body, signal) => {
    if (applied) await comment(issue, body, signal);
    f.pi.handlers.agent_start(); f.ctx.isIdle = () => false;
    cancellationObserved = signal.aborted;
    throw signal.reason;
  };
  await settleAndPoll(f.pi, f.ctx);
  assert.equal(cancellationObserved, true);
  const receipt = f.state().publications.find(p => p.key === 'settled-without-terminal');
  assert.equal(receipt.comment, 'intent'); assert.equal(receipt.state, null);
  assert.equal(f.state().terminal, null); assert.equal(f.state().halted, null);
  assert.equal(f.api.issues[0].state.id, id(4)); assert.notEqual(f.api.issues[0].delegate, null);
  assert.equal(f.api.thread.length, applied ? 2 : 1);
  await f.poll();
  assert.equal(f.api.thread.length, applied ? 2 : 1, 'control must not replay an aborted comment');
  assert.equal(f.state().publications.at(-1).comment === 'intent', !applied);
});

test('an intervening run that starts and settles during publication invalidates the old fallback epoch', async t => {
  const f = await fallbackFixture(t), comments = f.api.comments.bind(f.api);
  let reads = 0;
  f.api.comments = async (...args) => {
    if (++reads === 2) {
      f.pi.handlers.agent_start();
      await f.pi.handlers.agent_settled({}, f.ctx);
      await f.pi.drainSettled(f.ctx);
    }
    return comments(...args);
  };
  await settleAndPoll(f.pi, f.ctx);
  assert.equal(f.api.thread.length, 1); assert.equal(f.state().terminal, null);
  assert.deepEqual(f.state().publications.map(p => p.key), ['pickup']);
});

test('installed pi defers later settled-handler native wakes until after the connector handler returns', async t => {
  const f = await fallbackFixture(t), { AgentSession } = await installedAgentSession();
  const host = Object.create(AgentSession.prototype);
  Object.assign(host, { _deferredSettledActions: [], _isAgentRunActive: true, _agentRunAbortRequested: false, _emit: () => {} });
  host._tryExecuteExtensionCommand = async text => {
    assert.match(text, /^\/abra-linear settled /);
    await f.pi.commands['abra-linear'].handler(text.slice('/abra-linear '.length), f.ctx);
    return true;
  };
  host._startRun = async ({ message }) => {
    host._isAgentRunActive = true;
    f.ctx.isIdle = () => false;
    f.pi.handlers.agent_start(); f.pi.handlers.message_start({ message });
  };
  f.pi.sendUserMessage = (text, options) => { void host.prompt(text, options); };
  host._extensionRunner = { emit: async event => {
    await f.pi.handlers.agent_settled(event, f.ctx);
    // a poll can run while a later settled handler is still awaiting its result.
    await f.poll(); assert.equal(f.api.thread.length, 1);
    await host.sendCustomMessage({ customType: 'subagent-notify', content: 'scout finished; inspect its result', display: false, details: { runs: [{ runId: 'scout-1', status: 'completed' }] } }, { triggerTurn: true });
    assert.equal(f.ctx.isIdle(), true, 'installed pi has not drained the native wake yet');
    await f.poll(); assert.equal(f.api.thread.length, 1);
  } };
  await host._emitAgentSettled();
  assert.equal(f.ctx.isIdle(), false, 'native completion starts after all settled handlers return');
  await f.poll();
  assert.equal(f.api.thread.length, 1); assert.equal(f.state().terminal, null);
  assert.deepEqual(f.state().publications.map(p => p.key), ['pickup']);
  assert.equal(f.api.issues[0].state.id, id(4)); assert.notEqual(f.api.issues[0].delegate, null);
});

test('confirmed fallback comment canceled by wake allows later real review and exact stopped-owner handoff', async t => {
  const f = await watchFixture(t);
  await f.pi.tools.abra_linear_checkpoint.execute('bind', { ...checkpoint('bind'), requestedDelivery: 'report' }, null, null, f.ctx);
  await settleAndPoll(f.pi, f.ctx);
  const comment = f.api.comment.bind(f.api);
  f.api.comment = async (...args) => {
    const value = await comment(...args);
    f.pi.handlers.agent_start(); f.ctx.isIdle = () => false;
    return value;
  };
  await settleAndPoll(f.pi, f.ctx);
  const canceled = new Store(f.path, f.cfg).load().records[0].publications.at(-1);
  assert.equal(canceled.canceled, true); assert.equal(canceled.state, null); assert.ok(canceled.comment !== 'intent');
  assert.equal(f.api.thread.length, 2, 'a confirmed public comment cannot be retracted');
  f.api.comment = comment; f.ctx.isIdle = () => true;
  await f.pi.tools.abra_linear_checkpoint.execute('review', { ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/actual-findings' } }, null, null, f.ctx);
  await settleAndPoll(f.pi, f.ctx);
  await f.command(`watch-check ${f.nonce} ${randomUUID()}`);
  assert.equal(f.pi.entries.at(-1).data.state, 'handoff');
  const state = new Store(f.path, f.cfg).load();
  assert.equal(state.active, null); assert.equal(state.records[0].terminal, 'review');
  assert.deepEqual(state.records[0].managedProofs, [], 'coordinator-only work still passes exact native owner verification');
  assert.deepEqual(state.records[0].publications.find(p => p.key === canceled.key), canceled);
  assert.equal(f.api.issues[0].state.id, id(5));
});

for (const step of ['comment', 'state', 'unassign']) test(`canceled fallback retains issued uncertain ${step} and blocks release until explicit reconciliation`, async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  const method = step === 'state' ? 'status' : step, original = f.api[method].bind(f.api);
  let current = true;
  f.api[method] = async () => { current = false; throw new DOMException('request canceled after starting', 'AbortError'); };
  await assert.rejects(f.connector.publish('settled-without-terminal', 'blocked: interrupted fallback', id(6), f.connector.controller.signal, () => current));
  f.connector.cancelFallbackPublication(); f.api[method] = original;
  const receipt = f.connector.active.publications.at(-1);
  assert.equal(receipt.canceled, true); assert.equal(receipt[step], 'intent');
  const input = { ...checkpoint('review'), delivery: { kind: 'report', reference: 'https://example.test/actual-report' } };
  if (step === 'unassign') await assert.rejects(f.connector.checkpoint(input), /unassignment outcome uncertain/);
  else await f.connector.checkpoint(input);
  await assert.rejects(f.connector.release('owners stopped', async () => []), /terminal checkpoint|unresolved partial publication/);
  const writes = f.api.calls.filter(c => ['comment', 'status', 'unassign'].includes(c)).length;
  await assert.rejects(f.connector.publish('settled-without-terminal', 'blocked: interrupted fallback', id(6), f.connector.controller.signal), /cannot be replayed/);
  assert.equal(f.api.calls.filter(c => ['comment', 'status', 'unassign'].includes(c)).length, writes);
  await f.connector.reconcile({ key: receipt.key, [step]: 'not-applied', evidence: 'operator confirmed original request ended without applying; inspected remote issue and native owners' });
  assert.deepEqual(receipt.notApplied, [step]);
  await f.connector.checkpoint(input);
  await f.connector.release('all exact native owners inspected and stopped', async () => []);
  const saved = f.store.load(); assert.equal(saved.active, null);
  assert.equal(saved.records[0].publications.find(p => p.key === receipt.key).canceled, true);
});

test('ordinary checkpoints cannot cancel publications or use the automatic fallback key', async t => {
  const f = fixture(t); await f.connector.enable('session-1'); await bind(f);
  await assert.rejects(f.connector.checkpoint({ ...checkpoint('blocked'), key: 'settled-without-terminal' }), /reserved/);
  const raw = fs.readFileSync(f.store.path, 'utf8');
  for (const extra of [{ canceled: true }, { canceled: false }, { canceled: 'true' }, { notApplied: ['comment'] }]) {
    const state = JSON.parse(raw); Object.assign(state.records[0].publications[0], extra);
    fs.writeFileSync(f.store.path, JSON.stringify(state));
    assert.throws(() => new Store(f.path, f.cfg).load(), /fallback/);
  }
  fs.writeFileSync(f.store.path, raw);
});
