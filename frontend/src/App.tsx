import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { useState, useEffect, useRef } from 'react';
import { healthApi } from './api/client';
import type { HealthCheckResult } from './api/client';
import AgentChat from './pages/AgentChat';
import ProjectList from './pages/ProjectList';
import ProjectDetail from './pages/ProjectDetail';
import WorkflowEditor from './pages/WorkflowEditor';
import './App.css';

function ApiStatusIndicator() {
  const [health, setHealth] = useState<HealthCheckResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [showPopup, setShowPopup] = useState(false);
  const [checking, setChecking] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);

  const doCheck = async () => {
    setChecking(true);
    setLoading(true);
    try {
      const result = await healthApi.checkServices();
      setHealth(result);
    } catch {
      setHealth({ overall: 'degraded', services: {} });
    } finally {
      setLoading(false);
      setChecking(false);
    }
  };

  useEffect(() => {
    doCheck();
    const interval = setInterval(doCheck, 30000); // 每 30 秒自动检测
    return () => clearInterval(interval);
  }, []);

  // 点击外部关闭弹窗
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        setShowPopup(false);
      }
    };
    if (showPopup) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showPopup]);

  const overallOk = health?.overall === 'healthy';
  const statusClass = loading ? 'checking' : overallOk ? 'ok' : 'error';

  const SERVICE_LABELS: Record<string, { label: string; icon: string }> = {
    agnes_api: { label: 'Agnes AI', icon: '🤖' },
    redis: { label: 'Redis', icon: '💾' },
    celery: { label: 'Celery Worker', icon: '⚙️' },
  };

  return (
    <div className="api-status" ref={popupRef}>
      <button
        className={`api-status-btn ${statusClass}`}
        onClick={() => setShowPopup(!showPopup)}
        title={loading ? '检测中...' : overallOk ? '所有服务正常' : '部分服务异常'}
        disabled={checking}
      >
        <span className={`status-dot ${statusClass}`} />
        <span className="status-text">
          {checking ? '检测中' : loading ? '检测中' : overallOk ? '服务正常' : '服务异常'}
        </span>
      </button>

      {showPopup && (
        <div className="api-status-popup">
          <div className="popup-header">
            <span>服务状态检测</span>
            <button className="popup-retest" onClick={doCheck} disabled={checking}>
              {checking ? '检测中...' : '重新检测'}
            </button>
          </div>
          <div className="popup-body">
            {!health && !loading && (
              <div className="popup-empty">无法连接后端服务</div>
            )}
            {health && Object.entries(health.services).map(([key, svc]) => {
              const meta = SERVICE_LABELS[key] || { label: key, icon: '❓' };
              return (
                <div key={key} className={`popup-service ${svc.status}`}>
                  <div className="popup-service-left">
                    <span className="popup-service-icon">{meta.icon}</span>
                    <span className="popup-service-name">{meta.label}</span>
                  </div>
                  <div className="popup-service-right">
                    <span className={`popup-service-badge ${svc.status}`}>
                      {svc.status === 'ok' ? '正常' : svc.status === 'warning' ? '警告' : '异常'}
                    </span>
                    <span className="popup-service-msg">{svc.message}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function Nav() {
  const location = useLocation();
  const isAgentChat = location.pathname === '/';
  const activeHash = location.hash || '#new';

  return (
    <nav className="app-nav">
      <Link to="/" className={`nav-brand ${isAgentChat ? 'active' : ''}`}>
        <div className="brand-text">
          <span className="brand-title">FrameWeaver</span>
          <span className="brand-subtitle">帧的编织者，从文本到视频的完整工作流</span>
        </div>
      </Link>
      <div className="nav-links">
        <Link
          to="/#new"
          className={`nav-link ${isAgentChat && activeHash !== '#history' ? 'active' : ''}`}
        >
          智能体
        </Link>
        <Link
          to="/projects"
          className={`nav-link ${location.pathname.startsWith('/projects') ? 'active' : ''}`}
        >
          项目
        </Link>
        <a
          href="/#new"
          className={`nav-link ${isAgentChat && activeHash !== '#history' ? 'active' : ''}`}
        >
          新建任务
        </a>
        <a
          href="/#history"
          className={`nav-link ${isAgentChat && activeHash === '#history' ? 'active' : ''}`}
        >
          历史记录
        </a>
      </div>

      <div className="nav-right">
        <ApiStatusIndicator />
      </div>
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Nav />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<AgentChat />} />
            <Route path="/projects" element={<ProjectList />} />
            <Route path="/projects/:projectId" element={<ProjectDetail />} />
            <Route path="/workflows/:workflowId" element={<WorkflowEditor />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
