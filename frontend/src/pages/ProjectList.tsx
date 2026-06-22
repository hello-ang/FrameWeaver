import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectApi } from '../api/client';
import type { Project } from '../types';

export default function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const navigate = useNavigate();

  const fetchProjects = async () => {
    try {
      const data = await projectApi.list();
      setProjects(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchProjects(); }, []);

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      const p = await projectApi.create({ name: name.trim(), description: desc.trim() || undefined });
      setProjects(prev => [p, ...prev]);
      setShowModal(false);
      setName('');
      setDesc('');
    } catch (e) {
      alert(e instanceof Error ? e.message : '创建失败');
    }
  };

  const handleDelete = async (id: string, projectName: string) => {
    if (!confirm(`确认删除项目 "${projectName}"？`)) return;
    try {
      await projectApi.delete(id);
      setProjects(prev => prev.filter(p => p.id !== id));
    } catch (e) {
      alert(e instanceof Error ? e.message : '删除失败');
    }
  };

  if (loading) return <div className="page"><p>加载中...</p></div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">项目列表</h1>
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          + 新建项目
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="empty">
          <div className="empty-icon">📂</div>
          <p className="empty-text">暂无项目，点击"新建项目"开始</p>
        </div>
      ) : (
        <div className="card-grid">
          {projects.map(p => (
            <div key={p.id} className="card" onClick={() => navigate(`/projects/${p.id}`)}>
              <div className="card-title">{p.name}</div>
              <div className="card-desc">{p.description || '暂无描述'}</div>
              <div className="card-meta">
                <span className={`badge badge-${p.status}`}>{p.status}</span>
                <span>{p.created_at ? new Date(p.created_at).toLocaleDateString() : ''}</span>
              </div>
              <div className="card-actions" onClick={e => e.stopPropagation()}>
                <button className="btn btn-sm" onClick={() => navigate(`/projects/${p.id}`)}>
                  打开
                </button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(p.id, p.name)}>
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2 className="modal-title">新建项目</h2>
            <div className="form-group">
              <label>项目名称</label>
              <input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="输入项目名称" autoFocus />
            </div>
            <div className="form-group">
              <label>描述（可选）</label>
              <textarea className="textarea" value={desc} onChange={e => setDesc(e.target.value)} placeholder="项目描述..." />
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={!name.trim()}>创建</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
