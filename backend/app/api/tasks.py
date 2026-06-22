"""任务管理 API"""

import json
import asyncio
from typing import Dict, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.task import Task, TaskStatus
from app.api.schemas import TaskResponse, MessageResponse

router = APIRouter()

# WebSocket 连接管理
active_connections: Dict[str, Set[WebSocket]] = {}


async def notify_task_update(task_id: str, data: dict):
    """向所有监听指定任务的 WebSocket 客户端推送更新"""
    if task_id in active_connections:
        message = json.dumps(data, ensure_ascii=False)
        disconnected = set()
        for ws in active_connections[task_id]:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.add(ws)
        active_connections[task_id] -= disconnected


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    """查询任务状态和详情"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_dict()


@router.get("/{task_id}/download")
def download_task_output(task_id: str, db: Session = Depends(get_db)):
    """下载任务输出文件（视频/图片/字幕）"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    out = task.output_result or {}
    # 优先视频，其次图片，其次字幕
    file_path = out.get("video_path") or out.get("image_url") or out.get("subtitle_path")
    if not file_path:
        raise HTTPException(status_code=404, detail="无输出文件")

    p = Path(file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="文件已丢失")

    # 根据文件类型设置 MIME
    ext = p.suffix.lower()
    mime_map = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".srt": "text/plain",
        ".ass": "text/plain",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(p),
        filename=p.name,
        media_type=media_type,
    )


@router.post("/{task_id}/cancel", response_model=MessageResponse)
def cancel_task(task_id: str, db: Session = Depends(get_db)):
    """取消任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
        raise HTTPException(status_code=400, detail=f"任务状态为 {task.status.value}，无法取消")

    task.status = TaskStatus.CANCELLED
    db.commit()

    # 如果有 Celery 任务ID，发送撤销信号
    if task.celery_task_id:
        from app.workers.celery_app import celery_app
        celery_app.control.revoke(task.celery_task_id, terminate=True)

    return MessageResponse(message=f"任务 {task_id} 已取消")


class TaskUpdateRequest(BaseModel):
    input_params: dict = None


@router.put("/{task_id}", response_model=TaskResponse)
def update_task(task_id: str, req: TaskUpdateRequest, db: Session = Depends(get_db)):
    """更新任务参数"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if req.input_params is not None:
        task.input_params = req.input_params
    db.commit()
    db.refresh(task)
    return task.to_dict()


@router.websocket("/ws/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str):
    """WebSocket 实时任务状态推送"""
    await websocket.accept()

    if task_id not in active_connections:
        active_connections[task_id] = set()
    active_connections[task_id].add(websocket)

    try:
        while True:
            # 保持连接，接收客户端心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        active_connections[task_id].discard(websocket)
        if not active_connections[task_id]:
            del active_connections[task_id]
