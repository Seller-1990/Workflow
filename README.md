# 工作流管理系统 (Workflow Manager)

这是一个基于 Python + PySide6 开发的桌面端工作流编排工具，旨在解决复杂数据处理任务的自动化执行问题。支持将 Python 脚本、Excel 刷新、Power BI 刷新等异构任务串联成工作流，并提供可视化管理、日志追踪和通知功能。

## ✨ 核心功能

- **🚀 多类型任务编排**
  - **Python 脚本**：无缝集成现有业务脚本。
  - **Excel 自动化**：自动打开、刷新数据连接、保存（基于 Win32 COM）。
  - **Power BI**：支持 PBI 数据集刷新。
  - **子工作流**：支持工作流嵌套调用。

- **📊 可视化与管理**
  - **DAG 视图**：清晰展示步骤间的依赖关系。
  - **步骤管理**：支持启用/禁用步骤，灵活调整执行计划。
  - **运行历史**：记录每次运行的状态、耗时和详细日志。

- **🔔 自动化与通知**
  - **钉钉通知**：工作流执行完毕后自动推送消息到钉钉群（支持自定义模板）。
  - **文件监听**：监控指定文件夹的新增文件，自动触发工作流运行。
  - **并行执行**：支持任务并行处理，提升效率。

## 🛠️ 技术栈

- **语言**: Python 3.12
- **UI 框架**: PySide6 (Qt for Python)
- **数据存储**: SQLite + SQLAlchemy
- **自动化**: pywin32 (Excel/Com接口)
- **打包**: PyInstaller

## 📦 快速开始

### 开发环境运行

1. 克隆仓库
```bash
git clone https://github.com/Seller-1990/Workflow.git
cd Workflow
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 启动应用
```bash
python src/main.py
```

### 🔨 打包构建

本项目包含完整的 `pyinstaller` 配置。

```bash
pyinstaller build.spec
```
构建完成后，可执行文件位于 `dist/工作流管理.exe`。

## 📝 目录结构

* `src/`: 源代码目录
  * `ui/`: 界面相关代码
  * `executors/`: 任务执行器（Python, Excel等）
  * `engine.py`: 工作流核心引擎
* `data/`: 数据库文件目录
* `logs/`: 运行日志
* `0*.md`: 项目详细说明文档

## 📄 License

MIT
