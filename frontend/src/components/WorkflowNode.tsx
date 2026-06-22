import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import { NODE_TYPES_CONFIG, type NodeTypeKey } from '../types';

function WorkflowNode({ data, selected }: NodeProps) {
  const nodeType = data.nodeType as NodeTypeKey;
  const config = NODE_TYPES_CONFIG[nodeType];
  const color = config?.color || '#6366f1';
  const icon = config?.icon || '⚡';

  // 显示关键参数摘要
  const params = (data.params || {}) as Record<string, unknown>;
  const summary = (() => {
    if (nodeType === 'text_to_video') {
      const text = (params.text as string) || '';
      return text ? `"${text.slice(0, 24)}${text.length > 24 ? '...' : ''}"` : '未配置文本';
    }
    if (nodeType === 'video_analysis' || nodeType === 'subtitle_generation') {
      return (params.video_path as string) ? '已配置' : '未配置输入';
    }
    if (nodeType === 'voice_synthesis') {
      const text = (params.text as string) || '';
      return text ? `"${text.slice(0, 24)}..."` : '未配置文本';
    }
    if (nodeType === 'image_to_video') {
      const url = (params.image_url as string) || '';
      const paths = (params.image_paths as string[]) || [];
      const mode = (params.mode as string) || 'i2v';
      if (url) return `🔗 ${url.slice(-30)} (${mode})`;
      if (paths.length > 0) return `${paths.length} 张图片 (${mode})`;
      return '未选择图片';
    }
    if (nodeType === 'video_processing' || nodeType === 'audio_processing') {
      return (params.action as string) || '未选择操作';
    }
    return '';
  })();

  return (
    <div className={`flow-node ${selected ? 'selected' : ''} ${data.taskStatus ? `status-${data.taskStatus}` : ''}`} style={{ borderColor: selected ? color : undefined }}>
      <Handle type="target" position={Position.Left} style={{ background: color }} />
      <div className="flow-node-header" style={{ background: color + '15' }}>
        <span>{icon}</span>
        <span>{(data.label as string) || config?.label || nodeType}</span>
      </div>
      <div className="flow-node-body">
        {summary}
      </div>
      <Handle type="source" position={Position.Right} style={{ background: color }} />
      {data.taskStatus === 'running' && data.taskProgress !== undefined && (
        <div className="flow-node-progress">
          <div className="flow-node-progress-fill" style={{ width: `${Math.max(data.taskProgress as number, 5)}%`, background: color }} />
        </div>
      )}
    </div>
  );
}

export default memo(WorkflowNode);
