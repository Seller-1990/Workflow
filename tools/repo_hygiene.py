# -*- coding: utf-8 -*-
"""Repository hygiene checks for release artifacts and local secret residue."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


TRACKED_ARTIFACT_PREFIXES = ("build/", "dist/", "data/", "logs/")
TRACKED_ARTIFACT_SUFFIXES = (".exe", ".db", ".sqlite", ".sqlite3")
TEXT_SUFFIXES = {".json", ".py", ".md", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".spec"}
SECRET_PATTERN = re.compile(r"access_token=(?!<redacted>)(?!local-token\b)[A-Za-z0-9._~+-]{8,}")


@dataclass(frozen=True)
class HygieneIssue:
    kind: str
    path: Path
    message: str
    line_number: int | None = None


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def list_tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    raw_paths = result.stdout.decode("utf-8", errors="replace").split("\0")
    return [root / raw_path for raw_path in raw_paths if raw_path]


def local_sensitive_candidates(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("workflows_export*.json") if path.is_file())


def find_tracked_artifacts(paths: list[Path], root: Path) -> list[HygieneIssue]:
    issues: list[HygieneIssue] = []
    for path in paths:
        rel = _display_path(path, root)
        lower_rel = rel.lower()
        if lower_rel.startswith(TRACKED_ARTIFACT_PREFIXES) or lower_rel.endswith(TRACKED_ARTIFACT_SUFFIXES):
            issues.append(
                HygieneIssue(
                    kind="tracked-artifact",
                    path=path,
                    message=f"tracked generated/runtime artifact: {rel}",
                )
            )
    return issues


def _should_scan_text(path: Path, root: Path) -> bool:
    rel = _display_path(path, root)
    if rel.startswith("tests/"):
        return False
    return path.suffix.lower() in TEXT_SUFFIXES


def find_secret_matches(paths: list[Path], root: Path) -> list[HygieneIssue]:
    issues: list[HygieneIssue] = []
    for path in paths:
        if not path.is_file() or not _should_scan_text(path, root):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if SECRET_PATTERN.search(line):
                issues.append(
                    HygieneIssue(
                        kind="secret-residue",
                        path=path,
                        line_number=line_number,
                        message=f"possible webhook token residue: {_display_path(path, root)}:{line_number}",
                    )
                )
    return issues


def run_checks(root: Path) -> list[HygieneIssue]:
    tracked = list_tracked_files(root)
    scan_paths = sorted(set(tracked + local_sensitive_candidates(root)))
    return find_tracked_artifacts(tracked, root) + find_secret_matches(scan_paths, root)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    issues = run_checks(root)
    if not issues:
        print("Repository hygiene check passed.")
        return 0

    print("Repository hygiene check failed:")
    for issue in issues:
        print(f"- [{issue.kind}] {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
