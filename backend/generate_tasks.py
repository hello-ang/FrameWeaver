
import sys
content = """\"\"\"Celery 异步任务定义\"\"\"

import json
import logging
from datetime import datetime
from pathlib import Path
import uuid as _uuid
import httpx

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models.task import Task, TaskStatus
from app.models.workflow import Workflow

logger = logging.getLogger(__name__)

def _download_file_robust(url: str, local_path: str, max_retries: int = 3):
    import time
    last_err = None
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=300.0) as client:
                resp = client.get(url, follow_redirects=True)
                resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return
        except Exception as e:
            last_err = e
            time.sleep(5)
    raise Exception(f"文件下载失败(重试{max_retries}次): {last_err}")

def _update_task(task_id: str, **kwargs):
    \"\"\"更新任务状态\"\"\"
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            for key, value in kwargs.items():
                setattr(task, key, value)
            db.commit()
            _push_task_update(task)
    finally:
        db.close()

def _push_task_update(task: Task):
    \"\"\"推送任务状态更新（通过 Redis Pub/Sub）\"\"\"
    try:
        import redis as redis_lib
        from app.config import settings
        r = redis_lib.Redis.from_url(settings.redis_url)
        r.publish(f"task:{task.id}", json.dumps(task.to_dict(), ensure_ascii=False))
    except Exception:
        pass

def _update_workflow_status(workflow_id: str):
    \"\"\"更新工作流状态\"\"\"
    from app.services.workflow_service import update_workflow_status
    db = SessionLocal()
    try:
        update_workflow_status(workflow_id, db)
    finally:
        db.close()

@celery_app.task(bind=True, name="app.workers.tasks.run_ai_task")
def run_ai_task(self, task_id: str):
    \"\"\"执行单个常规 AI 任务\"\"\"
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status == TaskStatus.CANCELLED:
            return {"error": f"任务跳过或不存在"}
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        db.commit()
        _push_task_update(task)
        
        params = task.input_params or {}
        task_type = task.task_type.value if hasattr(task.task_type, "value") else str(task.task_type)
        
        # Dispatch based on task_type
        if task_type == "audio_generation":
            from app.ai.voice_synthesis import synthesize_voice
            out_path = str(Path(params.get("output_dir", "./storage/temp")) / f"audio_{_uuid.uuid4().hex[:8]}.mp3")
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            res = synthesize_voice(text=params.get("text", ""), output_path=out_path)
            task.output_result = {"success": True, "audio_path": res}
            
        elif task_type == "subtitle_generation":
            from app.ai.subtitle_generator import generate_subtitle
            out_path = str(Path(params.get("output_dir", "./storage/temp")) / f"sub_{_uuid.uuid4().hex[:8]}.srt")
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            res = generate_subtitle(audio_path=params.get("audio_path", ""), output_path=out_path)
            task.output_result = {"success": True, "subtitle_path": res}
            
        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.completed_at = datetime.utcnow()
        db.commit()
        _push_task_update(task)
        return {"success": True}
        
    except Exception as e:
        logger.exception(f"任务 {task_id} 失败")
        if "task" in locals() and task:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        return {"error": str(e)}
    finally:
        db.close()

@celery_app.task(bind=True, name="app.workers.tasks.process_video")
def process_video(self, task_id: str):
    \"\"\"执行视频处理任务\"\"\"
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status == TaskStatus.CANCELLED:
            return {"error": "跳过"}
            
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        db.commit()
        _push_task_update(task)
        
        params = task.input_params or {}
        action = params.get("action")
        
        from app.services.video_service import concat_videos, merge_audio_video, burn_subtitle
        
        if action == "concat":
            out = str(Path(params.get("output_dir", "./storage/temp")) / f"concat_{_uuid.uuid4().hex[:8]}.mp4")
            res = concat_videos(params.get("input_paths", []), out)
            task.output_result = {"success": True, "video_path": res}
        elif action == "merge_audio":
            out = str(Path(params.get("output_dir", "./storage/temp")) / f"merged_{_uuid.uuid4().hex[:8]}.mp4")
            res = merge_audio_video(params.get("video_path"), params.get("audio_path"), out)
            task.output_result = {"success": True, "video_path": res}
        elif action == "subtitle":
            out = str(Path(params.get("output_dir", "./storage/temp")) / f"sub_{_uuid.uuid4().hex[:8]}.mp4")
            res = burn_subtitle(params.get("video_path"), params.get("subtitle_path"), out)
            task.output_result = {"success": True, "video_path": res}
            
        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.completed_at = datetime.utcnow()
        db.commit()
        _push_task_update(task)
    except Exception as e:
        logger.exception(f"处理视频失败: {e}")
        if "task" in locals() and task:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            db.commit()
            _push_task_update(task)
    finally:
        db.close()

@celery_app.task(bind=True, name="app.workers.tasks.run_agent_workflow")
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
    \"\"\"
    执行完整的视频生成 Agent 工作流。
    \"\"\"
    from app.ai.agnes_client import get_agnes_client
    from app.config import settings
    
    agnes_client = get_agnes_client()
    output_dir = str(settings.OUTPUT_DIR / f"agent_{_uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    if scene_character_map:
        scene_character_map = {int(k): v for k, v in scene_character_map.items()}
        
    # Phase 1: 角色设定图
    character_image_urls = {}
    character_names = {}
    for i, task_id in enumerate(character_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                continue
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            char_name = params.get("character_name", f"角色{i}")
            provided_url = params.get("provided_url", "")
            character_names[i] = char_name
            
            if provided_url:
                character_image_urls[i] = provided_url
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "image_url": provided_url, "provided": True}
                task.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(task)
                continue
                
            res = agnes_client.generate_image(prompt=prompt)
            img_url = res.get("data", [{}])[0].get("url", "")
            if img_url:
                local_path = str(Path(output_dir) / f"char_{i}.jpg")
                _download_file_robust(img_url, local_path)
                character_image_urls[i] = img_url
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "image_url": img_url, "local_path": local_path}
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "生成失败"
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
        finally:
            db.close()

    # Phase 2a: 首帧
    first_frame_urls = []
    for i, task_id in enumerate(first_frame_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                first_frame_urls.append("")
                continue
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            
            ref_urls = []
            char_indices = scene_character_map.get(i, []) if scene_character_map else []
            
            # 【重要修复】多角色提示词绑定
            if len(char_indices) >= 2:
                names = [character_names.get(idx, f"角色{idx}") for idx in char_indices]
                anti_mix = f"【重要约束：画面包含 {
.join(names)}。请严格按照参考图顺序对应他们的外貌，绝不能张冠李戴或将特征混淆！】 "
                prompt = anti_mix + prompt
                
            for idx in char_indices:
                if idx in character_image_urls:
                    ref_urls.append(character_image_urls[idx])
                    
            res = agnes_client.generate_image(prompt=prompt, image_urls=ref_urls if ref_urls else None)
            img_url = res.get("data", [{}])[0].get("url", "")
            if img_url:
                local_path = str(Path(output_dir) / f"ff_{i}.jpg")
                _download_file_robust(img_url, local_path)
                first_frame_urls.append(img_url)
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "image_url": img_url, "local_path": local_path}
            else:
                first_frame_urls.append("")
                task.status = TaskStatus.FAILED
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            first_frame_urls.append("")
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
        finally:
            db.close()
            
    # Phase 2b: 尾帧
    last_frame_urls = []
    for i, task_id in enumerate(last_frame_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                last_frame_urls.append("")
                continue
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            
            ref_urls = []
            char_indices = scene_character_map.get(i, []) if scene_character_map else []
            
            if len(char_indices) >= 2:
                names = [character_names.get(idx, f"角色{idx}") for idx in char_indices]
                anti_mix = f"【重要约束：画面包含 {
.join(names)}。请严格按照参考图顺序对应他们的外貌，绝不能张冠李戴或将特征混淆！】 "
                prompt = anti_mix + prompt
                
            for idx in char_indices:
                if idx in character_image_urls:
                    ref_urls.append(character_image_urls[idx])
                    
            res = agnes_client.generate_image(prompt=prompt, image_urls=ref_urls if ref_urls else None)
            img_url = res.get("data", [{}])[0].get("url", "")
            if img_url:
                local_path = str(Path(output_dir) / f"lf_{i}.jpg")
                _download_file_robust(img_url, local_path)
                last_frame_urls.append(img_url)
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "image_url": img_url, "local_path": local_path}
            else:
                last_frame_urls.append("")
                task.status = TaskStatus.FAILED
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            last_frame_urls.append("")
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
        finally:
            db.close()

    # Phase 3: 视频生成
    output_paths = []
    for i, task_id in enumerate(scene_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                continue
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            
            ff_url = first_frame_urls[i] if i < len(first_frame_urls) else None
            lf_url = last_frame_urls[i] if i < len(last_frame_urls) else None
            
            if ff_url:
                from app.ai.image_to_video import image_to_video
                res = image_to_video(prompt=prompt, image_url=ff_url, end_image_url=lf_url)
                if res.get("success"):
                    vid_url = res.get("video_url")
                    local_path = str(Path(output_dir) / f"vid_{i}.mp4")
                    _download_file_robust(vid_url, local_path)
                    output_paths.append(local_path)
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {"success": True, "video_path": local_path}
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = res.get("error", "未知错误")
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "缺失首帧"
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
        finally:
            db.close()
            
    # Phase 4 & 5
    if other_task_ids or concat_task_id:
        upstream_video = None
        if concat_task_id and len(output_paths) > 0:
            db = SessionLocal()
            try:
                task = db.query(Task).filter(Task.id == concat_task_id).first()
                if task and task.status != TaskStatus.CANCELLED:
                    task.status = TaskStatus.RUNNING
                    db.commit()
                    _push_task_update(task)
                    
                    from app.services.video_service import concat_videos
                    out = str(Path(output_dir) / "final_concat.mp4")
                    upstream_video = concat_videos(output_paths, out)
                    
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {"success": True, "video_path": upstream_video}
                    task.completed_at = datetime.utcnow()
                    db.commit()
                    _push_task_update(task)
            except Exception as e:
                logger.exception("拼接失败")
            finally:
                db.close()
        elif output_paths:
            upstream_video = output_paths[0]
            
        if other_task_ids and upstream_video:
            for tid, ttype in other_task_ids:
                db = SessionLocal()
                try:
                    t = db.query(Task).filter(Task.id == tid).first()
                    if t and t.status != TaskStatus.CANCELLED:
                        p = t.input_params or {}
                        if "video_path" not in p: p["video_path"] = upstream_video
                        if "input_path" not in p: p["input_path"] = upstream_video
                        t.input_params = p
                        db.commit()
                finally:
                    db.close()
                if ttype in ["video_processing", "audio_processing"]:
                    process_video(tid)
                else:
                    run_ai_task(tid)

    _update_workflow_status(workflow_id)
    return {"success": True}
"""
with open("e:/开发/视频工作流/backend/app/workers/tasks.py", "w", encoding="utf-8") as f:
    f.write(content)

