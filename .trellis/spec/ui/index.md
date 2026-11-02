# Qt UI specification router

## Scope and applicability

Shared Qt presentation and the run-page layout contracts. Run execution and
persistence boundaries remain under the [backend router](../backend/index.md).

| When changing | Read |
|---|---|
| Shared QSS root backgrounds or local dialog surfaces | [Local dialog background](./dialog-background.md) |
| Ordinary or table-local checkbox styles | [Checkbox indicators](./checkbox-indicators.md) |
| Narrow workflow titles, board selection hints or history cell values | [Full-value access for clipped text](./clipped-text.md) |
| History animation signals, direct splitter allocation or automatic profiles | [Collapsed run-history ownership](./history-splitter.md) |
| Specs, Research or task manifests | [Context curation](../context-curation.md) |

## Validation entry points

- `python -B -m pytest -p no:cacheprovider -q tests/test_ui_evidenced_repairs.py`
- Run the additional behavior tests named in the selected leaf.
- `python -B -m pytest -p no:cacheprovider -q`
- `git diff --check`
- Native visible-window interaction and screenshot inspection are separate from
  offscreen regression tests; an unavailable input channel is not a pass.
