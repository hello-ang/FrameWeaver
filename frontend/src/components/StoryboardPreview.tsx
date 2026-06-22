import { useState } from 'react';
import type { AgentScene, AgentCharacter } from '../types';

interface GlobalSettings {
  global_style: string;
  global_negative_prompt: string;
  global_camera_motion: string;
  width: number;
  height: number;
}

interface Props {
  characters?: AgentCharacter[];
  scenes: AgentScene[];
  global?: GlobalSettings;
  onCharacterUpdate?: (index: number, updates: Partial<AgentCharacter>) => void;
  onSceneUpdate: (index: number, updates: Partial<AgentScene>) => void;
  onGlobalUpdate?: (updates: Partial<GlobalSettings>) => void;
}

const CAMERA_OPTIONS = [
  { value: 'static', label: '静态' },
  { value: 'zoom in', label: '推进' },
  { value: 'zoom out', label: '拉远' },
  { value: 'pan left', label: '左摇' },
  { value: 'pan right', label: '右摇' },
  { value: 'tilt up', label: '上仰' },
  { value: 'tilt down', label: '下俯' },
  { value: 'dolly in', label: '推轨' },
  { value: 'orbit', label: '环绕' },
];

const STYLE_OPTIONS = [
  'cinematic', 'anime', 'documentary', 'dreamy', 'vintage',
  'noir', 'fantasy', 'realistic', 'watercolor',
];

