"""媒体文件数据模型"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import String, Integer, DateTime, JSON, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MediaType(str, PyEnum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    SUBTITLE = "subtitle"
    OTHER = "other"


class Media(Base):
    __tablename__ = "media_files"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, comment="所属项目ID"
    )
    filename: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="原始文件名"
    )
    file_path: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="存储路径"
    )
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType), nullable=False, comment="媒体类型"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, default=0, comment="文件大小(字节)"
    )
    mime_type: Mapped[str | None] = mapped_column(
        String(100), comment="MIME类型"
    )
    extra_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSON, comment="媒体元数据(分辨率、时长、帧率等)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="上传时间"
    )

    # 关系
    project: Mapped["Project"] = relationship(back_populates="media_files")  # noqa: F821

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "media_type": self.media_type.value if self.media_type else None,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
