"""Celery 异步任务定义"""

import json
import logging
from datetime import datetime

import httpx

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models.task import Task, TaskStatus
from app.models.workflow import Workflow

logger = logging.getLogger(__name__)


def _update_task(task_id: str, **kwargs):
    """更新任务状态"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            for key, value in kwargs.items():
                setattr(task, key, value)
            db.commit()

            # 通过 WebSocket 推送状态更新
            _push_task_update(task)
    finally:
        db.close()


def _push_task_update(task: Task):
    """推送任务状态更新（通过 Redis Pub/Sub）"""
    try:
        import redis as redis_lib
        from app.config import settings

        r = redis_lib.Redis.from_url(settings.redis_url)
        r.publish(
            f"task:{task.id}",
            json.dumps(task.to_dict(), ensure_ascii=False),
        )
    except Exception:
        pass  # Redis 不可用时静默处理


def _update_workflow_status(workflow_id: str):
    """更新工作流状态"""
    from app.services.workflow_service import update_workflow_status
    update_workflow_status(workflow_id)


@celery_app.task(bind=True, name="app.workers.tasks.run_ai_task", max_retries=2)
def run_ai_task(self, task_id: str):
    """
    执行 AI 类型任务的通用入口。
    支持: text_to_video, video_analysis, subtitle_generation, voice_synthesis, image_to_video
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return {"error": f"任务 {task_id} 不存在"}

        # 标记为运行中
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        task.progress = 0
        db.commit()
        _push_task_update(task)

        params = task.input_params or {}
        task_type = task.task_type

        # 根据任务类型分发到对应的 AI 模块
        if task_type.value == "text_to_video":
            result = _execute_text_to_video(params)
        elif task_type.value == "video_analysis":
            result = _execute_video_analysis(params)
        elif task_type.value == "subtitle_generation":
            result = _execute_subtitle_generation(params)
        elif task_type.value == "voice_synthesis":
            result = _execute_voice_synthesis(params)
        elif task_type.value == "image_to_video":
            r
        else:
            result = {"success": False, "error": f"未知的AI任务类型: {task_type.value}"}

        # 更新任务结果
        if result.get("success"):
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.output_result = result
        else:
            task.status = TaskStatus.FAILED
            task.error_message = result.get("error", "未知错误")
            task.output_result = result

        task.completed_at = datetime.utcnow()
        db.commit()
        _push_task_update(task)
        _update_workflow_status(task.workflow_id)

        return result

    except Exception as exc:
        # 重试逻辑
        try:
            self.retry(exc=exc, countdown=60)
        except self.MaxRetriesExceededError:
            db2 = SessionLocal()
            try:
                task = db2.query(Task).filter(Task.id == task_id).first()
                if task:
                    task.status = TaskStatus.FAILED
                    task.error_message = str(exc)
                    task.completed_at = datetime.utcnow()
                    db2.commit()
                    _push_task_update(task)
                    _update_workflow_status(task.workflow_id)
            finally:
                db2.close()
            raise
    finally:
        db.close()


