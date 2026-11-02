# -*- coding: utf-8 -*-
"""Build and style the collapsible section header/body, without owning state."""



def setup_section_content(section, *, header_padding, title, title_font_size, title_weight, body_padding, body_top_padding, ui):
    root = ui.QVBoxLayout(section)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    header = ui.QWidget()
    header_layout = ui.QHBoxLayout(header)
    header_layout.setContentsMargins(int(header_padding), 0, int(header_padding), 0)
    header_layout.setSpacing(8)
    header.setFixedHeight(section._header_height)

    section.btn_toggle = ui.QToolButton()
    section.btn_toggle.setObjectName("sectionChevron")
    section.btn_toggle.setAutoRaise(True)
    section.btn_toggle.setCursor(ui.Qt.PointingHandCursor)
    section.btn_toggle.clicked.connect(section.toggle)
    section.btn_toggle.setFixedSize(18, 18)
    section.btn_toggle.setIconSize(ui.QSize(18, 18))
    header_layout.addWidget(section.btn_toggle, alignment=ui.Qt.AlignVCenter)

    section.title_label = ui.QLabel(title)
    f = section.title_label.font()
    f.setPointSize(int(title_font_size))
    if int(title_weight) >= 700:
        f.setWeight(ui.QFont.Weight.Bold)
    elif int(title_weight) >= 600:
        f.setWeight(ui.QFont.Weight.DemiBold)
    else:
        f.setWeight(ui.QFont.Weight.Normal)
    section.title_label.setFont(f)
    header_layout.addWidget(section.title_label)
    header_layout.addStretch()

    section.header_actions = ui.QWidget()
    section.header_actions_layout = ui.QHBoxLayout(section.header_actions)
    section.header_actions_layout.setContentsMargins(0, 0, 0, 0)
    section.header_actions_layout.setSpacing(8)
    header_layout.addWidget(section.header_actions, alignment=ui.Qt.AlignRight | ui.Qt.AlignVCenter)

    root.addWidget(header)

    section.body = ui.QWidget()
    section.body_layout = ui.QVBoxLayout(section.body)
    section.body_layout.setContentsMargins(int(body_padding), int(body_top_padding), int(body_padding), int(body_padding))
    section.body_layout.setSpacing(10)
    root.addWidget(section.body)



def section_stylesheet(widget, *, colors, radius) -> str:
    """卡片风格：白色卡片 + 微妙边框，悬停边框加深（亮/暗共用一份）。"""
    return f"""
        QFrame#collapsibleSection {{
            border-radius: {radius}px;
            background: {colors['surface_card']};
            border: 1px solid {colors['border_subtle']};
        }}
        QFrame#collapsibleSection:hover {{
            border-color: {colors['border']};
        }}
        QToolButton#sectionChevron {{
            color: {colors['text_tertiary']};
            border: none;
            background: transparent;
        }}
        """
