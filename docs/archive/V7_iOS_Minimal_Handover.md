# 工作流管理系统 (Workflow Manager) - V7 iOS 极简版交接文档

## 1. 项目基础说明

### 1.1 项目简介
**项目名称**：工作流管理系统 (AI Workflow Manager)
**核心用途**：用于编排、管理和执行基于 Python/Excel/PowerBI 的自动化数据处理工作流。
**技术架构**：
- **语言**：Python 3.x
- **GUI 框架**：PySide6 (Qt for Python)
- **设计工具**：Pencil (用于 UI 原型设计，文件：`designs/ios_minimal_focus.pen`)
- **数据存储**：SQLite (通过 `src/database.py` 管理)

### 1.2 核心功能已实现
- **工作流管理**：CRUD（增删改查）、复制、重命名。
- **步骤编排**：支持 Python 脚本、Excel 刷新、Power BI 刷新等多种步骤类型；支持拖拽排序；支持配置前置依赖（DAG）。
- **DAG 可视化**：自动生成有向无环图，展示步骤依赖关系，支持泳道布局（按用途阶段 S1, S2...）。
- **运行控制**：全流程运行、断点运行、单步运行、失败重试。
- **日志系统**：实时日志捕获（stdout/stderr）、运行历史记录。

### 1.3 本次优化目标 (V7 iOS Minimal)
将原本标准的桌面软件界面（Standard Qt 风格）彻底改造为 **macOS/iOS 原生极简风格**。
- **视觉风格**：全白背景 (`#FFFFFF` & `#F6F7F8`)、去除多余边框、大圆角 (`16px-20px`)、Apple Blue 主色 (`#007AFF`)。
- **交互体验**：三栏式布局，扁平化层级，更现代的视觉反馈。

---

## 2. 已完成的功能改动详情 (V7 Redesign)

本次更新主要集中在 `src/ui/` 目录下的 UI 渲染层，核心逻辑层（`src/core/`, `src/database.py`）保持稳定。

### 2.1 全局设计系统 (Design System)
*   **文件**：`src/ui/theme.py`
*   **改动详情**：
    *   **色彩 (Colors)**：
        *   `primary`: 改为 Apple Blue (`#007AFF`)。
        *   `background`: 全局背景改为纯白 (`#FFFFFF`)。
        *   `surface`: 卡片/容器背景改为浅灰 (`#F6F7F8`)，用于构建视觉层级（代替边框）。
        *   `border`: 移除了大部分边框定义，或改为极淡的 `#E5E5EA`。
    *   **圆角 (Radius)**：
        *   `default`: `12px`
        *   `large`: `16px` (用于大卡片容器)
    *   **字体 (Fonts)**：
        *   首选 `DM Sans`，回退到 `Microsoft YaHei`。
    *   **样式表 (Stylesheet)**：
        *   重写了全局 QSS，去除了 `QGroupBox` 的默认边框和标题栏背景，改为扁平化设计。

### 2.2 主窗口布局 (Main Layout)
*   **文件**：`src/ui/main_window.py`
*   **改动详情**：
    *   **结构调整**：严格的三栏布局（左侧列表、中间编排、右侧日志）。
    *   **样式注入**：移除了旧版 Splitter 的可见把手样式，通过 `setObjectname` (`LeftPanel`, `CenterPanel`, `RightPanel`) 精确控制各区域背景色。

### 2.3 中间核心面板 (Center Panel)
*   **步骤列表 (`src/ui/step_table.py`)**：
    *   **列宽优化**：根据 V7 设计稿硬编码了列宽（顺序 48px, 脚本 448px 等），修复了内容截断问题。
    *   **视觉降噪**：移除了表格网格线，改用行背景交替或 hover 高亮；表头背景改为透明或极淡灰色。
    *   **拖拽修复**：前期已修复 `ReorderableTable` 的拖拽排序逻辑，确保 UI 排序与数据库 `order` 字段同步。
