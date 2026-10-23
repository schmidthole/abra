# abra runtime image: full debian userland, key-only sshd for operators, and an
# optional trigger listener. see docs/container.md.
FROM debian:trixie-20261020@sha256:4c25275446ca371766b8b093c696782eabce06263fccacb8d5d813b3dc44b308

# pinned tool versions; downloads are checked against these checksums.
ARG NODE_VERSION=24.22.1
ARG NODE_SHA256_AMD64=6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6
ARG NODE_SHA256_ARM64=dbabf7a1cbf947e6059ffad2c27b80041db97dea1e553b62afdee7f13fca336e
ARG GH_VERSION=2.103.1
# sha256 of https://cli.github.com/packages/githubcli-archive-keyring.gpg
# (signing key 7f38bbb59d064dbcb3d84d725612b36462313325)
ARG GH_KEYRING_SHA256=6084d5d7bd8e288441e0e94fc6275570895da18e6751f70f057485dc2d1a811b
ARG CLAUDE_CODE_VERSION=2.1.308
# the published codex-acp 2.2.2 predates the required subagent protocol.
ARG CODEX_ACP_COMMIT=082be156aacac3ef21e231da2efcdf5f6af34a6b
# must match the pins in bin/tasks and bin/github
ARG TASKS_AXI_VERSION=0.2.5
ARG GH_AXI_VERSION=0.1.35
# linear-axi is not published to npm (the npm package of that name is
# unrelated); it is built from its source repo at this commit.
ARG LINEAR_AXI_COMMIT=85b701f3bec4f83242a7fec170c8d0e9b9f7d722

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# debian packages come from the signed debian archive of the pinned release,
# upgraded at build time to pick up security fixes.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl git jq less make nano openssh-client openssh-server \
        procps python3 python3-venv ripgrep tini tmux vim-tiny xz-utils \
    && rm -f /etc/ssh/ssh_host_* \
    && rm -rf /var/lib/apt/lists/*

# gh from the official signed apt repository, keyring checked by checksum.
RUN curl -fsSLo /usr/share/keyrings/githubcli-archive-keyring.gpg \
        https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && echo "${GH_KEYRING_SHA256}  /usr/share/keyrings/githubcli-archive-keyring.gpg" | sha256sum -c - \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "gh=${GH_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && gh --version

# node and npm from the official release tarball, checked by checksum.
# corepack is removed: abra needs no extra package managers.
RUN arch="$(dpkg --print-architecture)" \
    && case "${arch}" in \
        amd64) node_arch=x64; sum="${NODE_SHA256_AMD64}" ;; \
        arm64) node_arch=arm64; sum="${NODE_SHA256_ARM64}" ;; \
        *) echo "unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac \
    && curl -fsSLo /tmp/node.tar.xz \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
    && echo "${sum}  /tmp/node.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner \
        --exclude='*/CHANGELOG.md' --exclude='*/README.md' \
    && rm -rf /tmp/node.tar.xz /usr/local/lib/node_modules/corepack /usr/local/bin/corepack \
    && node --version \
    && npm --version

# claude code, pinned; npm checks registry integrity hashes.
RUN npm install --global --no-fund --no-audit "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force \
    && claude --version

# the acp adapter the resident trigger runtime drives. every package is pinned
# with its registry integrity hash in docker/claude-agent-acp/package-lock.json;
# install scripts are skipped, and it runs the image's claude through
# CLAUDE_CODE_EXECUTABLE.
COPY docker/claude-agent-acp/package.json docker/claude-agent-acp/package-lock.json \
    /opt/claude-agent-acp/
RUN cd /opt/claude-agent-acp \
    && npm ci --omit=dev --ignore-scripts --no-fund --no-audit \
    && npm cache clean --force \
    && test -x node_modules/.bin/claude-agent-acp \
    && ln -s /opt/claude-agent-acp/node_modules/.bin/claude-agent-acp /usr/local/bin/claude-agent-acp

# build the audited adapter source with locked dependencies, including the same
# codex cli for both resident and headless runs. esbuild's optional platform
# package supplies its binary without running install scripts.
RUN git init -q /opt/codex-acp \
    && cd /opt/codex-acp \
    && git fetch -q --depth 1 https://github.com/agentclientprotocol/codex-acp.git "${CODEX_ACP_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${CODEX_ACP_COMMIT}" \
    && rm -rf .git
