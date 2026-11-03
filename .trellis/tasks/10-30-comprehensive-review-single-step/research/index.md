# Research index — comprehensive review and single-step execution

## Confirmed conclusions

- Single-step argument editing is opt-in and remains UI-session state.
- Earlier scoped-consent implementation is superseded by the user's explicit all-entry path-confirmation removal decision; see [current path/range summary](./path-policy-and-range-summary.md). Normal execution/lifecycle validation stays in force.
- Board card-height work and queued layouts had reproducible redundant work; minimal fixes have regression coverage.
- Phase 8 source and automated coverage are complete for the four confirmed UI fixes; see [UI repair summary](./ui-repair-summary.md). The original finite review found two P2 issues (literal tooltip values and transition-time divider restoration); mainline reproduced and minimally fixed both. The finite F1/F2 follow-up found no surviving actionable defect at confidence >=80 in those corrections, not in all WIP. Final frozen integration:796 passed/1 skipped/2 existing warnings in116.00s;797 collected;193 src/tests Python hashes unchanged. Affected UI/docs103 and isolated helper4 passed. Final hotspot fails (39 baseline increases,4 over1000); strict hygiene fails on38 local residues. 788/789/192 is pre-correction;784 and767 are earlier snapshots.
- Startup-stop ownership is now explicit and atomic with history creation. A fresh bounded read-only review found no actionable defect at confidence >=80 in this delta; no whole-project defect-free claim.

## Rejected hypotheses

- Fewer QTextDocument insertion API calls alone establish a faster, equivalent log renderer.
- Animation visibility checks, run-state projection, run locks, and documented test seams are removable merely because they look defensive.
- A legacy global risk digest automatically authorizes every unchanged risky subset.

## Continuation status

- The bounded Python/BAT correction and existing engine/history consumers are frozen and accepted within the declared I/O limits; the integrated full suite and actual-capture/real isolated-DB diagnostic probe passed. The completed finite independent read-only Phase 5 review found no actionable correctness issue at confidence >=80 in the named delta; it did not execute tests or edit code. This is not a whole-project defect-free or all-quality-gates-green claim.
- [Executor output ownership summary](./executor-output-summary.md) defines this follow-up; [investigation evidence](./evidence/executor-output-ownership.md) separates source facts, intermediate agent tests and mainline counterexamples. [Root-cause analysis](./evidence/executor-output-root-cause.md) records rejected ownership assumptions. Cross-process cancellation and unknown-commit reconciliation were excluded from Phase5; they are now separately authorized Phase9 work, not retroactively part of Phase5 acceptance.

## Current decisions

- 7.0.0 is released (historical fact): commit `3edc923` pushed on branch `chore/ocr-auto-review` with annotated tag `v7.0.0`; the actual pre-push check ran 967 passed/1 skipped/2 existing warnings. Package run 41486757336 succeeded on Windows and failed on macOS during pre-package tests because Darwin process identity is missing, so no macOS 7.0.0 package exists. Patch 7.0.1 is implemented and locally accepted: Darwin identity reads PID plus kernel creation time via libproc `proc_pidinfo` (unknown liveness never treated as death, reused PID matched by creation time), and the observer-lifecycle regression test performs test-only finally cleanup (assertion failure closes the observer and restores engine state; product owner-thread lifecycle unchanged). Acceptance: owner-focused 50 passed/17.39s; full 984 passed/1 skipped/2 existing Query.get warnings in 173.50s exit0; broad/risky/hotspot/requirements/compile/diff all exit0 (risky 0 unapproved, 16 allowlisted; hotspot 0 regressions); release metadata/docs/CI guards 10 passed in0.27s; Trellis implement/check manifests (20 each) validated; non-strict tracked hygiene passed. No new native acceptance and no strict rerun; commit, tag and macOS CI package remain pending; native Phase6 stays blocked. See [completion scope](./completion-summary.md).
- Phase9 is authorized and in progress: the user selected compatible additive migration code, isolated old-DB/fault-recovery tests and unified completion; see [completion scope](./completion-summary.md). Earlier deferred backend/module work is now included, but no real working DB may be opened or migrated.
- Preserve unrelated WIP and user data; no new dependency, user-data deletion, or real DB/QSettings access. The earlier phase-local no-commit/push/version-bump restriction was superseded by the user's later explicit request to commit, push and update the version tag; this does not unblock native Phase6.
- All-entry path consent is retired; retain legacy DB compatibility, complete execution snapshots and the engine's selected-step total. Reparent the existing range button into the visible plan toolbar.
- Do not write a run terminal state after StepLog cleanup failure.
- Do not regenerate hotspot baselines to hide module growth.

