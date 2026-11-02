# -*- coding: utf-8 -*-
"""The startup font follows the same public tokens as the global stylesheet."""

from ui import theme


def test_application_font_matches_existing_shared_tokens():
    font = theme.application_font()

    assert font.families() == list(theme.FONT_FAMILIES)
    assert font.pixelSize() == theme.FONT_SIZE_PX


def test_application_font_resolves_current_tokens_on_each_call(monkeypatch):
    monkeypatch.setattr(theme, "FONT_FAMILIES", ("Arial", "Microsoft YaHei"))
    monkeypatch.setattr(theme, "FONT_SIZE_PX", 17)

    font = theme.application_font()
    other = theme.application_font()

    assert font.families() == ["Arial", "Microsoft YaHei"]
    assert font.pixelSize() == 17
    assert other is not font
    font.setPixelSize(25)
    assert other.pixelSize() == 17
    assert '"Arial", "Microsoft YaHei", sans-serif' in theme.get_stylesheet()
    assert "font-size: 17px" in theme.get_stylesheet()
