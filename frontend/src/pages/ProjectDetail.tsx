import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { projectApi, workflowApi, mediaApi } from '../api/client';
import type { Project, Workflow, Media } from '../types';

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [mediaFiles, setMediaFiles] = useState<Media[]>([]);
  const [activeTab, setActiveTab] = useState<'workflows' | 'media'>('workflows');
  const [showWfModal, setShowWfModal] = useState(false);
  const [wfName, setWfName] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!projectId) return;
    loadData();
  }, [projectId]);

  const loadData = async () => {
    if (!projectId) return;
    try {
      const [p, wfs, media] = await Promise.all([
        projectApi.get(projectId),
        workflowApi.list(projectId),
        mediaApi.list(projectId),
      ]);
      setProject(p);
      setWorkflows(wfs);
      setMediaFiles(media);
    } catch (e) {
      console.error(e);
    }
  };

  const createWorkflow = async () => {
    if (!wfName.trim() || !projectId) return;
    try {
      const wf = await workflowApi.create({
        project_id: projectId,
        name: wfName.trim(),
      });
      setWorkflows(prev => [wf, ...prev]);
      setShowWfModal(false);
      setWfName('');
    } catch (e) {
      alert(e instanceof Error ? e.message : '创建失败');
    }
  };

  const deleteWorkflow = async (id: string, name: string) => {
    if (!confirm(`确认删除工作流 "${name}"？`)) return;
    try {
      await workflowApi.delete(id);
      setWorkflows(prev => prev.filter(w => w.id !== id));
    } catch (e) {
      alert(e instanceof Error ? e.message : '删除失败');
    }
  };

  const handleUpload = async (files: FileList | null) => {
    if (!files || !projectId) return;
    setUploading(true);
    try {
      const uploads: Media[] = [];
      for (const file of Array.from(files)) {
        const media = await mediaApi.upload(file, projectId);
        uploads.push(media);
      }
      setMediaFiles(prev => [...uploads, ...prev]);
    } catch (e) {
      alert(e instanceof Error ? e.message : '上传失败');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const deleteMedia = async (id: string) => {
    if (!confirm('确认删除此文件？')) return;
    try {
      await mediaApi.delete(id);
      setMediaFiles(prev => prev.filter(m => m.id !== id));
    } catch (e) {
      alert(e instanceof Error ? e.message : '删除失败');
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const mediaTypeIcon: Record<string, string> = {
    video: '🎬', audio: '🎵', image: '🖼️', subtitle: '📝', other: '📄',
  };

  if (!project) return <div className="page"><p>加载中...</p></div>;

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to="/">项目</Link>
        <span>/</span>
        <span>{project.name}</span>
      </div>

      <div className="page-header">
        <div>
          <h1 className="page-title">{project.name}</h1>
          {project.description && <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginTop: 4 }}>{project.description}</p>}
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${activeTab === 'workflows' ? 'active' : ''}`} onClick={() => setActiveTab('workflows')}>
          工作流 ({workflows.length})
        </button>
        <button className={`tab ${activeTab === 'media' ? 'active' : ''}`} onClick={() => setActiveTab('media')}>
          媒体资源 ({mediaFiles.length})
        </button>
      </div>

      {activeTab === 'workflows' && (
        <>
          <div style={{ marginBottom: 16 }}>
            <button className="btn btn-primary" onClick={() => setShowWfModal(true)}>+ 新建工作流</button>
          </div>
          {workflows.length === 0 ? (
            <div className="empty">
              <div className="empty-icon">🔧</div>
              <p className="empty-text">暂无工作流，点击创建开始</p>
            </div>
          ) : (
            <div className="card-grid">
              {workflows.map(wf => (
                <div key={wf.id} className="card">
                  <div className="card-title">{wf.name}</div>
                  <div className="card-desc">{wf.description || '暂无描述'}</div>
                  <div className="card-meta">
                    <span className={`badge badge-${wf.status}`}>{wf.status}</span>
                    <span>{(wf.nodes || []).length} 个节点</span>
                  </div>
                  <div className="card-actions">
                    <button className="btn btn-sm btn-primary" onClick={() => navigate(`/workflows/${wf.id}`)}>
                      编辑
                    </button>
                    <button className="btn btn-sm btn-danger" onClick={() => deleteWorkflow(wf.id, wf.name)}>
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {activeTab === 'media' && (
        <>
          <div style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
              {uploading ? '上传中...' : '+ 上传文件'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="video/*,audio/*,image/*,.srt,.vtt,.ass"
              style={{ display: 'none' }}
              onChange={e => handleUpload(e.target.files)}
            />
          </div>
          {mediaFiles.length === 0 ? (
            <div className="empty">
              <div className="empty-icon">📁</div>
              <p className="empty-text">暂无媒体资源</p>
            </div>
          ) : (
            <div className="media-grid">
              {mediaFiles.map(m => (
                <div key={m.id} className="media-card">
                  <div className="media-thumb">
                    {m.media_type === 'image' ? (
                      <img src={`/storage/uploads/${m.file_path.split('uploads/')[1] || ''}`} alt={m.filename} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : (
                      mediaTypeIcon[m.media_type || 'other'] || '📄'
                    )}
                  </div>
                  <div className="media-info">
                    <div className="media-name" title={m.filename}>{m.filename}</div>
                    <div className="media-meta">
                      {formatSize(m.file_size)}
                      {m.metadata?.duration ? ` · ${Math.round(Number(m.metadata.duration))}s` : ''}
                    </div>
                    <div style={{ marginTop: 4, display: 'flex', gap: 4 }}>
                      <a className="btn btn-sm" href={mediaApi.getDownloadUrl(m.id)} download={m.filename}>下载</a>
                      <button className="btn btn-sm btn-danger" onClick={() => deleteMedia(m.id)}>删除</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {showWfModal && (
        <div className="modal-overlay" onClick={() => setShowWfModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2 className="modal-title">新建工作流</h2>
            <div className="form-group">
              <label>工作流名称</label>
              <input className="input" value={wfName} onChange={e => setWfName(e.target.value)} placeholder="输入工作流名称" autoFocus />
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowWfModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={createWorkflow} disabled={!wfName.trim()}>创建</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
