import { test } from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join, resolve } from 'node:path';
import { configuration, LinearClient, Connector, Store } from '../../extensions/linear/core.mjs';
import { ClientCredentials, SCOPES, storeCredentials, readCredentials } from '../../extensions/linear/auth.mjs';
import { setup } from '../../extensions/linear/setup.mjs';
import { install } from '../../extensions/linear/pi.mjs';

const root = resolve('.');
const id = n => `00000000-0000-0000-0000-${String(n).padStart(12, '0')}`;
const env = { CLIENT_ID: 'client-id', CLIENT_SECRET: 'private-client-secret' };
const base = () => configuration({ version: 1, auth: { clientIdEnv: 'CLIENT_ID', clientSecretEnv: 'CLIENT_SECRET' }, workspaceId: id(1), personaId: id(2), teams: [{ id: id(3), working: id(4), inReview: id(5), blocked: id(6) }], repositories: [{ name: 'abra', path: root, remote: 'https://github.com/example/abra', base: 'main', teamId: id(3), labelId: id(7) }], timeoutMs: 100 });
const states = () => [4, 5, 6].map(n => ({ id: id(n), name: `state-${n}`, type: n === 4 ? 'started' : 'unstarted', team: { id: id(3) } }));
const connection = nodes => ({ nodes, pageInfo: { hasNextPage: false, endCursor: null } });
const response = (value, status = 200) => ({ ok: status === 200, status, headers: new Headers(), json: async () => value });
function boundary() {
  const calls = [];
  const fake = { calls, tokenCount: 0, identity: id(2), tokenStatus: 200, graphStatus: 200, scope: SCOPES.join(' '), expires: 100, states: states(), hook: null };
  fake.fetcher = async (url, options) => {
    calls.push({ url, ...options });
    if (fake.hook) await fake.hook(url, options);
    options.signal?.throwIfAborted();
    if (url.endsWith('/oauth/token')) {
      fake.tokenCount++;
      return response({ access_token: `private-access-${fake.tokenCount}`, token_type: 'Bearer', expires_in: fake.expires, scope: fake.scope }, fake.tokenStatus);
    }
    const { query, variables } = JSON.parse(options.body);
    if (fake.graphStatus !== 200) return response({}, fake.graphStatus);
    if (query.includes('AbraIdentity')) return response({ data: { viewer: { id: fake.identity, name: 'app' }, organization: { id: id(1), name: 'workspace' } } });
    if (query.includes('AbraTeams')) return response({ data: { teams: connection([{ id: id(3), name: 'engineering', key: 'eng' }]) } });
    if (query.includes('AbraStates')) return response({ data: { workflowStates: connection(fake.states) } });
    if (query.includes('AbraLabels')) return response({ data: { issueLabels: connection([7, 8].map(n => ({ id: id(n), name: `route-${n}`, team: { id: id(3) } }))) } });
    if (query.includes('AbraDelegated')) return response({ data: { issues: connection([]) } });
    return response({ data: { ok: true, variables } });
  };
  return fake;
}
function client(fake, extra = {}, config = base()) {
  const provider = new ClientCredentials(config, { env, fetcher: fake.fetcher, ...extra });
  return { provider, api: new LinearClient(config, provider, fake.fetcher) };
}
function temporary(t) {
  fs.mkdirSync(join(root, '.cache/auth-tests'), { recursive: true });
  const path = fs.mkdtempSync(join(root, '.cache/auth-tests/trial-'));
  t.after(() => fs.rmSync(path, { recursive: true, force: true }));
  return path;
}

test('client credentials use exact documented form and single-flight identity-pinned acquisition', async () => {
  const fake = boundary(), { provider, api } = client(fake);
  await Promise.all(Array.from({ length: 20 }, () => api.query('query Read { ok }')));
  assert.equal(fake.tokenCount, 1);
  const request = fake.calls[0];
  assert.equal(request.redirect, 'error');
  assert.equal(request.headers['Content-Type'], 'application/x-www-form-urlencoded');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(request.body)), { grant_type: 'client_credentials', client_id: env.CLIENT_ID, client_secret: env.CLIENT_SECRET, scope: SCOPES.join(',') });
  assert.equal(fake.calls.filter(c => c.body.includes('AbraIdentity')).length, 1);
  assert.ok(fake.calls.slice(1).every(c => c.headers.Authorization === 'Bearer private-access-1'));
  provider.dispose();
});

