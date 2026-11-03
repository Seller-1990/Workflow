# Evidenced UI repair — summary

## Decision

The user confirmed four UI repairs and authorized main-session implementation:
light local-dialog contrast, ordinary checkbox states, full-value access for
clipped text, and releasing collapsed history space to the live log. The source
and automated-regression scope is complete; native visual acceptance is not.
No backend, data cleanup, release, dependency, commit or push is included.

## Implementation boundary

- Reordered the shared transparent QWidget / opaque root rules after Qt red
  pixels proved alpha=0. Dialog input/accept/cancel behavior stays intact.
- Shared `get_checkbox_stylesheet(colors)` is reused globally and by step tables;
  no IosSwitch replacement, signal changes or resource-file dependency.
- Workflow titles, selection hints and history cells expose complete values
  without resetting saved column widths. New `plain_text_tooltip` escapes once
  into explicit Qt rich text with pre-wrap, preserving literal tags, entities,
  spaces and newlines. Existing card/stage detail routes are not redesigned.
- `collapse_requested` saves/restores parent constraints before animation;
  `collapsed_changed` constrains the direct splitter child only at completion.
  Accepted divider moves during collapse update the expanded snapshot and manual
  flag; completed-fold drags cannot overwrite it. Transient state stays in memory,
  not QSettings. Run/log ownership and backend code are unchanged.
- Nine production paths are in scope: the original eight UI paths plus the new
  `src/ui/text_utils.py`. Their full HEAD diffs include prior WIP and must not be
  attributed wholesale to this batch.

## Independent review and correction

The original finite `ui-repair-final-review` found two P2 issues, not zero:
F1 (97%) identified tooltip rich-text interpretation losing literal values;
F2 (84%, initially static) identified accepted transition-time divider changes
being overwritten by the old expanded snapshot. Mainline reached both failures
with new regressions, applied the minimal corrections above, and verified them.

The same reviewer's finite F1/F2 follow-up found no surviving actionable defect
at confidence >=80 in those corrections. It was static, ran no tests/app and does
not establish whole-project correctness or native visual acceptance. An optional
helper-isolation concern was separately excluded by mainline: 4 parameterized
cases passed in a fresh pytest process.

## Current verification

Final post-correction mainline suite: **796 passed / 1 skipped / 2 existing
Query.get warnings in 116.00s**, with **797 collected**. All **193 src/tests Python
file hashes** were identical before/after the full suite and before/after the
final05 static gates. No production/test Python has changed since that run.
Affected UI/docs coverage passed **103 cases in 8.83s**; isolated helper semantics
passed **4 cases in 0.68s**. The skipped test requires external notification;
external sending was not enabled.

Final individual gates passed compile, requirements, broad-except (0 regressions),
risky calls (0 unapproved / 16 allowlisted), tracked hygiene, environment and
tracked diff whitespace. **Hotspot failed: 39 baseline increases / 4 files over
1000 lines. Strict hygiene failed: 38 local-residue issues only.** No baseline
was rewritten and no data/residue was deleted. A runner exit0 is not an aggregate
green verdict.

767-pass is pre-repair; 784-pass is early integration; 788-pass / 789 collected /
192 Python hashes is pre-F1/F2 correction. None is current final acceptance.

## Reusable contracts and context

- `.trellis/spec/ui/dialog-background.md`
- `.trellis/spec/ui/checkbox-indicators.md`
- `.trellis/spec/ui/clipped-text.md`
- `.trellis/spec/ui/history-splitter.md`

Final post-correction checks passed: docs/CI guards **7 cases in0.36s**;
Trellis and independent exact-policy assertions validated **16 entries per
manifest**, including all four UI leaves and no legacy mixed collection.
The bounded final08 check passed **19-file whitespace**, **47 local links**,
**193 Python hashes**, active/unarchived metadata and Phase6 blocked/Phase8
source-and-automation complete. Known Git conversion advisories were retained.
The earlier final03 checks predate correction; exact current logs and wrapper
failure dispositions are in `evidence/ui-repair-verification.md`.

## Remaining constraints

Prior native screenshots actually evidenced the light dialog and collapsed
history issues. Native input later diverged despite cursor checks, with no
established cause. No new native window was launched in Phase 8; repeated input
remains stopped. **Phase 6 complete native visual acceptance stays blocked.**
Offscreen pixels, QTest and full-suite success do not validate native popup,
checkbox glyph/focus, all tri-state rendering or the full page/theme/size matrix.

StepLog unknown-commit idempotency, cross-process cancellation, CLI exceptional
preflight close, unrelated module splitting and all previous physical-I/O limits
remain outside this batch. Read `evidence/ui-repair-verification.md` to challenge
reproduction, counterarguments, review scope, source attribution or any test/gate
claim. Keep the Trellis task active/unarchived; no commit or release is authorized.
