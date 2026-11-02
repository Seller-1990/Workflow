# Checkbox indicator visibility

## Applicability

Read when changing ordinary `QCheckBox` theme rules or a local stylesheet that
can override them, including step-table and runtime-argument forms. This does
not replace the separate `IosSwitch` control.

## Required behavior

- `get_checkbox_stylesheet(colors: dict) -> str` defines the shared indicator
  rules; `get_stylesheet(dark)` and `build_table_stylesheet(colors)` reuse them.
- Unchecked indicators have a visible outline rather than an entirely
  transparent grab. Checked fill is distinguishable from unchecked fill in
  light and dark themes. Disabled selected state differs from enabled selected
  state. Preserve the existing focus and indeterminate selectors.
- Use existing theme colors. Do not introduce a runtime image-file dependency.
- Styling must not change checkbox signals, default values, argument overrides,
  edit-mode restrictions or explicit save-defaults behavior.

## Forbidden behavior

- Do not maintain a second, weaker table-only indicator definition that overrides
  the shared rule.
- Do not call a different pixel image proof of a readable check glyph, keyboard
  focus, tri-state semantics or completed native acceptance.

## Required validation

Run `tests/test_ui_evidenced_repairs.py`: ordinary/table/arguments surfaces in
both themes, enabled/disabled and checked/unchecked. Verify an indicator at
least 14px square, unchecked outline-to-center contrast at least 3:1, different
checked/unchecked images and different enabled/disabled selected images.
Retain `tests/test_single_step_ui.py` and runtime-argument behavior coverage.
Native visual and keyboard-focus acceptance remains a separate check.

## Example

```python
# Correct: the local table rules share the ordinary-checkbox contract.
return table_styles + get_checkbox_stylesheet(colors)
```

## Related contracts

- [Local dialog background](./dialog-background.md)