test('legacy scope arrays authenticate and renew with the exact allowed scope set', async () => {
  let now = 0;
  const fake = boundary(), { provider, api } = client(fake, { clock: () => now });
  fake.scope = [...SCOPES].reverse(); fake.expires = 30 * 86400;
  try {
    assert.deepEqual(await api.query('query Read { ok }'), { ok: true, variables: {} });
    assert.equal(fake.tokenCount, 1);
    now = provider.renewAt;
    await api.query('query Read { ok }');
    assert.equal(fake.tokenCount, 2);
    assert.equal(fake.calls.filter(c => c.body.includes('AbraIdentity')).length, 2);
    assert.equal(fake.calls.filter(c => c.body.includes('query Read')).length, 2);
  } finally { provider.dispose(); }
});

for (const [name, scope] of [
  ['extra scope', [...SCOPES, 'write']],
  ['missing scope', SCOPES.slice(1)],
  ['nonstring entry', [...SCOPES, 1]],
  ['nested array', [SCOPES]],
  ['null entry', [...SCOPES.slice(0, -1), null]],
  ['empty array', []],
  ['missing scopes', undefined],
  ['object instead of array', { scopes: SCOPES }],
]) {
  test(`malformed or unauthorized scope arrays fail before issue requests: ${name}`, async () => {
    const fake = boundary(), { provider, api } = client(fake);
    fake.scope = scope;
    try {
      await assert.rejects(api.query('query Read { ok }'), error => error.auth === true);
      assert.equal(fake.tokenCount, 1);
      assert.equal(fake.calls.filter(c => c.url.endsWith('/graphql')).length, 0);
    } finally { provider.dispose(); }
  });
}

test('proactive renewal before expiry needs no restart and revalidates identity', async () => {
  let now = 0;
  const fake = boundary(), { provider, api } = client(fake, { clock: () => now });
  await api.query('query Read { ok }');
  now = 89999; await api.query('query Read { ok }'); assert.equal(fake.tokenCount, 1);
  now = 90000; await Promise.all([api.query('query Read { ok }'), api.query('query Read { ok }')]);
  assert.equal(fake.tokenCount, 2); assert.equal(provider.expires, 190000);
  assert.match(provider.redact('private-access-1 private-access-2 private-client-secret'), /^(\[redacted\] ){2}\[redacted\]$/);
  provider.dispose();
});

for (const failure of ['revoked', 'scope expansion', 'scope loss', 'wrong identity', 'bad expiry', 'network secret']) {
  test(`renewal fails closed with redacted bounded error: ${failure}`, async () => {
    let now = 0;
    const fake = boundary(), { provider, api } = client(fake, { clock: () => now });
    await api.query('query Read { ok }'); now = 90000;
    if (failure === 'revoked') fake.tokenStatus = 401;
    if (failure === 'scope expansion') fake.scope += ' write';
    if (failure === 'scope loss') fake.scope = 'read';
    if (failure === 'wrong identity') fake.identity = id(99);
    if (failure === 'bad expiry') fake.expires = 0;
    if (failure === 'network secret') fake.hook = async () => { throw new Error(env.CLIENT_SECRET); };
    await assert.rejects(api.query('mutation Uncertain { ok }'), error => error.auth === true && !error.message.includes(env.CLIENT_SECRET));
    assert.equal(fake.calls.filter(c => c.body.includes('mutation')).length, 0);
    provider.dispose();
  });
}

