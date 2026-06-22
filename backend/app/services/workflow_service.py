"""工作流编排服务 - 负责解析工作流定义并调度任务执行"""

import json
from collections import defaultdict, deque
from typing import Optional

from app.database import SessionLocal
from app.models.workflow import Workflow
from app.models.task import Task, TaskStatus, TaskType


# 节点类型到任务类型的映射
NODE_TYPE_TO_TASK_TYPE = {
    "text_to_video": TaskType.TEXT_TO_VIDEO,
    "video_analysis": TaskType.VIDEO_ANALYSIS,
    "subtitle_generation": TaskType.SUBTITLE_GENERATION,
    "voice_synthesis": TaskType.VOICE_SYNTHESIS,
    "image_to_video": TaskType.IMAGE_TO_VIDEO,
    "video_processing": TaskType.VIDEO_PROCESSING,
    "audio_processing": TaskType.AUDIO_PROCESSING,
}


def execute_workflow(workflow_id: str, runtime_params: Optional[dict] = None) -> list[str]:
    """
    执行工作流：解析节点依赖关系，创建任务并按拓扑顺序提交到 Celery。

    Args:
        workflow_id: 工作流ID
        runtime_params: 运行时参数覆盖

    Returns:
        创建的任务ID列表
    """
    db = SessionLocal()
    try:
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"工作流 {workflow_id} 不存在")

        nodes = workflow.nodes or []
        edges = workflow.edges or []

        if not nodes:
            raise ValueError("工作流没有定义节点")

        # 构建节点映射和邻接表
        node_map = {n["id"]: n for n in nodes}
        adjacency = defaultdict(list)  # source -> [targets]
        in_degree = defaultdict(int)

        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            adjacency[source].append(target)
            in_degree[target] += 1

        # 为所有节点初始化 in_degree（处理孤立节点）
        for node in nodes:
            if node["id"] not in in_degree:
                in_degree[node["id"]] = 0

        # 拓扑排序确定执行顺序
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        execution_order = []

        while queue:
            current = queue.popleft()
            execution_order.append(current)
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 为每个节点创建任务并提交
        task_ids = []
        previous_task_id = None

        for node_id in execution_order:
            node = node_map[node_id]
            node_type = node.get("type", "video_processing")
            task_type = NODE_TYPE_TO_TASK_TYPE.get(node_type, TaskType.VIDEO_PROCESSING)

            # 合并节点参数和运行时参数
            params = {**node.get("params", {}), **(runtime_params or {})}

            # 创建任务记录
            task = Task(
                workflow_id=workflow_id,
                node_id=node_id,
                task_type=task_type,
                status=TaskStatus.PENDING,
                input_params=params,
            )
            db.add(task)
            db.flush()  # 获取ID
            task_ids.append(task.id)

        db.commit()

        # 提交到 Celery 执行
        _dispatch_tasks(workflow_id, task_ids, execution_order, adjacency)

        return task_ids

    finally:
        db.close()


def _dispatch_tasks(
    workflow_id: str,
    task_ids: list[str],
    execution_order: list[str],
    adjacency: dict,
):
    """将任务提交到 Celery 执行"""
    from app.workers.tasks import run_ai_task, process_video

    for task_id, node_id in zip(task_ids, execution_order):
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                continue

            task_type = task.task_type

            # 根据任务类型选择对应的 Celery 任务
            if task_type in [TaskType.VIDEO_PROCESSING, TaskType.AUDIO_PROCESSING]:
                result = process_video.delay(task_id)
            else:
                result = run_ai_task.delay(task_id)

            task.celery_task_id = result.id
            db.commit()
        finally:
            db.close()


def update_workflow_status(workflow_id: str):
    """检查工作流所有任务状态，更新工作流整体状态"""
    db = SessionLocal()
    try:
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            return

        tasks = db.query(Task).filter(Task.workflow_id == workflow_id).all()
        if not tasks:
            return

        statuses = [t.status for t in tasks]

        if all(s == TaskStatus.COMPLETED for s in statuses):
            workflow.status = "completed"
        elif any(s == TaskStatus.FAILED for s in statuses):
            workflow.status = "paused"
        elif any(s == TaskStatus.RUNNING for s in statuses):
            workflow.status = "running"

        db.commit()
    finally:
        db.close()

