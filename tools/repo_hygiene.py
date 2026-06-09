# -*- coding: utf-8 -*-
"""Repository hygiene checks for release artifacts and local secret residue."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


TRACKED_ARTIFACT_PREFIXES = ("build/", "dist/", "data/", "logs/")
TRACKED_ARTIFACT_SUFFIXES = (".exe", ".db", ".sqlite", ".sqlite3")
TEXT_SUFFIXES = {".json", ".py", ".md", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".spec"}
SECRET_PATTERN = re.compile(r"access_token=([A-Za-z0-9._~+-]{3,}|<redacted>)")
STRICT_LOCAL_DIRS = ("build", "dist", "data", "logs")
STRICT_LOCAL_CACHE_DIRS = ("__pycache__", ".pytest_cache")
STRICT_LOCAL_EXPORT_PATTERNS = ("audit_export.json", "tmp_export.json", "workflows_export*.json")
ALLOWLISTED_FAKE_TOKENS = frozenset(
    {
        "<redacted>",
        "contract-token",
        "integration-secret-token",
        "local-token",
        "secret-token",
        "dev-token",
        "other-token",
        "imported",
        "imported-token",
        "test-token",
        "request-token",
        "provider-token",
    }
)


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
    candidates: set[Path] = set()
    for pattern in STRICT_LOCAL_EXPORT_PATTERNS:
        candidates.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(candidates, key=lambda path: _display_path(path, root))


def list_local_residue_paths(root: Path) -> list[Path]:
    residues: set[Path] = set()
    for dirname in STRICT_LOCAL_DIRS:
        path = root / dirname
        if path.exists():
            residues.add(path)
    for dirname in STRICT_LOCAL_CACHE_DIRS:
        residues.update(path for path in root.rglob(dirname) if path.is_dir())
    residues.update(local_sensitive_candidates(root))
    return sorted(residues, key=lambda path: _display_path(path, root))


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


def find_local_residue(paths: list[Path], root: Path) -> list[HygieneIssue]:
    return [
        HygieneIssue(
            kind="local-residue",
            path=path,
            message=f"local-only residue present (strict mode): {_display_path(path, root)}",
        )
        for path in paths
    ]


def _should_scan_text(path: Path, root: Path) -> bool:
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
            if any(token not in ALLOWLISTED_FAKE_TOKENS and len(token) >= 8 for token in SECRET_PATTERN.findall(line)):
                issues.append(
                    HygieneIssue(
                        kind="secret-residue",
                        path=path,
                        line_number=line_number,
                        message=f"possible webhook token residue: {_display_path(path, root)}:{line_number}",
                    )
                )
    return issues


def run_checks(root: Path, *, strict: bool = False, tracked_paths: list[Path] | None = None) -> list[HygieneIssue]:
    tracked = tracked_paths if tracked_paths is not None else list_tracked_files(root)
    scan_paths = list(tracked)
    if strict:
        scan_paths = sorted(set(scan_paths + local_sensitive_candidates(root)))
    issues = find_tracked_artifacts(tracked, root) + find_secret_matches(scan_paths, root)
    if strict:
        issues.extend(find_local_residue(list_local_residue_paths(root), root))
    return issues


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repository hygiene checks.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail on local-only residue such as build/dist/data/logs caches and local export JSON files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    issues = run_checks(root, strict=args.strict)
    if not issues:
        print("Repository hygiene check passed.")
        return 0

    print("Repository hygiene check failed:")
    for issue in issues:
        print(f"- [{issue.kind}] {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
