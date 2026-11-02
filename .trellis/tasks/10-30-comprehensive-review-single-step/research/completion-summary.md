# Unified remaining-work completion

## Current continuation — release preparation (2026-11-03)

The user later explicitly requested committing, pushing and updating the version tag,
superseding prior phase-local restrictions against those operations. Release metadata is
aligned at `7.0.0` in `src/config.py`, `src/__init__.py` and README; the focused
release-metadata suite passed **3 tests**. The previously recorded full suite
(**967 passed / 1 skipped / 2 existing warnings**) predates that version metadata
update, so the exact candidate must pass the actual pre-push hook before publication.
The staged candidate has 176 paths: 79 `src/`, 62 `tests/`, 17 Spec files, 15
active-task files and 3 root files. Scratch evidence, user artifacts, and the unrelated
`scripts/ocr-review.sh` change are excluded. Do not claim all gates are green:
working-strict has not been rerun, and native Phase6 remains blocked after the one
authorized probe failed; no retry or product matrix is allowed. Keep the task
`in_progress` and unarchived.

## Decision and authorization

On 2026-10-31 the user requested all remaining work in one continuation and chose
“允许兼容迁移（推荐）”. Additive SQLite migration code and isolated old-database
upgrade/fault-recovery tests are authorized. Do not open or migrate the real
working database, delete/move user data, add dependencies, send notifications or
source externally, commit, push, package, bump versions, or archive this task.

## Current conclusion — delegated01 verification (2026-10-31 15:10)

Canonical evidence: `.dsh-tmp/verify-recheck-20261031-02/completion-result.json`
(generated 2026-10-31 15:10:55). On a 291-path checkpoint with drift 0 / missing 0 the
current tree passes locally: hotspot gate **0 regressions** with checker and baseline
unchanged, untracked-Python whitespace **0 findings across 88 files**, and
compile/requirements/broad/risky/tracked-hygiene/environment/tracked-diff all exit 0.
Affected scope: 5 modules, **69 passed in 7.17s**. Collection **968**; full run
**967 passed / 1 skipped / 2 existing warnings in 224.25s** with source_unchanged=true.
A fresh isolated CLI demo passed with execution steps `[2,2,3]`, 42 audit events,
33 allowed SQLite events all under the output dir, owners released, saved defaults
unchanged and the expected invalid-range exit 2.

Not completed, do not report green: the **working-strict gate was NOT run** this round
(51 local residues are a historical count); native Phase 6 stays **blocked** and was
not executed; the new delivery copy and closeout are deferred (planned paths
`.dsh-tmp/completion-delivery-20261031-delegated01/source/` and
`.dsh-tmp/completion-closeout-20261031-delegated01/result.json` — not produced yet, no
counts). Scope note, not a pending task: the historical 61-module / 612-case focused
set was not rerun separately because the 968-case full run already covers the whole
test set. The 2 warnings are pre-existing SQLAlchemy LegacyAPI warnings, and the
W292 in `tests/test_engine_force_stop_run.py` is a pre-existing non-blocking format
note that no source change addresses.

Two narrow refactors landed under user tool-recorded choices: 14 files lost **20**
trailing CRLF blank lines (6 files lost two, 8 lost one — a deviation from the
"one blank line per file" wording, disclosed and not retro-edited), AST-equal 14/14;
and 3 complete presentation tests moved to
`tests/test_script_run_args_dialog_presentation.py` with `tests/conftest.py` path
configuration moved to `pytest.ini`, preserving SRC-before-project-root order under
pytest 8.3.3. Migration proof uses 4 explicit old→new node ids plus Counter multiset
equality: 964 unmapped identical, 968 mapped equal, duplicates 0. The original
static-prediction false verdict and the fact that the L3 full run happened before the
correction remain disclosed.

Observation limits: the real DB was only observed by `stat` (unchanged size/mtime does
not prove it was never opened or read); one redirected INI does not prove no registry
write; the pytest chain has no socket audit, so "no network" is unmeasured; the CLI
audit covers only its own 9 child processes.

## Historical conclusion — freeze15 (superseded for current source)

The three backend lifetime/persistence items and focused responsibility extractions
are implemented and automatically verified. This is not all-task completion: the
native Phase6 matrix remains blocked, the original hotspot gate still fails on two
necessary test-growth paths, and the working copy retains local runtime residues.
Source closeout preserves each check's actual outcome; it does not establish native
acceptance, all-task completion or all-quality-gates-green.