## Unresolved questions

- Startup ownership correction and reached-branch regressions remain preserved. Same-engine status/cancel can still wait behind DB creation; Phase9 adds a separate persisted local-process owner/request protocol rather than claiming that the in-memory lock coordinates other processes.
- Native visual acceptance is partial/blocked: 30 captures inspected and real range/default/temporary/failure execution evidenced before Phase 8. The recorded dialog/checkbox/clipping/history defects now have scoped source fixes and automated regressions, but no new native acceptance. Further input remains stopped after actual Qt events diverged from requested coordinates; cause is not established. Both isolated sessions exited normally with relevant source hashes unchanged. Full native matrix, new native tooltip/checkbox rendering and untested interactions remain open; see desktop evidence.
- Latest Phase9 freeze15 is automatically verified: full03=967 passed/1 skipped/2 existing warnings,968 collected; affected03=612 passed across61 modules;290 scoped hashes unchanged and119 owner paths independently match. cli-demo02 passes actual isolated CLI dry-run/only/range/history/invalid-range with execution2,2,3, unique operation keys and released owners. Reached red/green and the ONE two-file static follow-up close the reproduced F1 pre-slot chain; F2's exact uncertain-publication identity boundary stays fixed. No global defect-free verdict. Original gates03 still fails two necessary test-growth paths449>402 and16>11, no file over1000; working-strict49 checkpoint residues are retained. The initial complete delivery `completion-delivery-20261031-final01` has505 files/267 Python files, exact payload and0 isolated strict issues; working-copy strict reports51 retained local residues. Later document edits make it intermediate. Additional new-Python whitespace checks fail on14 real EOF blank lines across87 files while290 frozen hashes/119 owner paths still match. Final post-document source/context outcomes are bound by the final02 manifest and external closeout receipt named in the completion summary; no all-gates-green claim. Repository-only fontless-offscreen harness196/original23-order verification is closed, not native acceptance. See [completion checkpoint](./completion-summary.md). Native remains blocked with no input retries. Early QSettings view1→0 writes stay disclosed; original value unknown/no guessed rollback, later runs use early scratch INI. Phase5 physical-I/O limits remain unchanged.

## Summaries and evidence

- [Authorized unified completion scope](./completion-summary.md)
- [Remaining-work verification](./evidence/remaining-work-verification.md)
- [Four evidenced UI repairs](./ui-repair-summary.md)
- [UI red/green, quality and independent-review evidence](./evidence/ui-repair-verification.md)
- [Latest path-policy and visible-range continuation](./path-policy-and-range-summary.md)
- [Current review and implementation summary](./final-review-summary.md)
- [Original scope and recovery summary](./recovery-and-single-step-summary.md)
- [Final verification evidence](./evidence/final-verification.md)
- [Finite independent output-ownership review](./evidence/executor-output-final-review.md)
- [Bounded startup ownership and test-reachability verification](./evidence/final-correctness-review.md)
- [Review finding dispositions](./evidence/review-dispositions.md)
- [Bounded board-queue lifecycle verification](./evidence/final-efficiency-review.md)
- [Startup-test root-cause analysis](./evidence/startup-test-root-cause.md)
- Pre-adoption audit records, retained without migration: [correctness](./bug-audit.md), [efficiency and architecture](./efficiency-architecture-audit.md), [single-step implementation](./single-step-implementation.md).
