"""任务数据模型"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import String, Text, DateTime, JSON, Float, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TaskStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, PyEnum):
    TEXT_TO_VIDEO = "text_to_video"
    VIDEO_ANALYSIS = "video_analysis"
    SUBTITLE_GENERATION = "subtitle_generation"
    VOICE_SYNTHESIS = "voice_synthesis"
    IMAGE_TO_VIDEO = "image_to_video"
    IMAGE_GENERATION = "image_generation"
    VIDEO_PROCESSING = "video_processing"
    AUDIO_PROCESSING = "audio_processing"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id"), nullable=False, comment="所属工作流ID"
    )
    node_id: Mapped[str | None] = mapped_column(
        String(100), comment="工作流节点ID"
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType), nullable=False, comment="任务类型"
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, comment="任务状态"
    )
    progress: Mapped[float] = mapped_column(
        Float, default=0.0, comment="进度百分比 0-100"
    )
    input_params: Mapped[dict | None] = mapped_column(
        JSON, comment="输入参数 (JSON)"
    )
    output_result: Mapped[dict | None] = mapped_column(
        JSON, comment="输出结果 (JSON)"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, comment="错误信息"
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(100), comment="Celery任务ID"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="开始执行时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="完成时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 关系
    workflow: Mapped["Workflow"] = relationship(back_populates="tasks")  # noqa: F821

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "task_type": self.task_type.value if self.task_type else None,
            "status": self.status.value if self.status else None,
            "progress": self.progress,
            "input_params": self.input_params,
            "output_result": self.output_result,
            "error_message": self.error_message,
            "celery_task_id": self.celery_task_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