- StepLog creation now has a persistent operation key, full initial-payload conflict
  checking, clean-session unknown-commit reconciliation and database uniqueness.
  Isolated fault/concurrency/multiprocess tests preserve legacy duplicate rows and
  validate additive/restartable migrations. This does not make business scripts
  exactly-once; legacy calls without a key remain separate operations.
- Run publication atomically includes an exact history/run/owner identity. Other
  processes persist stop requests, not live terminal states. The owner observes,
  acknowledges and finalizes through cooperative cancellation; unknown liveness
  is not death. Real isolated processes cover live/dead owners and stale requests.
- CLI run/retry/dry-run and the import runner close successfully constructed engines
  in finally, retaining existing outcomes, error propagation and compatibility seams.
- Responsibility extractions preserve public facades, late binding, selection,
  animation/splitter behavior and all-entry path-consent retirement. No quality
  checker or baseline was rewritten and no tests compressed, removed or reordered.

## Correctness findings and bounded disposition

The original finite backend review found two real lifecycle gaps, not a clean
verdict. F2's specified commit-acknowledgement-loss plus first-reader-loss boundary
is corrected: unverified publication candidates stay outside ordinary finalization;
recovery/adoption and conditional release match history, run and owner token,
including replacement rows reusing numeric/run IDs. Persistent database failure
can still prevent cleanup; no unconditional release guarantee is claimed.

F1 required a second narrow correction. A child future may be RUNNING before its
budget slot is reserved, survive real parent timeout/grace, then resume after a new
root starts. Reached pre-slot red tests fail twice: both publish a late child and
stop request, and the healthy next root changes cancelled False->True. Freeze15
adds exactly two production lines under the existing engine-then-budget startup
locks: reject an already-own-cancelled nested request before shared writes or
publication. The recovery test adds147 lines and covers healthy/already-cancelled
next-root state, normal nested execution and post-cleanup roots. Other42 backend
paths, including F2, remain unchanged from freeze14.

Mainline read green49/final246 and the exact delta. The ONE two-file static follow-up
found no surviving actionable correctness issue at confidence>=80 in this F1 delta,
challenging early-return finalization, cancellation after the check and lock order.
The finite CLI/snapshot/numeric and15-path UI-extraction reviews likewise found no
surviving >=80 issue in their named scopes. All review conclusions are static-only,
separate from execution evidence, and are not whole-project defect-free claims.

## Latest executed verification

Evidence root: `.dsh-tmp/completion-verification-20261031-v01/`.

- `owned-freezes03`: backend44/CLI8/boundaries14/UI53,119 unique paths independently
  rehashed without mismatch. All implementation owners explicitly hold.
- `full03`:967 passed/1 skipped/2 existing Query.get warnings in190.32s;968 collected
  in default `tests` order, no exclusions/reordering. All290 scoped source/test/tool/
  quality/CI/hook/config hashes match before/after, changed_paths=[].
- `affected03`:612 passed/2 existing warnings in135.94s across61 retained owner/
  consumer modules, matching the explicit full03 checkpoint before/after. Counts
  overlap full03 and are not additive.
- `cli-demo02`: actual CLI dry-run/only2/range2–3/history-detail/invalid independent
  --to checks pass. Safe self-written steps execute2,2,3; two success histories,
  three success StepLogs with unique operation keys, released owners and unchanged
  saved defaults are observed. Early INI/SQLite guards record42 events with isolated
  database paths and no network attempts; notifications are disabled, webhooks0.
  The environment-sanitized demo step only appends scratch JSONL/prints; do not
  extend launcher auditing to that child interpreter. Source matches full03.
- `gates03`: compile/requirements/broad/risky/tracked-hygiene/environment/tracked-diff
  exit0; broad0 regressions, risky0 unapproved/16 allowlisted. Original hotspot exits1
  only on tests/test_script_run_args_dialog.py449>402 and tests/conftest.py16>11;
  no file exceeds1000. Working-strict exits1 on49 local residues at that checkpoint.
  Data/logs/build/dist/caches stay intact. These are gate failures, not runner failure.