*   **DAG 可视化 (`src/ui/dag_view.py`)**：
    *   **泳道重绘**：背景色按阶段（S1, S2）交替显示（白/浅灰），与全局 Theme 统一。
    *   **节点样式**：节点卡片改为圆角矩形，左侧带有状态色条（Color Strip），去除了复杂的阴影。
    *   **高度自适应**：视图高度现在会根据最大泳道长度自动计算。
*   **编辑器 (`src/ui/step_editor.py`)**：
    *   **浏览按钮**：添加了 "📁" 图标，按钮文字改为 "📁 浏览"，输入框背景改为 `#F6F7F8` 无边框风格。

### 2.4 左右侧面板
*   **左侧 (`workflow_list.py`, `run_control.py`)**：卡片化容器，去除了标题栏的边框线。
*   **右侧 (`log_panel.py`, `run_history.py`)**：日志区域背景改为深色或纯白（当前为纯白配合浅灰边框），圆角化处理。

---

## 3. 项目当前进度与卡点

### 3.1 总体进度
- [x] **V7 设计稿 (Pencil)**：已定稿，节点名称已汉化（主界面、基础配置等）。
- [x] **V7 代码实现**：所有 UI 组件代码均已更新。
- [x] **编译检查**：`python -m compileall src -q` 通过，无语法错误。

### 3.2 已解决的关键问题
- **依赖库路径问题**：已确认开发环境路径配置正确。
- **拖拽排序失效**：通过重写 `dropEvent` 并在数据库层强制更新 `order` 字段解决。
- **UI 错位**：通过统一 Theme Token 和硬编码关键尺寸（如列宽）解决。

### 3.3 当前卡点/风险
- **视觉还原度验证**：目前代码已修改，但尚未进行人工视觉验收。可能存在细微的 Padding/Margin 与设计稿不一致的情况。
- **图标资源**：部分按钮（如“浏览”）使用了 Unicode 字符（📁）而非 SVG 图标，可能在不同系统下显示不一致。

---

## 4. 后期实施任务规划 (优先级排序)

### P0: 视觉验收与微调 (Visual Verification)
1.  **启动应用**：运行 `python src/main.py`。
2.  **截图对比**：将运行界面与 `designs/ios_minimal_focus.pen` (Pencil) 进行像素级对比。
3.  **调整细节**：
    *   检查间距（Padding/Margin）是否拥挤或过宽。
    *   检查字体渲染是否清晰（Windows 下 Python Qt 字体有时候需要微调 Hinting）。
    *   检查颜色对比度，特别是浅灰背景上的文字。

### P1: 功能回归测试 (Regression Testing)
1.  **拖拽排序**：再次确认拖拽步骤后，顺序号是否正确更新，且保存后重启依然有效。
2.  **DAG 联动**：修改依赖关系后，DAG 图是否实时刷新且连线正确。
3.  **运行日志**：执行一个 Mock 步骤，观察日志面板的滚动和着色是否正常。

### P2: 体验优化 (UX Polish)
1.  **图标矢量化**：将 Unicode 图标替换为 `qtawesome` (FontAwesome) 或本地 SVG 资源，确保跨平台一致性。
2.  **暗色模式 (Dark Mode)**：当前的 V7 架构（`theme.py` 集中管理）非常容易扩展暗色模式。只需增加一套 `DARK_COLORS` 并实现切换逻辑。
3.  **动画效果**：给 DAG 节点的展开/收起、步骤列表的添加/删除增加简单的 `QPropertyAnimation` 过渡。

### P3: 工程化整理
1.  **代码清理**：移除 `V6` 遗留的注释代码（如有）。
2.  **文档更新**：更新 `README.md` 截图。

---

**致新接手 AI 的话**：
代码结构非常清晰，UI 逻辑与业务逻辑分离。修改样式请优先调整 `src/ui/theme.py`。如果发现布局问题，请直接定位到对应的 Panel 类（如 `StepTablePanel` 或 `DAGViewPanel`）。Pencil 文件是视觉的唯一真理来源 (SSOT)，请保持代码与 Pencil 设计的一致性。
