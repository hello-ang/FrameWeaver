import { useState, useRef, useEffect, useCallback } from 'react';
import type { AgentPlan, AgentScene, AgentCharacter, AgentExecutionResult, ReferenceImage } from '../types';
import { agentApi, referenceApi } from '../api/client';
import StoryboardPreview from '../components/StoryboardPreview';
import ExecutionProgress from '../components/ExecutionProgress';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  plan?: AgentPlan;
  execution?: AgentExecutionResult;
  timestamp: Date;
}

const ASPECT_RATIOS = [
  { value: '16:9', label: '16:9', desc: '横屏', resolution: '1152x768' },
  { value: '9:16', label: '9:16', desc: '竖屏', resolution: '768x1152' },
  { value: '1:1', label: '1:1', desc: '方形', resolution: '1024x1024' },
  { value: '4:3', label: '4:3', desc: '经典', resolution: '1024x768' },
  { value: '21:9', label: '21:9', desc: '超宽', resolution: '1536x640' },
];

const DURATION_PRESETS = [
  { value: 15, label: '15秒' },
  { value: 30, label: '30秒' },
  { value: 60, label: '1分钟' },
  { value: 120, label: '2分钟' },
  { value: 150, label: '2分30秒' },
  { value: 0, label: '自定义' },
];

const DEFAULT_MESSAGES: ChatMessage[] = [
  {
    id: 'welcome',
    role: 'assistant',
    content: '你好！我是AI视频创作智能体。告诉我你想要什么视频，我来帮你规划、生成、合成。\n\n你可以在下方选择画面比例和时长，然后描述你的视频内容即可。\n\n上传参考图后，在输入框中输入 @ 即可引用已有图片。',
    timestamp: new Date(),
  },
];

const REF_TYPE_OPTIONS = [
  { value: 'character', label: '角色' },
  { value: 'scene', label: '场景' },
  { value: 'keyframe', label: '关键帧' },
];