- `context03`:20/20 same-set legal manifest references,30 local links,15 edited
  documents without whitespace errors; active/unarchived, Phase6 blocked and Phase9
  in_progress. Final document edits require a fresh closeout check.

## UI and native boundary

Historical193 passed/1 wrapping failure remains recorded. Its reached cause is an
explicit Windows/offscreen fontless test process resolving text to icon-only codicon.
Repository test-only bootstrap conditionally loads an existing local CJK font, not
a production dialog/QSS/font/icon workaround. Original23-order verification passes196,
preserving194 earlier identities and10 original test bodies/decorators; twelve real
icon registrations and original/640/420 wrapping invariants are reached. The14 helper
unit cases are included in the latest integrated suite. No font is downloaded/installed.
This closes the harness issue, not native Windows acceptance; do not rerun that special
sequence or retry native input without a new authorized, viable input approach.

Phase6 stays blocked after actual Qt event/input divergence and two harmless failed
channel probes (checks=[]); cause is not established. Full page/theme/size coverage,
history-detail/restore, explicit default saving, controlled running-stop and native
checkbox/tooltip rendering remain unaccepted. Earlier30 captures and real range/default/
temporary/failure effects are partial historical evidence, not a complete new matrix.
Early UI check1/check2 missed QSettings isolation and wrote view1 then0. The prior value
is unknown; no guessed rollback was made. Later runs install scratch INI constructors
before product imports; do not claim real preferences were untouched throughout.

## Remaining constraints and challenge path

The earlier493-file/255-Python delivery, full01=942/587 affected and freeze14=965/610
are historical checkpoints, not final delivery acceptance for freeze15. The first
complete snapshot `completion-delivery-20261031-final01` contains505 files/267 Python
files, includes tracked files plus required untracked source/tests/tools/Spec/task/plan
content, has no Python omissions, preserves source_unchanged=true/payload_exact=true,
and passes the same strict hygiene checker with0 issues. The working copy has51
local-residue findings at that checkpoint; nothing was deleted. Subsequent document
edits make final01 intermediate, not the final current-document revision.

`completion-context-20261031-final01` passed20/20 same-set legal references,31 local
links and15 edited documents; independent Trellis validation passed20/20, tracked
diff-check exits0. Additional `completion-static-20261031-final01` fails on14 real
extra blank lines at EOF among87 untracked Python files. All290 frozen hashes and119
owner paths still match and version remains6.0.3. These EOF findings are not LF/CRLF
advisory false positives and are not superseded by strict hygiene0. No format-only
source changes were appended to invalidate the967/612-tested checkpoint.

Definitive post-document output locations for the **historical** freeze15 revision are
`.dsh-tmp/completion-delivery-20261031-final02/source/` and its `manifest-result.json`,
`.dsh-tmp/completion-context-20261031-final02/result.json`, and the external seal
`.dsh-tmp/completion-closeout-20261031-final01/result.json`. Those receipts bind actual
source/document hashes, payload equality, context checks and each retained failure for
that snapshot only — the 505-file / 267-Python counts are historical, and the current
worktree no longer matches their complete hash set. For the **current** revision the
delivery copy and external seal are deferred until these documents freeze; planned
paths are `.dsh-tmp/completion-delivery-20261031-delegated01/source/` and
`.dsh-tmp/completion-closeout-20261031-delegated01/result.json` (planned, not produced,
counts unknown). Final receipts stay outside the payload so reporting their hashes does
not mutate captured documents; do not write this session's own frozen hashes back into
these documents.

The earlier493-file/255-Python delivery, full01=942/587 affected and freeze14=965/610
are historical checkpoints, not delivery acceptance for the current tree. The first
complete snapshot `completion-delivery-20261031-final01` contains505 files/267 Python
files and passed the same strict hygiene checker with0 issues; the working copy keeps
its local residues and nothing was deleted.

Keep task active/in_progress/unarchived. The current tree passes the hotspot gate with
0 regressions and has 0 untracked-Python whitespace findings; the working-strict gate is
not run this round and its historical 51 local residues are preserved without deletion.
Do not claim all gates green or native acceptance.
Cooperative cancellation does not force-terminate arbitrary descendants or bound every
synchronous filesystem/sink/close operation. Read the independent backend Spec leaves
for contracts and [verification evidence](./evidence/remaining-work-verification.md)
for reached experiments, counterexamples, artifact paths and remaining blockers.
