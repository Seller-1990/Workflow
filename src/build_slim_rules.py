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

# V9.3：qtawesome 字体裁剪——项目只使用 fa5s（solid）与 fa5b（brands，Python logo）
# 两种前缀（src/ui/icons.py 的 _ICON_MAP），其余字体文件在打包时丢弃，由运行时 hook
# （tools/qtawesome_fa5_runtime_hook.py）保证 qtawesome 不再尝试加载它们
# （否则 FileNotFoundError 会被 ui.icons 吞成"图标全空白"）。
QTAWESOME_FONTS_DIR_PREFIX = "qtawesome\\fonts\\"
QTAWESOME_KEEP_FONT_FILES = {
    "fontawesome5-solid-webfont-5.15.4.ttf",
    "fontawesome5-solid-webfont-charmap-5.15.4.json",
    "fontawesome5-brands-webfont-5.15.4.ttf",
    "fontawesome5-brands-webfont-charmap-5.15.4.json",
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
    if normalized.startswith(QTAWESOME_FONTS_DIR_PREFIX):
        return normalized[len(QTAWESOME_FONTS_DIR_PREFIX):] in QTAWESOME_KEEP_FONT_FILES
    return True
