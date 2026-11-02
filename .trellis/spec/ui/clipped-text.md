# Full-value access for clipped text

## Applicability

Read when changing workflow headings, board selection hints or run-history
cells that may be narrower than a user-controlled value.

## Required behavior

- Clipping is controlled only if the full value remains reachable through a
  complete tooltip, a detail view or another explicit full-value affordance.
  Arbitrarily long names need not be fully expanded at every window width.
- Workflow title and board selection hint are `Qt.PlainText` labels, can shrink
  in the layout, and update their tooltip whenever their text changes, including
  empty/reset states. Do not leave an old workflow name in the tooltip.
- Dynamic full-value tooltips use `plain_text_tooltip(text: str) -> str` from
  `ui.text_utils`: escape the input once into explicit Qt rich text with
  `white-space: pre-wrap`. Literal tags/entities, spaces and newlines must survive
  Qt's interpretation. Empty input remains an empty tooltip.
- History cells retain their complete displayed value in their tooltip. Run ID
  retains the identifier plus diagnostics/step counts; status retains status
  text, diagnostics and notification failure details. Empty-state cells also
  expose their message.
- Preserve existing card/stage/detail tooltips and saved history column widths.
  Do not reset stored widths merely to accommodate a particular long sample.

## Forbidden behavior

- Do not treat every shortened cell as data loss when it already has a complete
  detail route, or hard-clip important content without an alternative.
- Do not use `minimumSizeHint()` as evidence that `QSizePolicy.Ignored` prevents
  shrinking: the policy changes layout allocation, not the original hint.

## Required validation

Run `tests/test_ui_evidenced_repairs.py`: long workflow title with special
characters, actual constrained label geometry, reset tooltip, long stage hint,
all history columns, notification/step diagnostics, empty state and restoration
of custom column widths. Recognized `<b>`, `&amp;` and `<img>` fixtures must
round-trip through `QTextDocumentFragment.fromHtml(...).toPlainText()` without
interpreting user markup or collapsing whitespace. Comparing stored `toolTip()`
strings alone is insufficient. The helper cases must also pass in isolation.
These semantic checks do not inspect the native popup's rendering; actual
appearance needs separate native verification.

## Example

```python
from ui.text_utils import plain_text_tooltip

label.setTextFormat(Qt.PlainText)
label.setText(full_value)
label.setToolTip(plain_text_tooltip(full_value))  # Update on resets too.
```

## Related contracts

- [Local dialog background](./dialog-background.md)
