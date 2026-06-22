import { useState, useEffect, useRef } from 'react';
import type { Task } from '../types';
import { workflowApi, agentApi, taskApi } from '../api/client';
import TaskCard from './TaskCard';

interface Props {
  workflowId: string;
  taskIds: string[];
}

// 阶段分组逻辑
function getPhase(task: Task): { key: string; label: string; icon: string; color: string } {
  const nodeId = task.node_id || '';
  const action = (task.input_params?.action as string) || '';

  if (nodeId.startsWith('scene_design_') || action === 'scene_design') {
    return { key: 'scene_design', label: '场景设计', icon: '🏞️', color: '#ec4899' };
  }
  if (nodeId.startsWith('char_') || action === 'character_design') {
    return { key: 'character', label: '角色设定', icon: '🎨', color: '#8b5cf6' };
  }
  if (
    nodeId.startsWith('keyframe_') ||
    nodeId.startsWith('first_frame_') ||
    nodeId.startsWith('last_frame_') ||
    action === 'first_frame' ||
    action === 'last_frame' ||
    action === 'keyframe' ||
    (task.task_type === 'image_generation' && action !== 'character_design' && action !== 'scene_design')
  ) {
    return { key: 'keyframe', label: '分镜画面', icon: '🖼️', color: '#06b6d4' };
  }
  if (
    nodeId.startsWith('scene_') ||
    task.task_type === 'image_to_video' ||
    task.task_type === 'text_to_video'
  ) {
    return { key: 'video', label: '视频生成', icon: '🎬', color: '#f59e0b' };
  }
  return { key: 'post', label: '后期合成', icon: '✨', color: '#10b981' };
}

const PHASE_ORDER = ['character', 'scene_design', 'keyframe', 'video', 'post'];

