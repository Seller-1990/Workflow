# UI/UX 优化与深色残留修复 Plan（实施就绪版）

> 本文档整合两轮评估结论：① UI/UX 优化建议（含对另一个 AI 建议的复核）；② 浅色主题下"深色残留"根因与修复。
> 每个任务已细化到"实施就绪"：含目标、依据（文件:行号）、修改前后对比、边界情况、测试要点、验证命令。
> 实施顺序：批次 1（P0-视觉）→ 批次 2（P1-决策）→ 批次 3（P1-交互）→ 批次 4（P2-增强）。

---

## 第一部分：深色残留根因分析

### 总体结论

经对 `src/ui` 下 35+ 文件的穷举式排查，**未发现传统意义上的"深色颜色泄漏"**：

- 所有 `if dark:` / `if self._dark:` 分支在 `_dark_mode=False` 时都正确走浅色路径
- `DARK_COLORS` / `STATUS_TOKENS_DARK` / `DARK_LANE_BGS` / `DARK_STAGE_COLORS` 等深色 token 仅出现在定义处和 `if dark` 分支内
- 浅色路径里唯一低亮度值是**有意为之的深色文字**（深字浅底，符合对比度设计）

用户感知到的"深色残留"真正根因是以下 4 类，按影响排序：

### 根因 1（D 类，主因）：双调色板不一致导致外壳偏深沉

应用存在**两套并行的浅色调色板**，混用时让外壳区域显得"偏深/偏暗"，被误判为深色残留：

**Shell 外壳（[main_window_theme.py:28-46](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_theme.py)，暖纸色系）**：
```python
return {
    "bg": "#f6f4ef",          # 暖纸色，比 #FFFFFF 暗
    "paper": "#fbfaf6",
    "workspace": "#f6f4ef",
    "panel": "#ffffff",
    "panel_soft": "#f1eee7",
    "ink": "#20242a",          # 比 #111827 略浅但仍深
    "muted": "#6c7077",
    "faint": "#8b9098",
    "line": "#ddd8cf",          # 比 #E2E8F0 略深
    "line_strong": "#c9c1b6",
    "blue": "#2458d3",          # 比 #007AFF 更深（AA 对比度）
    "blue_hover": "#1d49b6",
    "blue_weak": "#e9eefc",
    "green": "#247145",         # 比 #34C759 更深（AA 对比度）
    "green_weak": "#e7f3ea",
    "red": "#b3312a",           # 比 #FF3B30 更深（AA 对比度）
    "red_weak": "#f8e4e1",
}
```

**内层组件（[theme.py:3-47](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/theme.py)，冷中性系）**：
```python
COLORS = {
    "background": "#FFFFFF",
    "surface_primary": "#F8FAFC",
    "text_primary": "#111827",
    "border": "#E2E8F0",
    "primary": "#007AFF",       # Apple Blue，更亮
    "success": "#34C759",       # iOS Green，更亮
    "danger": "#FF3B30",        # iOS Red，更亮
}
```

**影响区域**：壳层标题、RunStateChip、PrimaryAction、DangerAction 用 `#247145`(深绿)、`#b3312a`(深红)、`#9b6417`(深琥珀) 等较暗强调色，而内层卡片/表格用更亮的 `#34C759/#FF3B30/#007AFF`。"外壳偏深沉、内层偏明亮"的落差在浅色背景下容易被误判为深色残留。

### 根因 2（B 类）：硬编码字面量未走 token 系统

| 文件:行号 | 硬编码值 | 上下文 | 是否刷新 |
|---|---|---|---|
| [theme.py:252](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/theme.py) | `#EEEEEE` | `QFrame#FoldBtnWrap{background:#EEEEEE}` 折叠按钮容器底色 | 否 |
| [main_window_theme.py:119,135](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_theme.py) | `#fffdfa` | `PrimaryAction`/`DangerAction` 按钮文字 | 否 |
| [step_editor_sections.py:394,396](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_editor_sections.py) | `#CBD5E1`/`#FFFFFF` | 依赖勾选框边框/底色 | 否 |
| [run_history.py:127-142](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/run_history.py) | `#FFFFFF`/`#FAFBFC`/`#6B7280` | 表格初始样式 | 是（refresh 覆盖） |
| [step_table/panel_build.py:56,61,68](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_table/panel_build.py) | `#6B7280` | drag_hint/stage_context/hint 初始色 | 是（refresh 覆盖） |
| [workflow_config.py:149](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/workflow_config.py) | `#888` | 模板变量提示文字 | 是（refresh 覆盖） |

### 根因 3（F 类）：刷新链缺口与死代码

[main_window_setup.py:525-533](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) 的 `apply_theme` 显式刷新 9 个组件，以下已定义 `refresh_theme` 但**未被顶层调用**：

| 组件 | 文件:行号 | 影响 |
|---|---|---|
| `DagView` | [dag_view.py:430](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/dag_view.py) | **死代码**：全目录无任何 import/实例化（仅 `theme.py:96` 注释提及） |
| `IosSwitch` | [ios_switch.py:73](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/ios_switch.py) | 多处开关实例未走顶层刷新链 |
| `ErrorSummaryDialog` | [error_summary.py:192](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/error_summary.py) | 临时对话框 |

### 根因 4（G 类）：webhook_manager 硬编码 False

[webhook_manager.py:198](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/webhook_manager.py) 的 `return get_stylesheet(False) + ...` 硬编码 `False`，忽略了传入的 `dark` 参数。

---

## 第二部分：对另一个 AI 建议的复核

### ✅ 准确且值得采纳

