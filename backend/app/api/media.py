"""媒体文件 API"""

import uuid
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.media import Media, MediaType
from app.api.schemas import MediaResponse, MessageResponse

router = APIRouter()

# MIME 类型到 MediaType 的映射
MIME_TO_MEDIA_TYPE = {
    "video/mp4": MediaType.VIDEO,
    "video/webm": MediaType.VIDEO,
    "video/x-msvideo": MediaType.VIDEO,
    "video/quicktime": MediaType.VIDEO,
    "audio/mpeg": MediaType.AUDIO,
    "audio/wav": MediaType.AUDIO,
    "audio/ogg": MediaType.AUDIO,
    "image/jpeg": MediaType.IMAGE,
    "image/png": MediaType.IMAGE,
    "image/webp": MediaType.IMAGE,
    "image/gif": MediaType.IMAGE,
    "text/vtt": MediaType.SUBTITLE,
    "application/x-subrip": MediaType.SUBTITLE,
}


def detect_media_type(content_type: str | None, filename: str) -> MediaType:
    """检测媒体类型"""
    if content_type and content_type in MIME_TO_MEDIA_TYPE:
        return MIME_TO_MEDIA_TYPE[content_type]

    # 基于文件扩展名推断
    ext = Path(filename).suffix.lower()
    ext_map = {
        ".mp4": MediaType.VIDEO, ".webm": MediaType.VIDEO, ".avi": MediaType.VIDEO,
        ".mov": MediaType.VIDEO, ".mkv": MediaType.VIDEO, ".flv": MediaType.VIDEO,
        ".mp3": MediaType.AUDIO, ".wav": MediaType.AUDIO, ".ogg": MediaType.AUDIO,
        ".flac": MediaType.AUDIO, ".aac": MediaType.AUDIO,
        ".jpg": MediaType.IMAGE, ".jpeg": MediaType.IMAGE, ".png": MediaType.IMAGE,
        ".webp": MediaType.IMAGE, ".gif": MediaType.IMAGE, ".bmp": MediaType.IMAGE,
        ".srt": MediaType.SUBTITLE, ".vtt": MediaType.SUBTITLE, ".ass": MediaType.SUBTITLE,
    }
    return ext_map.get(ext, MediaType.OTHER)


@router.post("/upload", response_model=MediaResponse, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    project_id: str = Query(..., description="所属项目ID"),
    db: Session = Depends(get_db),
):
    """上传媒体文件"""
    # 生成唯一文件名
    ext = Path(file.filename).suffix if file.filename else ""
    unique_name = f"{uuid.uuid4().hex}{ext}"

    # 按项目分子目录存储
    project_dir = settings.UPLOAD_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    file_path = project_dir / unique_name

    # 保存文件
    content = await file.read()
    file_size = len(content)

    if file_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小超过限制 ({settings.MAX_UPLOAD_SIZE // (1024*1024)}MB)",
        )

    with open(file_path, "wb") as f:
        f.write(content)

    # 检测媒体类型
    media_type = detect_media_type(file.content_type, file.filename or "")

    # 获取媒体元数据
    media_metadata = {}
    if media_type == MediaType.VIDEO:
        media_metadata = _get_video_metadata(str(file_path))
    elif media_type == MediaType.AUDIO:
        media_metadata = _get_audio_metadata(str(file_path))
    elif media_type == MediaType.IMAGE:
        media_metadata = _get_image_metadata(str(file_path))

    # 创建数据库记录
    media = Media(
        project_id=project_id,
        filename=file.filename or unique_name,
        file_path=str(file_path),
        media_type=media_type,
        file_size=file_size,
        mime_type=file.content_type,
        extra_metadata=media_metadata,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media.to_dict()


@router.get("/{media_id}", response_model=MediaResponse)
def get_media(media_id: str, db: Session = Depends(get_db)):
    """获取媒体文件信息"""
    media = db.query(Media).filter(Media.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    return media.to_dict()


@router.get("/{media_id}/download")
def download_media(media_id: str, db: Session = Depends(get_db)):
    """下载媒体文件"""
    media = db.query(Media).filter(Media.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="媒体文件不存在")

    file_path = Path(media.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已丢失")

    return FileResponse(
        path=str(file_path),
        filename=media.filename,
        media_type=media.mime_type or "application/octet-stream",
    )


@router.delete("/{media_id}", response_model=MessageResponse)
def delete_media(media_id: str, db: Session = Depends(get_db)):
    """删除媒体文件"""
    media = db.query(Media).filter(Media.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="媒体文件不存在")

    # 删除物理文件
    file_path = Path(media.file_path)
    if file_path.exists():
        file_path.unlink()

    db.delete(media)
    db.commit()
    return MessageResponse(message=f"媒体文件 '{media.filename}' 已删除")


@router.get("", response_model=list[MediaResponse])
def list_media(
    project_id: str = Query(..., description="项目ID"),
    media_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """列出项目下的媒体文件"""
    query = db.query(Media).filter(Media.project_id == project_id)
    if media_type:
        query = query.filter(Media.media_type == media_type)
    media_list = query.order_by(Media.created_at.desc()).offset(skip).limit(limit).all()
    return [m.to_dict() for m in media_list]


def _get_video_metadata(file_path: str) -> dict:
    """获取视频元数据"""
    try:
        import ffmpeg
        probe = ffmpeg.probe(file_path)
        video_stream = next(
            (s for s in probe["streams"] if s["codec_type"] == "video"), None
        )
        audio_stream = next(
            (s for s in probe["streams"] if s["codec_type"] == "audio"), None
        )
        return {
            "duration": float(probe.get("format", {}).get("duration", 0)),
            "width": int(video_stream["width"]) if video_stream else None,
            "height": int(video_stream["height"]) if video_stream else None,
            "fps": eval(video_stream.get("r_frame_rate", "0")) if video_stream else None,
            "codec": video_stream.get("codec_name") if video_stream else None,
            "has_audio": audio_stream is not None,
        }
    except Exception:
        return {}


def _get_audio_metadata(file_path: str) -> dict:
    """获取音频元数据"""
    try:
        import ffmpeg
        probe = ffmpeg.probe(file_path)
        audio_stream = next(
            (s for s in probe["streams"] if s["codec_type"] == "audio"), None
        )
        return {
            "duration": float(probe.get("format", {}).get("duration", 0)),
            "sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else None,
            "channels": int(audio_stream.get("channels", 0)) if audio_stream else None,
            "codec": audio_stream.get("codec_name") if audio_stream else None,
        }
    except Exception:
        return {}


def _get_image_metadata(file_path: str) -> dict:
    """获取图片元数据"""
    try:
        from PIL import Image
        img = Image.open(file_path)
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
        }
    except Exception:
        return {}
