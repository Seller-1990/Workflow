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
    hint = _cleanup_hint()
    message = f"No usable TLS CA certificate bundle found; attempted: {attempted}"
    if hint:
        message += f" {hint}"
    raise FileNotFoundError(message)


def _cleanup_hint() -> str:
    """检测运行时临时目录被系统清理的迹象,给出可操作的恢复提示。

    PyInstaller onefile 模式下,应用长时间运行期间系统磁盘清理可能删除
    %TEMP%/_MEI* 中未被进程锁定的数据文件(certifi/cacert.pem 等),导致
    通知发送时 CA bundle 缺失。常见恢复方式:重启应用(重新解压)。
    """
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not bundle_root:
        return ""
    root = Path(bundle_root)
    if root.exists():
        missing = not (root / "certifi").exists()
        if missing:
            return (
                "运行时临时目录存在但缺少解压文件(可能被系统磁盘清理删除),"
                "请关闭并重新启动应用后重试。"
            )
    return ""



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