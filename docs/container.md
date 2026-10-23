# container

the `Dockerfile` builds a debian (trixie, full userland) image for running abra
headless with triggers. an operator reaches it over ssh to set up the instance
and its specialty; the container runs sshd always and, optionally, one trigger
listener.

## contents

only what abra needs, pinned:

| tool | source | check |
| --- | --- | --- |
| debian trixie base | `debian:trixie-<date>@sha256:...` | image digest |
| python 3, git, make, openssh, tini, tmux, nano, vim-tiny, less, ripgrep, jq, curl, procps | signed debian archive | apt signatures |
| node and npm | nodejs.org release tarball | sha256 in the `Dockerfile` |
| gh | official signed apt repo (cli.github.com) | keyring sha256, apt signatures |
| claude code | npm, `@anthropic-ai/claude-code` | npm registry integrity |
| claude-agent-acp | `/opt/claude-agent-acp`, `npm ci` from `docker/claude-agent-acp/package-lock.json`, install scripts off | lockfile integrity hash for every package |
| tasks-axi, gh-axi | npx cache prefetched at the `bin/tasks` and `bin/github` pins | npm registry integrity |
| linear-axi | `/opt/linear-axi`, built from github.com/schmidthole/linear-axi at `LINEAR_AXI_COMMIT`, `npm ci` with install scripts off, dev packages pruned; `linear-axi` on `PATH` | commit hash checked after fetch, lockfile integrity hash for every package |
| slack adapter deps | venv `/opt/venvs/slack` | `docker/requirements-slack.txt` hashes |
| black | venv `/opt/venvs/black`, on `PATH` | `requirements-dev.txt` hashes |

versions are `ARG`s at the top of the `Dockerfile`. debian packages are upgraded
at build time from the pinned release's security archive, so a rebuild picks up
security fixes. `docker/requirements-slack.txt` must keep the same versions as
`triggers/requirements-slack.txt` (a test checks this).

## layout

| path | what |
| --- | --- |
| `/home/abra` | the persistent volume: everything below lives here |
| `/home/abra/abra` | instance root (`ABRA_ROOT`), seeded on first start |
| `/home/abra/.claude` | claude code config and sessions |
| `/home/abra/.config/gh` | gh config, if you use `gh auth login` |
| `/home/abra/.abra-sshd` | ssh host key, generated on first start (0600) |
| `/etc/abra/ssh/authorized_keys` | mounted operator public keys (`ABRA_AUTHORIZED_KEYS` overrides) |
| `/opt/abra` | the image's read-only copy of abra, used only for seeding |
| `/run/abra` | per-start runtime files (0700), not in the image or the volume |

the container runs as `abra` (uid 1000, gid 1000). the volume must be writable
by that user.

## entrypoint

`tini` is pid 1 and reaps agent subprocesses. it runs `docker/entrypoint.py`,
which:

1. checks `ABRA_TRIGGER`: unset or `none` runs sshd only; `slack` or `linear`
   also runs that listener; anything else exits 1.
2. reads the authorized keys file. a missing, empty, oversized, or malformed file
   exits 1 (fail closed). the keys are copied to `/run/abra/authorized_keys` (0600)
   at each start, so rotate keys by updating the secret and restarting.
3. seeds `ABRA_ROOT` from `/opt/abra` only if the path does not exist. an existing
   root is never written to.
4. generates the ed25519 host key into the volume on first start and reuses it
   afterwards.
5. starts `sshd` on port 2222 and, with `ABRA_TRIGGER=slack`,
   `/opt/venvs/slack/bin/python $ABRA_ROOT/triggers/slack.py --root $ABRA_ROOT --name $ABRA_NAME`
   (`ABRA_NAME` defaults to `abra`), or with `ABRA_TRIGGER=linear`
   `/usr/bin/python3 $ABRA_ROOT/triggers/linear.py --root $ABRA_ROOT --name $ABRA_NAME`.

