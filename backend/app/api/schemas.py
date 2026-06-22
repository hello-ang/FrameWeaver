"""Pydantic 请求/响应模型"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ===== Project Schemas =====
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: Optional[str] = Field(None, description="项目描述")


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|archived)$")


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: str
    created_at: Optional[str]
    updated_at: Optional[str]

    model_config = {"from_attributes": True}


# ===== Workflow Schemas =====
class WorkflowNode(BaseModel):
    id: str = Field(..., description="节点唯一ID")
    type: str = Field(..., description="节点类型")
    label: str = Field("", description="节点显示名称")
    params: dict = Field(default_factory=dict, description="节点参数")
    position: dict = Field(default_factory=lambda: {"x": 0, "y": 0}, description="节点位置")


class WorkflowEdge(BaseModel):
    id: str
    source: str = Field(..., description="源节点ID")
    target: str = Field(..., description="目标节点ID")
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None


class WorkflowCreate(BaseModel):
    project_id: str = Field(..., description="所属项目ID")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    nodes: Optional[list[WorkflowNode]] = None
    edges: Optional[list[WorkflowEdge]] = None
    config: Optional[dict] = None


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[list[WorkflowNode]] = None
    edges: Optional[list[WorkflowEdge]] = None
    config: Optional[dict] = None


class WorkflowResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str]
    status: str
    nodes: Optional[list[dict]]
    edges: Optional[list[dict]]
    config: Optional[dict]
    created_at: Optional[str]
    updated_at: Optional[str]

    model_config = {"from_attributes": True}


class WorkflowRunRequest(BaseModel):
    """执行工作流请求"""
    params: Optional[dict] = Field(default_factory=dict, description="运行时参数覆盖")


# ===== Task Schemas =====
class TaskResponse(BaseModel):
    id: str
    workflow_id: str
    node_id: Optional[str]
    task_type: Optional[str]
    status: Optional[str]
    progress: float
    input_params: Optional[dict]
    output_result: Optional[dict]
    error_message: Optional[str]
    celery_task_id: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: Optional[str]

    model_config = {"from_attributes": True}


# ===== Media Schemas =====
class MediaResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    file_path: str
    media_type: Optional[str]
    file_size: int
    mime_type: Optional[str]
    metadata: Optional[dict]
    created_at: Optional[str]

    model_config = {"from_attributes": True}


# ===== 通用响应 =====
class MessageResponse(BaseModel):
    message: str
    data: Optional[dict] = None
