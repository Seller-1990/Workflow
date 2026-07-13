# -*- coding: utf-8 -*-
"""Resolve the TLS CA bundle used by packaged HTTP clients."""

from __future__ import annotations

import os
import sys
from pathlib import Path


CA_BUNDLE_ENV_VARS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")


def resolve_ca_bundle() -> Path:
    """Return an existing CA bundle or raise a diagnostic FileNotFoundError."""
    candidates = list(_candidate_paths())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    attempted = ", ".join(str(path) for path in candidates) or "<none>"
    raise FileNotFoundError(f"No usable TLS CA certificate bundle found; attempted: {attempted}")


def configure_ca_bundle_environment() -> Path:
    """Point requests/OpenSSL environment variables at a verified bundle."""
    ca_bundle = resolve_ca_bundle()
    for name in CA_BUNDLE_ENV_VARS:
        configured = os.environ.get(name)
        if not configured or not Path(configured).is_file():
            os.environ[name] = str(ca_bundle)
    return ca_bundle


def _candidate_paths():
    for name in CA_BUNDLE_ENV_VARS:
        configured = os.environ.get(name)
        if configured:
            yield Path(configured).expanduser()

    try:
        import certifi

        yield Path(certifi.where())
    except (ImportError, OSError):
        pass

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        root = Path(bundle_root)
        yield root / "certifi" / "cacert.pem"
        yield root / "cacert.pem"