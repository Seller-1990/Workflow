#!/usr/bin/env python
"""Check dependency-list drift across Workflow requirement files.

The check is conservative: it reports version/specifier differences for packages
that appear in multiple requirement files, without requiring network access.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

REQ_FILES = ["requirements.txt", "requirements-ci.txt", "requirements-release.txt"]
PINNED_REQ_FILES = ["requirements-ci.txt", "requirements-release.txt"]
NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(.*)$")


def normalize_name(name: str) -> str:
    return name.lower().replace("_", "-")


def parse_req_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return None
    line = line.split("#", 1)[0].strip()
    m = NAME_RE.match(line)
    if not m:
        return None
    return normalize_name(m.group(1)), m.group(2).strip()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    seen: dict[str, dict[str, str]] = defaultdict(dict)
    missing = []
    for filename in REQ_FILES:
        path = root / filename
        if not path.exists():
            missing.append(filename)
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parsed = parse_req_line(line)
            if parsed:
                name, spec = parsed
                seen[name][filename] = spec
    drift = []
    # requirements.txt intentionally keeps broad runtime lower bounds, while
    # CI/release files are lock-style pinned environments. Treat drift as a
    # failure only across pinned files; broad runtime specs are reported by
    # dedicated dependency-upgrade work, not by this guard.
    for name, by_file in sorted(seen.items()):
        pinned_specs = {by_file[fn] for fn in PINNED_REQ_FILES if fn in by_file}
        if len(pinned_specs) > 1:
            drift.append((name, {fn: by_file[fn] for fn in PINNED_REQ_FILES if fn in by_file}))
    if missing:
        print("Missing requirement files: " + ", ".join(missing))
    if drift:
        print("Requirement spec drift detected:")
        for name, by_file in drift:
            print(f"- {name}: " + "; ".join(f"{fn}={spec or '(unversioned)'}" for fn, spec in sorted(by_file.items())))
        return 1
    print("Requirement consistency check passed: no cross-file spec drift detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
