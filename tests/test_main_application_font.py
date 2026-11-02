# -*- coding: utf-8 -*-
"""Launcher consumes the public theme-font API without a real GUI or database."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("event_loop_error", [False, True])
def test_main_uses_theme_application_font_and_always_releases_session(monkeypatch, tmp_path, event_loop_error):
    import main as launcher

    app = MagicMock()
    app.exec.return_value = 17
    if event_loop_error:
        app.exec.side_effect = RuntimeError("event loop failed")
    application_type = MagicMock(return_value=app)
    window = MagicMock()
    window_type = MagicMock(return_value=window)
    font = object()
    font_factory = MagicMock(return_value=font)
    cleanup_session = MagicMock()
    configure_ca = MagicMock()
    modules = {
        "PySide6": {"__path__": []},
        "PySide6.QtCore": {
            "Qt": SimpleNamespace(HighDpiScaleFactorRoundingPolicy=SimpleNamespace(PassThrough="pass-through")),
            "QTimer": MagicMock(),
        },
        "PySide6.QtGui": {"QIcon": MagicMock()},
        "PySide6.QtWidgets": {"QApplication": application_type},
        "config": {
            "APP_NAME": "Isolated workflow", "APP_VERSION": "test-only",
            "ICON_PATH": tmp_path / "no-icon", "LOG_DIR": tmp_path,
        },
        "tls_ca": {"configure_ca_bundle_environment": configure_ca},
        "ui": {"__path__": [], "MainWindow": window_type},
        "ui.theme": {"application_font": font_factory},
        "database": {"cleanup_session": cleanup_session},
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(launcher, "_try_dispatch_cli", lambda _argv: None)

    if event_loop_error:
        with pytest.raises(RuntimeError, match="event loop failed"):
            launcher.main([])
    else:
        assert launcher.main([]) == 17

    font_factory.assert_called_once_with()
    app.setFont.assert_called_once_with(font)
    window.show.assert_called_once_with()
    cleanup_session.assert_called_once_with()
    configure_ca.assert_called_once_with()
    app.setStyle.assert_called_once_with("Fusion")
