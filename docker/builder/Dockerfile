# Builder / test-writer container for the cleanroom plugin.
# The ONLY host folder this container ever sees is the sandbox, bind-mounted at /work by compose.yaml.
# Pin the base image by digest for reproducible builds:  docker buildx imagetools inspect node:22-bookworm-slim
FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.304

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pytest ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && npm cache clean --force

COPY entrypoint.sh isolation_probe.sh guard.py settings.json /opt/cleanroom/
RUN chmod 0555 /opt/cleanroom/entrypoint.sh /opt/cleanroom/isolation_probe.sh /opt/cleanroom/guard.py \
 && chmod 0444 /opt/cleanroom/settings.json

# Non-root. compose.yaml additionally sets read_only, cap_drop ALL and no-new-privileges.
USER node
ENV HOME=/home/node
WORKDIR /work
ENTRYPOINT ["/opt/cleanroom/entrypoint.sh"]
