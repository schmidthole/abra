import * as fs from 'node:fs';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';
import { randomUUID } from 'node:crypto';
import { requireValue, safePath, readJson, ApiError } from './core.mjs';

export const SCOPES = ['read', 'issues:create', 'comments:create', 'app:assignable'];
export const credentialDirectory = () => join(homedir(), '.abra-linear');

function privateDirectory(directory, create = false) {
  requireValue(typeof process.getuid === 'function', 'private credential storage requires posix ownership and modes');
  safePath(join(directory, 'credentials.json'), create);
  const info = fs.statSync(directory);
  requireValue(info.isDirectory() && (info.mode & 0o777) === 0o700 && info.uid === process.getuid(), 'credential directory must be owned by this user with mode 0700');
}
export function readCredentials(path) {
  privateDirectory(dirname(path)); safePath(path);
  const info = fs.statSync(path);
  requireValue(info.isFile() && info.nlink === 1 && (info.mode & 0o777) === 0o600 && info.uid === process.getuid(), 'credential file must be owned by this user with mode 0600');
  const value = readJson(path);
  requireValue(typeof value.clientId === 'string' && value.clientId.length > 0 && typeof value.clientSecret === 'string' && value.clientSecret.length > 0 && Object.keys(value).every(k => ['clientId', 'clientSecret'].includes(k)), 'invalid credential file');
  return value;
}
// called only after explicit plaintext-storage consent; never overwrite another credential.
export function storeCredentials(value, directory = credentialDirectory()) {
  privateDirectory(directory, true);
  const path = join(directory, `${randomUUID()}.json`);
  fs.writeFileSync(path, JSON.stringify(value) + '\n', { flag: 'wx', mode: 0o600 });
  return path;
}
export function resolveCredentials(auth, env = process.env) {
  const value = auth.credentialsFile ? readCredentials(auth.credentialsFile) : { clientId: env[auth.clientIdEnv], clientSecret: env[auth.clientSecretEnv] };
  requireValue(typeof value.clientId === 'string' && value.clientId.trim() && typeof value.clientSecret === 'string' && value.clientSecret.trim(), 'client credential references are not populated');
  return value;
}

export class ClientCredentials {
  constructor(config, { fetcher = fetch, env = process.env, clock = Date.now } = {}) {
    Object.assign(this, { config, fetcher, env, clock });
    this.secrets = new Set(); this.expires = 0; this.controller = new AbortController();
  }
  remember(value) {
    requireValue(this.secrets.size < 256 || this.secrets.has(value), 'credential redaction capacity reached; stop and reconcile before a fresh session');
    this.secrets.add(value);
  }
  redact(value) {
    for (const secret of this.secrets) value = value.split(secret).join('[redacted]');
    return value;
  }
  invalidate() { this.expires = 0; this.renewAt = 0; }
  async get(signal, verify) {
    signal?.throwIfAborted(); this.controller.signal.throwIfAborted();
    if (this.token && this.clock() < this.renewAt) return this.token;
    if (!this.pending) {
      const controller = new AbortController();
      const requestSignal = AbortSignal.any([controller.signal, this.controller.signal, AbortSignal.timeout(this.config.timeoutMs)]);
      const flight = { controller, waiters: 0 };
      this.pending = flight;
      flight.promise = this.acquire(requestSignal, verify).finally(() => { if (this.pending === flight) this.pending = null; });
      flight.promise.catch(() => {});
    }
    const flight = this.pending; flight.waiters++;
    let abort;
    const cancelled = new Promise((_, reject) => {
      abort = () => reject(new ApiError('linear authentication cancelled', { auth: true }));
      signal?.addEventListener('abort', abort, { once: true });
    });
    try { return await Promise.race([flight.promise, cancelled]); }
    finally {
      signal?.removeEventListener('abort', abort);
      if (--flight.waiters === 0 && this.pending === flight) { flight.controller.abort(); }
    }
  }
  async acquire(signal, verify) {
    try {
      const credentials = resolveCredentials(this.config.auth, this.env);
      this.remember(credentials.clientSecret);
      const started = this.clock();
      const response = await this.fetcher('https://api.linear.app/oauth/token', {
        method: 'POST', redirect: 'error', signal,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ grant_type: 'client_credentials', client_id: credentials.clientId, client_secret: credentials.clientSecret, scope: SCOPES.join(',') }).toString(),
      });
      if (!response.ok) throw new Error('token rejected');
      const value = await response.json();
      requireValue(typeof value.access_token === 'string' && value.access_token.length > 0 && value.token_type?.toLowerCase() === 'bearer' && Number.isFinite(value.expires_in) && value.expires_in >= 2 && value.expires_in <= 366 * 86400, 'invalid token response');
      this.remember(value.access_token);
      const scopes = typeof value.scope === 'string' ? value.scope.split(/[ ,]+/).filter(Boolean) : value.scope;
      requireValue(Array.isArray(scopes) && scopes.every(s => typeof s === 'string') && new Set(scopes).size === SCOPES.length && SCOPES.every(s => scopes.includes(s)), 'unexpected token scopes');
      await verify(value.access_token, signal);
      signal.throwIfAborted();
      this.expires = started + value.expires_in * 1000;
      this.renewAt = this.expires - Math.min(300000, value.expires_in * 100);
      requireValue(this.clock() < this.renewAt, 'token already needs renewal');
      this.token = value.access_token;
      return this.token;
    } catch {
      this.token = null; this.renewAt = 0;
      throw new ApiError('linear client authentication failed; check credentials, fixed scopes and pinned workspace/app locally; no automatic scope changes or mutation replay', { auth: true });
    }
  }
  dispose() { this.controller.abort(); this.token = null; this.renewAt = 0; }
}
