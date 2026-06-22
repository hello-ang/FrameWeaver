"""工作流 API"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.workflow import Workflow
from app.models.task import Task, TaskStatus, TaskType
from app.api.schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowRunRequest,
    MessageResponse,
    TaskResponse,
)
from app.services.workflow_service import execute_workflow

router = APIRouter()


@router.post("", response_model=WorkflowResponse, status_code=201)
def create_workflow(data: WorkflowCreate, db: Session = Depends(get_db)):
    """创建新工作流"""
    workflow = Workflow(
        project_id=data.project_id,
        name=data.name,
        description=data.description,
        nodes=[n.model_dump() for n in data.nodes] if data.nodes else [],
        edges=[e.model_dump() for e in data.edges] if data.edges else [],
        config=data.config,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow.to_dict()


@router.get("", response_model=list[WorkflowResponse])
def list_workflows(
    project_id: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """获取工作流列表"""
    query = db.query(Workflow)
    if project_id:
        query = query.filter(Workflow.project_id == project_id)
    workflows = query.order_by(Workflow.created_at.desc()).offset(skip).limit(limit).all()
    return [w.to_dict() for w in workflows]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """获取工作流详情"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return workflow.to_dict()


@router.put("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(workflow_id: str, data: WorkflowUpdate, db: Session = Depends(get_db)):
    """更新工作流"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    update_data = data.model_dump(exclude_unset=True)
    if "nodes" in update_data and update_data["nodes"] is not None:
        update_data["nodes"] = [n.model_dump() if hasattr(n, "model_dump") else n for n in update_data["nodes"]]
    if "edges" in update_data and update_data["edges"] is not None:
        update_data["edges"] = [e.model_dump() if hasattr(e, "model_dump") else e for e in update_data["edges"]]

    for key, value in update_data.items():
        setattr(workflow, key, value)

    db.commit()
    db.refresh(workflow)
    return workflow.to_dict()


@router.delete("/{workflow_id}", response_model=MessageResponse)
def delete_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """删除工作流（自动取消运行中的任务）"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    # 取消所有运行中/排队中的任务
    _cancel_workflow_tasks(workflow_id, db)

    db.delete(workflow)
    db.commit()
    return MessageResponse(message=f"工作流 '{workflow.name}' 已删除")


@router.post("/{workflow_id}/run", response_model=MessageResponse)
def run_workflow(workflow_id: str, data: WorkflowRunRequest, db: Session = Depends(get_db)):
    """执行工作流"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    if not workflow.nodes:
        raise HTTPException(status_code=400, detail="工作流没有定义节点")

    # 更新状态为运行中
    workflow.status = "running"
    db.commit()

    # 异步执行工作流
    task_ids = execute_workflow(workflow_id, data.params or {})

    return MessageResponse(
        message=f"工作流 '{workflow.name}' 已开始执行",
        data={"task_ids": task_ids},
    )


@router.post("/{workflow_id}/resume", response_model=MessageResponse)
def resume_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """恢复执行暂停的工作流"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    if workflow.status not in ["paused", "failed"]:
        raise HTTPException(status_code=400, detail="只能恢复已暂停或失败的工作流")

    # 更新状态为运行中
    workflow.status = "running"
    db.commit()

    # 重新下发智能体任务（由于任务逻辑已经支持幂等和跳过已完成，可以直接重发）
    from app.agent.executor import AgentExecutor
    tasks = db.query(Task).filter(Task.workflow_id == workflow_id).all()
    node_id_to_task_id = {t.node_id: t.id for t in tasks if t.node_id}
    
    wf_def = {
        "nodes": workflow.nodes,
        "edges": workflow.edges,
        "name": workflow.name,
        "description": workflow.description
    }

    executor = AgentExecutor()
    executor._dispatch_agent_tasks(workflow_id, wf_def, node_id_to_task_id)

    return MessageResponse(message=f"工作流 '{workflow.name}' 已恢复执行")



@router.get("/{workflow_id}/tasks", response_model=list[TaskResponse])
def get_workflow_tasks(workflow_id: str, db: Session = Depends(get_db)):
    """获取工作流的所有任务"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    tasks = db.query(Task).filter(Task.workflow_id == workflow_id).order_by(Task.created_at).all()
    return [t.to_dict() for t in tasks]


@router.post("/{workflow_id}/cancel", response_model=MessageResponse)
def cancel_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """取消工作流中所有运行中/排队中的任务"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    cancelled = _cancel_workflow_tasks(workflow_id, db)
    workflow.status = "cancelled"
    db.commit()

    return MessageResponse(message=f"已取消 {cancelled} 个任务")


def _cancel_workflow_tasks(workflow_id: str, db) -> int:
    """取消工作流的所有运行中/排队中的任务，返回取消数量"""
    from app.workers.celery_app import celery_app

    tasks = (
        db.query(Task)
        .filter(Task.workflow_id == workflow_id)
        .filter(Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))
        .all()
    )

    for task in tasks:
        task.status = TaskStatus.CANCELLED
        if task.celery_task_id:
            try:
                celery_app.control.revoke(task.celery_task_id, terminate=True)
            except Exception:
                pass

    db.commit()
    return len(tasks)