test('auth error invalidates token but never replays uncertain graphql mutation', async () => {
  const fake = boundary(), { provider, api } = client(fake);
  await api.query('query Read { ok }'); fake.graphStatus = 401;
  await assert.rejects(api.query('mutation Uncertain { ok }'), error => error.auth);
  assert.equal(fake.tokenCount, 1);
  assert.equal(fake.calls.filter(c => c.body.includes('mutation')).length, 1);
  fake.graphStatus = 200;
  await api.query('query Read { ok }'); assert.equal(fake.tokenCount, 2);
  provider.dispose();
});

test('one cancelled waiter does not cancel shared acquisition for other callers', async () => {
  const fake = boundary(), gate = Promise.withResolvers(), entered = Promise.withResolvers();
  fake.hook = async url => { if (url.endsWith('/oauth/token')) { entered.resolve(); await gate.promise; } };
  const { provider, api } = client(fake);
  const controller = new AbortController();
  const first = api.query('query Read { ok }', {}, controller.signal);
  const second = api.query('query Read { ok }');
  await entered.promise; controller.abort();
  await assert.rejects(first, /cancelled/);
  assert.equal(fake.calls[0].signal.aborted, false);
  gate.resolve(); await second; assert.equal(fake.tokenCount, 1);
  provider.dispose();
});

test('all cancelled waiters abort token request; already-aborted calls do no io', async () => {
  const fake = boundary(), entered = Promise.withResolvers();
  fake.hook = async (url, options) => { if (url.endsWith('/oauth/token')) {
    entered.resolve(); await new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true }));
  } };
  const { provider, api } = client(fake), controller = new AbortController();
  const first = api.query('query Read { ok }', {}, controller.signal);
  await entered.promise; controller.abort(); await assert.rejects(first);
  assert.equal(fake.calls[0].signal.aborted, true);
  const count = fake.calls.length;
  await assert.rejects(api.query('query Read { ok }', {}, controller.signal)); assert.equal(fake.calls.length, count);
  provider.dispose();
});

test('token endpoint deadline and disposal abort hanging acquisition without retries', async () => {
  for (const dispose of [false, true]) {
    const fake = boundary(), entered = Promise.withResolvers();
    fake.hook = async (_url, options) => { entered.resolve(); await new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true })); };
    const { provider, api } = client(fake);
    const keepAlive = setInterval(() => {}, 200);
    try {
      const pending = api.query('query Read { ok }'); await entered.promise;
      if (dispose) provider.dispose();
      await assert.rejects(pending, error => error.auth);
      assert.equal(fake.calls.length, 1); assert.equal(fake.calls[0].signal.aborted, true);
    } finally { clearInterval(keepAlive); provider.dispose(); }
  }
});

test('connector renews on ordinary polling and pauses admission on revocation', async t => {
  let now = 0;
  const fake = boundary(), cfg = base(), { provider, api } = client(fake, { clock: () => now }, cfg), path = temporary(t);
  const connector = new Connector({ root: path, config: cfg, store: new Store(path, cfg), api, host: { idle: () => true, notify: () => {}, cancel: async () => {} } });
  t.after(() => connector.dispose());
  await connector.enable('session'); now = 90000; await connector.poll();
  assert.equal(fake.tokenCount, 2); now = 180000; fake.tokenStatus = 401;
  await connector.poll(); assert.equal(connector.mode, 'paused'); assert.equal(connector.active, undefined);
  assert.equal(connector.redacted('private-access-1 private-client-secret'), '[redacted] [redacted]');
  await connector.dispose(); assert.equal(provider.controller.signal.aborted, true);
});

test('private credential storage rejects broad modes, symlinks and hardlinks without overwriting', t => {
  const path = temporary(t), directory = join(path, 'secrets');
  const file = storeCredentials({ clientId: env.CLIENT_ID, clientSecret: env.CLIENT_SECRET }, directory);
  assert.equal(fs.statSync(directory).mode & 0o777, 0o700); assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  assert.equal(readCredentials(file).clientSecret, env.CLIENT_SECRET);
  fs.chmodSync(file, 0o644); assert.throws(() => readCredentials(file), /0600/); fs.chmodSync(file, 0o600);
  fs.chmodSync(directory, 0o755); assert.throws(() => readCredentials(file), /0700/); fs.chmodSync(directory, 0o700);
  const link = join(directory, 'linked.json'); fs.symlinkSync(file, link); assert.throws(() => readCredentials(link), /unsafe/); fs.unlinkSync(link);
  fs.linkSync(file, link); assert.throws(() => readCredentials(file), /0600/); fs.unlinkSync(link);
  const linkedDirectory = join(path, 'linked'); fs.symlinkSync(directory, linkedDirectory); assert.throws(() => storeCredentials({}, linkedDirectory), /unsafe/);
  assert.equal(fs.readdirSync(directory).length, 1);
});

