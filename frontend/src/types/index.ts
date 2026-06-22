/**
 * API 类型定义
 */

export interface Project {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowNode {
  id: string;
  type: string;
  label: string;
  params: Record<string, unknown>;
  position: { x: number; y: number };
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  source_handle?: string;
  target_handle?: string;
}

export interface Workflow {
  id: string;
  project_id: string;
  name: string;
  description?: string;
  status: string;
  nodes?: WorkflowNode[];
  edges?: WorkflowEdge[];
  config?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface Task {
  id: string;
  workflow_id: string;
  node_id?: string;
  task_type?: string;
  status?: string;
  progress: number;
  input_params?: Record<string, unknown>;
  output_result?: Record<string, unknown>;
  error_message?: string;
  celery_task_id?: string;
  started_at?: string;
  completed_at?: string;
  created_at?: string;
}

export interface Media {
  id: string;
  project_id: string;
  filename: string;
  file_path: string;
  media_type?: string;
  file_size: number;
  mime_type?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

export interface MessageResponse {
  message: string;
  data?: Record<string, unknown>;
}

// 节点类型定义
export const NODE_TYPES_CONFIG = {
  text_to_video: {
    label: '文生视频',
    color: '#6366f1',
    icon: '🎬',
    defaultParams: {
      text: '',
      api_provider: 'agnes',
      api_key: '',
    },
  },
  video_analysis: {
    label: '视频分析',
    color: '#06b6d4',
    icon: '🔍',
    defaultParams: {
      video_path: '',
      extract_keyframes: true,
      detect_faces: false,
    },
  },
  subtitle_generation: {
    label: '自动字幕',
    color: '#10b981',
    icon: '📝',
    defaultParams: {
      video_path: '',
      language: 'zh',
      model_name: 'base',
    },
  },
  voice_synthesis: {
    label: '配音合成',
    color: '#f59e0b',
    icon: '🎙️',
    defaultParams: {
      text: '',
      voice: 'zh-CN-XiaoxiaoNeural',
      rate: '+0%',
    },
  },
  image_to_video: {
    label: '图生视频',
    color: '#ec4899',
    icon: '🖼️',
    defaultParams: {
      image_url: '',
      image_paths: [],
      prompt: '',
      duration: 5,
      mode: 'i2v',
      api_provider: 'agnes',
    },
  },
  video_processing: {
    label: '视频处理',
    color: '#8b5cf6',
    icon: '✂️',
    defaultParams: {
      action: 'trim',
      input_path: '',
    },
  },
  audio_processing: {
    label: '音频处理',
    color: '#14b8a6',
    icon: '🔊',
    defaultParams: {
      action: 'adjust_volume',
      input_path: '',
    },
  },
} as const;

export type NodeTypeKey = keyof typeof NODE_TYPES_CONFIG;

// ===== Agent 智能体类型 =====

export interface AgentCharacter {
  name: string;
  description: string;
  image_prompt: string;
  image_url?: string;
  provided_url?: string;
}

export interface AgentScene {
  index: number;
  prompt: string;
  prompt_cn: string;
  duration: number;
  first_frame_prompt: string;
  first_frame_prompt_cn?: string;
  last_frame_prompt: string;
  last_frame_prompt_cn?: string;
  camera_motion: string;
  scene_characters: string[];
  time_breakdown: string;
  // 向后兼容
  keyframe_prompt?: string;
}

export interface AgentPlan {
  plan_id: string;
  title: string;
  total_duration: number;
  characters: AgentCharacter[];
  scenes: AgentScene[];
  // 全局锁定参数
  global_style: string;
  global_negative_prompt: string;
  global_camera_motion: string;
  width: number;
  height: number;
  // 配音/字幕
  enable_voiceover: boolean;
  enable_subtitle: boolean;
  voiceover_text: string;
  voiceover_voice: string;
  status: string;
  user_request: string;
  error?: string;
}

export interface AgentExecutionResult {
  success: boolean;
  workflow_id?: string;
  project_id?: string;
  task_ids?: string[];
  error?: string;
}

export interface ReferenceImage {
  id: string;
  name: string;
  ref_type: 'character' | 'scene' | 'keyframe';
  url: string;
}
