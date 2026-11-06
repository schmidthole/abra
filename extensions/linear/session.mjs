import * as fs from 'node:fs';
import { requireValue } from './core.mjs';

export const dedicatedMarker = 'abra-linear-dedicated';
const bootstrapText = 'operator requested a dedicated linear coordinator session. this bootstrap saves recovery context only; no issue has been admitted and no model turn is requested. configured authority remains unchanged; wait for connector dispatch or explicit recovery controls.';
const uuid = value => typeof value === 'string' && /^[a-f0-9-]{36}$/.test(value);

export function seedDedicatedSession(sm, handoff) {
  sm.appendCustomEntry(dedicatedMarker, { version: 1, ...handoff });
  // custom-only sessions are not initially written by pi; a truthful user context is.
  sm.appendMessage({ role: 'user', content: bootstrapText, timestamp: Date.now() });
  verifySavedBootstrap(sm);
}

function bootstrapHandoff(sm) {
  const entries = sm.getBranch(), markers = entries.filter(e => e.type === 'custom' && e.customType === dedicatedMarker);
  const messages = entries.filter(e => e.type === 'message');
  const data = markers[0]?.data;
  requireValue(markers.length === 1 && data?.version === 1 && ['interactive', 'watch'].includes(data.source) && uuid(data.token) && typeof data.previousSession === 'string' && data.previousSession !== sm.getSessionId(), 'dedicated bootstrap handoff required');
  requireValue(messages.length === 1 && messages[0].message.role === 'user' && messages[0].message.content === bootstrapText && entries.every(e => ['model_change', 'thinking_level_change', 'message'].includes(e.type) || e === markers[0]), 'dedicated bootstrap must be fresh and unused');
  return data;
}

export function verifySavedDedicated(sm) {
  const file = sm.getSessionFile();
  requireValue(file, 'dedicated session must use persistent storage');
  const entries = fs.readFileSync(file, 'utf8').trimEnd().split('\n').map(line => JSON.parse(line));
  requireValue(entries[0]?.type === 'session' && entries[0].id === sm.getSessionId() && JSON.stringify(entries[0]) === JSON.stringify(sm.getHeader()), 'saved dedicated session identity disagrees');
  const marker = sm.getBranch().find(e => e.type === 'custom' && e.customType === dedicatedMarker);
  requireValue(marker && entries.some(e => JSON.stringify(e) === JSON.stringify(marker)), 'dedicated recovery marker was not saved');
  return entries;
}

export function verifySavedBootstrap(sm) {
  const handoff = bootstrapHandoff(sm), entries = verifySavedDedicated(sm);
  requireValue(JSON.stringify(entries.slice(1)) === JSON.stringify(sm.getBranch()), 'dedicated bootstrap was not completely saved');
  return handoff;
}
