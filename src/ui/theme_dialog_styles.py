# -*- coding: utf-8 -*-
"""Shared QSS templates for themed modal dialogs and menus."""

_MSG_BOX_STYLE = """
QMessageBox {{
    background-color: {bg};
    color: {fg};
}}
QMessageBox QLabel {{
    color: {fg};
    background-color: transparent;
}}
QMessageBox QPushButton {{
    background-color: {btn_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 20px;
    min-width: 80px;
    font-weight: 500;
}}
QMessageBox QPushButton:hover {{
    background-color: {hover};
}}
"""

_INPUT_DIALOG_STYLE = """
QInputDialog {{
    background-color: {bg};
    color: {fg};
}}
QInputDialog QLabel {{
    color: {fg};
    background-color: transparent;
}}
QInputDialog QLineEdit {{
    background-color: {input_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 12px;
}}
QInputDialog QLineEdit:focus {{
    border: 1px solid {focus};
}}
QInputDialog QPushButton {{
    background-color: {btn_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 20px;
    min-width: 80px;
    font-weight: 500;
}}
QInputDialog QPushButton:hover {{
    background-color: {hover};
}}
QInputDialog QComboBox {{
    background-color: {input_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 12px;
}}
"""

_MENU_STYLE = """
QMenu {{
    background-color: {bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    background-color: transparent;
    color: {fg};
    border-radius: 6px;
    padding: 7px 12px;
    margin: 1px 0px;
}}
QMenu::item:selected {{
    background-color: {hover};
    color: {fg};
}}
QMenu::item:disabled {{
    color: {muted};
    background-color: transparent;
}}
QMenu::separator {{
    height: 1px;
    margin: 6px 8px;
    background: {divider};
}}
"""