export default function ExecutionProgress({ workflowId, taskIds }: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editPrompt, setEditPrompt] = useState('');
  const [rerunning, setRerunning] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  const startPolling = () => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = window.setInterval(async () => {
      try {
        const list = await workflowApi.getTasks(workflowId);
        setTasks(list);
        const done = list.every(
          (t) => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled'
        );
        if (done && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } catch {}
    }, 3000);
  };

  useEffect(() => {
    const fetchTasks = async () => {
      try {
        const list = await workflowApi.getTasks(workflowId);
        setTasks(list);
        setLoading(false);
        const allDone = list.every(
          (t) => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled'
        );
        if (allDone && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } catch (err) {
        setLoading(false);
      }
    };

    fetchTasks();
    intervalRef.current = window.setInterval(fetchTasks, 3000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [workflowId]);

  const completedCount = tasks.filter((t) => t.status === 'completed').length;
  const totalCount = tasks.length;
  const allDone = totalCount > 0 && completedCount === totalCount;
  const hasFailed = tasks.some((t) => t.status === 'failed');
  const hasCompleted = tasks.some((t) => t.status === 'completed');
  const hasPending = tasks.some((t) => t.status === 'pending');
  const allPending = totalCount > 0 && tasks.every((t) => t.status === 'pending');
  const needsRetry = allPending || (hasFailed && !tasks.some((t) => t.status === 'running'));
  const needsContinue = hasCompleted && (hasPending || hasFailed) && !tasks.some((t) => t.status === 'running');
  const hasRunning = tasks.some((t) => t.status === 'running' || t.status === 'pending');

  // 找到最终成品任务（后期合成中已完成的视频处理任务）
  const finalTask = tasks
    .filter((t) => t.status === 'completed' && t.output_result?.video_path)
    .pop();

  const handleRetry = async () => {
    setRetrying(true);
    try {
      // 使用 /continue 接口，幂等跳过已完成任务，只重跑失败的
      const result = await agentApi.continue(workflowId);
      if (result.success) startPolling();
    } catch (err) {
      console.error('重新执行失败:', err);
    } finally {
      setRetrying(false);
    }
  };

  const handleCancel = async () => {
    if (!confirm('确定停止所有运行中的任务？')) return;
    setCancelling(true);
    try {
      await workflowApi.cancel(workflowId);
      const list = await workflowApi.getTasks(workflowId);
      setTasks(list);
    } catch (err) {
      console.error('取消失败:', err);
    } finally {
      setCancelling(false);
    }
  };

  const handleContinue = async () => {
    setContinuing(true);
    try {
      const result = await agentApi.continue(workflowId);
      if (result.success) startPolling();
    } catch (err) {
      console.error('继续执行失败:', err);
    } finally {
      setContinuing(false);
    }
  };

  const handleRerunTask = async (taskId: string) => {
    setRerunning(taskId);
    try {
      if (editingTaskId === taskId && editPrompt.trim()) {
        await taskApi.rerun(taskId, editPrompt.trim());
      } else {
        await taskApi.rerun(taskId);
      }
      setEditingTaskId(null);
      const list = await workflowApi.getTasks(workflowId);
      setTasks(list);
    } catch (err) {
      console.error('重新生成失败:', err);
    } finally {
      setRerunning(null);
    }
  };

  const handleSavePrompt = async (taskId: string) => {
    try {
      await taskApi.updatePrompt(taskId, editPrompt);
      setEditingTaskId(null);
    } catch (err) {
      console.error('保存提示词失败:', err);
    }
  };

  const startEditPrompt = (task: Task) => {
    setEditPrompt((task.input_params?.prompt as string) || '');
    setEditingTaskId(task.id);
  };

  // 按阶段分组
  const grouped = new Map<string, Task[]>();
  for (const task of tasks) {
    const phase = getPhase(task);
    if (!grouped.has(phase.key)) grouped.set(phase.key, []);
    grouped.get(phase.key)!.push(task);
  }
  const sortedGroups = [...grouped.entries()].sort(
    ([a], [b]) => PHASE_ORDER.indexOf(a) - PHASE_ORDER.indexOf(b)
  );

  if (loading) {
    return (
      <div className="exec-progress">
        <div className="exec-loading">正在获取任务状态...</div>
      </div>
    );
  }

  return (
    <div className="exec-progress">
      {/* 顶部进度条 */}
      <div className="exec-summary">
        <div className="exec-summary-bar">
          <div className="exec-summary-fill" style={{ width: `${totalCount ? (completedCount / totalCount) * 100 : 0}%` }} />
        </div>
        <div className="exec-summary-text-row">
          <span className="exec-summary-text">
            <span className="notranslate">{completedCount}/{totalCount} 任务完成</span>
            {allDone && <span> - 全部完成!</span>}
            {hasFailed && <span> - 存在失败</span>}
            {allPending && <span> - 未启动</span>}
          </span>
          <div className="exec-action-buttons">
            {allDone && finalTask && (
              <button className="exec-download-btn" onClick={() => taskApi.download(finalTask.id)}>
                ⬇️ 下载成品
              </button>
            )}
            {needsContinue && (
              <button className="exec-continue-btn" onClick={handleContinue} disabled={continuing}>
                {continuing ? '提交中...' : '▶️ 继续执行'}
              </button>
            )}
            {needsRetry && (
              <button className="exec-retry-btn" onClick={handleRetry} disabled={retrying}>
                {retrying ? '提交中...' : '🔄 重新执行'}
              </button>
            )}
            {hasRunning && (
              <button className="exec-cancel-btn" onClick={handleCancel} disabled={cancelling}>
                {cancelling ? '停止中...' : '⏹ 停止'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 阶段列表 + 卡片网格 */}
      <div className="exec-phase-list">
        {sortedGroups.map(([phaseKey, phaseTasks], groupIdx) => {
          const phase = getPhase(phaseTasks[0]);
          const phaseDone = phaseTasks.filter((t) => t.status === 'completed').length;
          const phaseTotal = phaseTasks.length;
          const phaseRunning = phaseTasks.some((t) => t.status === 'running');
          const phaseFailed = phaseTasks.some((t) => t.status === 'failed');
          const phaseProgress = phaseTotal ? (phaseDone / phaseTotal) * 100 : 0;

          const nextGroup = sortedGroups[groupIdx + 1];
          const nextHasPending = nextGroup && nextGroup[1].some(
            (t) => t.status === 'pending' || t.status === 'failed'
          );
          const showNextStep = phaseDone === phaseTotal && phaseTotal > 0 && !phaseRunning && nextHasPending;

          return (
            <div key={phaseKey} className="exec-phase-section">
              <div className="exec-phase-header">
                <span className="exec-phase-icon">{phase.icon}</span>
                <span className="exec-phase-label">{phase.label}</span>
                <span className="exec-phase-count notranslate">{phaseDone}/{phaseTotal}</span>
                <div className="exec-phase-bar-mini">
                  <div className="exec-phase-fill-mini" style={{ width: `${phaseProgress}%`, background: phase.color }} />
                </div>
                {phaseRunning && <span className="exec-phase-badge running">进行中</span>}
                {phaseFailed && !phaseRunning && <span className="exec-phase-badge failed">有失败</span>}
                {!phaseRunning && !phaseFailed && phaseDone === phaseTotal && phaseTotal > 0 && (
                  <span className="exec-phase-badge done">完成</span>
                )}
              </div>

              {/* 卡片网格 */}
              <div className="exec-card-grid">
                {phaseTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    editingTaskId={editingTaskId}
                    editPrompt={editPrompt}
                    setEditPrompt={setEditPrompt}
                    rerunning={rerunning}
                    onStartEdit={startEditPrompt}
                    onSavePrompt={handleSavePrompt}
                    onCancelEdit={() => setEditingTaskId(null)}
                    onRerun={handleRerunTask}
                  />
                ))}
              </div>

              {showNextStep && (
                <div className="exec-next-step">
                  <button onClick={handleContinue} disabled={continuing} className="exec-next-step-btn">
                    {continuing ? '提交中...' : `▶️ 下一步：${nextGroup ? getPhase(nextGroup[1][0]).label : ''}`}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
