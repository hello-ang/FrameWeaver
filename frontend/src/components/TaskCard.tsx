import type { Task } from '../types';
import { taskApi } from '../api/client';

const STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  running: '生成中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_COLORS: Record<string, string> = {
  pending: '#6b7280',
  running: '#3b82f6',
  completed: '#10b981',
  failed: '#ef4444',
  cancelled: '#9ca3af',
};

const TYPE_LABELS: Record<string, string> = {
  text_to_video: '文生视频',
  video_analysis: '视频分析',
  subtitle_generation: '自动字幕',
  voice_synthesis: '配音合成',
  image_to_video: '图生视频',
  image_generation: '图片生成',
  video_processing: '视频处理',
  audio_processing: '音频处理',
};

function getDisplayName(task: Task): string {
  const action = (task.input_params?.action as string) || '';
  const sceneIndex = typeof task.input_params?.scene_index === 'number'
    ? task.input_params.scene_index + 1
    : null;

  if (action === 'character_design' && task.input_params?.character_name) {
    return `角色: ${task.input_params.character_name}`;
  }
  if (action === 'scene_design' && sceneIndex !== null) {
    return `场景 ${sceneIndex}`;
  }
  if (task.input_params?.character_name) {
    return `角色: ${task.input_params.character_name}`;
  }
  if (action === 'first_frame' && sceneIndex !== null) {
    return `分镜 ${sceneIndex} 首帧`;
  }
  if (action === 'last_frame' && sceneIndex !== null) {
    return `分镜 ${sceneIndex} 尾帧`;
  }
  if ((task.task_type === 'image_to_video' || task.task_type === 'text_to_video') && sceneIndex !== null) {
    const chain = sceneIndex > 1 ? ' (链式)' : '';
    return `分镜 ${sceneIndex} 视频${chain}`;
  }
  return (task.input_params?.prompt_cn as string) || TYPE_LABELS[task.task_type || ''] || task.task_type || '';
}

interface Props {
  task: Task;
  editingTaskId: string | null;
  editPrompt: string;
  setEditPrompt: (v: string) => void;
  rerunning: string | null;
  onStartEdit: (task: Task) => void;
  onSavePrompt: (taskId: string) => void;
  onCancelEdit: () => void;
  onRerun: (taskId: string) => void;
}

export default function TaskCard({
  task, editingTaskId, editPrompt, setEditPrompt, rerunning,
  onStartEdit, onSavePrompt, onCancelEdit, onRerun,
}: Props) {
  const status = task.status || 'pending';
  const isRunning = status === 'running';
  const isPending = status === 'pending';
  const isFailed = status === 'failed';
  const isCompleted = status === 'completed';
  const displayName = getDisplayName(task);
  const desc = (task.input_params?.prompt_cn as string) || '';
  const shortDesc = desc.length > 60 ? desc.substring(0, 60) + '...' : desc;
  const dialogue = (task.input_params?.dialogue as string) || '';
  const imageUrl = isCompleted ? (task.output_result?.image_url as string) : '';
  const videoUrl = isCompleted ? (task.output_result?.video_url as string) : '';
  const hasOutput = isCompleted && (
    task.output_result?.video_path ||
    task.output_result?.image_url ||
    task.output_result?.subtitle_path
  );
  const isImageTask = task.task_type === 'image_generation' || task.task_type === 'image_to_video' || task.task_type === 'text_to_video';
  const canEdit = (isCompleted || isFailed) && task.task_type !== 'video_processing';

  return (
    <div className={`task-card ${status}`}>
      {/* 预览区 */}
      <div className="task-card-preview">
        {isRunning && isImageTask ? (
          <div className="task-card-skeleton">
            <div className="skeleton-scan-line" />
            <span className="skeleton-label">AI 生成中...</span>
            <div className="task-card-progress-bar">
              <div className="task-card-progress-fill pulse" style={{ width: `${Math.max(task.progress, 8)}%` }} />
            </div>
          </div>
        ) : imageUrl ? (
          <img src={imageUrl} alt={displayName} className="task-card-img" />
        ) : videoUrl ? (
          <video src={videoUrl} controls preload="metadata" className="task-card-video" />
        ) : isPending ? (
          <div className="task-card-placeholder">
            <span className="placeholder-icon">⏳</span>
          </div>
        ) : isRunning ? (
          <div className="task-card-skeleton">
            <div className="skeleton-scan-line" />
            <span className="skeleton-label">处理中...</span>
          </div>
        ) : isFailed ? (
          <div className="task-card-placeholder failed">
            <span className="placeholder-icon">✕</span>
            {task.error_message && <span className="task-card-error-text">{task.error_message}</span>}
          </div>
        ) : (
          <div className="task-card-placeholder">
            <span className="placeholder-icon">📄</span>
          </div>
        )}

        {/* 状态角标 */}
        <div className="task-card-badge" style={{ background: STATUS_COLORS[status] }}>
          {STATUS_LABELS[status] || status}
          {isRunning && <span className="task-card-pct"> {Math.round(task.progress)}%</span>}
        </div>
      </div>

      {/* 信息区 */}
      <div className="task-card-body">
        <div className="task-card-title" title={displayName}>{displayName}</div>

        {shortDesc && (
          <div className="task-card-desc" title={desc}>{shortDesc}</div>
        )}

        {dialogue && (
          <div className="task-card-dialogue" title={dialogue}>
            💬 {dialogue.length > 25 ? dialogue.substring(0, 25) + '...' : dialogue}
          </div>
        )}

        {/* 提示词编辑 */}
        {editingTaskId === task.id && (
          <div className="task-card-edit">
            <textarea
              value={editPrompt}
              onChange={(e) => setEditPrompt(e.target.value)}
              rows={3}
              placeholder="输入新的提示词..."
            />
            <div className="task-card-edit-btns">
              <button className="task-card-btn save" onClick={() => onSavePrompt(task.id)}>保存</button>
              <button className="task-card-btn cancel" onClick={onCancelEdit}>取消</button>
            </div>
          </div>
        )}

        {/* 操作按钮 */}
        <div className="task-card-actions">
          {hasOutput && (
            <button className="task-card-btn download" onClick={() => taskApi.download(task.id)}>
              ⬇️ 下载
            </button>
          )}
          {canEdit && editingTaskId !== task.id && (
            <>
              <button className="task-card-btn edit" onClick={() => onStartEdit(task)}>
                ✏️ 编辑
              </button>
              <button
                className="task-card-btn rerun"
                onClick={() => onRerun(task.id)}
                disabled={rerunning === task.id}
              >
                {rerunning === task.id ? '提交中...' : (isFailed ? '🔄 重试' : '🔄 重生成')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
