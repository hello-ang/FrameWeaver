/**
 * API 请求客户端
 */

const BASE_URL = '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `请求失败: ${res.status}`);
  }

  return res.json();
}

// ===== Projects =====
import type { Project, Workflow, Task, Media, MessageResponse, AgentPlan, AgentExecutionResult, ReferenceImage } from '../types';

export const projectApi = {
  list: (params?: { skip?: number; limit?: number; status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.skip) qs.set('skip', String(params.skip));
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.status) qs.set('status', params.status);
    const query = qs.toString();
    return request<Project[]>(`/projects${query ? `?${query}` : ''}`);
  },
  get: (id: string) => request<Project>(`/projects/${id}`),
  create: (data: { name: string; description?: string }) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<MessageResponse>(`/projects/${id}`, { method: 'DELETE' }),
};

// ===== Workflows =====
export const workflowApi = {
  list: (projectId?: string) => {
    const qs = projectId ? `?project_id=${projectId}` : '';
    return request<Workflow[]>(`/workflows${qs}`);
  },
  get: (id: string) => request<Workflow>(`/workflows/${id}`),
  create: (data: {
    project_id: string;
    name: string;
    description?: string;
    nodes?: unknown[];
    edges?: unknown[];
    config?: Record<string, unknown>;
  }) => request<Workflow>('/workflows', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Workflow>) =>
    request<Workflow>(`/workflows/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<MessageResponse>(`/workflows/${id}`, { method: 'DELETE' }),
  run: (id: string, params?: Record<string, unknown>) =>
    request<MessageResponse>(`/workflows/${id}/run`, {
      method: 'POST',
      body: JSON.stringify({ params: params || {} }),
    }),
  getTasks: (id: string) => request<Task[]>(`/workflows/${id}/tasks`),
  cancel: (id: string) =>
    request<MessageResponse>(`/workflows/${id}/cancel`, { method: 'POST' }),
  resume: (id: string) =>
    request<MessageResponse>(`/workflows/${id}/resume`, { method: 'POST' }),
};

// ===== Tasks =====
export const taskApi = {
  get: (id: string) => request<Task>(`/tasks/${id}`),
  cancel: (id: string) =>
    request<MessageResponse>(`/tasks/${id}/cancel`, { method: 'POST' }),
  updateParams: (id: string, inputParams: Record<string, unknown>) =>
    request<Task>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify({ input_params: inputParams }) }),
  updatePrompt: (id: string, prompt: string) =>
    request<MessageResponse>(`/agent/task/${id}/prompt`, { method: 'PUT', body: JSON.stringify({ prompt }) }),
  rerun: (id: string, prompt?: string) =>
    request<MessageResponse>(`/agent/task/${id}/rerun`, {
      method: 'POST',
      body: JSON.stringify({ prompt: prompt || null }),
    }),
  /** 触发浏览器下载任务输出文件 */
  download: (id: string) => {
    const a = document.createElement('a');
    a.href = `${BASE_URL}/tasks/${id}/download`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  },
};

// ===== Media =====
export const mediaApi = {
  list: (projectId: string, mediaType?: string) => {
    const qs = new URLSearchParams({ project_id: projectId });
    if (mediaType) qs.set('media_type', mediaType);
    return request<Media[]>(`/media?${qs.toString()}`);
  },
  get: (id: string) => request<Media>(`/media/${id}`),
  upload: async (file: File, projectId: string) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE_URL}/media/upload?project_id=${projectId}`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error('上传失败');
    return res.json() as Promise<Media>;
  },
  delete: (id: string) =>
    request<MessageResponse>(`/media/${id}`, { method: 'DELETE' }),
  getDownloadUrl: (id: string) => `${BASE_URL}/media/${id}/download`,
};

// ===== Health =====
export interface ServiceStatus {
  status: 'ok' | 'warning' | 'error';
  message: string;
  model?: string;
}

export interface HealthCheckResult {
  overall: 'healthy' | 'degraded';
  services: {
    agnes_api?: ServiceStatus;
    redis?: ServiceStatus;
    celery?: ServiceStatus;
  };
}

export const healthApi = {
  checkServices: () => request<HealthCheckResult>('/health/services'),
};

// ===== Agent 智能体 =====
export const agentApi = {
  chat: (message: string, projectId?: string, references?: { name: string; ref_type: string; url: string }[]) =>
    request<AgentPlan>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ message, project_id: projectId, references: references || [] }),
    }),
  confirm: (planId: string, projectId?: string) =>
    request<AgentExecutionResult>('/agent/confirm', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, project_id: projectId }),
    }),
  adjust: (planId: string, adjustments: Record<string, unknown>[]) =>
    request<AgentPlan>('/agent/adjust', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, adjustments }),
    }),
  getSession: (planId: string) =>
    request<AgentPlan>(`/agent/sessions/${planId}`),
  retry: (workflowId: string) =>
    request<AgentExecutionResult>('/agent/retry', {
      method: 'POST',
      body: JSON.stringify({ workflow_id: workflowId }),
    }),
  continue: (workflowId: string) =>
    request<AgentExecutionResult>('/agent/continue', {
      method: 'POST',
      body: JSON.stringify({ workflow_id: workflowId }),
    }),
};

// ===== 参考图管理 =====
export const referenceApi = {
  upload: async (file: File, name: string, refType: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);
    formData.append('ref_type', refType);
    const res = await fetch(`${BASE_URL}/agent/reference/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || '上传失败');
    }
    return res.json() as Promise<ReferenceImage>;
  },
  list: () => request<ReferenceImage[]>('/agent/references'),
  delete: (id: string) =>
    request<MessageResponse>(`/agent/reference/${id}`, { method: 'DELETE' }),
};