test('strict configuration supports legacy or client references but never inline secrets or both', () => {
  for (const auth of [{ clientSecret: 'secret' }, { clientIdEnv: 'CLIENT_ID', clientSecretEnv: 'secret-value' }, { credentialsFile: 'relative' }, { credentialsFile: '/file', clientSecretEnv: 'CLIENT_SECRET' }]) {
    assert.throws(() => configuration({ ...base(), auth }));
  }
  assert.throws(() => configuration({ ...base(), tokenEnv: 'TOKEN' }));
  const legacy = base(); delete legacy.auth; legacy.tokenEnv = 'TOKEN'; assert.equal(configuration(legacy).tokenEnv, 'TOKEN');
});

function wizard(t, { cancelAt = 0, persist = false, multiple = false, existing } = {}) {
  const directory = temporary(t), path = join(directory, 'checkout'), secretDirectory = join(directory, 'secrets');
  fs.mkdirSync(join(path, '.pi'), { recursive: true }); fs.mkdirSync(join(path, 'data'));
  const registry = Object.fromEntries(['abra', 'other'].slice(0, multiple ? 2 : 1).map(name => [name, { path: root, origin: `git@github.com:example/${name}.git`, base: 'main' }]));
  fs.writeFileSync(join(path, 'data/repos.json'), JSON.stringify(registry));
  const configPath = join(path, '.pi/abra-linear.json');
  if (existing) fs.writeFileSync(configPath, JSON.stringify(existing));
  const fake = boundary(), notifications = [], prompts = [];
  let step = 0;
  const ctx = { cwd: path, mode: 'tui', hasUI: true, isProjectTrusted: () => true, isIdle: () => true, hasPendingMessages: () => false, sessionManager: { getSessionId: () => 'setup-session' }, ui: {
    confirm: async (title, body, options) => {
      if (title === 'linear read-only discovery in progress') return new Promise(resolve => options.signal.addEventListener('abort', () => resolve(false), { once: true }));
      prompts.push({ title, body }); return ++step !== cancelAt;
    },
    input: async title => { prompts.push({ title }); if (++step === cancelAt) return undefined; return title.includes('secret') ? 'CLIENT_SECRET' : 'CLIENT_ID'; },
    select: async (title, values) => {
      prompts.push({ title, values }); if (++step === cancelAt) return undefined;
      if (title === 'durable credential source' && persist) return values[1];
      if (title === 'repositories' && multiple) return values[1];
      return values[0];
    },
    notify: (message, type) => notifications.push({ message, type }),
  } };
  return { ctx, fake, configPath, path, prompts, notifications, secretDirectory, run: () => setup(ctx, '.pi', { env, fetcher: fake.fetcher, secretDirectory }) };
}

test('wizard discovers complete team/status/label mappings and multiple registered repositories, saves report-only without admission', async t => {
  const f = wizard(t, { multiple: true }); assert.equal(await f.run(), true);
  const saved = configuration(JSON.parse(fs.readFileSync(f.configPath)));
  assert.equal(saved.authority.mode, 'report'); assert.equal(saved.personaId, id(2)); assert.equal(saved.workspaceId, id(1));
  assert.deepEqual(saved.teams, base().teams); assert.equal(saved.repositories.length, 2);
  assert.equal(saved.repositories[1].labelId, id(8)); assert.equal(saved.repositories[0].remote, 'https://github.com/example/abra');
  assert.equal(f.fake.calls.some(c => /mutation|AbraDelegated/.test(c.body)), false);
  assert.equal(fs.existsSync(join(f.path, 'data/linear/owner.lock')), false);
  const artifacts = fs.readFileSync(f.configPath, 'utf8') + JSON.stringify(f.notifications) + JSON.stringify(f.prompts);
  assert.equal(artifacts.includes(env.CLIENT_SECRET), false); assert.equal(artifacts.includes('private-access-'), false);
  assert.equal(fs.existsSync(f.secretDirectory), false);
});

