"""Celery 异步任务定义"""

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


def _normalize_image_size(width: int = 1152, height: int = 768) -> str:
    """将任意尺寸映射到 Agnes AI 支持的图片尺寸。
    支持: 1024x1024, 1792x1024, 1024x1792"""
    ratio = width / height if height > 0 else 1.0
    if ratio > 1.3:   # 横屏 (16:9 等)
        return "1792x1024"
    elif ratio < 0.77: # 竖屏 (9:16 等)
        return "1024x1792"
    else:               # 方屏
        return "1024x1024"


def _generate_image_robust(agnes_client, prompt: str, size: str = "1792x1024",
                           image_urls: list | None = None, max_retries: int = 5) -> dict:
    """带自动重试的图片生成，解决 Agnes API 偶发的连接断开和服务器繁忙问题"""
    import time
    import random
    last_err = None
    for attempt in range(max_retries):
        try:
            return agnes_client.generate_image(prompt=prompt, size=size, image_urls=image_urls)
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            is_503 = any(kw in err_msg for kw in [
                "503", "繁忙", "busy", "service unavailable", "overloaded",
            ])
            is_network = any(kw in err_msg for kw in [
                "disconnect", "timeout", "connection", "ssl", "eof", "reset", "pool",
            ])
            is_download_fail = any(kw in err_msg for kw in [
                "下载图片失败", "download image", "upstream_error",
            ])
            if is_503:
                # 服务器繁忙：更长的等待时间 + 随机抖动避免并发冲突
                # 20s, 45s, 70s, 100s, 130s（加随机 0-10s）
                wait = 20 + 25 * attempt + random.randint(0, 10)
                logger.warning(f"Agnes API 503 服务器繁忙(尝试 {attempt+1}/{max_retries})，{wait}s 后重试")
                time.sleep(wait)
            elif is_download_fail:
                wait = 15 * (attempt + 1)
                logger.warning(f"Agnes 服务器下载图片失败(尝试 {attempt+1}/{max_retries})，{wait}s 后重试: {e}")
                time.sleep(wait)
            elif is_network:
                wait = 10 * (attempt + 1)
                logger.warning(f"图片生成网络错误(尝试 {attempt+1}/{max_retries})，{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                raise
    raise last_err


# Agnes API 服务器无法下载的图床域名
_UNRELIABLE_HOSTS = ["tmpfiles.org", "0x0.st"]


def _ensure_image_urls_accessible(image_urls: list[str] | None) -> list[str] | None:
    """确保图片 URL 对 Agnes API 服务器可达。
    
    处理三种情况:
    1. 本地 API 路径 (/api/agent/reference/file/xxx) → 转为自托管 URL 或重传图床
    2. 不可靠图床 URL → 从本地/网络获取后重传
    3. 其他 URL → 直接保留
    """
    if not image_urls:
        return image_urls

    import httpx
    import json as _json
    from pathlib import Path as _Path
    from app.ai.agnes_client import AgnesClient

    # 从 index.json 加载本地文件路径映射
    _url_to_local = {}
    _index_path = _Path(__file__).parent.parent.parent / "storage" / "references" / "index.json"
    try:
        if _index_path.exists():
            with open(_index_path, "r", encoding="utf-8") as f:
                for entry in _json.load(f):
                    if entry.get("url") and entry.get("local_path"):
                        _url_to_local[entry["url"]] = entry["local_path"]
    except Exception:
        pass

    result = []
    for url in image_urls:
        # 情况1: 本地 API 路径（未配置 PUBLIC_BASE_URL 时的参考图）
        if url.startswith("/api/agent/reference/file/"):
            filename = url.split("/")[-1]
            local_path = settings.STORAGE_DIR / "references" / filename
            if local_path.exists():
                image_data = local_path.read_bytes()
                # 优先上传到图床获取公网 URL（Agnes img2img 需要可下载的 URL）
                new_url = AgnesClient.upload_image_data(image_data, filename)
                if new_url and not new_url.startswith("data:"):
                    logger.info(f"本地参考图上传到图床: {new_url[:80]}")
                    result.append(new_url)
                    continue
                # 回退: 自托管 URL
                public_url = AgnesClient.get_public_url_for_local_file(str(local_path))
                if public_url:
                    logger.info(f"本地参考图转自托管 URL: {public_url}")
                    result.append(public_url)
                    continue
                # 最终回退: base64 data URI
                try:
                    data_uri = AgnesClient.bytes_to_data_uri(image_data, filename)
                    logger.info(f"本地参考图转 base64 data URI (大小: {len(data_uri)//1024}KB)")
                    result.append(data_uri)
                    continue
                except Exception as e:
                    logger.warning(f"Base64 转换也失败: {e}")
            logger.warning(f"本地参考图文件不存在: {local_path}，保留原 URL")
            result.append(url)
            continue

        # 情况2: 不可靠图床
        is_unreliable = any(host in url for host in _UNRELIABLE_HOSTS)
        if not is_unreliable:
            result.append(url)
            continue

        # 不可靠图床：优先从本地文件读取，否则从网络下载
        logger.info(f"检测到不可靠图床 URL，尝试重新上传: {url[:80]}...")
        image_data = None

        # 方式1：从本地文件读取（最可靠）
        local_path = _url_to_local.get(url, "")
        if local_path and _Path(local_path).exists():
            try:
                image_data = _Path(local_path).read_bytes()
                logger.info(f"从本地文件读取成功: {local_path}")
            except Exception as e:
                logger.warning(f"本地文件读取失败: {e}")

        # 方式2：从网络下载
        if image_data is None:
            try:
                with httpx.Client(timeout=60.0) as client:
                    resp = client.get(url, follow_redirects=True)
                    resp.raise_for_status()
                    image_data = resp.content
                logger.info(f"从网络下载成功: {url[:80]}")
            except Exception as e:
                logger.warning(f"网络下载也失败: {e}")

        if image_data:
            new_url = AgnesClient.upload_image_data(image_data)
            if new_url:
                result.append(new_url)
                continue
            logger.warning(f"所有图床重传失败，保留原 URL")
        else:
            logger.warning(f"无法获取图片数据(本地+网络均失败)")

        result.append(url)

    return result


# 角色设定图 prompt 中需要去除的无关后缀
_STRIP_KEYWORDS = [
    "ON A PURE WHITE BACKGROUND", "CONSISTENT FEATURES",
    "clean studio lighting", "professional concept art",
    "FULL BODY character design sheet", "front and 3/4 view",
]


def _build_identity_prompt(
    char_indices: list[int],
    character_names: dict[int, str],
    character_prompts: dict[int, str],
    character_image_urls: dict[int, list[str]],
    scene_prompt: str,
    mode: str = "image",
    provided_urls: dict[int, str] | None = None,
    scene_design_url: str = "",
) -> tuple[str, list[str]]:
    """
    构建带角色身份强绑定的增强 prompt。
    
    Args:
        char_indices: 场景角色索引列表
        character_names: {idx: name}
        character_prompts: {idx: 角色详细外貌英文 prompt}
        character_image_urls: {idx: [角色设定图 URL 列表]} (主肖像、三视图、表情图、饰品图)
        scene_prompt: 原始场景 prompt
        mode: "image"(首帧/尾帧) 或 "video"(图生视频)
        provided_urls: {idx: 用户提供的原始参考图 URL}（区分用户参考图 vs AI 生成图）
        scene_design_url: 场景环境设计图 URL
    
    Returns:
        (final_prompt, ref_urls)
    """
    provided_urls = provided_urls or {}
    ref_urls = []
    identity_blocks = []
    all_names = []
    has_user_ref = False  # 是否有用户提供的参考图

    for idx in char_indices:
        name = character_names.get(idx, f"角色{idx}")
        all_names.append(name)

        # 提取角色外貌核心描述
        char_appearance = character_prompts.get(idx, "")
        for strip_kw in _STRIP_KEYWORDS:
            char_appearance = char_appearance.replace(strip_kw, "").strip(" ,.")

        user_ref = provided_urls.get(idx, "")
        gen_refs = character_image_urls.get(idx, [])
        if isinstance(gen_refs, str):
            gen_refs = [gen_refs]  # 向后兼容

        if user_ref:
            # 用户提供的参考图 —— 最高优先级
            has_user_ref = True
            ref_urls.append(user_ref)
            ref_num = len(ref_urls)
            # 如果 AI 生成的设定图，全部作为参考
            added_gen = []
            for gen_url in gen_refs:
                if gen_url and gen_url != user_ref:
                    ref_urls.append(gen_url)
                    added_gen.append(len(ref_urls))

            identity_blocks.append(
                f"[USER REFERENCE IMAGE #{ref_num} = {name} (ABSOLUTE GROUND TRUTH)]:\n"
                f"  Appearance Description: {char_appearance}\n"
                f"  >>> CRITICAL: This is the USER'S ORIGINAL REFERENCE. The character '{name}' "
                f"in the output MUST be a PIXEL-PERFECT REPRODUCTION of Reference Image #{ref_num}.\n"
                f"  You MUST replicate EXACTLY: same face shape, same eye color, same hairstyle and hair color, "
                f"same body build and proportions, same costume design, same armor shape and color scheme, "
                f"same weapon design, same accessories, same material textures.\n"
                f"  DO NOT redesign, reimagine, simplify, or alter ANY visual aspect of this character. "
                f"Treat it as a PHOTOGRAPHIC BLUEPRINT."
                + (f"\n  [Additional design sheets #{added_gen} show the same character from multiple angles for reference.]"
                   if added_gen else "")
            )
        elif gen_refs:
            # AI 生成的多张设定图全部作为参考
            first_ref_num = len(ref_urls) + 1
            for gen_url in gen_refs:
                if gen_url:
                    ref_urls.append(gen_url)
            ref_num = first_ref_num
            identity_blocks.append(
                f"[Reference Images #{first_ref_num} = {name}]:\n"
                f"  Appearance: {char_appearance}\n"
                f"  >>> MANDATORY: The character '{name}' in the output MUST be a DIRECT REPRODUCTION "
                f"of Reference Image #{ref_num}. Copy EXACTLY: "
                f"same facial features, same hairstyle and hair color, same body proportions, "
                f"same costume design and colors, same armor/weapon design, same accessories. "
                f"Treat the reference image as a PHOTOGRAPHIC BLUEPRINT - replicate it pixel-perfectly "
                f"in the new scene context. DO NOT redesign, reimagine, or alter ANY visual aspect."
            )
        elif char_appearance:
            identity_blocks.append(
                f"[Character {name} (text description only)]: {char_appearance}\n"
                f"  >>> {name} MUST maintain this EXACT appearance throughout."
            )

    enhanced_parts = []
    n = len(all_names)

    # 最高优先级：参考图严格复制指令
    if ref_urls:
        ref_compliance = (
            "【⚠️ REFERENCE IMAGE STRICT COMPLIANCE - HIGHEST PRIORITY ⚠️】\n"
            f"You are provided with {len(ref_urls)} reference image(s). "
            "These are NOT inspiration or style guides - they are EXACT VISUAL SPECIFICATIONS.\n"
            "For EACH reference image:\n"
            "- Copy the character's face, hair, costume, armor, weapons, accessories EXACTLY as shown\n"
            "- Preserve the EXACT color palette, material textures, and design details\n"
            "- The character in your output MUST be recognizably the SAME person/creature as in the reference\n"
            "- If the reference shows a blue armored warrior, your output MUST show a blue armored warrior "
            "with the SAME armor design, SAME helmet shape, SAME color scheme\n"
            "- NEVER substitute, redesign, or 'improve' the reference character's appearance\n"
        )
        if has_user_ref:
            ref_compliance += (
                "\n⚠️ USER-PROVIDED REFERENCES ARE SACRED: These images were given by the user as the "
                "EXACT visual specification. The user expects the generated characters to look IDENTICAL "
                "to their reference images. Any deviation in face, hair, costume, color, or body type "
                "is a CRITICAL FAILURE. Match the reference images as closely as physically possible."
            )
        enhanced_parts.append(ref_compliance)

    # 场景环境参考
    if scene_design_url:
        ref_urls.append(scene_design_url)
        scene_ref_num = len(ref_urls)
        enhanced_parts.append(
            f"【SCENE ENVIRONMENT REFERENCE】\n"
            f"Reference Image #{scene_ref_num} shows the environment/background for this scene. "
            f"Use it as the background setting reference. Characters should be placed WITHIN this environment."
        )

    if n >= 1 and identity_blocks:
        names_str = ", ".join(all_names)
        enhanced_parts.append(
            f"【CHARACTER IDENTITY LOCK】\n"
            f"EXACTLY {n} character(s): {names_str}.\n"
            f"Each character below is bound to a specific reference image. "
            f"Their appearance is PERMANENTLY LOCKED - no variations allowed.\n\n"
            + "\n".join(identity_blocks)
        )

    if n >= 2:
        names_str = " and ".join(all_names)
        enhanced_parts.append(
            f"【ANTI-IDENTITY-SWAP】\n"
            f"STRICT SEPARATION: {names_str} must be visually DISTINCT at all times.\n"
            f"DO NOT swap faces, costumes, weapons, hair colors, armor colors, or body types.\n"
            f"DO NOT add extra people, extra limbs, or extra characters.\n"
            f"Each character's visual identity is LOCKED to their reference image - PERMANENT and UNCHANGEABLE."
        )

    if mode == "video":
        enhanced_parts.append(
            "【MOTION IDENTITY PRESERVATION】\n"
            "During the entire video motion, each character's appearance MUST remain 100% consistent "
            "from the first frame to the last frame. NO gradual changes in face, hair, costume, or body shape. "
            "The character in the final frame MUST be visually IDENTICAL to the character in the starting frame, "
            "except for pose/action changes described in the prompt."
        )

    enhanced_parts.append(scene_prompt)

    final_prompt = "\n\n".join(enhanced_parts)
    return final_prompt, ref_urls

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
    """更新任务状态"""
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
    """推送任务状态更新（通过 Redis Pub/Sub）"""
    try:
        import redis as redis_lib
        from app.config import settings
        r = redis_lib.Redis.from_url(settings.redis_url)
        r.publish(f"task:{task.id}", json.dumps(task.to_dict(), ensure_ascii=False))
    except Exception:
        pass

def _update_workflow_status(workflow_id: str):
    """更新工作流状态"""
    from app.services.workflow_service import update_workflow_status
    update_workflow_status(workflow_id)

@celery_app.task(bind=True, name="app.workers.tasks.run_ai_task")
def run_ai_task(self, task_id: str):
    """执行单个常规 AI 任务"""
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
            out_dir = str(Path(params.get("output_dir", "./storage/temp")) / f"sub_{_uuid.uuid4().hex[:8]}")
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            res = generate_subtitle(video_path=params.get("audio_path", ""), output_dir=out_dir)
            task.output_result = {"success": True, "subtitle_path": res.srt_path if res.success else None, "error": res.error}
            
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
    """执行视频处理任务"""
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
    scene_design_task_ids: list[str] | None = None,
    scene_design_map: dict[int, str] | None = None,
):
    """
    执行完整的视频生成 Agent 工作流（支持断点恢复和自动跳过已完成任务）。
    """
    from app.ai.agnes_client import get_agnes_client
    from app.config import settings
    from app.services.workflow_service import update_workflow_status
    
    agnes_client = get_agnes_client()
    output_dir = str(settings.OUTPUT_DIR / f"agent_{_uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    if scene_character_map:
        scene_character_map = {int(k): v for k, v in scene_character_map.items()}
    if scene_design_map:
        scene_design_map = {int(k): v for k, v in scene_design_map.items()}
    if scene_design_task_ids is None:
        scene_design_task_ids = []
        
    # Phase 1: 角色设定图（每角色 1 张综合设定图，基于参考图 img2img 或纯文生图）
    character_image_urls = {}  # {char_index: [url]}
    character_names = {}
    phase1_failed = False
    
    for i, task_id in enumerate(character_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                continue
                
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            char_name = params.get("character_name", f"角色{i}")
            char_idx = params.get("character_index", i)
            provided_url = params.get("provided_url", "")
            character_names[char_idx] = char_name
            
            # 幂等判断：如果已经完成，直接取结果并跳过
            if task.status == TaskStatus.COMPLETED:
                out = task.output_result or {}
                if out.get("image_url"):
                    character_image_urls.setdefault(char_idx, []).append(out["image_url"])
                elif provided_url:
                    character_image_urls.setdefault(char_idx, []).append(provided_url)
                continue
                
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            # 有参考图时先确保 URL 可访问，再做 img2img
            ref_for_gen = None
            if provided_url:
                logger.info(f"角色 {char_name} 原始参考图: {provided_url[:80]}")
                safe_urls = _ensure_image_urls_accessible([provided_url])
                ref_for_gen = safe_urls if safe_urls else None
                if ref_for_gen:
                    for u in ref_for_gen:
                        is_data = u.startswith("data:")
                        logger.info(f"角色 {char_name} img2img URL: {'[base64 data URI]' if is_data else u[:100]}")
            res = _generate_image_robust(agnes_client, prompt=prompt, image_urls=ref_for_gen)
            img_url = res.get("data", [{}])[0].get("url", "")
            if img_url:
                local_path = str(Path(output_dir) / f"char_{char_idx}.jpg")
                _download_file_robust(img_url, local_path)
                character_image_urls.setdefault(char_idx, []).append(img_url)
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "image_url": img_url, "local_path": local_path}
                if provided_url:
                    logger.info(f"角色 {char_name} 基于参考图 img2img 生成完成")
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "生成失败"
                phase1_failed = True
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
            phase1_failed = True
        finally:
            db.close()
            
    if phase1_failed:
        update_workflow_status(workflow_id)
        return {"success": False, "status": "paused", "error": "Phase 1 (角色设计) failed"}

    # Phase 1b: 场景环境设计
    scene_design_urls = {}  # {scene_index: url}
    phase1b_failed = False
    
    for i, task_id in enumerate(scene_design_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                continue
                
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            scene_idx = params.get("scene_index", i)
            
            # 幂等判断
            if task.status == TaskStatus.COMPLETED:
                out = task.output_result or {}
                if out.get("image_url"):
                    scene_design_urls[scene_idx] = out["image_url"]
                continue
            
            if not prompt:
                # 没有环境 prompt，跳过
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "skipped": True}
                task.completed_at = datetime.utcnow()
                db.commit()
                _push_task_update(task)
                continue
            
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            res = _generate_image_robust(agnes_client, prompt=prompt)
            img_url = res.get("data", [{}])[0].get("url", "")
            if img_url:
                local_path = str(Path(output_dir) / f"scene_design_{scene_idx}.jpg")
                _download_file_robust(img_url, local_path)
                scene_design_urls[scene_idx] = img_url
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "image_url": img_url, "local_path": local_path}
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "生成失败"
                phase1b_failed = True
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
            phase1b_failed = True
        finally:
            db.close()
    
    if phase1b_failed:
        update_workflow_status(workflow_id)
        return {"success": False, "status": "paused", "error": "Phase 1b (场景设计) failed"}

    # 从数据库中预取所有角色的 image_prompt 和 provided_url
    character_prompts = {}
    provided_urls = {}
    for i, task_id in enumerate(character_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task and task.input_params:
                char_idx = task.input_params.get("character_index", i)
                character_prompts[char_idx] = task.input_params.get("prompt", "")
                pu = task.input_params.get("provided_url", "")
                if pu:
                    provided_urls[char_idx] = pu
        finally:
            db.close()

    # Phase 2a: 首帧（只有 scene 0 需要生成首帧）
    scene0_ff_url = ""
    phase2a_failed = False
    for i, task_id in enumerate(first_frame_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                continue
                
            if task.status == TaskStatus.COMPLETED:
                out = task.output_result or {}
                if out.get("image_url"):
                    scene0_ff_url = out["image_url"]
                continue
                
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            scene_idx = params.get("scene_index", i)
            
            char_indices = scene_character_map.get(scene_idx, []) if scene_character_map else []
            sd_url = scene_design_urls.get(scene_idx, "")
            final_prompt, ref_urls = _build_identity_prompt(
                char_indices, character_names, character_prompts,
                character_image_urls, prompt, mode="image",
                provided_urls=provided_urls,
                scene_design_url=sd_url,
            )
            ref_urls = _ensure_image_urls_accessible(ref_urls)
                    
            res = _generate_image_robust(agnes_client, prompt=final_prompt, image_urls=ref_urls if ref_urls else None)
            img_url = res.get("data", [{}])[0].get("url", "")
            if img_url:
                local_path = str(Path(output_dir) / f"ff_{scene_idx}.jpg")
                _download_file_robust(img_url, local_path)
                scene0_ff_url = img_url
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.output_result = {"success": True, "image_url": img_url, "local_path": local_path}
            else:
                task.status = TaskStatus.FAILED
                phase2a_failed = True
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
            phase2a_failed = True
        finally:
            db.close()
            
    if phase2a_failed:
        update_workflow_status(workflow_id)
        return {"success": False, "status": "paused", "error": "Phase 2a (首帧) failed"}
            
    # Phase 2b: 尾帧
    last_frame_urls = []
    phase2b_failed = False
    for i, task_id in enumerate(last_frame_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                last_frame_urls.append("")
                continue
                
            if task.status == TaskStatus.COMPLETED:
                out = task.output_result or {}
                last_frame_urls.append(out.get("image_url", ""))
                continue
                
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            
            char_indices = scene_character_map.get(i, []) if scene_character_map else []
            sd_url = scene_design_urls.get(i, "")
            final_prompt, ref_urls = _build_identity_prompt(
                char_indices, character_names, character_prompts,
                character_image_urls, prompt, mode="image",
                provided_urls=provided_urls,
                scene_design_url=sd_url,
            )
            ref_urls = _ensure_image_urls_accessible(ref_urls)
                    
            res = _generate_image_robust(agnes_client, prompt=final_prompt, image_urls=ref_urls if ref_urls else None)
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
                phase2b_failed = True
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            last_frame_urls.append("")
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
            phase2b_failed = True
        finally:
            db.close()

    if phase2b_failed:
        update_workflow_status(workflow_id)
        return {"success": False, "status": "paused", "error": "Phase 2b (尾帧) failed"}

    # 构建链式帧复用的 first_frame_urls 数组
    num_scenes = len(last_frame_urls)
    first_frame_urls = []
    for si in range(num_scenes):
        if si == 0:
            first_frame_urls.append(scene0_ff_url)
        else:
            prev_lf = last_frame_urls[si - 1] if si - 1 < len(last_frame_urls) else ""
            first_frame_urls.append(prev_lf)

    # Phase 3: 视频生成
    output_paths = []
    phase3_failed = False
    for i, task_id in enumerate(scene_task_ids):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task or task.status == TaskStatus.CANCELLED:
                output_paths.append("")
                continue
                
            if task.status == TaskStatus.COMPLETED:
                out = task.output_result or {}
                output_paths.append(out.get("video_path", ""))
                continue
                
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
            
            params = task.input_params or {}
            prompt = params.get("prompt", "")
            
            char_indices = scene_character_map.get(i, []) if scene_character_map else []
            final_prompt, _ = _build_identity_prompt(
                char_indices, character_names, character_prompts,
                {}, prompt, mode="video", provided_urls=provided_urls,
            )
            
            ff_url = first_frame_urls[i] if i < len(first_frame_urls) else None
            lf_url = last_frame_urls[i] if i < len(last_frame_urls) else None
            
            if ff_url:
                from app.ai.image_to_video import image_to_video
                if lf_url:
                    res = image_to_video(prompt=final_prompt, image_paths=[ff_url, lf_url], mode="keyframes", duration=task.input_params.get("duration", 5.0))
                else:
                    res = image_to_video(prompt=final_prompt, image_url=ff_url, mode="i2v", duration=task.input_params.get("duration", 5.0))
                
                if res.success:
                    local_path = res.output_path
                    vid_url = res.video_url
                    output_paths.append(local_path)
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {"success": True, "video_path": local_path, "video_url": vid_url}
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = res.error or "未知错误"
                    output_paths.append("")
                    phase3_failed = True
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "缺失首帧"
                output_paths.append("")
                phase3_failed = True
                
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        except Exception as e:
            output_paths.append("")
            if "task" in locals() and task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
            phase3_failed = True
        finally:
            db.close()
            
    if phase3_failed:
        update_workflow_status(workflow_id)
        return {"success": False, "status": "paused", "error": "Phase 3 (视频生成) failed"}

    # Phase 3.5: 分镜级台词 TTS 配音合成
    for i, task_id in enumerate(scene_task_ids):
        if i >= len(output_paths) or not output_paths[i]:
            continue
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                continue
                
            # 幂等判断：如果 output_result 里的 video_path 已经带 _voiced.mp4，说明配过音了
            out = task.output_result or {}
            current_video_path = out.get("video_path", "")
            if current_video_path and current_video_path.endswith("_voiced.mp4"):
                output_paths[i] = current_video_path
                continue
                
            params = task.input_params or {}
            dialogue = params.get("dialogue", "").strip()
            if not dialogue:
                continue

            from app.ai.voice_synthesis import synthesize_voice
            tts_result = synthesize_voice(
                text=dialogue,
                voice=params.get("voice", "zh-CN-YunxiNeural"),
                output_dir=output_dir,
            )
            if not tts_result.success or not tts_result.audio_path:
                logger.warning(f"场景 {i} TTS 合成失败: {tts_result.error} (继续拼合无声视频)")
                continue

            from app.services.video_service import merge_audio_video
            merged_path = str(Path(output_dir) / f"scene_{i}_voiced.mp4")
            merge_audio_video(output_paths[i], tts_result.audio_path, merged_path)
            output_paths[i] = merged_path
            
            # 将合并后的路径存回数据库，以便恢复或下游使用
            out["video_path"] = merged_path
            task.output_result = out
            db.commit()
            _push_task_update(task)
        except Exception as e:
            logger.warning(f"场景 {i} 台词配音异常，跳过: {e}")
        finally:
            db.close()

    # Phase 4 & 5
    if other_task_ids or concat_task_id:
        upstream_video = None
        valid_outputs = [p for p in output_paths if p]
        if concat_task_id and len(valid_outputs) > 0:
            db = SessionLocal()
            try:
                task = db.query(Task).filter(Task.id == concat_task_id).first()
                if task and task.status != TaskStatus.CANCELLED:
                    if task.status == TaskStatus.COMPLETED:
                        upstream_video = (task.output_result or {}).get("video_path")
                    else:
                        task.status = TaskStatus.RUNNING
                        db.commit()
                        _push_task_update(task)
                        
                        from app.services.video_service import concat_videos
                        out = str(Path(output_dir) / "final_concat.mp4")
                        upstream_video = concat_videos(valid_outputs, out)
                        
                        task.status = TaskStatus.COMPLETED
                        task.progress = 100
                        task.output_result = {"success": True, "video_path": upstream_video}
                        task.completed_at = datetime.utcnow()
                        db.commit()
                        _push_task_update(task)
            except Exception as e:
                logger.exception("拼接失败")
                if "task" in locals() and task:
                    task.status = TaskStatus.FAILED
                    task.error_message = str(e)
                    db.commit()
                update_workflow_status(workflow_id)
                return {"success": False, "status": "paused", "error": "Phase 4 (拼接) failed"}
            finally:
                db.close()
        elif valid_outputs:
            upstream_video = valid_outputs[0]
            
        if other_task_ids and upstream_video:
            for tid, ttype in other_task_ids:
                db = SessionLocal()
                try:
                    t = db.query(Task).filter(Task.id == tid).first()
                    if t and t.status != TaskStatus.CANCELLED and t.status != TaskStatus.COMPLETED:
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

    update_workflow_status(workflow_id)
    return {"success": True}

# ============================================================
# 单任务重跑 Celery 任务
# ============================================================

@celery_app.task(bind=True, name="app.workers.tasks.run_single_task")
def run_single_task(self, task_id: str):
    """
    重新执行单个任务（用于局部重跑）。
    根据任务类型和 action 参数执行对应的生成逻辑。
    """
    from app.ai.agnes_client import get_agnes_client

    db = SessionLocal()
    task = None
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return {"error": "任务不存在"}

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        task.progress = 0
        db.commit()
        _push_task_update(task)

        params = task.input_params or {}
        action = params.get("action", "")
        task_type = task.task_type.value if hasattr(task.task_type, "value") else str(task.task_type)
        prompt = params.get("prompt", "")

        agnes_client = get_agnes_client()

        if task_type == "image_generation":
            # ------ 角色设定图 ------
            if action == "character_design":
                provided_url = params.get("provided_url", "")
                # 有参考图时先确保 URL 可访问，再做 img2img
                ref_for_gen = None
                if provided_url:
                    safe_urls = _ensure_image_urls_accessible([provided_url])
                    ref_for_gen = safe_urls if safe_urls else None
                res = _generate_image_robust(agnes_client, prompt=prompt, image_urls=ref_for_gen)
                img_url = res.get("data", [{}])[0].get("url", "")
                if img_url:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {"success": True, "image_url": img_url}
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = "未获取到图片URL"

            # ------ 场景环境设计图 ------
            elif action == "scene_design":
                res = _generate_image_robust(agnes_client, prompt=prompt)
                img_url = res.get("data", [{}])[0].get("url", "")
                if img_url:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {"success": True, "image_url": img_url}
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = "未获取到图片URL"

            # ------ 首帧 / 尾帧 ------
            elif action in ("first_frame", "last_frame", "keyframe"):
                width = params.get("width", 1152)
                height = params.get("height", 768)
                scene_idx = params.get("scene_index", 0)

                # 查询同工作流的角色设定任务，构建身份绑定 prompt
                workflow_id = task.workflow_id
                char_tasks = (
                    db.query(Task)
                    .filter(Task.workflow_id == workflow_id)
                    .filter(Task.task_type == "image_generation")
                    .all()
                )
                char_names = {}
                char_prompts = {}
                char_img_urls = {}   # {char_index: [url1, url2, ...]}
                prov_urls = {}
                for ct in char_tasks:
                    cp = ct.input_params or {}
                    if cp.get("action") != "character_design":
                        continue
                    ci = cp.get("character_index", len(char_names))
                    char_names[ci] = cp.get("character_name", f"角色{ci}")
                    out = ct.output_result or {}
                    img = out.get("image_url", "")
                    if img:
                        char_img_urls.setdefault(ci, []).append(img)
                    char_prompts[ci] = cp.get("prompt", "")
                    pu = cp.get("provided_url", "")
                    if pu:
                        prov_urls[ci] = pu

                # 查找场景环境设计图
                sd_url = ""
                sd_tasks = (
                    db.query(Task)
                    .filter(Task.workflow_id == workflow_id)
                    .filter(Task.task_type == "image_generation")
                    .all()
                )
                for sdt in sd_tasks:
                    sp = sdt.input_params or {}
                    if sp.get("action") == "scene_design" and sp.get("scene_index") == scene_idx:
                        sd_out = sdt.output_result or {}
                        sd_url = sd_out.get("image_url", "")
                        break

                # 获取场景角色映射
                scene_chars = params.get("scene_characters", [])
                char_indices = []
                for name in scene_chars:
                    for ci, cn in char_names.items():
                        if cn == name or name.lower() in cn.lower() or cn.lower() in name.lower():
                            char_indices.append(ci)
                            break
                if not char_indices:
                    # 回退：使用所有角色
                    char_indices = list(char_names.keys())

                enhanced_prompt, ref_urls = _build_identity_prompt(
                    char_indices, char_names, char_prompts,
                    char_img_urls, prompt, mode="image",
                    provided_urls=prov_urls,
                    scene_design_url=sd_url,
                )
                ref_urls = _ensure_image_urls_accessible(ref_urls)

                res = _generate_image_robust(
                    agnes_client,
                    prompt=enhanced_prompt,
                    size=_normalize_image_size(width, height),
                    image_urls=ref_urls if ref_urls else None,
                )
                img_url = res.get("data", [{}])[0].get("url", "")
                if img_url:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {"success": True, "image_url": img_url}
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = "未获取到图片URL"

            else:
                task.status = TaskStatus.FAILED
                task.error_message = f"不支持的 image_generation action: {action}"

        elif task_type == "image_to_video":
            # ------ 图生视频 ------
            # 找到同工作流的首帧/尾帧任务，获取其 output_result 中的 image_url
            workflow_id = task.workflow_id
            scene_idx = params.get("scene_index", 0)

            # 查询同工作流中该场景的首帧/尾帧 URL
            sibling_tasks = (
                db.query(Task)
                .filter(Task.workflow_id == workflow_id, Task.id != task_id)
                .filter(Task.status == TaskStatus.COMPLETED)
                .all()
            )
            ff_url = None
            lf_url = None
            for st in sibling_tasks:
                sp = st.input_params or {}
                if sp.get("scene_index") == scene_idx:
                    sa = sp.get("action", "")
                    out = st.output_result or {}
                    if sa == "first_frame" and out.get("image_url"):
                        ff_url = out["image_url"]
                    elif sa == "last_frame" and out.get("image_url"):
                        lf_url = out["image_url"]

            # 链式帧复用：如果当前场景没有首帧，查找上一场景的尾帧
            if not ff_url and scene_idx > 0:
                for st in sibling_tasks:
                    sp = st.input_params or {}
                    if sp.get("scene_index") == scene_idx - 1 and sp.get("action") == "last_frame":
                        out = st.output_result or {}
                        if out.get("image_url"):
                            ff_url = out["image_url"]
                            logger.info(f"单任务重跑: 场景 {scene_idx} 链式复用场景 {scene_idx-1} 的尾帧作为首帧")
                        break

            from app.ai.image_to_video import image_to_video
            duration = params.get("duration", 5.0)

            if ff_url:
                if lf_url:
                    result = image_to_video(prompt=prompt, image_paths=[ff_url, lf_url], mode="keyframes", duration=duration)
                else:
                    result = image_to_video(prompt=prompt, image_url=ff_url, mode="i2v", duration=duration)

                if result.success:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.output_result = {"success": True, "video_path": result.output_path, "video_url": result.video_url}
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = result.error or "视频生成失败"
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "缺失首帧图片，请先生成首帧"

        else:
            task.status = TaskStatus.FAILED
            task.error_message = f"不支持的任务类型: {task_type}"

        task.completed_at = datetime.utcnow()
        db.commit()
        _push_task_update(task)
        return {"success": task.status == TaskStatus.COMPLETED}

    except Exception as e:
        logger.exception(f"单任务重跑失败 {task_id}: {e}")
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            db.commit()
            _push_task_update(task)
        return {"error": str(e)}
    finally:
        db.close()