@celery_app.task(bind=True, name="app.workers.tasks.process_video", max_retries=2)
def process_video(self, task_id: str):
    """
    执行视频/音频处理任务。
    支持: 裁剪、拼接、转码、字幕烧录、音频处理等
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return {"error": f"任务 {task_id} 不存在"}

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        task.progress = 0
        db.commit()
        _push_task_update(task)

        params = task.input_params or {}
        action = params.get("action", "")

        from app.services import video_service, audio_service

        result = {}

        if action == "trim":
            output = video_service.trim_video(
                params["input_path"],
                params["start_time"],
                params["end_time"],
            )
            result = {"success": True, "output_path": output}

        elif action == "concat":
            output = video_service.concat_videos(params["input_paths"])
            result = {"success": True, "output_path": output}

        elif action == "transcode":
            output = video_service.transcode_video(
                params["input_path"],
                params.get("output_format", "mp4"),
                params.get("resolution"),
                params.get("bitrate"),
            )
            result = {"success": True, "output_path": output}

        elif action == "extract_audio":
            output = video_service.extract_audio(params["input_path"])
            result = {"success": True, "output_path": output}

        elif action == "merge_audio_video":
            output = video_service.merge_audio_video(
                params["video_path"],
                params["audio_path"],
            )
            result = {"success": True, "output_path": output}

        elif action == "burn_subtitle":
            o
                params["video_path"],
                params["subtitle_path"],
                style=params.get("style"),
            )
            result = {"success": True, "output_path": output}

        elif action == "thumbnail":
            output = video_service.generate_thumbnail(
                params["input_path"],
                params.get("time", 0),
                params.get("size", "320x180"),
            )
            result = {"success": True, "output_path": output}
            info = video_service.get_video_info(params["input_path"])
            result = {"success": True, "info": info}

        elif action == "adjust_volume":

        elif action == "adjust_volume":
            output = audio_service.adjust_volume(
                params["input_path"],
                params.get("volume", 1.0),
            )
            result = {"success": True, "output_path": output}

        else:
            result = {"success": False, "error": f"未知的视频处理操作: {action}"}

        if result.get("success"):
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.output_result = result
        else:
            task.status = TaskStatus.FAILED
            task.error_message = result.get("error", "未知错误")
            task.output_result = result

        task.completed_at = datetime.utcnow()
        db.commit()
        _push_task_update(task)
        _update_workflow_status(task.workflow_id)

        return result

    except Exception as exc:
        try:
            self.retry(exc=exc, countdown=60)
        except self.MaxRetriesExceededError:
            db2 = SessionLocal()
            try:
                task = db2.query(Task).filter(Task.id == task_id).first()
                if task:
                    task.status = TaskStatus.FAILED
                    task.error_message = str(exc)
                    task.completed_at = datetime.utcnow()
                    db2.commit()
                    _push_task_update(task)
                    _update_workflow_status(task.workflow_id)
            finally:
                db2.close()
            raise
    finally:
        db.close()
# MISSING LINE 251
# MISSING LINE 252
# MISSING LINE 253
# MISSING LINE 254
# MISSING LINE 255
# MISSING LINE 256
# MISSING LINE 257
    character_task_ids: list[str],
    keyframe_task_ids: list[str],
    scene_task_ids: list[str],
    concat_task_id: str | None = None,
):
    """
    智能体专用工作流：四阶段串行执行。
    Phase 1: 生成角色设定图 (text-to-image)
    Phase 2: 生成分镜关键帧 (image-to-image, 基于角色参考图)
    Phase 3: 图生视频 (image + text -> video)
    Phase 4: 视频拼接
    """
    from app.ai.agnes_client import get_agnes_client, AgnesAPIError
    from app.ai.image_to_video import image_to_video
    from app.services.video_service import concat_videos
    from app.config import settings
    from pathlib import Path
    import uuid as _uuid

    agnes_client = get_agnes_client()
    output_dir = str(settings.OUTPUT_DIR / f"agent_{_uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # ============ Phase 1: 角色设定图 ============
    character_image_urls: dict[str, str] = {}  # task_id -> url
    for i, task_id in enumerate(character_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                continue

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)

            params = task.input_params or {}
            prompt = params.get("prompt", "")
            char_name = params.get("character_name", f"character_{i}")

            # 生成角色设定图
            _push_task_update(task)
        finally:
            db.close()

        try:
            # 生成角色设定图
            result = agnes_client.generate_image(
                prompt=prompt,
def run_agent_workflow(
    self,
    workflow_id: str,
    character_task_ids: list[str],
    first_frame_task_ids: list[str],
    last_frame_task_ids: list[str],
    scene_task_ids: list[str],
    concat_task_id: str | None = None,
    other_task_ids: list[tuple[str, str]] | None = None,
    scene_character_map: dict[int, list[int]] | None = None,
):
    """
    智能体专用工作流：五阶段串行执行。
    Phase 1: 生成角色设定图 (text-to-image)
    Phase 2a: 生成分镜首帧 (image-to-image, 基于场景角色参考图)
    Phase 2b: 生成分镜尾帧 (image-to-image, 基于场景角色参考图)
    Phase 3: 图生视频 (keyframes 模式: 首帧+尾帧, 支持首尾帧连续性)
    Phase 4: 视频拼接
    Phase 5: 配音/字幕
    """
    from app.ai.agnes_client import get_agnes_client, AgnesAPIError
    from app.ai.image_to_video import image_to_video
    from app.services.video_service import concat_videos
    from app.config import settings
    from pathlib import Path
    import uuid as _uuid

    agnes_client = get_agnes_client()
    output_dir = str(settings.OUTPUT_DIR / f"agent_{_uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Celery JSON 序列化会将 int key 变成 str key，统一转为 int
    if scene_character_map:
        scene_character_map = {int(k): v for k, v in scene_character_map.items()}
    logger.info(f"scene_character_map: {scene_character_map}")
    logger.info(f"character_task_ids: {character_task_ids}, first_frame: {len(first_frame_task_ids)}, last_frame: {len(last_frame_task_ids)}, scenes: {len(scene_task_ids)}")

    # ============ Phase 1: 角色设定图 ============
    character_image_urls: dict[int, str] = {}  # character_index -> url
    for i, task_id in enumerate(character_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                continue

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            char_name = params.get("character_name", f"character_{i}")
            char_index = params.get("character_index", i)
            provided_url = params.get("provided_url", "")
            
            _push_task_update(task)
        finally:
            db.close()

        # 如果用户已提供参考图，跳过生成，直接使用
        if provided_url:
            logger.info(f"角色 '{char_name}' 已有参考图，跳过生成: {provided_url}")
            character_image_urls[char_index] = provided_url
            db = SessionLocal()
            try:
                task = db.query(Task).filter(Task.id == task_id).first()
                if task:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {
                        "success": True,
                        "image_url": provided_url,
                        "character_name": char_name,
                        "provided": True,
                    }
                    task.completed_at = datetime.utcnow()
                    db.commit()
                    _push_task_update(task)
            finally:
                db.close()
            continue

        try:
            result = agnes_client.generate_image(
                prompt=prompt,
                size="1024x1024",
            )

            db = SessionLocal()
            try:
                task = db.query(Task).filter(Task.id == task_id).first()
                if not task:
                    continue
                    
                img_url = result.get("data", [{}])[0].get("url", "")
                if img_url:
                    import urllib.request
                    import uuid as _uuid
                    from pathlib import Path
                    char_dir = Path(output_dir) / "characters"
                    char_dir.mkdir(parents=True, exist_ok=True)
                    local_path = char_dir / f"char_{_uuid.uuid4().hex[:8]}.jpg"
                    try:
                        urllib.request.urlretrieve(img_url, local_path)
                    except Exception as e:
                        logger.error(f"角色图片下载失败: {e}")
                        
                    character_image_urls[char_index] = img_url
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {
                        "success": True,
                        "image_url": img_url,
                        "local_path": str(local_path) if local_path.exists() else None,
                        "character_name": char_name,
                    }
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = "角色设定图生成失败: 未获取到图片URL"
                    task.output_result = {"success": False, "error": "未获取到图片URL"}

                task.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(task)
            finally:
                db.close()

        except Exception as exc:
            logger.exception(f"角色设定图 {i} 生成失败: {exc}")
            db = SessionLocal()
            try:
                t = db.query(Task).filter(Task.id == task_id).first()
                if t:
                    t.status = TaskStatus.FAILED
                    t.error_message = str(exc)
                    t.completed_at = datetime.utcnow()
                    db.commit()
                    _push_task_update(t)
            finally:
                db.close()

                        "local_path": str(local_path) if local_path.exists() else None,
                        "scene_index": params.get("scene_index", i),
                    }
                else:
                    keyframe_image_urls.append("")
                    task.status = TaskStatus.FAILED
                    task.error_message = "关键帧生成失败: 未获取到图片URL"
                    task.output_result = {"success": False, "error": "未获取到图片URL"}

                task.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(task)
            finally:
                db.close()

        except Exception as exc:
            logger.exception(f"关键帧 {i} 生成失败: {exc}")
            keyframe_image_urls.append("")
            db = SessionLocal()
            try:
                t = db.query(Task).filter(Task.id == task_id).first()
                if t:
                    t.status = TaskStatus.FAILED
                    t.error_message = str(exc)
                    t.completed_at = datetime.utcnow()
                    db.commit()
                    _push_task_update(t)
            finally:
                db.close()

    # ============ Phase 3: 图生视频 ============
    output_paths = []
    for i, task_id in enumerate(scene_task_ids):
        db = Ses
# MISSING LINE 484
# MISSING LINE 485
# MISSING LINE 486
# MISSING LINE 487
# MISSING LINE 488
# MISSING LINE 489
# MISSING LINE 490
# MISSING LINE 491
# MISSING LINE 492
# MISSING LINE 493
# MISSING LINE 494
# MISSING LINE 495
# MISSING LINE 496
# MISSING LINE 497
# MISSING LINE 498
# MISSING LINE 499
# MISSING LINE 500
# MISSING LINE 501
# MISSING LINE 502
# MISSING LINE 503
# MISSING LINE 504
# MISSING LINE 505
# MISSING LINE 506
# MISSING LINE 507
# MISSING LINE 508
# MISSING LINE 509
# MISSING LINE 510
# MISSING LINE 511
# MISSING LINE 512
# MISSING LINE 513
# MISSING LINE 514
# MISSING LINE 515
# MISSING LINE 516
# MISSING LINE 517
# MISSING LINE 518
# MISSING LINE 519
# MISSING LINE 520
# MISSING LINE 521
# MISSING LINE 522
# MISSING LINE 523
# MISSING LINE 524
# MISSING LINE 525
# MISSING LINE 526
# MISSING LINE 527
# MISSING LINE 528
# MISSING LINE 529
# MISSING LINE 530
# MISSING LINE 531
# MISSING LINE 532
# MISSING LINE 533
# MISSING LINE 534
# MISSING LINE 535
# MISSING LINE 536
# MISSING LINE 537
# MISSING LINE 538
# MISSING LINE 539
# MISSING LINE 540
# MISSING LINE 541
# MISSING LINE 542
# MISSING LINE 543
# MISSING LINE 544
# MISSING LINE 545
# MISSING LINE 546
# MISSING LINE 547
# MISSING LINE 548
# MISSING LINE 549
# MISSING LINE 550
# MISSING LINE 551
# MISSING LINE 552
# MISSING LINE 553
# MISSING LINE 554
# MISSING LINE 555
# MISSING LINE 556
# MISSING LINE 557
# MISSING LINE 558
# MISSING LINE 559
            if t:
                t.status = TaskStatus.FAILED
                t.error_message = str(exc)
                t.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(t)
        finally:
            db.close()

    # ============ Phase 4: 视频拼接 ============
    if concat_task_id and len(output_paths) >= 2:
        db = SessionLocal()
        try:
            concat_task = db.query(Task).filter(Task.id == concat_task_id).first()
            if concat_task:
                concat_task.status = TaskStatus.RUNNING
                concat_task.started_at = datetime.utcnow()
                db.commit()
                _push_task_update(concat_task)

                final_path = concat_videos(output_paths)

                concat_task.status = TaskStatus.COMPLETED
                concat_task.progress = 100
                concat_task.output_result = {"success": True, "output_path": final_path}
                concat_task.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(concat_task)
        except Exception as exc:
            logger.exception(f"视频拼接失败: {exc}")
            ct = db.query(Task).filter(Task.id == concat_task_id).first()
            if ct:
                ct.status = TaskStatus.FAILED
                ct.error_message = str(exc)
                ct.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(ct)
        finally:
            db.close()

    # 更新工作流状态
# MISSING LINE 601
# MISSING LINE 602
# MISSING LINE 603
# MISSING LINE 604
# MISSING LINE 605
# MISSING LINE 606
# MISSING LINE 607
# MISSING LINE 608
# MISSING LINE 609
# MISSING LINE 610
# MISSING LINE 611
# MISSING LINE 612
# MISSING LINE 613
# MISSING LINE 614
# MISSING LINE 615
# MISSING LINE 616
# MISSING LINE 617
# MISSING LINE 618
# MISSING LINE 619
# MISSING LINE 620
# MISSING LINE 621
# MISSING LINE 622
# MISSING LINE 623
# MISSING LINE 624
# MISSING LINE 625
# MISSING LINE 626
# MISSING LINE 627
# MISSING LINE 628
# MISSING LINE 629
# MISSING LINE 630
        "audio_path": result.audio_path,
        "duration": result.duration,
        "voice_name": result.voice_name,
        "error": result.error,
    }


def _execute_image_to_video(params: dict) -> dict:
    from app.ai.image_to_video import image_to_video, images_to_slideshow

    api_provider = params.get("api_provider", "agnes")
    image_paths = params.get("image_paths", [])
    image_url = params.get("image_url")
    prompt = params.get("prompt", "")
                    last_frame_urls.append("")
                    continue
                    
                img_url = result.get("data", [{}])[0].get("url", "")
                if img_url:
                    import urllib.request
                    import uuid as _uuid
                    from pathlib import Path
                    lf_dir = Path(output_dir) / "last_frames"
                    lf_dir.mkdir(parents=True, exist_ok=True)
                    local_path = lf_dir / f"lf_{_uuid.uuid4().hex[:8]}.jpg"
                    try:
                        urllib.request.urlretrieve(img_url, local_path)
                    except Exception as e:
                        logger.error(f"尾帧图片下载失败: {e}")

                    last_frame_urls.append(img_url)
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {
                        "success": True,
                        "image_url": img_url,
                        "local_path": str(local_path) if local_path.exists() else None,
                        "scene_index": scene_idx,
                    }
                else:
                    last_frame_urls.append("")
                    task.status = TaskStatus.FAILED
                    task.error_message = "尾帧生成失败: 未获取到图片URL"
                    task.output_result = {"success": False, "error": "未获取到图片URL"}

                task.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(task)
            finally:
                db.close()