if sshd or the listener exits for any reason, the other is stopped and the
container exits non-zero so the orchestrator restarts it; there is no restart
loop inside. the linear listener in app mode relies on this: it exits 1
before its app token expires, or when linear rejects it, so the restart mints a
fresh one. sigterm or sigint is forwarded to both, and the container exits 0
once they stop. the listener lets running turns finish on sigterm, so give the
container a long enough stop grace period.

## ssh

sshd runs as `abra`, so only `abra` can log in, and only with a key: no
passwords, no keyboard-interactive, no root, and no tcp, agent, x11, or tunnel
forwarding. sftp works for copying files.

## build

```sh
docker build -t abra:local .
```

`.dockerignore` keeps `.git`, `data/`, `operator/`, `specialty/`, `.worktrees/`,
`.sources/`, env files, `*.prod.*`, `*production*`, `prod-*`, `NOTES.md`,
`.claude/settings.local.json`, and caches out of the image. no secret is used at
build time.

## run

```sh
docker volume create abra-home
docker run -d --name abra \
  -p 127.0.0.1:2222:2222 \
  -v abra-home:/home/abra \
  -v "$PWD/authorized_keys:/etc/abra/ssh/authorized_keys:ro" \
  -e ANTHROPIC_API_KEY -e GH_TOKEN \
  -e ABRA_TRIGGER=slack -e ABRA_NAME=abra \
  -e SLACK_BOT_TOKEN -e SLACK_APP_TOKEN \
  --stop-timeout 300 \
  abra:local
ssh -p 2222 abra@127.0.0.1
```

`-e NAME` without a value passes the variable from your shell, so secrets stay
out of the command line. use `--env-file` with a file outside the repo, or your
platform's secret store.

| variable | effect |
| --- | --- |
| `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` | claude code auth (or run `claude` over ssh once to log in) |
| `GH_TOKEN` | gh auth (or `gh auth login` over ssh) |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | slack listener tokens, see [slack.md](slack.md) |
| `LINEAR_API_KEY` | linear bot key (user mode), plus the other `LINEAR_*` settings in [linear.md](linear.md) |
| `LINEAR_CLIENT_ID`, `LINEAR_CLIENT_SECRET` | linear agent app credentials (app mode, instead of `LINEAR_API_KEY`); pass with `-e LINEAR_CLIENT_ID -e LINEAR_CLIENT_SECRET -e ABRA_TRIGGER=linear` |
| `ABRA_TRIGGER` | `none` (default), `slack`, or `linear` |
| `ABRA_NAME` | bot name for the listener, default `abra` |
| `ABRA_ROOT` | instance root, default `/home/abra/abra` |
| `ABRA_AUTHORIZED_KEYS` | authorized keys path, default `/etc/abra/ssh/authorized_keys` |
| `ABRA_AGENT_CMD` | acp agent the listener hosts, default the image's `claude-agent-acp`, which runs the image's claude (`CLAUDE_CODE_EXECUTABLE`) |
| `ABRA_AGENT_MODE` | `1` sets the resident session to `bypassPermissions` (and makes `bin/abra` skip prompts); recommended here, since the container is the sandbox |
| `ABRA_WAKE_GRACE`, `ABRA_HEARTBEAT`, `ABRA_IDLE_CLEAR`, `ABRA_MAX_SESSION_AGE` | resident session timing, see [triggers.md](triggers.md) |
| `ABRA_MAX_CONCURRENCY`, `ABRA_SPECIALTY_DIR` | as in [README.md](../README.md) and [specialty.md](specialty.md) |

### environment in ssh sessions

