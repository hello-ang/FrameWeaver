"""AI 智能体 API 路由"""

import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.agent.agent_core import get_agent, AgentPlan
from app.agent.executor import AgentExecutor
from app.agent.reference_store import get_reference_store
from app.ai.agnes_client import AgnesClient
from app.config import settings

router = APIRouter()


# ===== Request / Response Schemas =====

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    project_id: Optional[str] = Field(None, description="关联项目ID（可选）")
    references: list[dict] = Field(default_factory=list, description="引用的参考图 [{name, ref_type, url}]")


class PlanResponse(BaseModel):
    plan_id: str
    title: str
    total_duration: float
    characters: list[dict] = []
    scenes: list[dict]
    # 全局锁定参数
    global_style: str = "cinematic"
    global_negative_prompt: str = ""
    global_camera_motion: str = "static"
    width: int = 1152
    height: int = 768
    # 配音/字幕
    enable_voiceover: bool
    enable_subtitle: bool
    voiceover_text: str
    voiceover_voice: str
    status: str
    user_request: str
    error: Optional[str] = None


class ConfirmRequest(BaseModel):
    plan_id: str = Field(..., description="计划ID")
    project_id: Optional[str] = Field(None, description="项目ID（可选，不填则自动创建）")


class AdjustRequest(BaseModel):
    plan_id: str = Field(..., description="计划ID")
    adjustments: list[dict] = Field(..., description="调整列表")


class ExecutionResponse(BaseModel):
    success: bool
    workflow_id: Optional[str] = None
    project_id: Optional[str] = None
    task_ids: Optional[list[str]] = None
    error: Optional[str] = None


class TaskRerunRequest(BaseModel):
    prompt: Optional[str] = Field(None, description="修改后的提示词（可选）")


class TaskPromptUpdateRequest(BaseModel):
    prompt: str = Field(..., description="新的提示词")


# ===== API Endpoints =====

@router.post("/chat", response_model=PlanResponse)
async def agent_chat(req: ChatRequest):
    """
    用户发送消息，AI 智能体分析并返回工作流计划。

    示例:
    ```json
    {"message": "我要一个功夫熊猫打架的视频，30秒"}
    ```
    """
    agent = get_agent()

    plan = agent.plan_from_user_request(req.message, references=req.references)

    if req.project_id:
        plan.project_id = req.project_id
        agent.cache_plan(plan)

    if plan.status == "failed":
        raise HTTPException(status_code=500, detail=plan.error)

    return PlanResponse(
        plan_id=plan.plan_id,
        title=plan.title,
        total_duration=plan.total_duration,
        characters=[c.__dict__ if hasattr(c, '__dict__') else c for c in plan.characters],
        scenes=[s.__dict__ if hasattr(s, '__dict__') else s for s in plan.scenes],
        global_style=plan.global_style,
        global_negative_prompt=plan.global_negative_prompt,
        global_camera_motion=plan.global_camera_motion,
        width=plan.width,
        height=plan.height,
        enable_voiceover=plan.enable_voiceover,
        enable_subtitle=plan.enable_subtitle,
        voiceover_text=plan.voiceover_text,
        voiceover_voice=plan.voiceover_voice,
        status=plan.status,
        user_request=plan.user_request,
        error=plan.error,
    )


@router.post("/confirm", response_model=ExecutionResponse)
async def agent_confirm(req: ConfirmRequest):
    """
    用户确认执行工作流计划。

    智能体会自动:
    1. 创建/关联项目
    2. 创建工作流（nodes + edges）
    3. 创建所有任务
    4. 提交到 Celery 执行
    """
    agent = get_agent()
    plan = agent.get_plan(req.plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在或已过期")

    if req.project_id:
        plan.project_id = req.project_id

    executor = AgentExecutor()
    result = executor.execute_plan(plan)

    # 更新缓存中的计划
    agent.cache_plan(plan)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "执行失败"))

    return ExecutionResponse(
        success=True,
        workflow_id=result["workflow_id"],
        project_id=result["project_id"],
        task_ids=result["task_ids"],
    )


