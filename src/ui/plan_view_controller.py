# -*- coding: utf-8 -*-
"""Switch plan surfaces without owning persistence or selection."""


def set_plan_view(window, index: int) -> None:
    window.plan_stack.setCurrentIndex(index)
    for btn, stack_index in getattr(window, "_view_buttons", []):
        btn.setObjectName("ViewSwitchActive" if stack_index == index else "ViewSwitch")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
    if index == 0 and hasattr(window, "workbench_board"):
        window.workbench_board.refresh_after_view_shown()