export default function StoryboardPreview({ characters, scenes, global, onCharacterUpdate, onSceneUpdate, onGlobalUpdate }: Props) {
  const [editCharIdx, setEditCharIdx] = useState<number | null>(null);
  const [editSceneIdx, setEditSceneIdx] = useState<number | null>(null);
  const [showGlobal, setShowGlobal] = useState(false);

  const RES_OPTIONS = [
    { w: 1152, h: 768, label: '横屏 720p' },
    { w: 1920, h: 1080, label: '1080p 横屏' },
    { w: 768, h: 1152, label: '竖屏' },
    { w: 1024, h: 1024, label: '方形' },
  ];

  return (
    <div className="storyboard">
      {/* 全局锁定参数 */}
      {global && (
        <div className="global-settings-section">
          <div className="global-settings-header" onClick={() => setShowGlobal(!showGlobal)} style={{ cursor: 'pointer' }}>
            <span className="global-settings-title">🎨 全局设定</span>
            <span className="global-settings-summary">
              <span>{global.global_style} · {global.width}x{global.height} · {showGlobal ? '收起 ▲' : '展开 ▼'}</span>
            </span>
          </div>
          {showGlobal && onGlobalUpdate && (
            <div className="global-settings-edit">
              <div className="global-settings-row">
                <label>
                  画面风格
                  <select
                    value={global.global_style}
                    onChange={(e) => onGlobalUpdate({ global_style: e.target.value })}
                  >
                    {STYLE_OPTIONS.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <label>
                  分辨率
                  <select
                    value={`${global.width}x${global.height}`}
                    onChange={(e) => {
                      const [w, h] = e.target.value.split('x').map(Number);
                      onGlobalUpdate({ width: w, height: h });
                    }}
                  >
                    {RES_OPTIONS.map((r) => (
                      <option key={`${r.w}x${r.h}`} value={`${r.w}x${r.h}`}>{r.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  默认运镜
                  <select
                    value={global.global_camera_motion}
                    onChange={(e) => onGlobalUpdate({ global_camera_motion: e.target.value })}
                  >
                    {CAMERA_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                全局负向提示词
                <input
                  type="text"
                  value={global.global_negative_prompt}
                  onChange={(e) => onGlobalUpdate({ global_negative_prompt: e.target.value })}
                  placeholder="blur, distortion, low quality..."
                />
              </label>
            </div>
          )}
        </div>
      )}

      {/* 角色设定区域 */}
      {characters && characters.length > 0 && (
        <div className="characters-section">
          <div className="characters-header">
            <span className="characters-title">👥 角色设定</span>
            <span className="characters-count">{characters.length} 个角色</span>
          </div>
          <div className="character-list">
            {characters.map((char, idx) => (
              <div
                key={idx}
                className={`character-card ${editCharIdx === idx ? 'editing' : ''}`}
              >
                {editCharIdx === idx ? (
                  <div className="character-edit">
                    <label>
                      角色名称
                      <input
                        type="text"
                        value={char.name}
                        onChange={(e) => onCharacterUpdate?.(idx, { name: e.target.value })}
                      />
                    </label>
                    <label>
                      中文描述
                      <textarea
                        rows={2}
                        value={char.description}
                        onChange={(e) => onCharacterUpdate?.(idx, { description: e.target.value })}
                      />
                    </label>
                    <label>
                      英文设定 Prompt
                      <textarea
                        rows={3}
                        value={char.image_prompt}
                        onChange={(e) => onCharacterUpdate?.(idx, { image_prompt: e.target.value })}
                      />
                    </label>
                    <button className="btn btn-sm" onClick={() => setEditCharIdx(null)}>
                      完成编辑
                    </button>
                  </div>
                ) : (
                  <div className="character-preview" onClick={() => setEditCharIdx(idx)}>
                    <div className="character-avatar">
                      {char.image_url ? (
                        <img src={char.image_url} alt={char.name || 'Unknown'} />
                      ) : (
                        <span className="character-icon">{(char.name || '?')[0]}</span>
                      )}
                    </div>
                    <div className="character-info">
                      <span className="character-name">{char.name}</span>
                      <span className="character-desc">{char.description}</span>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 分镜列表 */}
      <div className="storyboard-section-header">
        <span className="storyboard-title">🎬 分镜脚本</span>
        <span className="storyboard-count">{scenes.length} 个分镜</span>
      </div>
      <div className="storyboard-grid">
        {scenes.map((scene) => (
          <div
            key={scene.index}
            className={`storyboard-card ${editSceneIdx === scene.index ? 'editing' : ''}`}
          >
            <div className="scene-header">
              <span className="scene-number">#{scene.index + 1}</span>
              <span className="scene-duration">{scene.duration}s</span>
              <span className="scene-motion">{scene.camera_motion}</span>
            </div>

            {editSceneIdx === scene.index ? (
              <div className="scene-edit">
                <label>
                  中文描述
                  <input
                    type="text"
                    value={scene.prompt_cn}
                    onChange={(e) => onSceneUpdate(scene.index, { prompt_cn: e.target.value })}
                  />
                </label>
                <label>
                  秒级时间线
                  <textarea
                    rows={2}
                    value={scene.time_breakdown}
                    onChange={(e) => onSceneUpdate(scene.index, { time_breakdown: e.target.value })}
                    placeholder="0-3s: 角色入画; 3-8s: 对话..."
                  />
                </label>
                <label>
                  首帧中文画面描述
                  <textarea
                    rows={2}
                    value={scene.first_frame_prompt_cn || ''}
                    onChange={(e) => onSceneUpdate(scene.index, { first_frame_prompt_cn: e.target.value })}
                    placeholder="用中文描述分镜起点的画面细节"
                  />
                </label>
                <label>
                  首帧英文生图 Prompt
                  <textarea
                    rows={2}
                    value={scene.first_frame_prompt}
                    onChange={(e) => onSceneUpdate(scene.index, { first_frame_prompt: e.target.value })}
                    placeholder="英文生图提示词"
                  />
                </label>
                <label>
                  尾帧中文画面描述
                  <textarea
                    rows={2}
                    value={scene.last_frame_prompt_cn || ''}
                    onChange={(e) => onSceneUpdate(scene.index, { last_frame_prompt_cn: e.target.value })}
                    placeholder="用中文描述分镜终点的画面细节"
                  />
                </label>
                <label>
                  尾帧英文生图 Prompt
                  <textarea
                    rows={2}
                    value={scene.last_frame_prompt}
                    onChange={(e) => onSceneUpdate(scene.index, { last_frame_prompt: e.target.value })}
                    placeholder="英文生图提示词"
                  />
                </label>
                <label>
                  动作 Prompt (图生视频)
                  <textarea
                    rows={2}
                    value={scene.prompt}
                    onChange={(e) => onSceneUpdate(scene.index, { prompt: e.target.value })}
                    placeholder="描述该分镜中的动作和运动"
                  />
                </label>
                <label>
                  出场角色
                  <input
                    type="text"
                    value={(scene.scene_characters || []).join(', ')}
                    onChange={(e) => onSceneUpdate(scene.index, { scene_characters: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                    placeholder="逗号分隔角色名，如: 炎龙侠, 怪兽"
                  />
                </label>
                <div className="scene-edit-row">
                  <label>
                    时长(秒)
                    <input
                      type="number"
                      min={1}
                      max={18}
                      step={0.5}
                      value={scene.duration}
                      onChange={(e) => onSceneUpdate(scene.index, { duration: parseFloat(e.target.value) || 5 })}
                    />
                  </label>
                  <label>
                    运镜
                    <input
                      type="text"
                      value={scene.camera_motion}
                      onChange={(e) => onSceneUpdate(scene.index, { camera_motion: e.target.value })}
                      placeholder="运镜描述"
                    />
                  </label>
                </div>
                <button className="btn btn-sm" onClick={() => setEditSceneIdx(null)}>
                  完成编辑
                </button>
              </div>
            ) : (
              <div className="scene-preview" onClick={() => setEditSceneIdx(scene.index)}>
                <p className="scene-desc-cn">{scene.prompt_cn}</p>
                {scene.time_breakdown && (
                  <p className="scene-keyframe" title="时间线">
                    <span className="keyframe-label">时间线:</span> {scene.time_breakdown}
                  </p>
                )}
                {(scene.first_frame_prompt_cn || scene.first_frame_prompt) && (
                  <p className="scene-keyframe" title="首帧描述">
                    <span className="keyframe-label">首帧:</span> {scene.first_frame_prompt_cn || scene.first_frame_prompt}
                  </p>
                )}
                {(scene.last_frame_prompt_cn || scene.last_frame_prompt) && (
                  <p className="scene-keyframe" title="尾帧描述">
                    <span className="keyframe-label">尾帧:</span> {scene.last_frame_prompt_cn || scene.last_frame_prompt}
                  </p>
                )}
                <p className="scene-desc-en">{scene.prompt}</p>
                <div className="scene-tags">
                  <span className="tag">🎥 {scene.camera_motion}</span>
                  <span className="tag">{scene.duration}s</span>
                  {scene.scene_characters && scene.scene_characters.length > 0 && (
                    <span className="tag">👥 {scene.scene_characters.join(', ')}</span>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