@router.post("/adjust", response_model=PlanResponse)
async def agent_adjust(req: AdjustRequest):
    """
    用户微调工作流计划的某个分镜参数。

    示例:
    ```json
    {
        "plan_id": "xxx",
        "adjustments": [
            {"scene_index": 0, "prompt_cn": "功夫熊猫在竹林中练太极"},
            {"scene_index": 1, "duration": 12}
        ]
    }
    ```
    """
    agent = get_agent()
    plan = agent.adjust_plan(req.plan_id, req.adjustments)

    if plan.status == "failed":
        raise HTTPException(status_code=400, detail=plan.error)

    return PlanResponse(
        plan_id=plan.plan_id,
        title=plan.title,
        total_duration=plan.total_duration,
        characters=[c.__dict__ if hasattr(c, '__dict__') else c for c in plan.characters],
        scenes=[s.__dict__ if hasattr(s, '__dict__') else s for s in plan.scenes],
        global_style=plan.global_style,
        global_negative_prompt=plan.global_negative_prompt,
        global_camera_motion=plan.global_camera_motion,
        width=plan.width,
        height=plan.height,
        enable_voiceover=plan.enable_voiceover,
        enable_subtitle=plan.enable_subtitle,
        voiceover_text=plan.voiceover_text,
        voiceover_voice=plan.voiceover_voice,
        status=plan.status,
        user_request=plan.user_request,
        error=plan.error,
    )


