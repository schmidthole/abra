// terminal diagnostics are fixed local text, never exception messages or remote prose.
const descriptions = new Map([
  ['options-invalid', 'command options are invalid; run bin/linear-watch --help'],
  ['platform-unsupported', 'foreground watch requires posix signal/process-group support'],
  ['acknowledgment-required', 'explicit --trusted-managed-work acknowledgment is required'],
  ['configuration-invalid', 'connector configuration is missing, unreadable or invalid; inspect .pi/abra-linear.json locally'],
  ['watch-opt-in-required', 'configure watch.trustedManagedWork=true before using watch'],
  ['journal-invalid', 'saved connector metadata is unreadable, incompatible or unsafe; preserve it for manual reconciliation'],
  ['ownership-unresolved', 'existing tracked ownership or lock blocks startup; reconcile recorded owners'],
  ['child-start-failed', 'pi could not start or its process io failed; check the pi executable and local permissions'],
  ['child-stdin-failed', 'the pi command pipe failed; inspect the saved session and surviving owners'],
  ['child-exited', 'pi exited unexpectedly or unsuccessfully; inspect the saved session and surviving owners'],
  ['rpc-command-failed', 'pi rejected a control command; inspect the saved session and installed extension compatibility'],
  ['rpc-timeout', 'pi did not answer a control command before the deadline; inspect the saved session and surviving owners'],
  ['rpc-protocol-invalid', 'pi returned malformed, uncorrelated or out-of-order rpc data; check installed pi/extension compatibility'],
  ['extension-failed', 'pi reported an extension failure; inspect the saved session and installed extension compatibility'],
  ['outcome-missing', 'pi accepted the command without an explicit connector outcome; check installed extension compatibility'],
  ['session-not-idle', 'pi session is not fresh/idle or changed during handoff; reconcile saved session ownership'],
  ['handoff-invalid', 'saved handoff, lock or reporting receipts disagree; preserve and reconcile them'],
  ['shutdown-timeout', 'pi did not close before the shutdown deadline; child/native owners may survive'],
  ['shutdown-failed', 'pi shutdown was unsuccessful or protocol ownership remains uncertain'],
  ['stop-unresolved', 'stop deadline expired with tracked owners; reconcile the saved session and native runs'],
  ['connector-auth-failed', 'linear authentication/access failed; check configured credentials and pinned workspace/app access locally'],
  ['connector-request-failed', 'linear request failed or its outcome is unavailable; check access/connectivity and reconcile pending receipts'],
  ['connector-operation-failed', 'connector operation failed; inspect local task ownership and pending receipts'],
  ['native-ownership-uncertain', 'native ownership is unknown or unsupported; inspect captured native artifacts and reconcile every owner'],
  ['publication-pending', 'comment or status publication is uncertain; inspect remote receipts before any explicit reconciliation'],
  ['connector-check-failed', 'connector safety check failed; inspect saved session, task and native ownership evidence'],
  ['unknown-failure', 'failure details are not safely classified; inspect saved evidence locally'],
]);

export const diagnosticCode = code => descriptions.has(code) ? code : 'unknown-failure';
export const diagnosticText = code => `[${diagnosticCode(code)}] ${descriptions.get(diagnosticCode(code))}`;
export class WatchFailure extends Error {
  constructor(code) { super(diagnosticText(code)); this.code = diagnosticCode(code); }
}
export const failureCode = error => error instanceof WatchFailure ? diagnosticCode(error.code) : 'unknown-failure';
export const requireWatch = (ok, code) => { if (!ok) throw new WatchFailure(code); };
