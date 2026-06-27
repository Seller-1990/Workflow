# -*- coding: utf-8 -*-
"""slim 打包资源过滤规则。"""

from __future__ import annotations


SLIM1_DROP_EXACT_SUFFIXES = {
    "PySide6\\Qt6Pdf.dll",
    "PySide6\\Qt6Qml.dll",
    "PySide6\\Qt6QmlMeta.dll",
    "PySide6\\Qt6QmlModels.dll",
    "PySide6\\Qt6QmlWorkerScript.dll",
    "PySide6\\Qt6Quick.dll",
    "PySide6\\Qt6VirtualKeyboard.dll",
    "PySide6\\plugins\\platforminputcontexts\\qtvirtualkeyboardplugin.dll",
    "PySide6\\plugins\\imageformats\\qpdf.dll",
}

SLIM2_EXTRA_DROP_EXACT_SUFFIXES = {
    "PySide6\\Qt6Svg.dll",
    "PySide6\\plugins\\iconengines\\qsvgicon.dll",
    "PySide6\\plugins\\imageformats\\qsvg.dll",
    "Pythonwin\\mfc140u.dll",
    "Pythonwin\\win32ui.pyd",
    "图标.png",
}

KEEP_TRANSLATION_SUFFIXES = {
    "PySide6\\translations\\qt_zh_CN.qm",
    "PySide6\\translations\\qtbase_zh_CN.qm",
}


def should_keep_artifact(relative_name: str, profile: str = "slim1") -> bool:
    normalized = (relative_name or "").replace("/", "\\")
    drop_exact_suffixes = set(SLIM1_DROP_EXACT_SUFFIXES)
    if profile == "slim2":
        drop_exact_suffixes.update(SLIM2_EXTRA_DROP_EXACT_SUFFIXES)

    if normalized in drop_exact_suffixes:
        return False
    if normalized.startswith("PySide6\\translations\\"):
        return normalized in KEEP_TRANSLATION_SUFFIXES
    return True