COPY docker/codex-acp/package.json docker/codex-acp/package-lock.json /opt/codex-acp/
RUN cd /opt/codex-acp \
    && npm ci --ignore-scripts --no-fund --no-audit \
    && node build.mjs \
    && npm prune --omit=dev --ignore-scripts --no-fund --no-audit \
    && npm cache clean --force \
    && chmod 0755 dist/index.js \
    && ln -s /opt/codex-acp/dist/index.js /usr/local/bin/codex-acp \
    && ln -s /opt/codex-acp/node_modules/.bin/codex /usr/local/bin/codex \
    && codex --version \
    && codex-acp --version

# linear-axi for the linear trigger and abra's linear writes: fetched by commit
# and checked, every package from its lockfile with integrity hashes and install
# scripts off, built with its typescript compiler, then dev packages pruned.
RUN git init -q /opt/linear-axi \
    && cd /opt/linear-axi \
    && git fetch -q --depth 1 https://github.com/schmidthole/linear-axi.git "${LINEAR_AXI_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${LINEAR_AXI_COMMIT}" \
    && rm -rf .git \
    && npm ci --ignore-scripts --no-fund --no-audit \
    && ./node_modules/.bin/tsc -p tsconfig.json \
    && npm prune --omit=dev --ignore-scripts --no-fund --no-audit \
    && find node_modules -mindepth 1 -maxdepth 1 -type d -empty -delete \
    && npm cache clean --force \
    && chmod 0755 dist/bin/linear-axi.js \
    && ln -s /opt/linear-axi/dist/bin/linear-axi.js /usr/local/bin/linear-axi \
    && linear-axi --version

# python tools in their own virtualenvs, hash-pinned: the slack adapter
# dependencies, and black for `make format` from the repo's requirements-dev.txt.
COPY docker/requirements-slack.txt requirements-dev.txt /tmp/requirements/
RUN python3 -m venv /opt/venvs/slack \
    && /opt/venvs/slack/bin/pip install --no-cache-dir --disable-pip-version-check \
        --require-hashes --only-binary=:all: -r /tmp/requirements/requirements-slack.txt \
    && python3 -m venv /opt/venvs/black \
    && /opt/venvs/black/bin/pip install --no-cache-dir --disable-pip-version-check \
        --require-hashes --only-binary=:all: -r /tmp/requirements/requirements-dev.txt \
    && ln -s /opt/venvs/black/bin/black /usr/local/bin/black \
    && rm -rf /tmp/requirements \
    && black --version

# the abra user: no usable password, key-only ssh.
RUN useradd --create-home --uid 1000 --user-group --shell /bin/bash abra \
    && usermod --password '*' abra \
    && install -d -o abra -g abra -m 0700 /run/abra \
    && install -d -o abra -g abra -m 0755 /opt/abra-npm

ENV ABRA_ROOT=/home/abra/abra \
    ABRA_AGENT_PROVIDER=claude \
    CLAUDE_CODE_EXECUTABLE=/usr/local/bin/claude \
    CODEX_PATH=/usr/local/bin/codex \
    CODEX_HOME=/home/abra/.codex \
    DISABLE_AUTOUPDATER=1 \
    npm_config_cache=/opt/abra-npm \
    npm_config_prefer_offline=true \
    npm_config_update_notifier=false

# prefetch the npx packages the wrappers pin; prefer_offline serves them from
# this cache without contacting the registry.
USER abra
RUN npx --yes "tasks-axi@${TASKS_AXI_VERSION}" --help > /dev/null \
    && npx --yes "gh-axi@${GH_AXI_VERSION}" --help > /dev/null

# the image copy of abra seeds new instance roots; it stays read-only.
USER root
COPY . /opt/abra
RUN chmod -R u=rwX,go=rX /opt/abra \
    && chmod 0755 /opt/abra/bin/* /opt/abra/docker/entrypoint.py

USER abra
WORKDIR /home/abra
EXPOSE 2222
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/python3", "-I", "/opt/abra/docker/entrypoint.py"]
