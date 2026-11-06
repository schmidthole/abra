import * as fs from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { configuration, readJson, safePath, Store, LinearClient, requireValue } from './core.mjs';
import { ClientCredentials, SCOPES, resolveCredentials, storeCredentials, credentialDirectory } from './auth.mjs';

class Cancelled extends Error {}
const required = value => { if (value === undefined || value === false) throw new Cancelled(); return value; };
const display = value => String(value).replace(/[\x00-\x1f\x7f-\x9f]/g, '').slice(0, 180);
async function choose(ui, title, values, label) {
  requireValue(values.length > 0, 'no eligible choices; configure prerequisites in linear or the repository registry first');
  const options = values.map((value, index) => `${index + 1}. ${display(label(value))}`);
  return values[options.indexOf(required(await ui.select(title, options)))];
}
async function discover(ui, action) {
  const controller = new AbortController(), finished = new AbortController();
  let cancelled = false;
  const dialog = ui.confirm('linear read-only discovery in progress', 'press escape or confirm to cancel; requests have bounded deadlines.', { signal: finished.signal }).then(() => {
    if (!finished.signal.aborted) { cancelled = true; controller.abort(); }
  });
  try {
    const value = await action(controller.signal);
    if (cancelled) throw new Cancelled();
    return value;
  } catch (error) { if (cancelled) throw new Cancelled(); throw error; }
  finally { finished.abort(); await dialog; }
}
const identityQuery = 'query AbraIdentity { viewer { id name } organization { id name } }';
const teamsQuery = 'query AbraTeams($after: String) { teams(first: 100, after: $after) { nodes { id name key } pageInfo { hasNextPage endCursor } } }';
const statesQuery = 'query AbraStates($team: ID!, $after: String) { workflowStates(first: 100, after: $after, filter: {team: {id: {eq: $team}}}) { nodes { id name type team { id } } pageInfo { hasNextPage endCursor } } }';
const labelsQuery = 'query AbraLabels($after: String) { issueLabels(first: 100, after: $after) { nodes { id name team { id } } pageInfo { hasNextPage endCursor } } }';