export default function AgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    const saved = localStorage.getItem('agentChatHistory');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        return parsed.map((msg: any) => ({ ...msg, timestamp: new Date(msg.timestamp) }));
      } catch { /* ignore */ }
    }
    return DEFAULT_MESSAGES;
  });

  useEffect(() => { localStorage.setItem('agentChatHistory', JSON.stringify(messages)); }, [messages]);

  const clearHistory = () => { setMessages(DEFAULT_MESSAGES); localStorage.removeItem('agentChatHistory'); };

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  // 从 URL hash 读取标签状态
  const getTabFromHash = (): 'new' | 'history' => window.location.hash === '#history' ? 'history' : 'new';
  const [activeTab, setActiveTabRaw] = useState<'new' | 'history'>(getTabFromHash);
  const setActiveTab = (tab: 'new' | 'history') => {
    window.location.hash = tab === 'new' ? '#new' : '#history';
    setActiveTabRaw(tab);
  };
  useEffect(() => {
    const onHashChange = () => setActiveTabRaw(getTabFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [duration, setDuration] = useState(30);
  const [customDuration, setCustomDuration] = useState('');
  const [showCustomDuration, setShowCustomDuration] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ===== 参考图库 =====
  const [references, setReferences] = useState<ReferenceImage[]>([]);
  const [showRefPanel, setShowRefPanel] = useState(false);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploadType, setUploadType] = useState('character');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ===== @提及下拉菜单 =====
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionAtPos, setMentionAtPos] = useState(-1);
  const [mentionHighlight, setMentionHighlight] = useState(0);

  const loadReferences = useCallback(async () => {
    try { setReferences(await referenceApi.list()); } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadReferences(); }, [loadReferences]);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const addMessage = (msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    setMessages(prev => [...prev, { ...msg, id: crypto.randomUUID(), timestamp: new Date() }]);
  };

  // ===== @提及：输入变化 =====
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    const cursor = e.target.selectionStart ?? val.length;
    setInput(val);

    // 找到光标前最近的 @ 位置
    const before = val.substring(0, cursor);
    const atIdx = before.lastIndexOf('@');
    if (atIdx >= 0 && (atIdx === 0 || /[\s\n]/.test(before[atIdx - 1]))) {
      const query = before.substring(atIdx + 1);
      // 不包含空格且不太长，说明正在输入名称
      if (!/[\n]/.test(query) && query.length < 30) {
        setMentionQuery(query.toLowerCase());
        setMentionAtPos(atIdx);
        setMentionOpen(true);
        setMentionHighlight(0);
        return;
      }
    }
    setMentionOpen(false);
    setMentionAtPos(-1);
  };

  const filteredRefs = references.filter(r =>
    !mentionQuery || r.name.toLowerCase().includes(mentionQuery)
  );

  // 点击或回车选中某项
  const selectMention = (ref: ReferenceImage) => {
    const before = input.substring(0, mentionAtPos);
    const afterQuery = input.substring(mentionAtPos + 1 + mentionQuery.length);
    const newText = `${before}@${ref.name} ${afterQuery}`;
    setInput(newText);
    setMentionOpen(false);
    setMentionAtPos(-1);
    // 聚焦回 textarea，光标放在插入的引用后面
    setTimeout(() => {
      const ta = textareaRef.current;
      if (ta) {
        const pos = (before + `@${ref.name} `).length;
        ta.focus();
        ta.setSelectionRange(pos, pos);
      }
    }, 0);
  };

  // ===== 上传参考图 =====
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) { setUploadFile(file); setShowUploadDialog(true); }
  };

  const handleUpload = async () => {
    if (!uploadFile || !uploadName.trim()) return;
    setUploading(true);
    try {
      await referenceApi.upload(uploadFile, uploadName.trim(), uploadType);
      await loadReferences();
      setShowUploadDialog(false);
      setUploadFile(null);
      setUploadName('');
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '上传失败');
    } finally { setUploading(false); }
  };

  const handleDeleteRef = async (id: string) => {
    if (!confirm('确定删除该参考图？')) return;
    try {
      await referenceApi.delete(id);
      setReferences(prev => prev.filter(r => r.id !== id));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '删除失败');
    }
  };

  // ===== 发送 =====
  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const matchedRefs: { name: string; ref_type: string; url: string }[] = [];
    const atPattern = /@([^\s@]+)/g;
    let m;
    while ((m = atPattern.exec(text)) !== null) {
      const ref = references.find(r => r.name === m[1]);
      if (ref) matchedRefs.push({ name: ref.name, ref_type: ref.ref_type, url: ref.url });
    }

    const ratio = ASPECT_RATIOS.find(r => r.value === aspectRatio);
    const finalDuration = showCustomDuration ? (parseInt(customDuration) || 30) : duration;
    const fullMessage = `${text}，画面比例${aspectRatio}(${ratio?.desc || '横屏'})，总时长${finalDuration}秒，分辨率${ratio?.resolution || '1152x768'}。`;

    setInput('');
    setMentionOpen(false);
    addMessage({ role: 'user', content: fullMessage });
    setLoading(true);

    try {
      const plan = await agentApi.chat(fullMessage, undefined, matchedRefs);
      addMessage({
        role: 'assistant',
        content: `好的，我为你规划了 **${plan.title}** 视频方案：\n总时长 ${plan.total_duration} 秒，共 ${plan.scenes?.length || 0} 个分镜。${matchedRefs.length ? `\n已应用 ${matchedRefs.length} 张参考图。` : ''}\n\n请查看下方分镜脚本，满意后点击"确认执行"开始生成。`,
        plan,
      });
    } catch (err: unknown) {
      addMessage({ role: 'assistant', content: `抱歉，规划出错：${err instanceof Error ? err.message : '未知错误'}\n\n请重试。` });
    } finally { setLoading(false); }
  };

  const handleSceneUpdate = (planId: string, index: number, updates: Partial<AgentScene>) => {
    setMessages(prev => prev.map(msg => {
      if (msg.plan?.plan_id === planId) {
        return { ...msg, plan: { ...msg.plan, scenes: msg.plan.scenes.map((s, i) => i === index ? { ...s, ...updates } : s) } };
      }
      return msg;
    }));
  };

  const handleCharacterUpdate = (planId: string, index: number, updates: Partial<AgentCharacter>) => {
    setMessages(prev => prev.map(msg => {
      if (msg.plan?.plan_id === planId) {
        return { ...msg, plan: { ...msg.plan, characters: msg.plan.characters.map((c, i) => i === index ? { ...c, ...updates } : c) } };
      }
      return msg;
    }));
  };

  const handleGlobalUpdate = (planId: string, updates: Record<string, unknown>) => {
    setMessages(prev => prev.map(msg => msg.plan?.plan_id === planId ? { ...msg, plan: { ...msg.plan, ...updates } } : msg));
  };

  const handleConfirm = async (plan: AgentPlan) => {
    addMessage({ role: 'user', content: `确认执行！开始生成 ${plan.characters?.length || 0} 个角色 + ${plan.scenes?.length || 0} 个分镜视频` });
    setLoading(true);
    try {
      const result = await agentApi.confirm(plan.plan_id);
      addMessage({
        role: 'assistant',
        content: result.success
          ? `工作流已开始执行！共 ${result.task_ids?.length || 0} 个任务处理中。`
          : `执行失败：${result.error}`,
        execution: result,
      });
    } catch (err: unknown) {
      addMessage({ role: 'assistant', content: `执行出错：${err instanceof Error ? err.message : '未知错误'}` });
    } finally { setLoading(false); }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (mentionOpen && filteredRefs.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setMentionHighlight(h => (h + 1) % filteredRefs.length); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setMentionHighlight(h => (h - 1 + filteredRefs.length) % filteredRefs.length); return; }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); selectMention(filteredRefs[mentionHighlight]); return; }
      if (e.key === 'Escape') { setMentionOpen(false); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const handleDurationSelect = (value: number) => {
    if (value === 0) { setShowCustomDuration(true); setDuration(0); }
    else { setShowCustomDuration(false); setCustomDuration(''); setDuration(value); }
  };

  return (
    <div className="studio-container">
      {/* 左侧控制台 */}
      <div className="studio-sidebar">
        <div className="studio-header">
          <h2>AI 创作中台</h2>
          <p>全自动分镜、编排、生成、合成</p>
          <button onClick={clearHistory} className="studio-clear-btn" title="清空工作台">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" /></svg>
          </button>
        </div>

        <div className="studio-input-section">
          <label className="studio-label">画面描述</label>
          <div style={{ position: 'relative' }}>
            <textarea
              ref={textareaRef}
              className="studio-textarea"
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="描述你的视频... 输入 @ 可引用参考图"
              rows={4}
              disabled={loading}
            />
            {/* @提及下拉菜单 */}
            {mentionOpen && filteredRefs.length > 0 && (
              <div className="mention-dropdown">
                {filteredRefs.map((ref, idx) => (
                  <div
                    key={ref.id}
                    className={`mention-item${idx === mentionHighlight ? ' highlight' : ''}`}
                    onMouseDown={(e) => { e.preventDefault(); selectMention(ref); }}
                    onMouseEnter={() => setMentionHighlight(idx)}
                  >
                    <img src={ref.url} alt={ref.name} className="mention-thumb" />
                    <div className="mention-info">
                      <span className="mention-name">@{ref.name}</span>
                      <span className="mention-type">
                        {ref.ref_type === 'character' ? '角色' : ref.ref_type === 'scene' ? '场景' : '关键帧'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {mentionOpen && filteredRefs.length === 0 && mentionQuery && (
              <div className="mention-dropdown">
                <div className="mention-empty">没有匹配的参考图</div>
              </div>
            )}
          </div>
          <div className="studio-hints">
            <span onClick={() => setInput('功夫熊猫和老虎在竹林中激烈打斗，动作帅气')}>🐼 熊猫打斗</span>
            <span onClick={() => setInput('深海珊瑚礁中的热带鱼群，阳光穿透水面')}>🐠 海底纪录片</span>
            <span onClick={() => setInput('霓虹灯闪烁的赛博朋克城市夜景，飞行汽车穿梭')}>🏙️ 赛博朋克</span>
          </div>
        </div>

        {/* 参考图库面板 */}
        <div className="studio-ref-panel">
          <div className="studio-ref-toggle" onClick={() => setShowRefPanel(!showRefPanel)}>
            <span>参考图库 {references.length > 0 && `(${references.length})`}</span>
            <span className={`ref-arrow${showRefPanel ? ' open' : ''}`}>▼</span>
          </div>
          {showRefPanel && (
            <div className="studio-ref-body">
              <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleFileSelect} />
              <button className="studio-ref-upload-btn" onClick={() => fileInputRef.current?.click()}>
                + 上传参考图
              </button>
              {references.length === 0 ? (
                <div className="studio-ref-empty">暂无参考图，上传后可在输入框用 @名称 引用</div>
              ) : (
                <div className="studio-ref-grid">
                  {references.map(ref => (
                    <div key={ref.id} className="studio-ref-card" title={`@${ref.name} (${ref.ref_type === 'character' ? '角色' : ref.ref_type === 'scene' ? '场景' : '关键帧'})`}>
                      <img src={ref.url} alt={ref.name} />
                      <div className="studio-ref-label">{ref.name}</div>
                      <button className="studio-ref-del" onClick={() => handleDeleteRef(ref.id)}>×</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="studio-params-section">
          <div className="studio-param-group">
            <label className="studio-label">画面比例</label>
            <div className="studio-pills">
              {ASPECT_RATIOS.map(r => (
                <button key={r.value} className={`studio-pill${aspectRatio === r.value ? ' active' : ''}`} onClick={() => setAspectRatio(r.value)}>{r.label}</button>
              ))}
            </div>
          </div>
          <div className="studio-param-group">
            <label className="studio-label">视频时长</label>
            <div className="studio-pills">
              {DURATION_PRESETS.map(d => (
                <button
                  key={d.value}
                  className={`studio-pill${(!showCustomDuration && duration === d.value && d.value !== 0) || (showCustomDuration && d.value === 0) ? ' active' : ''}`}
                  onClick={() => handleDurationSelect(d.value)}
                >{d.label}</button>
              ))}
            </div>
            {showCustomDuration && (
              <div className="studio-custom-duration">
                <input type="number" value={customDuration} onChange={e => setCustomDuration(e.target.value)} placeholder="自定义秒数" min={1} max={600} />
                <span>秒</span>
              </div>
            )}
          </div>
        </div>

        <div className="studio-action-section">
          <button className="studio-generate-btn" onClick={handleSend} disabled={loading || !input.trim()}>
            {loading
              ? <span className="studio-loading-text"><span className="spinner"></span> <span>正在智能规划...</span></span>
              : <span>🚀 一键生成大片</span>}
          </button>
        </div>
      </div>

      {/* 右侧主舞台 */}
      <div className="studio-main">
        {activeTab === 'history' ? (
          /* 历史记录列表 */
          <div className="studio-history-list">
            {messages.filter(m => m.execution).length === 0 ? (
              <div className="studio-history-empty">
                <p>还没有执行过的任务</p>
                <p style={{ fontSize: 13, color: '#94a3b8' }}>在「新建任务」中输入描述并确认执行后，这里会显示历史记录</p>
              </div>
            ) : (
              messages.filter(m => m.execution).map((msg) => {
                // 找到对应的用户 prompt 消息
                const idx = messages.indexOf(msg);
                const userMsg = idx > 0 && messages[idx - 1]?.role === 'user' ? messages[idx - 1] : null;
                const planTitle = msg.plan?.title || userMsg?.content?.substring(0, 60) || '视频任务';
                const status = msg.execution?.success ? 'completed' : 'failed';
                return (
                  <div
                    key={msg.id}
                    className="history-card"
                    onClick={() => {
                      setActiveTab('new');
                      setTimeout(() => {
                        const el = document.getElementById(`exec-${msg.id}`);
                        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                      }, 100);
                    }}
                  >
                    <div className="history-card-header">
                      <span className="history-card-title">{planTitle}</span>
                      <span className={`history-card-status ${status}`}>
                        {status === 'completed' ? '已完成' : '有失败'}
                      </span>
                    </div>
                    <div className="history-card-meta">
                      {msg.plan && <span>{msg.plan.scenes?.length || 0} 个分镜 · {msg.plan.total_duration || 0}秒</span>}
                      {msg.execution?.task_ids && <span> · {msg.execution.task_ids.length} 个任务</span>}
                    </div>
                    <div className="history-card-time">
                      {new Date(msg.timestamp).toLocaleString('zh-CN')}
                    </div>
                    <button
                      className="history-card-view"
                      onClick={(e) => { e.stopPropagation(); setActiveTab('new'); setTimeout(() => { document.getElementById(`exec-${msg.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 100); }}
                    >
                      查看任务看板 →
                    </button>
                  </div>
                );
              })
            )}
          </div>
        ) : (
          /* 新建任务（原有内容） */
          (() => {
            const lastPromptIndex = messages.map(m => m.role === 'user' && !m.content.startsWith('确认执行！')).lastIndexOf(true);
            const currentMessages = lastPromptIndex >= 0 ? messages.slice(lastPromptIndex) : messages;
            
            return (
              <>
                {currentMessages.length === 1 && currentMessages[0].id === 'welcome' ? (
                  <div className="studio-empty">
                    <div className="studio-empty-icon">🎬</div>
                    <h3>欢迎来到 AI 创作中台</h3>
                    <p>在左侧输入您的创意，AI 将为您生成完整的分镜脚本和视频作品</p>
                  </div>
                ) : (
                  <div className="studio-feed">
                    {currentMessages.map(msg => {
                      if (msg.id === 'welcome') return null;
              if (msg.role === 'user') {
                return (
                  <div key={msg.id} className="studio-prompt-log">
                    <div className="prompt-label">Prompt</div>
                    <div className="prompt-text">{msg.content}</div>
                  </div>
                );
              }
              return (
                <div key={msg.id} className="studio-result-card">
                  {msg.plan && (
                    <div className="studio-plan-wrapper">
                      <div className="studio-plan-header">
                        <h3>{msg.plan.title || '分镜规划'}</h3>
                        <span className="plan-meta">共 {msg.plan.scenes?.length || 0} 个分镜 · 预计 {msg.plan.total_duration || 0} 秒</span>
                      </div>
                      <StoryboardPreview
                        characters={msg.plan.characters || []}
                        scenes={msg.plan.scenes || []}
                        global={{
                          global_style: msg.plan.global_style || 'cinematic',
                          global_negative_prompt: msg.plan.global_negative_prompt || '',
                          global_camera_motion: msg.plan.global_camera_motion || 'static',
                          width: msg.plan.width || 1152,
                          height: msg.plan.height || 768,
                        }}
                        onCharacterUpdate={(idx, u) => handleCharacterUpdate(msg.plan!.plan_id, idx, u)}
                        onSceneUpdate={(idx, u) => handleSceneUpdate(msg.plan!.plan_id, idx, u)}
                        onGlobalUpdate={u => handleGlobalUpdate(msg.plan!.plan_id, u)}
                      />
                      <div className="studio-plan-actions">
                        <button className="studio-btn-primary" onClick={() => handleConfirm(msg.plan!)} disabled={loading}>确认执行生成任务</button>
                      </div>
                    </div>
                  )}
                  {/* 锚点 */}
                  <div id={`exec-${msg.id}`} />
                  {msg.execution?.success && msg.execution.workflow_id && (
                    <div className="studio-execution-wrapper">
                      <div className="studio-execution-header"><h3>任务执行看板</h3></div>
                      <ExecutionProgress workflowId={msg.execution.workflow_id} taskIds={msg.execution.task_ids || []} />
                      {msg.execution.project_id && (
                        <a href={`/projects/${msg.execution.project_id}`} className="studio-btn-secondary" style={{ marginTop: 16, display: 'inline-block' }}>查看项目详情</a>
                      )}
                    </div>
                  )}
                  {!msg.plan && !msg.execution && <div className="studio-system-msg">{msg.content}</div>}
                </div>
              );
            })}
            <div ref={messagesEndRef} className="studio-bottom-padding" />
              </div>
            )}
          </>
          );
        })()
        )}
      </div>

      {/* 上传对话框 */}
      {showUploadDialog && (
        <div className="upload-overlay" onClick={() => !uploading && setShowUploadDialog(false)}>
          <div className="upload-dialog" onClick={e => e.stopPropagation()}>
            <h3>上传参考图</h3>
            {uploadFile && (
              <div className="upload-preview">
                <img src={URL.createObjectURL(uploadFile)} alt="preview" />
              </div>
            )}
            <div className="upload-field">
              <label>引用名称</label>
              <input type="text" value={uploadName} onChange={e => setUploadName(e.target.value)} placeholder="例如：炎龙侠、竹林场景..." />
            </div>
            <div className="upload-field">
              <label>参考类型</label>
              <div className="upload-type-btns">
                {REF_TYPE_OPTIONS.map(opt => (
                  <button key={opt.value} onClick={() => setUploadType(opt.value)} className={uploadType === opt.value ? 'active' : ''}>{opt.label}</button>
                ))}
              </div>
            </div>
            <div className="upload-actions">
              <button className="upload-cancel" onClick={() => setShowUploadDialog(false)} disabled={uploading}>取消</button>
              <button className="upload-confirm" onClick={handleUpload} disabled={uploading || !uploadName.trim()}>
                {uploading ? '上传中...' : '上传'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
