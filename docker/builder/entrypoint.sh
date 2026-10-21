#!/bin/sh
# Roles:
#   probe        run the isolation probe (no model call)
#   test-writer  write black-box tests from /work/spec.md + /work/contract.md
#   builder      implement the module from the spec, contract, style and tests
set -eu
role="${1:?usage: entrypoint.sh probe|test-writer|builder}"

case "$role" in
  probe)
    exec /opt/cleanroom/isolation_probe.sh
    ;;
  run-tests)
    # Runs the build's own tests on a copy of the build; no model call.
    cd /work && exec sh -c "${CLEANROOM_TEST_CMD:?CLEANROOM_TEST_CMD not set}"
    ;;
  test-writer|builder)
    : "${CLEANROOM_MODEL:?CLEANROOM_MODEL not set}"
    mkdir -p /work/out/_log
    if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
      # API key: --bare skips CLAUDE.md, auto memory, plugins and auto-discovered hooks/skills/MCP.
      isolation="--bare"
    elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
      # Subscription token from `claude setup-token`. --bare ignores this token, so isolation comes from:
      # an empty tmpfs HOME/config dir (no user settings, memory, plugins or MCP), a /work that holds only
      # manifest-approved files (no CLAUDE.md, no .claude/), and project settings not being loaded.
      export CLAUDE_CONFIG_DIR=/home/node/.claude
      isolation="--setting-sources user --disable-slash-commands"
    else
      echo "no builder credential: set CLEANROOM_BUILDER_OAUTH_TOKEN (subscription) or CLEANROOM_BUILDER_API_KEY" >&2
      exit 65
    fi
    # --strict-mcp-config with no --mcp-config: zero MCP servers.
    # --tools: only local file and shell tools; WebFetch/WebSearch are not even offered.
    # --settings: our own guard hooks (secondary to the container isolation) and deny rules.
    # --dangerously-skip-permissions is acceptable here only because the container is the boundary.
    # shellcheck disable=SC2086
    exec claude -p \
      $isolation \
      --model "$CLEANROOM_MODEL" \
      --tools "Read,Write,Edit,Bash,Glob,Grep" \
      --disallowedTools "WebFetch" "WebSearch" "mcp__*" \
      --strict-mcp-config \
      --settings /opt/cleanroom/settings.json \
      --append-system-prompt-file /work/AGENT.md \
      --no-session-persistence \
      --max-turns "${CLEANROOM_MAX_TURNS:-150}" \
      --max-budget-usd "${CLEANROOM_MAX_BUDGET_USD:-10}" \
      --dangerously-skip-permissions \
      --output-format stream-json --verbose \
      "You are the cleanroom ${role}. Your working directory is /work. Read /work/TASK.md and complete it. Only read and write files under /work." \
      > /work/out/_log/transcript.jsonl
    ;;
  *)
    echo "unknown role: $role" >&2
    exit 64
    ;;
esac
