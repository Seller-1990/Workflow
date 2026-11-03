# -*- coding: utf-8 -*-
"""Build the board shell without owning workflow or layout state."""



def setup_board_ui(panel, *, ui):
    panel.setFocusPolicy(ui.Qt.StrongFocus)
    root = ui.QVBoxLayout(panel)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(12)

    toolbar = ui.QFrame()
    toolbar.setObjectName("BoardToolbar")
    toolbar_layout = ui.QHBoxLayout(toolbar)
    toolbar_layout.setContentsMargins(0, 0, 0, 0)
    toolbar_layout.setSpacing(10)

    panel.selection_hint = ui.QLabel("选择一个工作流后开始编排")
    panel.selection_hint.setObjectName("SelectionHint")
    panel.selection_hint.setTextFormat(ui.Qt.PlainText)
    panel.selection_hint.setMinimumWidth(0)
    panel.selection_hint.setSizePolicy(ui.QSizePolicy.Ignored, ui.QSizePolicy.Preferred)
    panel.selection_hint.setToolTip(ui.plain_text_tooltip(panel.selection_hint.text()))
    toolbar_layout.addWidget(panel.selection_hint, stretch=1)

    panel.btn_add_step = ui.QPushButton("+ 添加步骤")
    panel.btn_add_step.setObjectName("GhostButton")
    panel.btn_add_step.setToolTip("添加步骤到当前选中的阶段")
    panel.btn_add_step.setAccessibleName("添加步骤")
    panel.btn_add_step.clicked.connect(panel._request_add_step)
    toolbar_layout.addWidget(panel.btn_add_step)

    panel.btn_add_stage = ui.QPushButton("+ 新阶段")
    panel.btn_add_stage.setObjectName("GhostButton")
    panel.btn_add_stage.setToolTip("在当前阶段之后新增阶段")
    panel.btn_add_stage.setAccessibleName("新增阶段")
    panel.btn_add_stage.clicked.connect(panel._request_add_stage)
    toolbar_layout.addWidget(panel.btn_add_stage)
    root.addWidget(toolbar)

    panel.batch_warning = ui.QLabel()
    panel.batch_warning.setObjectName("BatchWarning")
    panel.batch_warning.setWordWrap(True)
    panel.batch_warning.setTextInteractionFlags(ui.Qt.TextSelectableByMouse)
    panel.batch_warning.setVisible(False)
    root.addWidget(panel.batch_warning)

    panel.scroll = ui.QScrollArea()
    panel.scroll.setObjectName("StageBoardScroll")
    panel.scroll.setWidgetResizable(False)
    panel.scroll.setFrameShape(ui.QFrame.NoFrame)
    # 任务15：横向滚动条 AsNeeded——内容能放下时不占用空间
    panel.scroll.setHorizontalScrollBarPolicy(ui.Qt.ScrollBarAsNeeded)
    panel.scroll.setVerticalScrollBarPolicy(ui.Qt.ScrollBarAsNeeded)

    panel.board_widget = ui.QWidget()
    panel.board_widget.setObjectName("StageBoard")
    panel.board_widget.setSizePolicy(ui.QSizePolicy.Minimum, ui.QSizePolicy.Minimum)
    panel.board_layout = ui.QHBoxLayout(panel.board_widget)
    panel.board_layout.setContentsMargins(0, 0, 0, 0)
    panel.board_layout.setSpacing(ui.STAGE_LANE_GAP)
    panel.board_layout.setAlignment(ui.Qt.AlignLeft | ui.Qt.AlignTop)
    panel.scroll.setWidget(panel.board_widget)
    root.addWidget(panel.scroll, stretch=1)

    panel.empty_state = ui.QLabel("暂无步骤。开启编辑后点击“添加步骤”创建第一步。")
    panel.empty_state.setObjectName("EmptyState")
    panel.empty_state.setAlignment(ui.Qt.AlignCenter)
    panel.empty_state.setVisible(False)
    root.addWidget(panel.empty_state)

    panel.refresh_theme(False)
