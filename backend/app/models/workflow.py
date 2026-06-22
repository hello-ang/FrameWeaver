"""工作流数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, comment="所属项目ID"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="工作流名称")
    description: Mapped[str | None] = mapped_column(Text, comment="工作流描述")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", comment="状态: draft, ready, running, completed, failed"
    )
    nodes: Mapped[dict | None] = mapped_column(
        JSON, comment="工作流节点定义 (JSON)"
    )
    edges: Mapped[dict | None] = mapped_column(
        JSON, comment="节点连接关系 (JSON)"
    )
    config: Mapped[dict | None] = mapped_column(
        JSON, comment="工作流全局配置"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    project: Mapped["Project"] = relationship(back_populates="workflows")  # noqa: F821
    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        "Task", back_populates="workflow", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "nodes": self.nodes,
            "edges": self.edges,
            "config": self.config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