test('wizard discovery fully paginates teams, labels and states before selection and validation', async t => {
  const f = wizard(t), original = f.fake.fetcher, pages = new Map();
  f.fake.fetcher = async (url, options) => {
    if (url.endsWith('/graphql')) {
      const { query, variables } = JSON.parse(options.body);
      const field = query.includes('AbraTeams') ? 'teams' : query.includes('AbraLabels') ? 'issueLabels' : query.includes('AbraStates') ? 'workflowStates' : null;
      if (field) {
        pages.set(field, (pages.get(field) ?? 0) + 1);
        if (!variables.after) return response({ data: { [field]: { nodes: [], pageInfo: { hasNextPage: true, endCursor: 'second-page' } } } });
        assert.equal(variables.after, 'second-page');
      }
    }
    return original(url, options);
  };
  assert.equal(await f.run(), true);
  assert.deepEqual(Object.fromEntries(pages), { teams: 2, issueLabels: 2, workflowStates: 4 });
});

test('wizard refuses a concurrent config change without overwriting or storing credentials', async t => {
  const f = wizard(t, { persist: true }), original = f.ctx.ui.confirm;
  f.ctx.ui.confirm = async (title, body, options) => {
    if (title === 'save linear setup?') fs.writeFileSync(f.configPath, 'operator-owned replacement');
    return original(title, body, options);
  };
  assert.equal(await f.run(), false); assert.equal(fs.readFileSync(f.configPath, 'utf8'), 'operator-owned replacement');
  assert.equal(fs.existsSync(f.secretDirectory), false);
});

test('wizard cancellation at every ordinary dialog leaves no saved configuration, credentials or lock', async t => {
  const completed = wizard(t, { persist: true }); await completed.run();
  for (let cancelAt = 1; cancelAt <= completed.prompts.length; cancelAt++) {
    const f = wizard(t, { cancelAt, persist: true });
    assert.equal(await f.run(), false, `cancel step ${cancelAt}`);
    assert.equal(fs.existsSync(f.configPath), false); assert.equal(fs.existsSync(f.secretDirectory), false);
    assert.equal(fs.existsSync(join(f.path, 'data/linear/owner.lock')), false);
  }
});

test('wizard persists plaintext only after explicit consent; fresh child can authenticate without inherited env or token', async t => {
  const f = wizard(t, { persist: true }); assert.equal(await f.run(), true);
  assert.ok(f.prompts.some(p => p.title === 'save linear setup?' && p.body.includes('consent: store')));
  const saved = configuration(JSON.parse(fs.readFileSync(f.configPath)));
  assert.deepEqual(Object.keys(saved.auth), ['credentialsFile']);
  assert.equal(saved.auth.credentialsFile.startsWith(f.path + '/'), false);
  const fake = boundary(), { provider, api } = client(fake, { env: {} }, saved);
  await api.validate(); assert.equal(fake.tokenCount, 1);
  assert.equal(fs.statSync(saved.auth.credentialsFile).mode & 0o777, 0o600); provider.dispose();
});

test('two fresh foreground child processes acquire credentials from consented storage through watch-start', async t => {
  const f = wizard(t, { persist: true }); assert.equal(await f.run(), true);
  const saved = JSON.parse(fs.readFileSync(f.configPath)); saved.watch = { trustedManagedWork: true };
  fs.writeFileSync(f.configPath, JSON.stringify(saved));
  for (let child = 0; child < 2; child++) {
    const { stdout, stderr } = await promisify(execFile)(process.execPath, [join(root, 'tests/linear/fixtures/auth-child.mjs'), f.path], { cwd: root, env: { PATH: process.env.PATH, HOME: process.env.HOME }, timeout: 10000 });
    assert.equal(stdout, 'fresh child authenticated without inherited credentials\n'); assert.equal(stderr, '');
    assert.equal(fs.existsSync(join(f.path, 'data/linear/owner.lock')), false);
  }
});

