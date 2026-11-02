# -*- coding: utf-8 -*-
"""Construct the application font from the shared theme typography tokens."""


def build_application_font(families, pixel_size: int):
    from PySide6.QtGui import QFont

    font = QFont()
    font.setFamilies(list(families))
    font.setPixelSize(pixel_size)
    return font