// commands only: no model messages, secret inputs, polling, admission or issue mutations.
export async function setup(ctx, configDirectory = '.pi', { fetcher = fetch, env = process.env, secretDirectory, signal } = {}) {
  requireValue(ctx.mode === 'tui' && ctx.hasUI && ctx.isProjectTrusted(), 'setup requires a trusted interactive terminal session');
  requireValue(ctx.isIdle() && !ctx.hasPendingMessages(), 'setup requires idle pi without queued messages');
  signal?.throwIfAborted();
  const ui = Object.fromEntries(['select', 'confirm', 'input'].map(method => [method, (...args) => {
    const options = args[2] ?? {};
    return ctx.ui[method](args[0], args[1], { ...options, signal: signal && options.signal ? AbortSignal.any([signal, options.signal]) : signal ?? options.signal });
  }]));
  const path = join(ctx.cwd, configDirectory, 'abra-linear.json');
  safePath(path, true);
  const original = fs.existsSync(path) ? fs.readFileSync(path, 'utf8') : null;
  const existing = original === null ? null : configuration(JSON.parse(original));
  const store = new Store(ctx.cwd, existing ?? {});
  requireValue(!store.load().active && !fs.existsSync(store.lock), 'reconcile active connector/native ownership before setup');
  store.acquire(ctx.sessionManager.getSessionId());
  let credentials, provider, secretPath, temporary, stage = 'prerequisites';
  try {
    required(await ui.confirm('linear setup prerequisites', `workspace admin: create/edit your own oauth app at https://linear.app/settings/api/applications/new and enable client credentials tokens. no redirect server, webhook or native agent-session integration is supplied. use a dedicated app with exactly ${SCOPES.join(',')}; requesting different scopes revokes its existing app tokens. restrict app team access in linear after initial token creation (initially all public teams). pre-create three distinct nonterminal states per team: working must be started. register repositories with bin/worktree.py. load client id and secret into environment via your secret manager before launching pi; never paste secrets into chat, commands or these dialogs. continue with read-only discovery and token acquisition only?`));
    if (existing) required(await ui.confirm('replace existing connector configuration?', 'nothing is overwritten until final confirmation. identity pins and authority ceiling are preserved; existing journal identity must remain compatible. setup never starts polling.'));
    stage = 'credential references';
    const source = existing?.auth ? required(await ui.select('credential source', ['keep saved credential references', 'new environment references'])) : 'new environment references';
    let auth;
    if (source === 'keep saved credential references') auth = existing.auth;
    else {
      const clientIdEnv = required(await ui.input('client id environment variable name only, not its value', 'ABRA_LINEAR_CLIENT_ID'));
      const clientSecretEnv = required(await ui.input('client secret environment variable name only, never paste its value', 'ABRA_LINEAR_CLIENT_SECRET'));
      requireValue(/^[A-Z][A-Z0-9_]*$/.test(clientIdEnv) && /^[A-Z][A-Z0-9_]*$/.test(clientSecretEnv) && clientIdEnv !== clientSecretEnv, 'distinct uppercase environment variable names required');
      auth = { clientIdEnv, clientSecretEnv };
    }
    requireValue(!auth.credentialsFile?.startsWith(ctx.cwd + '/'), 'credential files must be outside checkout');
    credentials = resolveCredentials(auth, env);
    const storage = source === 'keep saved credential references' ? 'keep references' : required(await ui.select('durable credential source', ['keep references (secret manager must populate every pi/watch process)', 'save plaintext privately outside checkout (explicit consent at save)']));
    const persistSecret = storage.startsWith('save plaintext');
    stage = 'authentication and read-only discovery';
    const config = { auth, timeoutMs: existing?.timeoutMs ?? 15000, ...(existing ? { personaId: existing.personaId, workspaceId: existing.workspaceId } : {}) };
    provider = new ClientCredentials(config, { fetcher, env });
    const api = new LinearClient(config, provider, fetcher);
    const identity = await discover(ui, signal => api.query(identityQuery, {}, signal));
    required(await ui.confirm('pin workspace app identity?', `workspace: ${display(identity.organization.name)} (${identity.organization.id}); app persona: ${display(identity.viewer.name)} (${identity.viewer.id}). verify these are your intended workspace and app, not a human. existing pins cannot be changed by setup.`));
    config.personaId = identity.viewer.id; config.workspaceId = identity.organization.id;
    const [availableTeams, labels] = await discover(ui, async signal => [await api.pages(teamsQuery, {}, d => d.teams, signal), await api.pages(labelsQuery, {}, d => d.issueLabels, signal)]);
    stage = 'repository and team/status selection';
    const registry = readJson(join(ctx.cwd, 'data/repos.json'));
    const availableRepos = Object.entries(registry).map(([name, repo]) => ({ name, path: repo.path, remote: repo.origin?.replace(/^git@github.com:/, 'https://github.com/').replace(/\.git$/, ''), base: repo.base }));
    const repositories = [], teams = [];
    while (true) {
      const repo = await choose(ui, 'select registered repository', availableRepos.filter(r => !repositories.some(saved => saved.name === r.name)), r => `${r.name} — ${r.remote} — ${r.base}`);
      const team = await choose(ui, `team for ${repo.name}`, availableTeams, t => `${t.name} (${t.key})`);
      if (!teams.some(t => t.id === team.id)) {
        const states = (await discover(ui, signal => api.pages(statesQuery, { team: team.id }, d => d.workflowStates, signal))).filter(s => s.team?.id === team.id && ['backlog', 'unstarted', 'started'].includes(s.type));
        const saved = { id: team.id };
        for (const key of ['working', 'inReview', 'blocked']) {
          saved[key] = (await choose(ui, `${display(team.name)}: select ${key === 'inReview' ? 'in-review' : key} state`, states.filter(s => !Object.values(saved).includes(s.id) && (key !== 'working' || s.type === 'started')), s => `${s.name} (${s.type})`)).id;
        }
        teams.push(saved);
      }
      const label = await choose(ui, `routing label for ${repo.name}`, labels.filter(l => (!l.team || l.team.id === team.id) && !repositories.some(r => r.labelId === l.id)), l => l.name);
      repositories.push({ ...repo, teamId: team.id, labelId: label.id });
      if (repositories.length === availableRepos.length) break;
      if (required(await ui.select('repositories', ['finish selection', 'add another repository'])) === 'finish selection') break;
    }
    const { tokenEnv: _legacy, ...preserved } = existing ?? { version: 1, authority: { mode: 'report' } };
    const saved = configuration({ ...preserved, auth, workspaceId: config.workspaceId, personaId: config.personaId, repositories, teams });
    // validate before final confirmation and again after a private file reference is allocated.
    stage = 'final validation and save';
    await discover(ui, signal => new LinearClient(saved, provider, fetcher).validate(signal));
    const summary = `workspace/app pinned; ${repositories.map(r => r.name).join(', ')}; ${teams.length} team(s); authority unchanged: ${JSON.stringify(saved.authority)}. all eligible delegated issues in this scope may be admitted only on a later explicit start. ${persistSecret ? 'consent: store client id and secret as plaintext in a user-owned 0600 file under a 0700 directory outside the checkout. access tokens stay in memory only.' : 'keep credential references only; environment references must be populated by your secret manager on every launch, including foreground watch.'} save configuration without starting?`;
    required(await ui.confirm('save linear setup?', summary));
    signal?.throwIfAborted();
    requireValue(ctx.isProjectTrusted() && ctx.isIdle() && !ctx.hasPendingMessages(), 'trust/idle state changed during setup');
    safePath(path);
    requireValue((fs.existsSync(path) ? fs.readFileSync(path, 'utf8') : null) === original, 'configuration changed during setup; nothing overwritten');
    if (persistSecret) {
      const directory = secretDirectory ?? credentialDirectory();
      requireValue(directory !== ctx.cwd && !directory.startsWith(ctx.cwd + '/'), 'credentials must be stored outside checkout');
      secretPath = storeCredentials(credentials, directory);
      saved.auth = { credentialsFile: secretPath };
    }
    configuration(saved);
    // old correlations are never migrated, deleted or silently rebound to changed scope.
    stage = 'existing journal compatibility (preserve and reconcile before any manual archival)';
    new Store(ctx.cwd, saved).load();
    temporary = `${path}.${randomUUID()}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(saved, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    fs.renameSync(temporary, path); temporary = null; secretPath = null;
    ctx.ui.notify('linear setup saved; polling is off. use /abra-linear start only when ready to admit configured delegations.', 'info');
    return true;
  } catch (error) {
    ctx.ui.notify(error instanceof Cancelled ? 'linear setup cancelled; existing configuration unchanged; no polling started. acquired app tokens expire normally; revoke in linear if required.' : `linear setup blocked during ${stage}; configuration unchanged. check docs/linear-polling.md, credential references, app access, distinct nonterminal states, registry and existing journal compatibility locally. no automatic retry, scope expansion or reset.`, error instanceof Cancelled ? 'info' : 'error');
    return false;
  } finally {
    provider?.dispose(); credentials = null;
    if (temporary) fs.unlinkSync(temporary);
    if (secretPath) fs.unlinkSync(secretPath);
    store.release();
  }
}
