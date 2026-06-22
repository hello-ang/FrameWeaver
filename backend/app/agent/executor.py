"""智能体工作流执行器 - 自动创建项目/工作流并提交执行"""

import logging
import uuid
from typing import Optional

from app.database import SessionLocal
from app.models.project import Project
from app.models.workflow import Workflow
from app.models.task import Task, TaskStatus, TaskType
from app.agent.agent_core import AgentPlan
from app.agent.workflow_planner import WorkflowPlanner

logger = logging.getLogger(__name__)


class AgentExecutor:
    """
    智能体执行器：
    1. 确保项目存在（自动创建或使用已有）
    2. 将 AgentPlan 转换为工作流定义
    3. 创建工作流记录
    4. 提交到 Celery 执行
    """

    def __init__(self):
        self.planner = WorkflowPlanner()

    def execute_plan(self, plan: AgentPlan) -> dict:
        """
        执行确认后的工作流计划。

        Args:
            plan: 已确认的 AgentPlan

        Returns:
            dict: {"workflow_id", "project_id", "task_ids", "success", "error"}
        """
        if plan.status == "failed":
            return {"success": False, "error": plan.error}

        db = SessionLocal()
        try:
            # 1. 确保项目存在
            project_id = plan.project_id
            if project_id:
                project = db.query(Project).filter(Project.id == project_id).first()
                if not project:
                    project_id = None

            if not project_id:
                # 自动创建项目
                project = Project(
                    name=plan.title or plan.user_request[:50],
                    description=f"AI 智能体自动创建 - {plan.user_request[:100]}",
                    status="active",
                )
                db.add(project)
                db.flush()
                project_id = project.id

            # 2. 构建工作流定义
            wf_def = self.planner.build_workflow_definition(plan, project_id)

            # 3. 创建工作流记录
            workflow = Workflow(
                project_id=project_id,
                name=wf_def["name"],
                description=wf_def["description"],
                nodes=wf_def["nodes"],
                edges=wf_def["edges"],
                status="pending",
            )
            db.add(workflow)
            db.flush()
            workflow_id = workflow.id

            # 4. 为每个节点创建任务记录
            nodes = wf_def["nodes"]
            task_ids = []
            node_id_to_task_id = {}

            for node in nodes:
                node_type = node.get("type", "video_processing")
                task_type = self._map_task_type(node_type)

                task = Task(
                    workflow_id=workflow_id,
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

            # 5. 存储 node_id → task_id 映射到 workflow config（供 continue 端点恢复用）
            workflow.config = {
                "node_id_to_task_id": node_id_to_task_id,
            }

            # 6. 更新计划状态
            plan.status = "running"
            plan.workflow_id = workflow_id
            plan.project_id = project_id
            db.commit()

            # 7. 提交到 Celery（使用智能体专用任务）
            self._dispatch_agent_tasks(workflow_id, wf_def, node_id_to_task_id)

            return {
                "success": True,
                "workflow_id": workflow_id,
                "project_id": project_id,
                "task_ids": task_ids,
            }

        except Exception as e:
            logger.exception(f"执行工作流计划失败: {e}")
            db.rollback()
            plan.status = "failed"
            plan.error = str(e)
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def _dispatch_agent_tasks(
        self,
        workflow_id: str,
        wf_def: dict,
        node_id_to_task_id: dict[str, str],
    ):
        """使用智能体专用 Celery 任务提交，五阶段串行执行"""
        from app.workers.tasks import run_agent_workflow, run_ai_task

        nodes = wf_def.get("nodes", [])

        # 分类：角色设定图 vs 场景设计 vs 首帧 vs 尾帧 vs 图生视频 vs 拼接 vs 其他
        character_task_ids = []
        scene_design_task_ids = []
        first_frame_task_ids = []
        last_frame_task_ids = []
        scene_task_ids = []
        concat_task_id = None
        other_task_ids = []
        scene_character_map = {}  # {scene_index: [character_index]}
        scene_design_map = {}  # {scene_index: task_id}

        # 构建角色名到索引的映射
        char_name_to_index = {}
        for node in nodes:
            params = node.get("params", {})
            if node["type"] == "image_generation" and params.get("action") == "character_design":
                char_name = params.get("character_name", "")
                char_idx = params.get("character_index", 0)
                char_name_to_index[char_name] = char_idx

        def _fuzzy_match_char_name(scene_name: str) -> int | None:
            """模糊匹配角色名：精确匹配优先，回退到子串匹配"""
            if scene_name in char_name_to_index:
                return char_name_to_index[scene_name]
            for char_name, idx in char_name_to_index.items():
                if scene_name in char_name or char_name in scene_name:
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
                    # 从尾帧节点构建场景角色映射（因为链式帧复用下只有 scene0 有首帧节点）
                    scene_idx = params.get("scene_index", len(last_frame_task_ids) - 1)
                    scene_chars = params.get("scene_characters", [])
                    char_indices = []
                    for name in scene_chars:
                        idx = _fuzzy_match_char_name(name)
                        if idx is not None:
                            char_indices.append(idx)
                    if char_indices:
                        scene_character_map[scene_idx] = char_indices
                    logger.info(f"场景 {scene_idx} 角色映射: {scene_chars} -> {char_indices}")
                elif action == "keyframe":
                    # 向后兼容旧版关键帧节点
                    first_frame_task_ids.append(task_id)
                else:
                    other_task_ids.append((task_id, node["type"]))
            elif node["type"] == "image_to_video":
                scene_task_ids.append(task_id)
            elif node["type"] == "video_processing" and params.get("action") == "concat":
                concat_task_id = task_id
            else:
                other_task_ids.append((task_id, node["type"]))

        # 提交智能体工作流任务
        if scene_task_ids:
            run_agent_workflow.delay(
                workflow_id,
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
        else:
            for task_id, node_type in other_task_ids:
                db = SessionLocal()
                try:
                    task = db.query(Task).filter(Task.id == task_id).first()
                    if task:
                        result = run_ai_task.delay(task_id)
                        task.celery_task_id = result.id
                        db.commit()
                finally:
                    db.close()

    def _dispatch_tasks(
        self,
        workflow_id: str,
        wf_def: dict,
        node_id_to_task_id: dict[str, str],
    ):
        """将任务提交到 Celery，按照拓扑顺序执行"""
        from app.workers.tasks import run_ai_task, process_video

        edges = wf_def.get("edges", [])
        nodes = wf_def.get("nodes", [])

        # 构建邻接表和入度
        from collections import defaultdict, deque
        adjacency = defaultdict(list)
        in_degree = defaultdict(int)

        for edge in edges:
            adjacency[edge["source"]].append(edge["target"])
            in_degree[edge["target"]] += 1

        for node in nodes:
            if node["id"] not in in_degree:
                in_degree[node["id"]] = 0

        # 拓扑排序
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        execution_order = []
        while queue:
            current = queue.popleft()
            execution_order.append(current)
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 按执行顺序提交
        for node_id in execution_order:
            task_id = node_id_to_task_id.get(node_id)
            if not task_id:
                continue

            db = SessionLocal()
            try:
                task = db.query(Task).filter(Task.id == task_id).first()
                if not task:
                    continue

                # 根据任务类型选择 Celery 任务
                if task.task_type in [TaskType.VIDEO_PROCESSING, TaskType.AUDIO_PROCESSING]:
                    result = process_video.delay(task_id)
                else:
                    result = run_ai_task.delay(task_id)

                task.celery_task_id = result.id
                db.commit()
            finally:
                db.close()

    @staticmethod
    def _map_task_type(node_type: str) -> TaskType:
        """节点类型到任务类型映射"""
        mapping = {
            "text_to_video": TaskType.TEXT_TO_VIDEO,
            "video_analysis": TaskType.VIDEO_ANALYSIS,
            "subtitle_generation": TaskType.SUBTITLE_GENERATION,
            "voice_synthesis": TaskType.VOICE_SYNTHESIS,
            "image_to_video": TaskType.IMAGE_TO_VIDEO,
            "image_generation": TaskType.IMAGE_GENERATION,
            "video_processing": TaskType.VIDEO_PROCESSING,
            "audio_processing": TaskType.AUDIO_PROCESSING,
        }
        return mapping.get(node_type, TaskType.VIDEO_PROCESSING)
