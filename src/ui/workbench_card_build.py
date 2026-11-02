# -*- coding: utf-8 -*-
"""Build step-card labels and accessibility metadata."""



def setup_card_content(card, step, order_label, dep_text, *, ui):
    layout = ui.QVBoxLayout(card)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(6)

    top = ui.QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(6)

    batch_tip = (
        f"{order_label} 是执行批次。\n"
        "批次由阶段顺序、上游依赖和检查点自动计算。\n"
        "同一批次的步骤在依赖满足后可一起执行；启用自动并行时可并行运行。"
    )
    if order_label == "B?":
        batch_tip = "执行批次不可用；看板仅供顺序浏览。请检查上方的批次诊断信息。"
    order = ui.QLabel(order_label)
    order.setObjectName("StepOrder")
    order.setFixedWidth(42)
    order.setToolTip(batch_tip)
    order.setAccessibleName(f"执行批次 {order_label}")
    order.setAlignment(ui.Qt.AlignCenter)
    order.setAttribute(ui.Qt.WA_TransparentForMouseEvents, True)
    top.addWidget(order)

    # 类型图标 + 检查点盾牌图标（检查点卡片）。文字徽章（TypePill/“检查点”）已精简，
    # 避免 200px 紧凑泳道下顶行溢出截断；类型与检查点全称保留在 tooltip 和 accessibleName。
    # 图标颜色在创建时烘焙，保存引用供 refresh_theme 按当前主题重设
    from ui.icons import type_icon
    card._step_type = step.step_type
    card._is_gate = bool(getattr(step, "is_gate", False))
    card.type_icon_label = ui.QLabel()
    card.type_icon_label.setPixmap(
        type_icon(step.step_type, dark=False).pixmap(card.ICON_SIZE_PX, card.ICON_SIZE_PX)
    )
    card.type_icon_label.setAccessibleName(f"类型：{ui.TYPE_LABELS.get(step.step_type, step.step_type)}")
    card.type_icon_label.setAttribute(ui.Qt.WA_TransparentForMouseEvents, True)
    top.addWidget(card.type_icon_label)

    if card._is_gate:
        card.gate_icon_label = ui.QLabel()
        card.gate_icon_label.setPixmap(card._gate_pixmap(dark=False))
        card.gate_icon_label.setAccessibleName("检查点")
        card.gate_icon_label.setAttribute(ui.Qt.WA_TransparentForMouseEvents, True)
        top.addWidget(card.gate_icon_label)

    top.addStretch()
    card.status_badge = ui.QLabel("")
    card.status_badge.setObjectName("StatusBadge")
    card.status_badge.setProperty("stepStatus", "idle")
    card.status_badge.setAlignment(ui.Qt.AlignCenter)
    card.status_badge.setVisible(False)
    card.status_badge.setAttribute(ui.Qt.WA_TransparentForMouseEvents, True)
    top.addWidget(card.status_badge)
    layout.addLayout(top)

    title = ui.QLabel(step.name or "未命名步骤")
    title.setObjectName("StepTitle")
    title.setWordWrap(False)
    title.setMinimumWidth(0)
    title.setTextFormat(ui.Qt.PlainText)
    title.setSizePolicy(ui.QSizePolicy.Ignored, ui.QSizePolicy.Fixed)
    title.setAttribute(ui.Qt.WA_TransparentForMouseEvents, True)
    layout.addWidget(title)

    subtitle = ui.QLabel(card._subtitle(step, dep_text))
    subtitle.setObjectName("StepSubtitle")
    subtitle.setWordWrap(False)
    subtitle.setMinimumWidth(0)
    subtitle.setTextFormat(ui.Qt.PlainText)
    subtitle.setToolTip(ui.plain_text_tooltip(subtitle.text()))
    subtitle.setSizePolicy(ui.QSizePolicy.Ignored, ui.QSizePolicy.Fixed)
    subtitle.setAttribute(ui.Qt.WA_TransparentForMouseEvents, True)
    layout.addWidget(subtitle)
    card.subtitle = subtitle
    card._base_subtitle = subtitle.text()

    card.duration_badge = ui.QLabel("")
    card.duration_badge.setObjectName("DurationBadge")
    card.duration_badge.setVisible(False)
    card.duration_badge.setAttribute(ui.Qt.WA_TransparentForMouseEvents, True)
    layout.addWidget(card.duration_badge)

    card.setToolTip(
        f"{step.name}\n{batch_tip}\n类型：{ui.TYPE_LABELS.get(step.step_type, step.step_type)}\n"
        f"文件：{getattr(step, 'script_path', '') or '未设置'}\n{dep_text}"
    )
    card.setAccessibleName(f"步骤：{step.name}")