@router.get("/sessions/{plan_id}")
async def get_session(plan_id: str):
    """获取已缓存的工作流计划"""
    agent = get_agent()
    plan = agent.get_plan(plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")

    return plan.to_dict()


class RetryRequest(BaseModel):
    workflow_id: str = Field(..., description="要重新执行的工作流ID")


@router.post("/retry", response_model=ExecutionResponse)
async def agent_retry(req: RetryRequest):
    """
    重新提交工作流任务。
    用于 Celery worker 重启后任务丢失的场景：
    清除旧任务记录，重新创建并提交到 Celery。
    """
    from app.database import SessionLocal
    from app.models.workflow import Workflow
    from app.models.task import Task, TaskStatus, TaskType
    from app.agent.executor import AgentExecutor

    db = SessionLocal()
    try:
        workflow = db.query(Workflow).filter(Workflow.id == req.workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=404, detail="工作流不存在")

        nodes = workflow.nodes or []
        if not nodes:
            raise HTTPException(status_code=400, detail="工作流没有节点")

        # 删除旧的任务记录
        db.query(Task).filter(Task.workflow_id == req.workflow_id).delete()
        db.commit()

        # 重新创建任务记录并提交
        node_id_to_task_id = {}
        task_ids = []

        for node in nodes:
            node_type = node.get("type", "video_processing")
            task_type = AgentExecutor._map_task_type(node_type)

            task = Task(
                workflow_id=req.workflow_id,
                node_id=node["id"],
                task_type=task_type,
                status=TaskStatus.PENDING,
                input_params=node.get("params", {}),
            )
            db.add(task)
            db.flush()
            task_ids.append(task.id)
            node_id_to_task_id[node["id"]] = task.id

        db.commit()

        # 重新提交到 Celery
        wf_def = {"nodes": nodes, "edges": workflow.edges or []}
        executor = AgentExecutor()
        executor._dispatch_agent_tasks(req.workflow_id, wf_def, node_id_to_task_id)

        # 更新工作流状态
        workflow.status = "running"
        db.commit()

        return ExecutionResponse(
            success=True,
            workflow_id=req.workflow_id,
            project_id=workflow.project_id,
            task_ids=task_ids,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return ExecutionResponse(success=False, error=str(e))
    finally:
        db.close()


class ContinueRequest(BaseModel):
    workflow_id: str = Field(..., description="要继续执行的工作流ID")


@router.post("/continue", response_model=ExecutionResponse)
async def agent_continue(req: ContinueRequest):
    """
    从失败/中断处继续执行工作流。
    已完成的任务会被跳过（幂等），只执行未完成的任务。
    用于 Celery worker 断开或任务中途失败后的恢复场景。
    """
    from app.database import SessionLocal
    from app.models.workflow import Workflow
    from app.models.task import Task, TaskStatus
    from app.workers.tasks import run_agent_workflow
    import logging as _logging
    _log = _logging.getLogger(__name__)

    db = SessionLocal()
    try:
        workflow = db.query(Workflow).filter(Workflow.id == req.workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=404, detail="工作流不存在")

        nodes = workflow.nodes or []
        if not nodes:
            raise HTTPException(status_code=400, detail="工作流没有节点")

        # 从 workflow.config 恢复 node_id → task_id 映射
        wf_config = workflow.config or {}
        node_id_to_task_id = wf_config.get("node_id_to_task_id", {})

        # 如果 config 中没有存储，从数据库任务记录恢复
        if not node_id_to_task_id:
            tasks = db.query(Task).filter(Task.workflow_id == req.workflow_id).all()
            for t in tasks:
                if t.node_id:
                    node_id_to_task_id[t.node_id] = t.id

        if not node_id_to_task_id:
            raise HTTPException(status_code=400, detail="找不到任务映射，请使用“重新执行”")

        # 分类任务（与 _dispatch_agent_tasks 相同的逻辑）
        character_task_ids = []
        scene_design_task_ids = []
        first_frame_task_ids = []
        last_frame_task_ids = []
        scene_task_ids = []
        concat_task_id = None
        other_task_ids = []
        scene_character_map = {}
        scene_design_map = {}

        # 构建角色名到索引的映射
        char_name_to_index = {}
        for node in nodes:
            params = node.get("params", {})
            if node["type"] == "image_generation" and params.get("action") == "character_design":
                char_name = params.get("character_name", "")
                char_idx = params.get("character_index", 0)
                char_name_to_index[char_name] = char_idx

        def _fuzzy_match(name: str) -> int | None:
            if name in char_name_to_index:
                return char_name_to_index[name]
            for cn, idx in char_name_to_index.items():
                if name in cn or cn in name:
                    return idx
            return None

        for node in nodes:
            task_id = node_id_to_task_id.get(node["id"])
            if not task_id:
                continue
            params = node.get("params", {})
            if node["type"] == "image_generation":
                action = params.get("action", "")
                if action == "character_design":
                    character_task_ids.append(task_id)
                elif action == "scene_design":
                    scene_design_task_ids.append(task_id)
                    scene_idx = params.get("scene_index", len(scene_design_task_ids) - 1)
                    scene_design_map[scene_idx] = task_id
                elif action == "first_frame":
                    first_frame_task_ids.append(task_id)
                elif action == "last_frame":
                    last_frame_task_ids.append(task_id)
                    scene_idx = params.get("scene_index", len(last_frame_task_ids) - 1)
                    scene_chars = params.get("scene_characters", [])
                    char_indices = []
                    for name in scene_chars:
                        idx = _fuzzy_match(name)
                        if idx is not None:
                            char_indices.append(idx)
                    if char_indices:
                        scene_character_map[scene_idx] = char_indices
                elif action == "keyframe":
                    first_frame_task_ids.append(task_id)
                else:
                    other_task_ids.append((task_id, node["type"]))
            elif node["type"] == "image_to_video":
                scene_task_ids.append(task_id)
            elif node["type"] == "video_processing" and params.get("action") == "concat":
                concat_task_id = task_id
            else:
                other_task_ids.append((task_id, node["type"]))

        if not scene_task_ids:
            raise HTTPException(status_code=400, detail="没有视频任务需要继续")

        # 重新提交 run_agent_workflow（幂等：已完成的任务自动跳过）
        run_agent_workflow.delay(
            req.workflow_id,
            character_task_ids,
            first_frame_task_ids,
            last_frame_task_ids,
            scene_task_ids,
            concat_task_id,
            other_task_ids,
            scene_character_map,
            scene_design_task_ids,
            scene_design_map,
        )

        # 更新工作流状态
        workflow.status = "running"
        db.commit()

        _log.info(f"工作流 {req.workflow_id} 继续执行已触发")

        return ExecutionResponse(
            success=True,
            workflow_id=req.workflow_id,
            project_id=workflow.project_id,
            task_ids=list(node_id_to_task_id.values()),
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return ExecutionResponse(success=False, error=str(e))
    finally:
        db.close()


# ===== 单任务重跑 / 提示词更新 =====

@router.post("/task/{task_id}/rerun")
async def rerun_task(task_id: str, req: TaskRerunRequest = None):
    """重新执行单个任务（可选修改提示词后重跑）"""
    from app.database import SessionLocal
    from app.models.task import Task, TaskStatus

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        params = task.input_params or {}

        # 如果传入了新 prompt，更新
        if req and req.prompt is not None:
            params["prompt"] = req.prompt
            task.input_params = params

        # 重置状态
        task.status = TaskStatus.PENDING
        task.progress = 0
        task.output_result = None
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        db.commit()

        # 提交到 Celery 执行单个任务
        from app.workers.tasks import run_single_task
        celery_result = run_single_task.delay(task_id)
        task.celery_task_id = celery_result.id
        task.status = TaskStatus.RUNNING
        db.commit()

        return {"success": True, "task_id": task_id, "message": "任务已重新提交"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@router.put("/task/{task_id}/prompt")
async def update_task_prompt(task_id: str, req: TaskPromptUpdateRequest):
    """更新单个任务的提示词"""
    from app.database import SessionLocal
    from app.models.task import Task

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        params = task.input_params or {}
        params["prompt"] = req.prompt
        task.input_params = params
        db.commit()

        return {"success": True, "task_id": task_id, "message": "提示词已更新"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ===== 参考图管理 =====

@router.post("/reference/upload")
async def upload_reference(
    file: UploadFile = File(...),
    name: str = Form(..., description="引用名，如 '炎龙侠'"),
    ref_type: str = Form(..., description="类型: character / scene / keyframe"),
):
    """上传参考图到图库（始终保存本地，不依赖外部图床）"""
    if ref_type not in ("character", "scene", "keyframe"):
        raise HTTPException(status_code=400, detail="ref_type 必须是 character/scene/keyframe")

    ext = Path(file.filename).suffix if file.filename else ".png"
    unique_name = f"ref_{uuid.uuid4().hex[:8]}{ext}"
    ref_dir = settings.STORAGE_DIR / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    local_path = ref_dir / unique_name

    # 保存到本地
    with open(local_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 构建 URL：优先使用 PUBLIC_BASE_URL 自托管，否则用本地 API 路由
    if settings.PUBLIC_BASE_URL:
        public_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/storage/references/{unique_name}"
    else:
        public_url = f"/api/agent/reference/file/{unique_name}"

    store = get_reference_store()
    ref = store.add(name=name, ref_type=ref_type, url=public_url, local_path=str(local_path))

    return {
        "id": ref.id,
        "name": ref.name,
        "ref_type": ref.ref_type,
        "url": ref.url,
        "local_path": ref.local_path,
    }


@router.get("/references")
async def list_references():
    """获取所有参考图列表"""
    store = get_reference_store()
    return [
        {"id": r.id, "name": r.name, "ref_type": r.ref_type, "url": r.url}
        for r in store.list()
    ]


@router.delete("/reference/{ref_id}")
async def delete_reference(ref_id: str):
    """删除参考图"""
    store = get_reference_store()
    if not store.delete(ref_id):
        raise HTTPException(status_code=404, detail="参考图不存在")
    return {"detail": "已删除"}


@router.get("/reference/file/{filename}")
async def serve_reference_file(filename: str):
    """本地参考图文件访问（图床上传失败时的回退）"""
    from fastapi.responses import FileResponse
    file_path = settings.STORAGE_DIR / "references" / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(str(file_path))
