# Contributing

Thanks for helping. A few rules keep the clean-room guarantees intact.

## Ground rules
- **Fail closed.** A missing tool, a failed check or an unanswered question must stop the pipeline, never skip silently.
- **Humans answer gates.** No code path may answer a risk gate, approval or sign-off on the user's behalf, or default one.
- **Nothing upstream crosses the wall.** The builder sandbox receives only approved specs, contracts, style notes and
  filtered tests. Builder feedback stays file-level (scores only), never lines or diffs.
- **No legal claims.** Docs and output describe process and evidence, never immunity.

## Development
- Scripts use the Python standard library only (3.10+). Every script needs `--help`.
- Run the tests: `cd tests && python -m unittest -v test_core`
- Run the demo: `python examples/run_demo.py --dest /tmp/cleanroom-demo`
- Validate the plugin: `npx -y @anthropic-ai/claude-code plugin validate .`
- Changes to `docker/` should keep `python scripts/sandbox_run.py probe` passing (CI runs it on Linux).

## Reporting a weakness
If you find a way for upstream content to reach the builder, or for a gate to be bypassed, please open an issue
describing the path. Those are the most valuable reports this project can get.
