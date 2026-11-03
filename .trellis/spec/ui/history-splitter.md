# Collapsed run-history splitter ownership

## 1. Scope / Trigger

Read when changing history folding, `CollapsibleSection` animation signals, run
splitter profiles or log-visibility safeguards.

## 2. Signatures

- `collapse_requested: Signal(bool)` emits the new logical state before starting
  or skipping animation; unchanged-state requests do not emit.
- `collapsed_changed: Signal(bool)` retains its existing completed-state role.
- `collapsed_height: int` is the section header height, not its current animated
  height.
- `begin_run_history_collapse(window)`, `prepare_run_history_expand(window)` and
  `on_run_history_collapsed(window, collapsed)` coordinate the splitter's direct
  history child.

## 3. Contracts

- Before collapse animation, save expanded splitter sizes, direct-child min/max
  height constraints and the manual-adjustment flag in memory once.
- On completed collapse, constrain `RunHistoryPanel`, not only its nested section,
  to the header plus panel margins; the live log receives remaining space.
- Before expansion animation, restore parent height constraints and saved sizes.
  Do not leave the parent fixed until the expansion completes.
- Rapid reversals must leave only the final completed state and valid parent
  constraints. Hidden-tab folding must work without animation.
- Auto profiles/log visibility must not reopen a collapsed history area. Preserve
  manual divider choice on restore; Qt may clamp to available space/minima after
  a resize. A folded divider drag must not grow the history area.
- If the divider accepts a real manual move during collapse animation, update
  saved expanded sizes and its manual flag from the accepted allocation. Once
  the body is explicitly hidden at completed collapse, divider events must not
  overwrite that expanded snapshot. Restore must retain the latest accepted
  manual choice, not merely the position at collapse request.
- Keep these transient constraints out of QSettings. Existing saved column
  widths and unrelated run/log/DB ownership are unchanged.

## Forbidden behavior

- Do not set the parent fixed height from `section.height()` when collapse is
  only requested: that still contains the expanded height.
- Do not interpret a 44px nested section as proof the direct splitter child is
  also 44px.

## 4. Validation & Error Matrix

| State / action | Required outcome |
|---|---|
| Visible collapse starts | Expanded parent constraints remain until completion |
| Collapse completes | Direct child is header + margins; log receives the rest |
| Expand starts or collapse reverses | Parent min/max and saved layout restored before animation |
| Hidden-tab fold and resize | Same compact end state, with no animation dependency |
| Accepted divider move during collapse transition | Saved sizes and manual flag track accepted allocation |
| Divider drag while folded | Folded height and saved expanded allocation are unchanged |
| Forced running/idle profile while folded | Does not reopen the history area |

## 5. Good / Base / Bad Cases

- Good: requested state saves/restores allocation, completion compresses only the
  direct child; resize restoration is clamped by Qt's available geometry.
- Base: an unchanged-state request emits nothing and does not overwrite a saved
  expanded layout.
- Bad: fix the parent to its current expanded height when folding starts, or
  restore it only after an expansion animation that is already clipped.

## 6. Tests Required

Run `tests/test_ui_evidenced_repairs.py`: repeated themed collapse/expand;
hidden-tab resize; running/idle profiles; interrupted animation reversals;
reached QTest handle drag with held-button move events; narrow-height log
visibility; original min/max, manual flag and widths restored. Keyboard-trigger
collapse, pause mid-animation and drag the actual handle; assert `splitterMoved`
and a changed accepted allocation before verifying that expansion and a later
non-forced profile retain that allocation and manual flag. A completed-fold drag
alone does not cover the transition window. These are regressions, not actual
native desktop acceptance.

## 7. Wrong vs Correct

```python
# Wrong at the start of collapse: current height is still expanded.
history.setFixedHeight(history.section.height())
# Correct at completion, with the panel's top/bottom margins included.
history.setFixedHeight(history.section.collapsed_height + vertical_margins)
```

## Related contracts

- [Full-value access for clipped text](./clipped-text.md)
