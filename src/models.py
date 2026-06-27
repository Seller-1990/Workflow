# -*- coding: utf-8 -*-
"""SQLAlchemy ORM 模型定义"""

import json
import logging
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, Index
)
from sqlalchemy.orm import (
    DeclarativeBase, relationship, Mapped, mapped_column
)

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """ORM 基类"""
    pass


class Workflow(Base):
    """工作流模型"""
    __tablename__ = "workflows"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 配置
    chart_theme: Mapped[str] = mapped_column(String(64), default="default")
    parallel_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_workers: Mapped[int] = mapped_column(Integer, default=2)
    watch_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    watch_mode: Mapped[str] = mapped_column(String(64), default="any_change")
    watch_folders: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=8)
    settle_seconds: Mapped[int] = mapped_column(Integer, default=15)
    log_retention_days: Mapped[int] = mapped_column(Integer, default=30)  # 日志保留天数

    # 单脚本模式
    single_script_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    single_script_type: Mapped[str] = mapped_column(String(32), default="python")
    single_script_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    single_script_args: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    single_script_cwd: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 通知配置（JSON）
    notify_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系
    stages: Mapped[List["WorkflowStage"]] = relationship(
        "WorkflowStage",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStage.order",
    )
    steps: Mapped[List["Step"]] = relationship(
        "Step", back_populates="workflow", 
        cascade="all, delete-orphan",
        order_by="Step.order"
    )
    run_histories: Mapped[List["RunHistory"]] = relationship(
        "RunHistory", back_populates="workflow",
        cascade="all, delete-orphan"
    )
    versions: Mapped[List["WorkflowVersion"]] = relationship(
        "WorkflowVersion", back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowVersion.version.desc()"
    )

    def __repr__(self):
        return f"<Workflow(uid={self.uid!r}, name={self.name!r})>"

    def get_notify_config(self) -> dict:
        """获取通知配置"""
        if self.notify_config:
            try:
                return json.loads(self.notify_config)
            except json.JSONDecodeError as e:
                logger.warning("通知配置 JSON 解析失败: %s", e)
        return {}

    def set_notify_config(self, config: dict):
        """设置通知配置"""
        self.notify_config = json.dumps(config, ensure_ascii=False)

    def get_watch_folders(self) -> list:
        """获取监听目录列表"""
        if self.watch_folders:
            try:
                return json.loads(self.watch_folders)
            except json.JSONDecodeError as e:
                logger.warning("监听目录 JSON 解析失败: %s", e)
        return []

    def set_watch_folders(self, folders: list):
        """设置监听目录列表"""
        self.watch_folders = json.dumps(folders, ensure_ascii=False)

    def get_single_args(self) -> list:
        """获取单脚本参数列表"""
        if self.single_script_args:
            try:
                return json.loads(self.single_script_args)
            except json.JSONDecodeError as e:
                logger.warning("单脚本参数 JSON 解析失败: %s", e)
        return []


class WorkflowVersion(Base):
    """工作流配置版本历史"""
    __tablename__ = "workflow_versions"
    __table_args__ = (
        Index("uq_workflow_versions_workflow_version", "workflow_id", "version", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)  # 自增版本号
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)     # JSON 快照
    change_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="versions")


class WorkflowStage(Base):
    """用途阶段（人为归类的业务阶段）"""

    __tablename__ = "workflow_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="默认阶段")
    order: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="stages")

    def __repr__(self):
        return f"<WorkflowStage(uid={self.uid!r}, name={self.name!r}, order={self.order})>"