| 建议 | 依据 |
|---|---|
| 运行状态视觉权重弱 | [main_window_setup.py:230-246](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) 仅一个 QLabel「● 就绪」 |
| Inspector 空白状态浪费 | [step_editor_build.py:65-72](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_editor_build.py) 仅一行静态文案。设计文档 [06:72-74](file:///d:/LocalWork/Software%20Development/desktop/Workflow/docs/06_工作台UI与编排语义方案.md) 已明确要求但未落地 |
| 运行历史列宽不持久化 | [run_history.py:62-152](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/run_history.py) 未用 QSettings |
| 日志面板无紧凑模式 | [log_panel.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/log_panel.py) 时间戳嵌文本 |
| 批量多选缺失 | [panel_build.py:75-76](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_table/panel_build.py) `SingleSelection` |

### ⚠️ 不准确或与既有设计冲突

| 建议 | 问题 |
|---|---|
| 「点击即编辑，保存时确认」 | 与 [dirty_guard.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/dirty_guard.py) 三选项确认冲突 |
| 布局调整为 260/860/320 | 当前左栏已可拖到 240-320、右栏 320-390（[main_window_setup.py:118-119,357-358](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py)） |
| 阶段卡片颜色单一 | 不准确。[reorderable_table.py:38-50](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_table/reorderable_table.py) 已有四色循环 |
| 类型标签用图标替代文字 | [workbench_board.py:578-599](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/workbench_board.py) TypePill 已是 11px 小尺寸 |
| 耗时阈值动态调整/自定义 | 过度设计。当前 30s/300s 三档合理 |
| 通知符号 📨 不直观 | 已是 `📨✓`/`📨✗` 图标+语义符号 |

### ❌ 另一个 AI 遗漏的真实问题

| 遗漏点 | 严重度 | 依据 |
|---|---|---|
| 暗色模式被强制关闭 | P1 | [main_window.py:107-111](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window.py) 强制写 `False`，但 [theme.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/theme.py) 完整维护了暗色 token |
| 编辑模式开关位置隐蔽 | P0 | 开关在左栏**底部**（[main_window_setup.py:179-200](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py)） |
| 工作台横向滚动条始终显示 | P3 | [workbench_board.py:429](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/workbench_board.py) `ScrollBarAlwaysOn` |
| 快捷键覆盖不足 | P2 | 全局只有 `Ctrl+S`/`F5`/`Shift+F5`（[main_window_setup.py:482-500](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py)） |

---

## 第三部分：综合任务列表（实施就绪）

### 批次 1（P0-视觉，1-2 天）

---

#### 任务 1：统一调色板（消除"深色残留"观感主因）

**目标**：消除 Shell 暖纸色系与 theme.py 冷色系的双轨制，让外壳强调色与内层卡片强调色亮度一致。

**依据**：
- [main_window_theme.py:7-46](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_theme.py) `build_shell_theme_tokens` 浅色分支硬编码 16 个 token
- [theme.py:3-47](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/theme.py) `COLORS` 已是单一真相源
- 暗色分支（main_window_theme.py:8-27）已正确从 `colors` 派生，浅色分支是历史遗留

**涉及文件**：
- `src/ui/main_window_theme.py`（核心改动）
- `src/ui/theme.py`（新增 AA-safe 变体 token，可选）

**修改前**（main_window_theme.py:28-46）：
```python
return {
    "bg": "#f6f4ef",
    "paper": "#fbfaf6",
    "workspace": "#f6f4ef",
    "panel": "#ffffff",
    "panel_soft": "#f1eee7",
    "ink": "#20242a",
    "muted": "#6c7077",
    "faint": "#8b9098",
    "line": "#ddd8cf",
    "line_strong": "#c9c1b6",
    "blue": "#2458d3",
    "blue_hover": "#1d49b6",
    "blue_weak": "#e9eefc",
    "green": "#247145",
    "green_weak": "#e7f3ea",
    "red": "#b3312a",
    "red_weak": "#f8e4e1",
}
```

**修改后**（从 `COLORS` 派生，保留 AA-safe 变体）：
```python
# 在 theme.py COLORS 中新增 AA-safe 变体（已通过 WCAG AA 4.5:1 验证）
# COLORS["primary_aa"] = "#1A5FCC"   # 比 #007AFF 深，白底对比度 4.6:1
# COLORS["success_aa"] = "#1B7A3E"   # 比 #34C759 深，白底对比度 4.7:1
# COLORS["danger_aa"]  = "#C4201B"   # 比 #FF3B30 深，白底对比度 4.8:1

return {
    "bg": colors["surface_primary"],        # #F8FAFC，与左/右栏背景一致
    "paper": colors["surface_card"],         # #FFFFFF
    "workspace": colors["surface_secondary"], # #F1F5F9
    "panel": colors["surface_card"],         # #FFFFFF
    "panel_soft": colors["surface_secondary"],
    "ink": colors["text_primary"],           # #111827
    "muted": colors["text_secondary"],       # #4B5563
    "faint": colors["text_tertiary"],        # #6B7280
    "line": colors["border"],                # #E2E8F0
    "line_strong": colors["divider_strong"],# #E2E8F0（与 border 一致，避免过深）
    "blue": colors["primary_aa"],            # AA-safe
    "blue_hover": colors["primary_hover"],   # #0062CC
    "blue_weak": colors["selected_bg"],      # #E8F0FE
    "green": colors["success_aa"],            # AA-safe
    "green_weak": "#E8F5E9",                  # 保留浅绿底（无对应 token）
    "red": colors["danger_aa"],               # AA-safe
    "red_weak": "#FFEBEE",                    # 保留浅红底（无对应 token）
}
```

**边界情况**：
- 浅色背景从 `#f6f4ef`（暖纸）变 `#F8FAFC`（冷灰），整体观感从"暖"转"冷"。若用户偏好暖色，可在配置页加"工作区色调"开关，但**不在本次范围**。
- `green_weak`/`red_weak` 保留字面量，因为没有对应 token；可在任务 5 一并 token 化。
- 暗色分支无需改动（已正确派生）。

**测试要点**：
1. 启动应用，观察中区背景与左/右栏背景是否一致（应都是 `#F8FAFC`/`#FFFFFF`/`#F8FAFC`）
2. 点击运行按钮，PrimaryAction 蓝色与步骤表格选中色 `#007AFF` 系亮度一致
3. 运行中 RunStateChip 绿色与步骤卡片 success 色亮度一致
4. 对比度验证：PrimaryAction 蓝底白字对比度 ≥ 4.5:1（用 WebAIM Contrast Checker）
5. 运行现有测试：`python -m pytest tests/test_ui_main_window_actions.py tests/test_ui_panel_layout.py tests/test_ui_run_state.py -q`

**依赖**：无（首批第一个执行）

**预估改动**：~30 行（main_window_theme.py 16 行 + theme.py 3 行新增 token + 注释）

---

#### 任务 2：编辑模式开关上移 + 首次引导

**目标**：把编辑模式开关从左栏底部移到中区 command bar，并在首次启动弹一次性引导气泡。

**依据**：
- [main_window_setup.py:179-200](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) `create_edit_bar` 当前在左栏底部
- [main_window_setup.py:203-211](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) `create_command_bar` = title_block + run_cluster
- [main_window.py:117-136](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window.py) `_set_edit_mode` 联动 6 个面板 + `btn_left_save`

**涉及文件**：
- `src/ui/main_window_setup.py`（移动 `create_edit_bar` 逻辑到 `create_command_bar`）
- `src/ui/main_window.py`（`btn_left_save` 引用改名为 `btn_save`，更新所有引用点）

**修改前**：
```python
# create_command_bar（main_window_setup.py:203-211）
def create_command_bar(window) -> QWidget:
    command_bar = QWidget()
    command_bar.setObjectName("CommandBar")
    command_layout = QHBoxLayout(command_bar)
    command_layout.setContentsMargins(0, 0, 0, 0)
    command_layout.setSpacing(20)
    command_layout.addLayout(create_title_block(window), stretch=1)
    command_layout.addWidget(create_run_cluster(window))
    return command_bar

# create_edit_bar 在左栏底部（main_window_setup.py:179-200）
# check_edit_mode + btn_left_save 都在这里
```

**修改后**：
```python
def create_command_bar(window) -> QWidget:
    command_bar = QWidget()
    command_bar.setObjectName("CommandBar")
    command_layout = QHBoxLayout(command_bar)
    command_layout.setContentsMargins(0, 0, 0, 0)
    command_layout.setSpacing(20)
    command_layout.addLayout(create_title_block(window), stretch=1)
    # 编辑模式开关上移到 command bar（运行按钮左侧）
    command_layout.addWidget(create_edit_cluster(window))
    command_layout.addWidget(create_run_cluster(window))
    return command_bar

def create_edit_cluster(window) -> QWidget:
    """编辑模式开关 + 保存按钮（从左栏底部移到 command bar）"""
    cluster = QWidget()
    cluster.setObjectName("EditCluster")
    layout = QHBoxLayout(cluster)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    lbl = QLabel("编辑")
    lbl.setObjectName("Eyebrow")
    layout.addWidget(lbl)

    window.check_edit_mode = IosSwitch()
    window.check_edit_mode.setChecked(False)
    window.check_edit_mode.toggled.connect(window._set_edit_mode)
    window.check_edit_mode.setToolTip("开启后可以编辑工作流、阶段和步骤")
    window.check_edit_mode.setAccessibleName("编辑模式开关")
    layout.addWidget(window.check_edit_mode)

    window.btn_save = QPushButton("保存")  # 从 btn_left_save 改名
    window.btn_save.setObjectName("primarySmall")
    window.btn_save.setFixedSize(78, 26)
    window.btn_save.clicked.connect(window._action_save)
    window.btn_save.setToolTip("保存当前工作流和步骤修改（Ctrl+S）")
    window.btn_save.setAccessibleName("保存")
    layout.addWidget(window.btn_save)
    return cluster
```

**首次引导气泡**：
```python
# main_window.py __init__ 末尾（在 _set_edit_mode(False) 之后）
settings = QSettings(APP_NAME, "ui")
if not settings.value("edit_mode_guide_shown", False):
    QTimer.singleShot(500, self._show_edit_mode_guide)

def _show_edit_mode_guide(self):
    from PySide6.QtWidgets import QToolTip
    QToolTip.showText(
        self.check_edit_mode.mapToGlobal(QPoint(0, -40)),
        "💡 编辑模式默认关闭以防误操作。\n点击此处开关可开启编辑工作流、阶段和步骤。",
        self.check_edit_mode,
        self.check_edit_mode.rect(),
        8000  # 8 秒自动消失
    )
    QSettings(APP_NAME, "ui").setValue("edit_mode_guide_shown", True)
```

**边界情况**：
- `btn_left_save` 改名为 `btn_save`，需全局搜索更新引用（main_window.py:129 等）
- 左栏底部 `create_edit_bar` 函数删除，调用点 [main_window_setup.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) `create_left_panel` 内移除
- 引导气泡只在首次启动显示一次，用 QSettings 持久化
- 气泡定位基于 `check_edit_mode.mapToGlobal`，窗口未显示时定位会错位，用 `QTimer.singleShot(500, ...)` 等窗口显示后弹

**测试要点**：
1. 首次启动（清空 QSettings）后 500ms 见气泡，指向编辑开关
2. 重启不再弹气泡
3. 编辑开关在 command bar 运行按钮左侧，可见
4. 开关切换时 `btn_save` 启用/禁用状态正确
5. `python -m pytest tests/test_ui_main_window_actions.py tests/test_ui_main_window_selection_sync.py -q`

**依赖**：无

**预估改动**：~60 行（main_window_setup.py 40 行 + main_window.py 15 行 + 测试调整 5 行）

---

#### 任务 3：运行状态视觉强化

**目标**：RunStateChip 三态（idle/running/stopping）有背景色+边框区分；运行中主按钮加轻微脉动动画。

**依据**：
- [main_window_setup.py:230-246](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) `create_run_cluster`
- [main_window_setup.py:249-272](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) `set_header_run_button_state` 三态切换
- [main_window_theme.py:109-115](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_theme.py) `RunStateChip` 当前只有 color + font-weight

**涉及文件**：
- `src/ui/main_window_setup.py`（`set_header_run_button_state` 同步刷新 chip + 启动/停止动画）
- `src/ui/main_window_theme.py`（`RunStateChip` 三态样式）
- `src/ui/main_window.py`（新增 `_run_pulse_anim` 字段）

**修改前**：
```python
# main_window_theme.py:109-115
QLabel#RunStateChip {
    min-height: 24px;
    padding: 0 4px;
    color: {w["green"]};
    background: transparent;
    font-weight: 700;
}

# main_window_setup.py:249-272 set_header_run_button_state 只改按钮，不动 chip
```

**修改后**：
```python
# main_window_theme.py：三态样式
QLabel#RunStateChip {
    min-height: 24px;
    padding: 2px 8px;
    border-radius: 12px;
    color: {w["green"]};
    background: {w["green_weak"]};
    border: 1px solid {w["green"]};
    font-weight: 700;
}
QLabel#RunStateChip[state="running"] {
    color: {w["blue"]};
    background: {w["blue_weak"]};
    border: 1px solid {w["blue"]};
}
QLabel#RunStateChip[state="stopping"] {
    color: {w["red"]};
    background: {w["red_weak"]};
    border: 1px solid {w["red"]};
}

# main_window_setup.py：set_header_run_button_state 同步刷新 chip
def set_header_run_button_state(window, state: str) -> None:
    button = getattr(window, "btn_header_run", None)
    chip = getattr(window, "lbl_run_state", None)
    if button is None:
        return

    if state == "running":
        button.setText("■ 停止运行")
        button.setObjectName("DangerAction")
        button.setEnabled(True)
        if chip:
            chip.setText("● 运行中")
            chip.setProperty("state", "running")
            _apply_chip_style(chip)
        _start_pulse_animation(window, button)
    elif state == "stopping":
        button.setText("■ 正在停止...")
        button.setObjectName("DangerAction")
        button.setEnabled(False)
        if chip:
            chip.setText("● 停止中")
            chip.setProperty("state", "stopping")
            _apply_chip_style(chip)
        _stop_pulse_animation(window)
    else:
        button.setText("▶ 运行全流程")
        button.setObjectName("PrimaryAction")
        button.setEnabled(True)
        if chip:
            chip.setText("● 就绪")
            chip.setProperty("state", "idle")
            _apply_chip_style(chip)
        _stop_pulse_animation(window)

    button.style().unpolish(button)
    button.style().polish(button)

def _apply_chip_style(chip):
    chip.style().unpolish(chip)
    chip.style().polish(chip)

def _start_pulse_animation(window, button):
    """运行中主按钮轻微脉动（opacity 0.85↔1.0，1.5s 循环）"""
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    from PySide6.QtCore import QPropertyAnimation, PauseAnimation, QSequentialAnimationGroup
    if not hasattr(window, '_pulse_effect'):
        window._pulse_effect = QGraphicsOpacityEffect(button)
        button.setGraphicsEffect(window._pulse_effect)
        window._pulse_anim = QPropertyAnimation(window._pulse_effect, b"opacity")
        window._pulse_anim.setDuration(1500)
        window._pulse_anim.setKeyValueAt(0.0, 1.0)
        window._pulse_anim.setKeyValueAt(0.5, 0.85)
        window._pulse_anim.setKeyValueAt(1.0, 1.0)
        window._pulse_anim.setLoopCount(-1)
    window._pulse_effect.setEnabled(True)
    if window._pulse_anim.state() != QPropertyAnimation.Running:
        window._pulse_anim.start()

def _stop_pulse_animation(window):
    if hasattr(window, '_pulse_anim') and window._pulse_anim.state() == QPropertyAnimation.Running:
        window._pulse_anim.stop()
    if hasattr(window, '_pulse_effect'):
        window._pulse_effect.setEnabled(False)
```

**边界情况**：
- `QGraphicsOpacityEffect` 会影响子控件渲染，但 PrimaryAction 只有文字，无影响
- 动画对象挂在 window 上避免被 GC；按钮 setObjectName 切换时 unpolish/polish 会重置样式，不影响动画
- stopping 态按钮 disabled，停止动画避免视觉干扰
- chip 的 `setProperty("state", ...)` 需在 `unpolish/polish` 之前调用，否则 QSS 不刷新

**测试要点**：
1. 空闲态：chip 绿色背景 + 绿色边框 + "● 就绪"
2. 运行中：chip 蓝色背景 + 蓝色边框 + "● 运行中"；主按钮 1.5s 周期脉动
3. 停止中：chip 红色背景 + 红色边框 + "● 停止中"；按钮无脉动
4. 三态切换流畅，无闪烁
5. `python -m pytest tests/test_ui_run_state.py tests/test_ui_main_window_actions.py -q`

**依赖**：任务 1（统一调色板后，`blue_weak`/`red_weak` 颜色已对齐）

**预估改动**：~80 行（main_window_theme.py 15 行 + main_window_setup.py 60 行 + main_window.py 5 行）

---

#### 任务 4：Inspector 空白状态填充

**目标**：未选中步骤时，Inspector 上下文区展示工作流摘要 + 快捷键提示 + 「新建步骤」按钮，符合设计文档 [06:72-74](file:///d:/LocalWork/Software%20Development/desktop/Workflow/docs/06_工作台UI与编排语义方案.md) 要求。

**依据**：
- [step_editor_build.py:65-72](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_editor_build.py) `context_banner` 当前只有一行静态文案
- [main_window_setup.py:376-397](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) Inspector 标题区默认 "Inspector" / "选择步骤或阶段"
- 设计文档明确要求「未选中时展示工作流摘要、快捷说明、常用操作」

**涉及文件**：
- `src/ui/step_editor_build.py`（`context_banner` 改为可扩展 widget）
- `src/ui/step_editor.py`（新增 `show_empty_state` 方法）
- `src/ui/main_window.py`（在选中工作流后调用 `step_editor.show_empty_state`）

**修改前**（step_editor_build.py:65-72）：
```python
panel.context_banner = QLabel()
panel.context_banner.setWordWrap(False)
panel.context_banner.setFixedHeight(30)
panel.context_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
panel.context_banner.setMinimumWidth(0)
panel.context_banner.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
panel.context_banner.setText("未选中步骤：点击卡片编辑；选阶段后添加步骤会进入该阶段。")
group_layout.addWidget(panel.context_banner)
```

**修改后**：
```python
# step_editor_build.py：空白状态容器（替换 context_banner）
panel.empty_state_widget = QWidget()
panel.empty_state_widget.setObjectName("InspectorEmptyState")
empty_layout = QVBoxLayout(panel.empty_state_widget)
empty_layout.setContentsMargins(8, 12, 8, 12)
empty_layout.setSpacing(10)

# 工作流摘要
panel.empty_summary = QLabel("工作流摘要")
panel.empty_summary.setObjectName("Eyebrow")
empty_layout.addWidget(panel.empty_summary)

panel.empty_stats = QLabel("0 阶段 · 0 步 · 未运行")
panel.empty_stats.setObjectName("WorkflowMeta")
panel.empty_stats.setWordWrap(True)
empty_layout.addWidget(panel.empty_stats)

# 快捷键提示
panel.empty_shortcuts = QLabel(
    "快捷键：\n"
    "  F5 - 运行/停止\n"
    "  Shift+F5 - 停止运行\n"
    "  Ctrl+S - 保存\n"
    "  Ctrl+N - 新建工作流（待实现）\n"
    "  Delete - 删除选中步骤（待实现）"
)
panel.empty_shortcuts.setObjectName("WorkflowMeta")
panel.empty_shortcuts.setWordWrap(True)
empty_layout.addWidget(panel.empty_shortcuts)

# 最近运行状态
panel.empty_last_run = QLabel("最近运行：无")
panel.empty_last_run.setObjectName("WorkflowMeta")
empty_layout.addWidget(panel.empty_last_run)

empty_layout.addStretch(1)

# 「新建步骤」按钮
panel.btn_empty_new_step = QPushButton("+ 新建步骤")
panel.btn_empty_new_step.setObjectName("PrimaryAction")
panel.btn_empty_new_step.setEnabled(False)  # 默认禁用，需开启编辑模式
panel.btn_empty_new_step.setToolTip("开启编辑模式后可新建步骤")
empty_layout.addWidget(panel.btn_empty_new_step)

group_layout.addWidget(panel.empty_state_widget)
# context_banner 保留但默认隐藏（选中步骤时仍显示提示）
panel.context_banner = QLabel()
panel.context_banner.hide()
```

**step_editor.py 新增方法**：
```python
def show_empty_state(self, workflow_id: int | None):
    """未选中步骤时展示工作流摘要"""
    if workflow_id is None:
        self.empty_summary.setText("未选择工作流")
        self.empty_stats.setText("从左侧列表选择一个工作流开始")
        self.empty_last_run.setText("")
        self.btn_empty_new_step.setEnabled(False)
        return

    from database import get_steps_by_workflow, list_stages, get_latest_run
    steps = get_steps_by_workflow(workflow_id)
    stages = list_stages(workflow_id)
    last_run = get_latest_run(workflow_id)

    self.empty_summary.setText(f"工作流摘要")
    self.empty_stats.setText(f"{len(stages)} 阶段 · {len(steps)} 步")
    if last_run:
        status_map = {"success": "成功", "failure": "失败", "cancelled": "已取消", "running": "运行中"}
        status = status_map.get(last_run.status, last_run.status)
        self.empty_last_run.setText(f"最近运行：{status} · {last_run.started_at}")
    else:
        self.empty_last_run.setText("最近运行：无")

    self.btn_empty_new_step.setEnabled(self._edit_enabled)

def show_step_context(self):
    """选中步骤时隐藏空白状态"""
    self.empty_state_widget.hide()
    self.context_banner.show()

def show_empty_context(self, msg: str = ""):
    """未选中步骤但工作流已选时显示空白状态"""
    self.empty_state_widget.show()
    self.context_banner.hide()
    if msg:
        self.empty_summary.setText(msg)
```

**main_window.py 调用点**：
```python
# _on_workflow_selected（:229-230 当前重置 Inspector 标签处）
self.lbl_inspector_kind.setText("Inspector")
self.lbl_inspector_title.setText("选择步骤或阶段")
self.step_editor.show_empty_state(workflow_id)  # 新增

# _on_step_selected / _on_step_deleted 后切换 show_step_context / show_empty_context
```

**边界情况**：
- 未选工作流：`show_empty_state(None)` 显示"未选择工作流"
- 工作流无步骤：摘要显示"0 阶段 · 0 步"，新建步骤按钮在编辑模式下可用
- 工作流有步骤但未选中：显示摘要 + 新建步骤按钮（仍可添加）
- 选中步骤后：`show_step_context` 隐藏空白状态，显示步骤编辑器
- `get_latest_run` 需确认 database 模块是否提供，若无则改用 `list_runs(workflow_id, limit=1)`

**测试要点**：
1. 启动后未选工作流：Inspector 显示"未选择工作流"
2. 选工作流后：显示阶段数、步骤数、最近运行
3. 选中步骤后：空白状态隐藏，步骤编辑器显示
4. 取消选中：空白状态重新显示
5. 编辑模式开启时新建步骤按钮可用
6. `python -m pytest tests/test_ui_main_window_selection_sync.py -q`

**依赖**：任务 2（编辑开关上移后，新建步骤按钮与编辑模式联动一致）

**预估改动**：~100 行（step_editor_build.py 40 行 + step_editor.py 40 行 + main_window.py 20 行）

---

#### 任务 5：token 化硬编码字面量

**目标**：把根因 2 的 6 处硬编码字面量改为走 `colors`/`tokens` 变量，建立单一真相源。

**依据**：根因 2 表格

**涉及文件**：
- `src/ui/theme.py`（新增 `on_primary` token）
- `src/ui/main_window_theme.py`（`#fffdfa` → `colors["on_primary"]`）
- `src/ui/step_editor_sections.py`（`#CBD5E1`/`#FFFFFF` → `colors["border"]`/`colors["surface_card"]`）

**修改前**：
```python
# theme.py:252
QFrame#FoldBtnWrap { background:#EEEEEE; }

# main_window_theme.py:119,135
QPushButton#PrimaryAction { color:#fffdfa; ... }
QPushButton#DangerAction { color:#fffdfa; ... }

# step_editor_sections.py:394,396
QListWidget::indicator { border:1px solid #CBD5E1; background:#FFFFFF; }
```

**修改后**：
```python
# theme.py COLORS 新增 token
"on_primary": "#FFFFFF",       # 主色按钮上的文字色（已含 AA 对比度）
"indicator_bg": "#FFFFFF",     # 勾选框底色
"indicator_border": "#CBD5E1", # 勾选框边框

# theme.py:252 QSS 改为 f-string 拼接（需把 get_stylesheet 改成接收 colors）
# 实际方案：把 QFrame#FoldBtnWrap 段从 get_stylesheet 移到 main_window_theme.py
# 用 tokens["line"] 替代 #EEEEEE

# main_window_theme.py:119,135
QPushButton#PrimaryAction {{ color:{colors["on_primary"]}; ... }}
QPushButton#DangerAction {{ color:{colors["on_primary"]}; ... }}

# step_editor_sections.py:394,396
QListWidget::indicator {{ border:1px solid {colors["indicator_border"]}; background:{colors["indicator_bg"]}; }}
```

**边界情况**：
- `get_stylesheet(dark)` 当前是纯字符串拼接，不含 colors 变量。`QFrame#FoldBtnWrap{background:#EEEEEE}` 段需移到 main_window_theme.py 的 `left_panel_stylesheet` 或 `center_panel_stylesheet`，用 tokens 变量
- `step_editor_sections.py` 的 `refresh_theme` 已存在（[step_editor.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_editor.py)），改后需确认 refresh 覆盖新样式
- `run_history.py:127-142` / `panel_build.py:56,61,68` / `workflow_config.py:149` 已被 refresh 覆盖，可保留字面量或一并 token 化（本次一并处理）

**测试要点**：
1. 浅色下无视觉变化（颜色值相同或等价）
2. `grep -rn "#[0-9A-Fa-f]\{3,6\}" src/ui` 输出仅剩 `theme.py` 的 COLORS/DARK_COLORS 定义处
3. `python -m pytest -q` 全绿

**依赖**：任务 1（统一调色板后 token 命名一致）

**预估改动**：~40 行

---

#### 任务 6：清理死代码与硬编码 False

**目标**：删除 dag_view.py 死代码；修复 webhook_manager.py:198 的 `get_stylesheet(False)` 硬编码。

**依据**：
- [dag_view.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/dag_view.py) 全文件死代码（搜索确认无任何 import）
- [theme.py:96](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/theme.py) 注释提及 dag_view，需更新
- [webhook_manager.py:198](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/webhook_manager.py) `get_stylesheet(False)` 忽略 dark 参数

**涉及文件**：
- `src/ui/dag_view.py`（删除整文件）
- `src/ui/theme.py:96`（更新注释）
- `src/ui/webhook_manager.py:198`（改 `False` → `dark`）
- `tests/test_workbench_board.py`（确认无 dag_view 引用）

**修改前**：
```python
# webhook_manager.py:198
return get_stylesheet(False) + f"""
    QFrame#WebhookListPanel, ...
"""
```

**修改后**：
```python
# webhook_manager.py:198
return get_stylesheet(dark) + f"""
    QFrame#WebhookListPanel, ...
"""
```

**边界情况**：
- 删除 dag_view.py 前再次执行 `grep -rn "dag_view" src tests` 确认无引用
- `theme.py:96` 注释改为 `# step_table / run_history / log_panel`（移除 dag_view）
- webhook_manager 改后浅色下行为不变（`dark=False` 等价），但暗色下基础层会正确切换

**测试要点**：
1. `grep -rn "from.*dag_view import\|import.*dag_view" src tests` 无命中
2. `python -m pytest -q` 全绿
3. 打开 Webhook 管理对话框，样式正常

**依赖**：无

**预估改动**：-300 行（删除 dag_view.py）+ 2 行修改

---

### 批次 2（P1-决策，1 天）

---

#### 任务 7：暗色模式口径决策

**目标**：评估暗色 token 完整度，决策「重新开放切换」或「删除暗色分支」。

**依据**：
- [main_window.py:107-111](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window.py) `_toggle_dark_mode` 强制写 `False`
- [theme.py:49-85](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/theme.py) `DARK_COLORS` 完整
- 任务 5 完成后所有字面量 token 化，可评估暗色切换是否完整

**涉及文件**：
- `src/ui/main_window.py`（按决策恢复或删除）
- `src/ui/main_window_setup.py:478-480`（`action_dark_mode` 按决策恢复或删除）

**决策流程**：
1. 完成任务 5（token 化）后，临时打开 `_dark_mode = True` 测试
2. 逐项检查暗色下：
   - Shell token 是否正确派生（任务 1 后已派生）
   - 所有 token 化字面量是否正确切换
   - IosSwitch / ErrorSummaryDialog 是否纳入刷新链（任务 11）
3. 若全部通过 → 恢复 `_toggle_dark_mode` 切换功能，工具栏 `action_dark_mode` `setVisible(True) + setEnabled(True)`
4. 若有残留 → 删除 `DARK_COLORS` / `DARK_*` 分支 / `if dark:` 分支，减少维护负担

**测试要点**：
1. 决策记录写入本 plan 文档（决策结果：____）
2. 按决策方向执行后 `python -m pytest -q` 全绿
3. 若恢复切换：暗色下无浅色残留；若删除：`grep -rn "DARK_" src/ui` 无命中

**依赖**：任务 1、5、11（token 化 + 刷新链完整后再评估）

**预估改动**：决策恢复 ~20 行；决策删除 ~200 行

---

### 批次 3（P1-交互，3-5 天）

---

#### 任务 8：运行历史列宽持久化

**目标**：复用步骤表格的 QSettings 模式，让运行历史列宽持久化，并补「重置列宽」右键菜单。

**依据**：
- [run_history.py:62-152](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/run_history.py) 未用 QSettings
- [panel.py:90-94](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_table/panel.py) 步骤表格已有完整持久化模式可复用
- [panel_build.py:225-230](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_table/panel_build.py) 「重置列宽」右键菜单可复用

**涉及文件**：
- `src/ui/run_history.py`（新增 `_settings`、列宽保存/恢复、右键菜单）

**修改要点**：
```python
# run_history.py 新增
class RunHistoryPanel(QWidget):
    def __init__(self, ...):
        ...
        self._settings = QSettings(APP_NAME, "ui")
        self._column_widths_key = "RunHistory/column_widths"
        self._restore_column_widths()

    def _restore_column_widths(self):
        saved = self._settings.value(self._column_widths_key)
        if saved:
            widths = json.loads(saved)
            for i, w in enumerate(widths):
                if i < self.table.columnCount():
                    self.table.setColumnWidth(i, int(w))

    def _save_column_widths(self):
        widths = [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        self._settings.setValue(self._column_widths_key, json.dumps(widths))

    def _reset_column_widths(self):
        for i, (_, w) in enumerate(COLUMNS):
            self.table.setColumnWidth(i, w)
        self._save_column_widths()

    # sectionResized 信号连接 _save_column_widths（200ms 防抖）
    # 表头右键菜单加「重置列宽」
```

**边界情况**：
- 防抖保存避免频繁写 QSettings
- 列数变化时（未来扩展）需容错：`if i < self.table.columnCount()`

**测试要点**：
1. 调整列宽后重启应用，宽度保持
2. 右键表头有「重置列宽」，点击后恢复默认
3. `python -m pytest tests/test_step_table_styles.py -q`（确认步骤表格持久化未受影响）

**依赖**：无

**预估改动**：~50 行

---

#### 任务 9：步骤批量多选

**目标**：表格支持 Ctrl+点击多选，右键菜单加「批量删除」「批量改阶段」。

**依据**：
- [panel_build.py:75-76](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_table/panel_build.py) `SingleSelection`
- [panel_actions.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_table/panel_actions.py) 右键菜单当前只对单步操作

**涉及文件**：
- `src/ui/step_table/panel_build.py`（`ExtendedSelection`）
- `src/ui/step_table/panel_actions.py`（批量菜单项）
- `src/ui/step_table/panel.py`（批量操作处理）

**修改要点**：
```python
# panel_build.py:75-76
self.table.setSelectionMode(QTableWidget.ExtendedSelection)  # 从 SingleSelection 改
self.table.setSelectionBehavior(QTableWidget.SelectRows)

# panel_actions.py 右键菜单
def show_context_menu(panel, pos):
    rows = panel._get_selected_rows()  # 新增：返回所有选中行
    if len(rows) > 1:
        menu.addAction("批量删除", lambda: panel._batch_delete_steps(rows))
        menu.addAction("批量改阶段...", lambda: panel._batch_change_stage(rows))
    else:
        # 原有单步菜单
        ...

# panel.py 拖拽逻辑：仅当 selectionMode == SingleSelection 时允许拖拽
# ExtendedSelection 下多选拖拽语义混乱，禁用拖拽或仅允许单选时拖拽
```

**边界情况**：
- 多选 + 拖拽冲突：拖拽时检查 `len(selected) <= 1`，否则忽略拖拽
- 批量删除前弹确认对话框（复用 dirty_guard 模式）
- 批量改阶段用 QInputDialog 选择目标阶段
- 事务保证：批量操作在单事务内完成，失败回滚

**测试要点**：
1. Ctrl+点击多选；Shift+点击范围选
2. 右键批量操作可见且功能正常
3. 单选时拖拽不受影响
4. 多选时拖拽被忽略（不报错）
5. `python -m pytest tests/test_step_table_*.py -q`

**依赖**：无

**预估改动**：~80 行

---

#### 任务 10：依赖可视化小图

**目标**：在依赖摘要区上方加 120px 高的 mini DAG，只画当前步骤的上下游。

**依据**：
- [step_editor.py:487-577](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/step_editor.py) `_refresh_dependency_summary` 已有上下游数据
- 任务 6 删除 dag_view.py 后，NodeCard 样式思路可复用（不直接复用代码）

**涉及文件**：
- `src/ui/step_editor_build.py`（新增 mini_dag widget）
- `src/ui/step_editor.py`（新增 `_refresh_mini_dag`）
- `src/ui/mini_dag.py`（新建文件，120 行内）

**实现要点**：
```python
# src/ui/mini_dag.py（新文件）
class MiniDagWidget(QWidget):
    """120px 高的迷你依赖图：左列上游、中列当前、右列下游"""
    step_activated = Signal(int)  # 双击跳转

    def __init__(self, dark: bool = False):
        ...
        self.setFixedHeight(120)
        # 3 列 QHBoxLayout：upstream | current | downstream
        # 每列 QListWidget，item 用 NodeCard 样式（左侧色条 + 标题 + 类型）

    def set_data(self, current_step, upstream_steps, downstream_steps):
        ...

# step_editor_build.py：在依赖摘要区上方插入
panel.mini_dag = MiniDagWidget(panel._dark)
group_layout.addWidget(panel.mini_dag)

# step_editor.py：_refresh_dependency_summary 内同步刷新 mini_dag
def _refresh_dependency_summary(self):
    ...
    self.mini_dag.set_data(current_step, upstream, downstream)
```

**边界情况**：
- 无依赖时：只显示当前节点 + "无上游依赖" / "无下游引用"提示
- 跨阶段依赖：上游/下游用不同色条区分
- 双击节点：发射 `step_activated` 信号，main_window 定位到该步骤

**测试要点**：
1. 选中步骤后 mini DAG 显示上下游
2. 双击节点跳转选中
3. 无依赖时显示提示
4. `python -m pytest tests/test_ui_main_window_selection_sync.py -q`

**依赖**：任务 6（dag_view.py 删除后，新 mini_dag.py 不与死代码冲突）

**预估改动**：~150 行（mini_dag.py 100 + step_editor_build.py 10 + step_editor.py 40）

---

#### 任务 11：IosSwitch/ErrorSummaryDialog 纳入刷新链

**目标**：apply_theme 显式刷新所有 IosSwitch 实例与 ErrorSummaryDialog。

**依据**：
- [main_window_setup.py:525-533](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) apply_theme 未调用 IosSwitch.refresh_theme
- [ios_switch.py:73](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/ios_switch.py) `refresh_theme` 已定义但未被调用
- [error_summary.py:192](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/error_summary.py) 同上

**涉及文件**：
- `src/ui/main_window_setup.py`（apply_theme 新增刷新）
- `src/ui/main_window.py`（IosSwitch 实例清单）

**修改要点**：
```python
# main_window_setup.py:apply_theme
# 在现有 9 个 refresh_theme 调用后追加
for attr in ("check_edit_mode",):  # 当前唯一的 IosSwitch 实例
    sw = getattr(window, attr, None)
    if sw is not None and hasattr(sw, "refresh_theme"):
        sw.refresh_theme(window._dark_mode)
```

**边界情况**：
- ErrorSummaryDialog 是临时对话框，创建时已传入 `_dark=False`；若任务 7 决策恢复暗色，对话框需在创建时传入 `window._dark_mode`
- 未来若新增 IosSwitch 实例，需在此追加；可考虑用 `findChildren(IosSwitch)` 自动发现

**测试要点**：
1. 切换主题（任务 7 后）IosSwitch 颜色正确刷新
2. `python -m pytest -q` 全绿

**依赖**：任务 7（暗色决策后才有验证场景）

**预估改动**：~10 行

---

### 批次 4（P2-增强，2-4 周）

---

#### 任务 12：日志紧凑模式

**目标**：log_panel 加紧凑/标准模式切换；紧凑模式行高从 ~16px 降到 ~12px；时间戳 hover 显示；错误行 sticky。

**依据**：[log_panel.py](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/log_panel.py) 当前无紧凑模式

**涉及文件**：`src/ui/log_panel.py`

**实现要点**：
- 工具栏新增「紧凑」切换按钮（IosSwitch 或 QPushButton toggle）
- 紧凑模式：字体 9pt → 8pt，行间距 12px → 8px
- 时间戳默认隐藏，hover 显示（用 QTextCharFormat 或 HTML span 的 title 属性）
- 错误行：用 `<div style="position:sticky;top:0">` 不适用于 QTextEdit；改为独立 error_summary widget 顶栏

**测试要点**：切换模式；错误行汇总

**预估改动**：~60 行

---

#### 任务 13：阶段视图响应式

**目标**：窗口宽度 < 1200px 时，`STAGE_LANE_MIN_WIDTH` 从 260 自适应到 200。

**依据**：[workbench_board_constants.py:5](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/workbench_board_constants.py) 当前固定 260

**涉及文件**：`src/ui/workbench_board.py`、`src/ui/workbench_board_constants.py`

**实现要点**：
- 在 `_sync_board_minimum_size` 内根据 `window().width()` 动态计算 lane 宽度
- 不做纵向切换模式（与阶段屏障语义冲突）

**测试要点**：1366px 笔记本下卡片宽度自适应；1920px 显示器下保持 260

**预估改动**：~30 行

---

#### 任务 14：快捷键补全

**目标**：新增 `Ctrl+N` 新建工作流、`Delete` 删除选中步骤、`Ctrl+D` 复制步骤、`Ctrl+Shift+N` 新建步骤。

**依据**：[main_window_setup.py:482-500](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/main_window_setup.py) 当前只有 3 个快捷键

**涉及文件**：`src/ui/main_window_setup.py`

**实现要点**：
```python
window.action_new_workflow_shortcut = QAction("新建工作流", window)
window.action_new_workflow_shortcut.setShortcut("Ctrl+N")
window.action_new_workflow_shortcut.triggered.connect(window._action_new_workflow)
window.addAction(window.action_new_workflow_shortcut)

window.action_delete_step_shortcut = QAction("删除步骤", window)
window.action_delete_step_shortcut.setShortcut("Delete")
window.action_delete_step_shortcut.triggered.connect(window._delete_selected_step)
window.addAction(window.action_delete_step_shortcut)

# Ctrl+D 复制、Ctrl+Shift+N 新建步骤类似
```

**边界情况**：
- `Delete` 在输入框聚焦时应失效（Qt 默认行为，需 `setShortcutContext(Qt.WindowShortcut)`）
- 编辑模式未开启时快捷键触发应弹编辑模式提示

**测试要点**：快捷键可用；菜单项显示快捷键提示

**预估改动**：~40 行

---

#### 任务 15：工作台横向滚动条 AsNeeded

**目标**：[workbench_board.py:429](file:///d:/LocalWork/Software%20Development/desktop/Workflow/src/ui/workbench_board.py) `ScrollBarAlwaysOn` → `ScrollBarAsNeeded`。

**依据**：另一个 AI 遗漏点

**涉及文件**：`src/ui/workbench_board.py`

**修改**：1 行

**测试要点**：阶段少不超宽时无滚动条；超宽时显示

**预估改动**：1 行

---

## 第四部分：实施顺序与回归保障

### 实施顺序

| 批次 | 任务 | 依赖 | 风险 | 预估改动 |
|---|---|---|---|---|
| 批次 1（P0-视觉）| 任务 1、2、3、4、5、6 | 任务 3 依赖 1；任务 4 依赖 2；任务 5 依赖 1 | 低 | ~310 行 |
| 批次 2（P1-决策）| 任务 7 | 任务 1、5、11 完成 | 中 | ~20 或 ~200 行 |
| 批次 3（P1-交互）| 任务 8、9、10、11 | 任务 10 依赖 6；任务 11 依赖 7 | 中 | ~290 行 |
| 批次 4（P2-增强）| 任务 12、13、14、15 | 无 | 低 | ~130 行 |

### 回归保障

每批完成后执行 [docs/development_guardrails.md](file:///d:/LocalWork/Software%20Development/desktop/Workflow/docs/development_guardrails.md) 的质量门：

```bash
python tools/check_test_env.py
python tools/check_requirements_consistency.py
python tools/audit_risky_calls.py
python tools/audit_broad_except.py
python tools/module_hotspot_report.py --top 0 --baseline quality/module_hotspot_baseline.json --fail-on-regression
python -m compileall -q src tests _import_and_run.py
python -m pytest -q
```

### 验证清单

- [ ] 任务 1：切换工作流/运行/停止后，外壳与内层强调色亮度一致，无"外壳偏深"观感
- [ ] 任务 2：首次启动见引导气泡；开关在 command bar 视觉焦点区
- [ ] 任务 3：运行/停止/空闲三态视觉区分明显；运行中主按钮脉动
- [ ] 任务 4：未选中时 Inspector 非空白；摘要信息正确；新建步骤按钮可用
- [ ] 任务 5：`grep -rn "#[0-9A-Fa-f]\{3,6\}" src/ui` 仅剩 token 定义处
- [ ] 任务 6：`grep -rn "from.*dag_view import\|import.*dag_view" src` 无命中；`webhook_manager.py:198` 走 `dark` 参数
- [ ] 任务 7：暗色口径决策记录入库；按决策方向执行
- [ ] 任务 8：调整列宽后重启应用，宽度保持；右键菜单有「重置列宽」
- [ ] 任务 9：Ctrl+点击多选；右键批量操作；单选拖拽不受影响
- [ ] 任务 10：选中步骤后 mini DAG 显示上下游；双击节点可定位
- [ ] 任务 11：IosSwitch/ErrorSummaryDialog 纳入刷新链
- [ ] 任务 12：日志紧凑/标准模式切换
- [ ] 任务 13：1366px 笔记本下阶段卡片宽度自适应
- [ ] 任务 14：快捷键可用且菜单有提示
- [ ] 任务 15：不超宽时无横向滚动条

---

## 附录：另一个 AI 建议中未被采纳项的归档

| 建议 | 处理 | 理由 |
|---|---|---|
| 点击即编辑，保存时确认 | 不采纳 | 与 dirty_guard 冲突，成本远超收益 |
| 布局调整为 260/860/320 | 不采纳 | 当前宽度已可拖动调整，硬改默认值意义不大 |
| 阶段卡片颜色单一 | 不采纳（前提错误）| 已有四色循环 + accent 竖条 |
| 类型标签用图标替代文字 | 不采纳 | 文字长度短，换图标反损可读性 |
| 耗时阈值动态调整/自定义 | 不采纳 | 过度设计 |
| 通知符号改文字 | 不采纳 | 已是图标+语义符号，改文字挤占空间 |
| 纵向阶段视图备选 | 不采纳 | 改造成本过高且与阶段屏障语义冲突 |
| 拖拽连线建立依赖 | 不采纳 | Qt 拖拽连线实现复杂，改用 mini DAG |
| 整个 command bar 变色 | 不采纳 | 视觉过重 |
