# Path policy and visible range-run — summary

## Conclusion and selected decision

The user's explicit 2026-10-30 decision to remove path-risk confirmation from
**all entry points** is implemented. Desktop dispatch, CLI run/retry, engine
orchestration and `_import_and_run.py` no longer ask for or enforce path trust.
Legacy confirmation flags/signatures are accepted as no-ops. No migration or
silent trust write was used. Ordinary file/config/argument/mode validation,
complete execution snapshots, selected-step totals, exclusion, cancellation and
post-execution output-risk diagnostics remain.

The interval engine, CLI and dialog already existed, but the only desktop button
was under an explicitly hidden RunControlPanel. The same `btn_run_range` now lives
in the visible plan switch bar, retaining its signal, selection defaults, running
lock and theme owner. No parallel execution implementation was added.

## Verification and evidence boundaries

- Final mainline full suite after the import-runner compatibility cleanup:
  **767 passed, 1 skipped, 2 existing Query.get warnings in 104.90s**; 768 collected.
  The earlier 755-pass and 714-pass results are historical snapshots.
- Compilation, tracked diff/whitespace, requirements, broad-except (0), risky
  calls (0 unapproved / 16 allowlisted), tracked hygiene, environment and Trellis
  context checks passed. Hotspot checks failed: **35 baseline increases, 4 files
  over 1000 lines**. Strict hygiene failed on **32 local residues**. No baseline
  rewrite or data deletion was performed.
- One finite independent read-only review found no actionable correctness issue
  at confidence >=80 in the named consent-retirement/same-object-button delta.
  It ran no tests and had no exact pre-Phase-7 patch; its conclusion does not
  cover all older WIP or the later import-runner cleanup. Mainline read the latter
  cleanup and its regressions, and executed the final full suite separately.
- Actual isolated Windows main-entry interactions proved cancel creates no run,
  range 2–4 executes exactly those three steps (id6), unchecked single-step uses
  saved arguments directly (id7), parameter cancellation creates no run, and a
  temporary override executes without changing saved defaults (id8).
- Native visual acceptance is **partial and blocked**, not passed. Thirty window
  captures were inspected. Light-dialog contrast, checkbox affordance and text
  clipping issues were recorded. Later actual Qt events diverged from requested
  coordinates despite a pre-click cursor check; automated native input was
  stopped rather than retried indefinitely. Both product-check sessions exited
  normally; six relevant source hashes matched at close. No source cause for the
  input divergence was established, and it is not attributed to the product or
  the user.

## Implementation consequences and constraints

Preserve the no-consent policy and full snapshots when maintaining old digest
helpers/storage. Do not restore a gate from historical evidence or conflate
path consent with opt-in runtime arguments, stop confirmation or output cleanup
risk diagnostics. The optional `with_selected_steps` derivation was left intact;
its deletion was not a correctness requirement.

No commit, push, packaging, version bump, new dependency, migration, user-data
rewrite/deletion, real business script, external notification or OCR upload was
performed. Existing WIP and isolated evidence remain. Complete the missing native
matrix only through a stable input channel; additional UI fixes are not authorized
by this bounded product change.

## When to read evidence

Read [policy/range verification](./evidence/path-policy-and-range-verification.md)
for commands, red/green tests, review disposition and quality-gate results.
Read [desktop visual evidence](./evidence/desktop-visual-acceptance.md) for actual
screenshots/interactions, isolated DB evidence, input failures, normal closure and
explicitly untested cases. Historical scoped-consent evidence must not reinstate
its retired runtime policy.
