<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## Project Release Rules

- Before packaging after completed code/rules/documentation changes intended for
  release, update `APP_VERSION` in `src/config.py` first so packaged artifact
  names reflect the new version.
- Small scoped fixes, bug fixes, and small optimizations increment the patch
  version: `4.1.2 -> 4.1.3`.
- Broad changes, major refactors, or major feature changes increment the major
  version and reset minor/patch: `4.1.3 -> 5.0.0`.
- Do not auto-increment the minor version unless the user explicitly asks for a
  minor release.
- Pure rebuilds of the same already-versioned source do not require a version
  bump unless the user explicitly asks for one.
