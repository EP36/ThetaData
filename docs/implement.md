# Codex Execution Runbook

## Source of truth
- `docs/codex-plan.md` is the source of truth for sequencing, scope, and acceptance criteria.
- `AGENTS.md` contains repo-wide coding, testing, and safety rules.
- `README.md` contains setup and runtime expectations.

## Autonomy behavior
Execute the full plan in `docs/codex-plan.md` from the first unfinished step through the final step without asking for confirmation between steps.

After each step:
1. Inspect the relevant files.
2. Briefly summarize what will change.
3. Implement only the current step.
4. Run relevant validation:
   - tests
   - lint
   - type checks
   - build checks
   - local smoke checks where appropriate
5. Fix any failures immediately.
6. Briefly summarize what changed.
7. Continue to the next step automatically.

## When to pause
Pause only if one of these is true:
- a required secret, credential, or external dependency is missing
- validation fails in a way that cannot be resolved safely
- the next step would require a broad architectural change not covered by `docs/codex-plan.md`
- the repository is in a broken state that requires human intervention

## Scope control
- Keep diffs minimal and tightly scoped to the current step.
- Do not rewrite unrelated parts of the codebase.
- Preserve existing behavior unless the current step explicitly changes it.
- Do not introduce live trading by default.
- Keep frontend free of trading logic.
- Use mocks or stubs when integration points are not ready, and isolate them clearly.

## Documentation
- Update `README.md` whenever setup, usage, architecture, or limitations change.
- Add or update comments only when they clarify non-obvious logic.
- Document assumptions and simulation limitations, especially for backtesting and execution.

## Completion rule
Do not stop after “ready to proceed.”
Proceed automatically to the next step unless one of the pause conditions is met.