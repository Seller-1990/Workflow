# Local dialog background

## Applicability

Read when changing global QSS root surfaces or local Qt dialogs such as
`StepRangeDialog` and `ErrorSummaryDialog`.

## Required behavior

- `get_stylesheet(dark: bool) -> str` must leave `QMainWindow` and `QDialog`
  roots opaque in both themes, using `get_colors(dark)["background"]`.
- Generic transparent `QWidget` rules must not override those root surfaces.
  In the shared stylesheet, put generic rules before root rules rather than
  duplicating per-dialog background patches.
- Visible labels must contrast with their actual surface. Preserve the original
  dialog selection, accept and cancel behavior.

## Forbidden behavior

- Do not assume a QPalette alone overrides a later stylesheet rule.
- Do not infer native Windows compositing or completed desktop acceptance from
  an offscreen widget grab.

## Required validation

`tests/test_ui_evidenced_repairs.py` exercises range/failure dialogs in light and
dark themes: the root pixel is opaque and matches the theme background; label
contrast is at least 4.5:1. The range dialog retains selection and accept/cancel
results. Check the actual visible window separately before declaring native
visual acceptance.

## Example

```css
/* Wrong: a later QWidget rule can undo the root background. */
QDialog { background: white; }
QWidget { background: transparent; }

/* Correct shared order. */
QWidget { background: transparent; }
QDialog { background: white; }
```

## Related contracts

- [Checkbox indicators](./checkbox-indicators.md)
- [Clipped text accessibility](./clipped-text.md)
