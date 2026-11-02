# -*- coding: utf-8 -*-
"""Qt 文本展示的小型纯函数。"""

from html import escape


def plain_text_tooltip(text: str) -> str:
    """以显式富文本承载字面值，保留换行/空格且不解释用户标记。"""
    if not text:
        return ""
    return f'<qt><p style="white-space: pre-wrap;">{escape(text)}</p></qt>'
