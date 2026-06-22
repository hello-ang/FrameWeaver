import { useState, useEffect } from 'react';
import type { Node } from '@xyflow/react';
import { NODE_TYPES_CONFIG } from '../types';
import type { NodeTypeKey } from '../types';

interface Props {
  node: Node;
  onUpdate: (nodeId: string, params: Record<string, unknown>) => void;
  onDelete: () => void;
}

export default function NodeParamsPanel({ node, onUpdate, onDelete }: Props) {
  const nodeType = node.data.nodeType as NodeTypeKey;
  const config = NODE_TYPES_CONFIG[nodeType];
  const [params, setParams] = useState<Record<string, unknown>>({});

  useEffect(() => {
    setParams({ ...(node.data.params as Record<string, unknown>) || {} });
  }, [node.id, node.data.params]);

  const updateParam = (key: string, value: unknown) => {
    const next = { ...params, [key]: value };
    setParams(next);
    onUpdate(node.id, next);
  };

  const renderField = (key: string, value: unknown) => {
    // 布尔值
    if (typeof value === 'boolean') {
      return (
        <div className="form-group" key={key}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="checkbox"
              checked={value}
              onChange={e => updateParam(key, e.target.checked)}
            />
            {key}
          </label>
        </div>
      );
    }

    // 数字
    if (typeof value === 'number') {
      return (
        <div className="form-group" key={key}>
          <label>{key}</label>
          <input
            className="input"
            type="number"
            value={value}
            onChange={e => updateParam(key, Number(e.target.value))}
          />
        </div>
      );
    }

    // 数组
    if (Array.isArray(value)) {
      return (
        <div className="form-group" key={key}>
          <label>{key}（每行一个）</label>
          <textarea
            className="textarea"
            value={(value as string[]).join('\n')}
            onChange={e => updateParam(key, e.target.value.split('\n').filter(Boolean))}
          />
        </div>
      );
    }

    // 选择框（特定字段）
    if (key === 'action') {
      const options = nodeType === 'video_processing'
        ? ['trim', 'concat', 'transcode', 'extract_audio', 'merge_audio_video', 'burn_subtitle', 'thumbnail', 'video_info']
        : ['adjust_volume', 'mix_audio', 'convert_format', 'trim_audio', 'add_fade'];
      return (
        <div className="form-group" key={key}>
          <label>{key}</label>
          <select className="select" value={value as string} onChange={e => updateParam(key, e.target.value)}>
            {options.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      );
    }

    if (key === 'api_provider') {
      return (
        <div className="form-group" key={key}>
          <label>API 提供商</label>
          <select className="select" value={value as string} onChange={e => updateParam(key, e.target.value)}>
            <option value="agnes">Agnes AI（推荐）</option>
            <option value="mock">Mock（本地测试）</option>
            <option value="local">本地 FFmpeg</option>
          </select>
        </div>
      );
    }

    if (key === 'mode' && nodeType === 'image_to_video') {
      return (
        <div className="form-group" key={key}>
          <label>生成模式</label>
          <select className="select" value={value as string} onChange={e => updateParam(key, e.target.value)}>
            <option value="i2v">单图转视频</option>
            <option value="multi">多图视频</option>
            <option value="keyframes">关键帧动画</option>
          </select>
        </div>
      );
    }

    if (key === 'zoom_effect') {
      return (
        <div className="form-group" key={key}>
          <label>{key}</label>
          <select className="select" value={value as string} onChange={e => updateParam(key, e.target.value)}>
            <option value="none">无</option>
            <option value="zoom_in">放大</option>
            <option value="zoom_out">缩小</option>
            <option value="pan_left">左移</option>
            <option value="pan_right">右移</option>
          </select>
        </div>
      );
    }

    // 长文本
    if (key === 'text' || key === 'description') {
      return (
        <div className="form-group" key={key}>
          <label>{key === 'text' ? '文本内容' : key}</label>
          <textarea
            className="textarea"
            value={value as string}
            onChange={e => updateParam(key, e.target.value)}
            placeholder={key === 'text' ? '输入文字脚本或场景描述...' : ''}
          />
        </div>
      );
    }

    // 默认字符串
    return (
      <div className="form-group" key={key}>
        <label>{key}</label>
        <input
          className="input"
          value={value as string}
          onChange={e => updateParam(key, e.target.value)}
        />
      </div>
    );
  };

  return (
    <div className="params-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div className="params-panel-title">
          {config?.icon} {(node.data.label as string) || config?.label}
        </div>
        <button className="btn btn-sm btn-danger" onClick={onDelete}>删除</button>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
        ID: {node.id}
      </div>

      {Object.entries(params).map(([key, value]) => renderField(key, value))}

      {Object.keys(params).length === 0 && (
        <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>此节点无可配置参数</p>
      )}
    </div>
  );
}