class Step(Base):
    """步骤模型"""
    __tablename__ = "steps"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    
    # 基本信息
    uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # 用途阶段（人为归类）
    stage_uid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (
        Index('uq_steps_workflow_uid', 'workflow_id', 'uid', unique=True),
        Index('ix_steps_workflow_order', 'workflow_id', 'order'),
    )
    
    # 脚本配置
    step_type: Mapped[str] = mapped_column(String(32), default="python")  # python, excel_powerquery, powerbi_refresh
    script_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    args: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 数组
    cwd: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 执行配置
    is_gate: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否为门控步骤（阻塞后续并行）
    is_parallel: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否启用并行
    depends_on: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 依赖的步骤 UID（JSON 数组）
    
    # 其他配置
    chart_theme: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timeout_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    skip_on_success: Mapped[bool] = mapped_column(Boolean, default=False)  # 上次成功则跳过
    # ROI-2: 步骤显式声明的输出路径（JSON 数组）；监听冲突检测优先使用声明而非推断
    output_paths: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="steps")
    step_logs: Mapped[List["StepLog"]] = relationship(
        "StepLog", back_populates="step",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self):
        return f"<Step(uid={self.uid!r}, name={self.name!r}, order={self.order})>"
    
    def get_args(self) -> list:
        """获取参数列表"""
        if self.args:
            try:
                return json.loads(self.args)
            except json.JSONDecodeError as e:
                logger.warning("步骤参数 JSON 解析失败: %s", e)
        return []
    
    def set_args(self, args: list):
        """设置参数列表"""
        self.args = json.dumps(args, ensure_ascii=False)
    
    def get_depends_on(self) -> list:
        """获取依赖步骤列表"""
        if self.depends_on:
            try:
                return json.loads(self.depends_on)
            except json.JSONDecodeError as e:
                logger.warning("步骤依赖 JSON 解析失败: %s", e)
        return []
    
    def set_depends_on(self, deps: list):
        """设置依赖步骤列表"""
        self.depends_on = json.dumps(deps, ensure_ascii=False)

    def get_output_paths(self) -> list:
        """获取声明的输出路径列表（ROI-2）"""
        if self.output_paths:
            try:
                return json.loads(self.output_paths)
            except json.JSONDecodeError as e:
                logger.warning("步骤输出路径 JSON 解析失败: %s", e)
        return []

    def set_output_paths(self, paths: list):
        """设置声明的输出路径列表（ROI-2）"""
        self.output_paths = json.dumps([str(p) for p in (paths or [])], ensure_ascii=False)


class RunHistory(Base):
    """运行历史模型"""
    __tablename__ = "run_histories"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)

    # 运行信息
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, running, success, failure, cancelled
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 触发原因
    
    # 时间
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # 日志目录
    log_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 运行模式
    run_mode: Mapped[str] = mapped_column(String(32), default="full")  # full, from_step, only_step, retry_failed
    run_mode_param: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 相关参数

    # 执行追踪
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)  # 追踪 ID（同一次完整执行的顶级 ID）
    parent_run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)  # 父运行 ID（子工作流关联）

    # ROI-1: 通知结果（sent / failed:摘要 / skipped:原因），由 engine_core.notification 回写
    notify_status: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="run_histories")
    step_logs: Mapped[List["StepLog"]] = relationship(
        "StepLog", back_populates="run_history",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index('ix_run_histories_wf_status_time', 'workflow_id', 'status', 'start_time'),
        Index('ix_run_histories_wf_endtime', 'workflow_id', 'end_time'),  # HA3: 加速 only_finished 路径
    )
    
    def __repr__(self):
        return f"<RunHistory(run_id={self.run_id!r}, status={self.status!r})>"
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """计算运行时长"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class StepLog(Base):
    """步骤日志模型"""
    __tablename__ = "step_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_history_id: Mapped[int] = mapped_column(Integer, ForeignKey("run_histories.id"), nullable=False, index=True)
    step_id: Mapped[int] = mapped_column(Integer, ForeignKey("steps.id"), nullable=False, index=True)
    
    # 执行信息
    order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, running, success, failure, skipped
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 时间
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # 日志文件路径
    stdout_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 关系
    run_history: Mapped["RunHistory"] = relationship("RunHistory", back_populates="step_logs")
    step: Mapped["Step"] = relationship("Step", back_populates="step_logs")

    __table_args__ = (
        Index('ix_step_logs_run_status', 'run_history_id', 'status'),
        Index('ix_step_logs_step_status', 'step_id', 'status'),  # HA3: 加速 skip_on_success 检查
        # R2-#5: 加速 get_recent_step_logs_for_step（WHERE step_id=? AND run_history_id IN (...) ORDER BY run_history_id DESC）
        Index('ix_step_logs_step_run', 'step_id', 'run_history_id'),
    )

    def __repr__(self):
        return f"<StepLog(step_id={self.step_id}, status={self.status!r})>"
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """计算执行时长"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class RecentWorkflow(Base):
    """最近使用的子工作流"""
    __tablename__ = "recent_workflows"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class WebhookConfig(Base):
    """Webhook 配置模型"""
    __tablename__ = "webhook_configs"
    __table_args__ = (
        Index("uq_webhook_configs_name", "name", unique=True),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    keyword: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<WebhookConfig(id={self.id}, name={self.name!r})>"

