# -*- coding: utf-8 -*-
"""执行器策略测试共享辅助：伪造 Excel COM 依赖模块装配。"""

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def install_fake_excel_modules(monkeypatch, dispatch_ex):
    pythoncom_mod = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    win32_client_mod = SimpleNamespace(DispatchEx=dispatch_ex)
    win32_mod = SimpleNamespace(client=win32_client_mod)

    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom_mod)
    monkeypatch.setitem(sys.modules, "win32com", win32_mod)
    monkeypatch.setitem(sys.modules, "win32com.client", win32_client_mod)
