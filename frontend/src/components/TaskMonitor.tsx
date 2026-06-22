import type { Task } from '../types';
import { NODE_TYPES_CONFIG, type NodeTypeKey } from '../types';

interface Props {
  tasks: Task[];
  onClose: () => void;
}

const STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_COLORS: Record<string, string> = {
  pending: 'var(--warning)',
  running: 'var(--accent)',
  completed: 'var(--success)',
  failed: 'var(--danger)',
  cancelled: 'var(--text-muted)',
};

export default function TaskMonitor({ tasks, onClose }: Props) {
  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: 16,
      maxHeight: 300,
      overflow: 'auto',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h4 style={{ fontSize: 14, fontWeight: 600 }}>任务执行监控</h4>
        <button className="btn btn-sm" onClick={onClose}>关闭</button>
      </div>

      <div className="task-list">
        {tasks.map(task => {
          const config = NODE_TYPES_CONFIG[task.task_type as NodeTypeKey];
          const statusColor = STATUS_COLORS[task.status || 'pending'] || 'var(--text-muted)';

          return (
            <div key={task.id} className="task-item">
              <div style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: statusColor,
                flexShrink: 0,
              }} />
              <div className="task-item-info">
                <div className="task-item-type">
                  {config?.icon || '⚡'} {config?.label || task.task_type || '任务'}
                </div>
                <div className="task-item-meta">
                  {STATUS_LABELS[task.status || 'pending']}
                  {task.node_id && ` · 节点 ${task.node_id}`}
                  {task.error_message && ` · ${task.error_message}`}
                </div>
              </div>
              <div style={{ width: 120, flexShrink: 0 }}>
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{
                      width: `${task.progress}%`,
                      background: statusColor,
                    }}
                  />
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'right', marginTop: 2 }}>
                  {Math.round(task.progress)}%
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {tasks.length === 0 && (
        <p style={{ color: 'var(--text-muted)', fontSize: 13, textAlign: 'center', padding: 20 }}>
          暂无任务
        </p>
      )}
    </div>
  );
}