sshd starts sessions with a clean environment, so the entrypoint writes an
`Include`d sshd file, `/run/abra/sshd_env` (0600), that sets exactly these
variables for every ssh session, when set: `ABRA_ROOT`, `ABRA_NAME`,
`ABRA_TRIGGER`, `ABRA_SPECIALTY_DIR`, `ABRA_AGENT_MODE`, `ABRA_MAX_CONCURRENCY`,
`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`, `DISABLE_AUTOUPDATER`,
`npm_config_cache`, `npm_config_prefer_offline`, and `npm_config_update_notifier`.
this lets an operator run `bin/abra`, `bin/tasks`, and `claude` by hand. the
resident settings (`ABRA_AGENT_CMD`, `ABRA_WAKE_GRACE`, `ABRA_HEARTBEAT`,
`ABRA_IDLE_CLEAR`, `ABRA_MAX_SESSION_AGE`) and `CLAUDE_CODE_EXECUTABLE` are not
shared; the trigger listener gets the container's full environment.
the slack tokens, `LINEAR_API_KEY`, and `LINEAR_CLIENT_SECRET` are left out of
the session environment, but this is not a security boundary; export the linear
key by hand in a session that needs `linear-axi`. in app mode the listener mints
its token in memory; a session has no token unless one is exported by hand. a value containing `"`, `\`, or control characters is not
shared and its name is logged.

ssh sessions run as the same user as the entrypoint and the listener, so anyone
holding an authorized key can read every secret given to the container (claude
or anthropic, gh, slack, and linear), for example from `/proc/<pid>/environ`. only
authorize keys of people trusted with all of them, and scope the tokens to what
abra needs.

## kubernetes

- run one replica per instance root with a `Recreate` strategy: the trigger store
  takes a lock, and the volume is single-writer.
- a `PersistentVolumeClaim` (`ReadWriteOnce`) mounted at `/home/abra`, on an
  encrypted storage class.
- a secret with key `authorized_keys` mounted read-only at `/etc/abra/ssh`.
- a secret for the env variables, referenced with `secretKeyRef` or `envFrom`.
- pod `securityContext`: `runAsNonRoot: true`, `runAsUser: 1000`,
  `runAsGroup: 1000`, `fsGroup: 1000`; container `allowPrivilegeEscalation: false`,
  `capabilities: {drop: [ALL]}`, `seccompProfile: {type: RuntimeDefault}`. the
  root filesystem must stay writable (`/run/abra` and the npm cache).
- container port 2222 behind a `ClusterIP` service; reach it with
  `kubectl port-forward` or a private network, not a public load balancer.
- set `terminationGracePeriodSeconds` above 60 seconds: on sigterm the listener
  waits up to 60 seconds for the running turn, closes the agent session, and kills
  the agent's process group. a restart resumes the stored session; background
  agents that were running are gone and abra reconciles them from task notes.

## configure over ssh

```sh
ssh -p 2222 abra@<host>
cd ~/abra
git config --global user.name "abra" && git config --global user.email "abra@example.com"
git clone <your specialty repo> specialty   # or set ABRA_SPECIALTY_DIR
python3 bin/specialty.py check
bin/tasks --help
bin/github --help
```

clone the repos abra works on under the volume (for example `~/repos`) and
register them as described in [README.md](../README.md) or the specialty's
`specialty.json`. a running listener does not need a restart for specialty or
registry changes: abra reads them as it works, and the next session (after an
idle clear or restart) starts with the startup checks.

## upgrade

the image and the instance root upgrade separately.

- tools (node, claude code, gh, python deps, sshd): rebuild the image and
  recreate the container. the volume, and so the root, is kept.
- abra itself: the root is the operator's copy. the seeded copy has no git
  history; to manage it with git, replace it once with a clone while it holds no
  state yet, then pull to upgrade:

  ```sh
  mv ~/abra ~/abra.seed && git clone <abra repo url> ~/abra
  git -C ~/abra pull --ff-only
  ```

  restart the container after updating the root so the listener runs the new
  code. if `triggers/requirements-slack.txt` changed, rebuild the image too, since
  the listener uses the image's venv.

## security

- the volume holds the trigger store with message text in plaintext, claude
  sessions (the resident session included), and any gh or claude login. it must be encrypted at
  rest and not shared with other workloads.
- expose port 2222 only to operators (localhost binding, private network, or port
  forwarding). the host key is generated per volume; pin it in `known_hosts`.
- secrets come only from the runtime environment and mounted secrets. none is in
  an image layer, and the entrypoint never prints their values.
- `ABRA_AGENT_MODE=1` makes the resident session and `bin/abra` skip claude
  permission prompts; the container is then the sandbox, so keep its tokens
  narrowly scoped. without it, the runtime rejects every permission request except
  abra's own reply tool.
