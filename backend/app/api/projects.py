"""项目管理 API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.api.schemas import ProjectCreate, ProjectUpdate, ProjectResponse, MessageResponse

router = APIRouter()


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    """创建新项目"""
    project = Project(name=data.name, description=data.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.to_dict()


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    skip: int = 0,
    limit: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """获取项目列表"""
    query = db.query(Project)
    if status:
        query = query.filter(Project.status == status)
    projects = query.order_by(Project.created_at.desc()).offset(skip).limit(limit).all()
    return [p.to_dict() for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    """获取项目详情"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project.to_dict()


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, data: ProjectUpdate, db: Session = Depends(get_db)):
    """更新项目"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)

    db.commit()
    db.refresh(project)
    return project.to_dict()


@router.delete("/{project_id}", response_model=MessageResponse)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    """删除项目（自动取消运行中的任务）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 取消该项目下所有工作流的运行中任务
    from app.api.workflows import _cancel_workflow_tasks
    from app.models.workflow import Workflow
    workflows = db.query(Workflow).filter(Workflow.project_id == project_id).all()
    total_cancelled = 0
    for wf in workflows:
        total_cancelled += _cancel_workflow_tasks(wf.id, db)

    db.delete(project)
    db.commit()
    msg = f"项目 '{project.name}' 已删除"
    if total_cancelled:
        msg += f"，取消了 {total_cancelled} 个运行中的任务"
    return MessageResponse(message=msg)