test('wizard preserves legacy workspace/persona and pr authority while migrating credentials', async t => {
  const legacy = base(); delete legacy.auth; legacy.tokenEnv = 'OLD_TOKEN'; legacy.authority = { mode: 'pr', maxFiles: 2, maxChangedLines: 30 };
  const f = wizard(t, { existing: legacy }); assert.equal(await f.run(), true);
  const saved = JSON.parse(fs.readFileSync(f.configPath)); assert.deepEqual(saved.authority, legacy.authority);
  assert.equal(saved.tokenEnv, undefined); assert.equal(saved.personaId, legacy.personaId);
  const cancelled = wizard(t, { existing: legacy, cancelAt: 2 }); assert.equal(await cancelled.run(), false);
  assert.deepEqual(JSON.parse(fs.readFileSync(cancelled.configPath)), legacy);
});

test('wizard rejects changed identity, terminal/missing states and incompatible journal without persistence', async t => {
  for (const fault of ['identity', 'state', 'journal']) {
    const f = wizard(t, { existing: base(), persist: true });
    const before = fs.readFileSync(f.configPath, 'utf8');
    if (fault === 'identity') f.fake.identity = id(99);
    if (fault === 'state') f.fake.states = states().slice(0, 2);
    if (fault === 'journal') {
      const store = new Store(f.path, base()); store.acquire('old'); store.save({ version: 2, identity: store.identity, records: [], active: null }); store.release();
      f.ctx.ui.select = async (_title, values) => values[values.length - 1];
    }
    if (fault === 'journal') f.fake.states[2].id = id(44);
    assert.equal(await f.run(), false, fault); assert.equal(fs.readFileSync(f.configPath, 'utf8'), before);
    assert.equal(fs.existsSync(f.secretDirectory) && fs.readdirSync(f.secretDirectory).length > 0, false);
  }
});

test('wizard read-only discovery is cancellable and aborts token io', async t => {
  const f = wizard(t);
  f.ctx.ui.confirm = async (title, _body, options) => {
    if (title === 'linear read-only discovery in progress') return true;
    return true;
  };
  f.fake.hook = async (_url, options) => new Promise((_, reject) => {
    if (options.signal.aborted) reject(new Error('cancelled'));
    else options.signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true });
  });
  assert.equal(await f.run(), false); assert.equal(f.fake.calls[0].signal.aborted, true);
  assert.equal(fs.existsSync(f.configPath), false);
});

test('setup requires trusted idle terminal and cannot steal an existing ownership lock', async t => {
  for (const fault of ['rpc', 'untrusted', 'busy', 'lock']) {
    const f = wizard(t);
    if (fault === 'rpc') f.ctx.mode = 'rpc';
    if (fault === 'untrusted') f.ctx.isProjectTrusted = () => false;
    if (fault === 'busy') f.ctx.isIdle = () => false;
    if (fault === 'lock') { const store = new Store(f.path, {}); store.acquire('owner'); }
    await assert.rejects(f.run()); assert.equal(f.fake.calls.length, 0);
  }
});

test('registered setup command uses native dialogs only and never sends model messages or polls', async t => {
  const f = wizard(t), commands = new Map();
  install({ on: () => {}, registerCommand: (name, command) => commands.set(name, command), registerTool: () => {}, sendUserMessage: () => assert.fail('no model messages'), appendEntry: () => assert.fail('no session secret persistence') }, '.pi', { setup: { env, fetcher: f.fake.fetcher, secretDirectory: f.secretDirectory } });
  await commands.get('abra-linear').handler('setup', f.ctx);
  assert.equal(fs.existsSync(f.configPath), true); assert.equal(f.fake.calls.some(c => c.body.includes('AbraDelegated')), false);
});
