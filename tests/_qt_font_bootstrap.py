"""Supply real text glyphs only for fontless Windows offscreen test processes."""

from __future__ import annotations

import os
from pathlib import Path
import sys


_APPLICATION = None
_TEXT_SAMPLE = "中文ABCxyz012"


def _qt_types():
    from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
    from PySide6.QtWidgets import QApplication

    return QApplication, QFontDatabase, QFont, QFontMetrics


def _local_font_paths():
    windows = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    directory = Path(windows) / "Fonts"
    return tuple(directory / name for name in ("msyh.ttc", "simsun.ttc", "simhei.ttf"))


def _has_text_glyphs(database, font_type, metrics_type):
    for family in database.families():
        font = font_type(family)
        font.setPixelSize(13)
        metrics = metrics_type(font)
        if all(metrics.inFontUcs4(ord(char)) for char in _TEXT_SAMPLE) and metrics.horizontalAdvance(_TEXT_SAMPLE) > 0:
            return True
    return False


def bootstrap_text_font_for_offscreen():
    """Run before test collection; never change the app's font, style or settings."""
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        return
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        return

    application_type, database, font_type, metrics_type = _qt_types()
    global _APPLICATION
    _APPLICATION = application_type.instance()
    if _APPLICATION is None:
        _APPLICATION = application_type([])
    if not isinstance(_APPLICATION, application_type):
        raise RuntimeError("Windows offscreen UI tests require QApplication, not an existing QCoreApplication.")
    if _has_text_glyphs(database, font_type, metrics_type):
        return

    candidates = _local_font_paths()
    for path in candidates:
        if not path.is_file():
            continue
        font_id = database.addApplicationFont(str(path))
        if font_id < 0:
            continue
        if _has_text_glyphs(database, font_type, metrics_type):
            return
        database.removeApplicationFont(font_id)
    searched = ", ".join(str(path) for path in candidates)
    raise RuntimeError(
        "Windows offscreen Qt has no usable Chinese/Latin text font. "
        f"Checked existing local fonts: {searched}. "
        "Make an installed CJK font available in the Windows Fonts directory before running UI tests; "
        "icon-only fonts cannot validate text geometry. No fonts were downloaded or installed."
    )
