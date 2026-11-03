# -*- coding: utf-8 -*-
"""Construct the run-history/log splitter and its state callbacks."""



def build_run_tab(window, *, ui):
    run_page = ui.QWidget()
    run_page_layout = ui.QVBoxLayout(run_page)
    run_page_layout.setContentsMargins(0, 0, 0, 0)
    run_page_layout.setSpacing(0)
    window.run_splitter = ui.QSplitter(ui.Qt.Vertical)
    window.run_splitter.setObjectName("RunSplitter")
    window.run_splitter.setChildrenCollapsible(False)
    window.run_splitter.setHandleWidth(5)
    window.log_panel = ui.LogPanel()
    window.log_panel.setSizePolicy(ui.QSizePolicy.Expanding, ui.QSizePolicy.Expanding)
    window.run_history = ui.RunHistoryPanel()
    window.run_history.setSizePolicy(ui.QSizePolicy.Expanding, ui.QSizePolicy.Expanding)
    window.run_history.setMinimumHeight(180)
    window.log_panel.setMinimumHeight(220)
    window.run_splitter.addWidget(window.run_history)
    window.run_splitter.addWidget(window.log_panel)
    window.run_splitter.setSizes([360, 560])
    window.run_splitter.splitterMoved.connect(window._on_run_splitter_moved)
    window.run_history.section.collapse_requested.connect(
        lambda collapsed: (
            ui.panel_controller.begin_run_history_collapse(window)
            if collapsed else ui.panel_controller.prepare_run_history_expand(window)
        )
    )
    window.run_history.section.collapsed_changed.connect(
        lambda collapsed: ui.panel_controller.on_run_history_collapsed(window, collapsed)
    )
    run_page_layout.addWidget(window.run_splitter)
    window._run_tab_index = window.mode_tabs.addTab(run_page, "运行")
