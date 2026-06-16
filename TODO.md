# dug — TODO

## Short (1–2 hours each)

- [ ] **Model load caching** — sentence-transformers reloads 80MB on every `dug` invocation, adds ~1–2s cold start. Fix: cache the loaded model in a temp file or use a persistent daemon process.
- [ ] **Non-interactive init flags** — add `--local` / `--openai` flags to `dug init` so it can be scripted without the wizard prompt (useful for CI and dotfile setups).
- [ ] **Untrack `uv.lock`** — `uv.lock` is currently committed. Decide: keep it (reproducible installs) or gitignore it (lighter repo). Leaning toward gitignoring for a CLI tool.

## Medium (half day each)

- [ ] **`jedi` call graph edges** — add SYMBOL→SYMBOL "calls" edges for Python using the `jedi` library (no server, pure Python). Callers/callees of a stack trace symbol get a relevance boost in scoring. `uv add jedi`, ~50 lines of code.
- [ ] **README** — required before going public or sharing. Cover: what dug is, install command, `dug init` → `dug "error"` flow, how the learning loop works, contributing.

## Big (weekend)

- [ ] **Phase 6 — Distribution**
  - Tag `v0.1.0` and push
  - Publish to PyPI (`uv publish`)
  - Create `homebrew-dug` repo, add `Formula/dug-cli.rb`
  - Create `scoop-dug` repo, add `bucket/dug-cli.json`
  - Add `HOMEBREW_TAP_TOKEN` and `PYPI_TOKEN` to GitHub repo secrets
  - Test `curl install.sh` end-to-end on a clean machine
  - Test `pipx install dug-cli` on a clean machine
  - Verify GitHub Actions release workflow fires correctly on tag push
