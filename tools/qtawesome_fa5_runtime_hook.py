# -*- coding: utf-8 -*-
"""PyInstaller runtime hook：把 qtawesome 字体注册裁剪为 FA5（solid + brands）。

项目 _ICON_MAP（src/ui/icons.py）只使用 fa5s.*（solid）与 fa5b.python（brands，
Python logo 属 brands 族）两种前缀；slim 打包会按 build_slim_rules 丢弃其余
字体文件。qtawesome 在首次 qta.icon() 时对 _BUNDLED_FONTS 逐族急切 load_font，
文件缺失会抛 FileNotFoundError——该异常会被 ui.icons 的兜底 except 吞掉，
表现为"全部图标空白"。本 hook 在 main 之前把 _BUNDLED_FONTS 收窄到 FA5，
保证缺失字体不会被加载。
"""
import qtawesome

_QTAWESOME_KEEP_PREFIXES = ("fa5s", "fa5b")

qtawesome._BUNDLED_FONTS = tuple(
    fargs for fargs in qtawesome._BUNDLED_FONTS if fargs[0] in _QTAWESOME_KEEP_PREFIXES
)
