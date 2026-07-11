# fix: script args dialog encoding

## Goal

Fix the runtime CLI-parameter dialog so long Chinese step names and script paths render clearly instead of visually overlapping and looking garbled.

## What I Already Know

* User screenshot shows the "本次运行参数" dialog.
* The garbled-looking line is at the top of each step parameter group.
* `src/ui/script_run_args_dialog.py` uses the long step display text as a `QGroupBox` title.
* The global stylesheet sets `QGroupBox` `margin-top: 0px` and draws the title at the top-left, so the title can overlap the first child label.

## Requirements

* Do not use long step names as native `QGroupBox` titles in the runtime-args dialog.
* Show the step order/name as normal wrapped, selectable content inside the group.
* Keep script path, fixed args, argparse fields, manual fallback, and final preview behavior unchanged.
* Cover the regression with a small UI/unit test that does not require a real display.

## Acceptance Criteria

* [ ] A long Chinese step name no longer becomes a `QGroupBox` title.
* [ ] The step heading remains visible in the dialog as a wrapped label.
* [ ] Existing script-argument parsing and collection tests still pass.
* [ ] New regression test passes under `QT_QPA_PLATFORM=offscreen`.

## Definition of Done

* Focused regression test added.
* Focused tests pass.
* No release version bump unless packaging is requested; this is a source fix only.

## Out of Scope

* Redesigning the whole parameter dialog.
* Changing argparse static detection semantics.
* Packaging/release publishing.

## Technical Notes

* Relevant code: `src/ui/script_run_args_dialog.py`.
* Relevant tests: `tests/test_script_cli_parameters.py`, new focused UI test.
* Relevant specs: `.trellis/spec/backend/quality-guidelines.md`, `.trellis/spec/guides/index.md`.
