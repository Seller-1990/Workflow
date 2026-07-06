# Directory Structure

> How backend code is organized in this project.

---

## Overview

The project is a single Python application under `src/`. Large compatibility
facades still exist, but new logic should move toward focused modules with pure
helpers where possible.

---

## Directory Layout

```
src/
├── engine.py                  # WorkflowEngine facade and compatibility surface
├── engine_core/               # workflow lifecycle, scheduling, execution helpers
├── executors/                 # step executors and executor result policy
├── database.py                # DB initialization, migrations, facade exports
├── database_*.py              # focused database domains
├── ui/                        # Qt widgets/controllers and pure UI state helpers
├── cli.py                     # command handlers and CLI engine
├── cli_formatting.py          # pure CLI display helpers
└── cli_notifications.py       # CLI notification delivery helper
```

---

## Module Organization

Prefer adding pure helper modules when logic must be shared or tested without
heavy runtime dependencies:

- UI state projection belongs in `ui/run_state.py` or a focused pure helper.
- Run-history diagnostic text belongs in `ui/run_diagnostics.py`.
- CLI display mapping belongs in `cli_formatting.py`, not inline Qt-dependent
  command paths.
- CLI notification delivery belongs in `cli_notifications.py`, with `cli.py`
  keeping only the compatibility wrapper.
- Large widget stylesheets belong in focused style helpers such as
  `ui/workbench_board_styles.py` so widget files stay under hotspot limits.
- JSON import schema validation belongs in `database_import_validation.py`;
  `database_import_export.py` should orchestrate persistence and serialization.
- Run finalization consistency belongs in `engine_core/run_finalization.py`.

Keep facades (`engine.py`, `database.py`, `cli.py`) as compatibility entry
points, but avoid placing new business rules there unless the rule is truly
about the facade itself.

---

## Naming Conventions

Use snake_case module names. Focused helper names should describe the boundary,
for example `run_finalization`, `run_diagnostics`, or `import_export_security`.

---

## Examples

- `src/engine_core/run_finalization.py`: pure finalization ordering contract.
- `src/import_export_security.py`: pure export payload leak guard.
- `src/ui/run_diagnostics.py`: pure diagnostic text for run history.
- `src/cli_formatting.py`: pure CLI status display mapping.
- `src/cli_notifications.py`: CLI-controlled notification delivery.
- `src/database_import_validation.py`: pure workflow JSON import validation and
  import path warnings.
- `src/ui/main_window_steps.py`: MainWindow step/stage context restoration.
- `src/ui/workbench_board_styles.py`: board stylesheet and theme tokens.
