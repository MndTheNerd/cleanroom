# Changelog

## 0.3.0
- Builder can run on a Claude subscription: `claude setup-token` → `CLEANROOM_BUILDER_OAUTH_TOKEN` (default), or an API key.
- Plugin option `builder_auth` (`subscription` / `api_key`).
- Repository is its own marketplace: `/plugin marketplace add <owner>/<repo>`.
- CI: unit tests on Linux/Windows/macOS, `claude plugin validate`, container isolation probe, end-to-end demo.

## 0.2.0
- Optional add-ons chosen at install (JPlag + Java, ScanCode Toolkit), installed in the background; offline ScanCode source.
- `/cleanroom:addons` command.

## 0.1.0
- Initial release: license gate, six human risk gates, similarity scan and partition, spec filter, sandboxed
  test-writer/builder with SHA-256 manifests, verify (tests, equivalence, winnowing, JPlag), swap/clean, leftover grep,
  ScanCode scan, report, hash-chained provenance log.
