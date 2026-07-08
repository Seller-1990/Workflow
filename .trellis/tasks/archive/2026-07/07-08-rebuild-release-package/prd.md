# PRD: Rebuild Release Package

## Goal

Rebuild the current application package from the latest committed source.

## Requirements

- Produce a Windows package on the current Windows host using the default
  release spec.
- Run the packaged app `--self-check` smoke test.
- Check whether macOS Intel packaging is possible from this environment and
  report the exact limitation if not.
- Leave unrelated untracked files untouched.

## Acceptance Criteria

- Windows build command completes successfully.
- Packaged executable passes `--self-check`.
- Artifact paths and hashes are reported.
- macOS Intel status is explicitly stated.

## Technical Notes

- Default Windows release command: `python -m PyInstaller build_slim2.spec --noconfirm`.
- macOS Intel package requires an Intel macOS host/runner and cannot be
  cross-built from Windows.
