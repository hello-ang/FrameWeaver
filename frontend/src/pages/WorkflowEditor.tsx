import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  Panel,
} from '@xyflow/react';
import type { Node, Edge, Connection, NodeTypes } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { workflowApi, taskApi } from '../api/client';
import { NODE_TYPES_CONFIG, type NodeTypeKey, type Task } from '../types';
import WorkflowNode from '../components/WorkflowNode';
import NodeParamsPanel from '../components/NodeParamsPanel';
import TaskMonitor from '../components/TaskMonitor';

const nodeTypes: NodeTypes = {
  workflowNode: WorkflowNode,
};

export default function WorkflowEditor() {
  const { workflowId } = useParams<{ workflowId: string }>();
  const [workflow, setWorkflow] = useState<ReturnType<typeof workflowApi.get> extends Promise<infer T> ? T : never | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [showTasks, setShowTasks] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<'palette' | 'params'>('palette');
  const reactFlowRef = useRef<HTMLDivElement>(null);

  const isWorkflowActive = useMemo(() => {
    return tasks.some(t => ['pending', 'running'].includes(t.status || ''));
  }, [tasks]);

  // 加载工作流
  useEffect(() => {
    if (!workflowId) return;
    (async () => {
      try {
        const wf = await workflowApi.get(workflowId);
        setWorkflow(wf);

        // 转换后端节点为 ReactFlow 节点
        const rfNodes: Node[] = (wf.nodes || []).map(n => ({
          id: n.id,
          type: 'workflowNode',
          position: n.position || { x: 0, y: 0 },
          data: {
            nodeType: n.type,
            label: n.label || NODE_TYPES_CONFIG[n.type as NodeTypeKey]?.label || n.type,
            params: n.params || {},
          },
        }));

        const rfEdges: Edge[] = (wf.edges || []).map(e => ({
          id: e.id,
          source: e.source,
          target: e.target,
          sourceHandle: e.source_handle,
          targetHandle: e.target_handle,
        }));

        setNodes(rfNodes);
        setEdges(rfEdges);
      } catch (e) {
        console.error(e);
      }
    })();
  }, [workflowId, setNodes, setEdges]);

  // 全局轮询定时器引用
  const pollIntervalRef = useRef<number | null>(null);

  const startPolling = useCallback(async (taskIds: string[]) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    pollIntervalRef.current = window.setInterval(async () => {
      try {
        if (!workflowId) return;
        const [wfResult, results] = await Promise.all([
          workflowApi.get(workflowId),
          Promise.all(taskIds.map(id => taskApi.get(id)))
        ]);
        setWorkflow(wfResult);
        setTasks(results);
        const allDone = results.every(t => ['completed', 'failed', 'cancelled'].includes(t.status || ''));
        if ((allDone || wfResult.status === 'paused' || wfResult.status === 'failed') && pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
      } catch {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      }
    }, 2000);
  }, [workflowId]);

  // 加载任务状态
  useEffect(() => {
    if (!workflowId) return;
    (async () => {
      try {
        const taskList = await workflowApi.getTasks(workflowId);
        if (taskList && taskList.length > 0) {
          setTasks(taskList);
          const isActive = taskList.some(t => ['pending', 'running'].includes(t.status || ''));
          if (isActive) {
            startPolling(taskList.map(t => t.id));
          }
        }
      } catch (e) {
        console.error('获取任务失败:', e);
      }
    })();
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [workflowId, startPolling]);

  // 连线回调
  const onConnect = useCallback((connection: Connection) => {
    setEdges(eds => addEdge({
      ...connection,
      id: `edge-${Date.now()}`,
      animated: true,
    }, eds));
  }, [setEdges]);

  // 节点点击
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
    setSidebarTab('params');
  }, []);

  // 画布点击
  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    setSidebarTab('palette');
  }, []);

  // 从侧边栏拖拽添加节点
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData('application/reactflow') as NodeTypeKey;
    if (!nodeType || !reactFlowRef.current) return;

    const rect = reactFlowRef.current.getBoundingClientRect();
    const position = {
      x: event.clientX - rect.left - 90,
      y: event.clientY - rect.top - 20,
    };

    const config = NODE_TYPES_CONFIG[nodeType];
    const newNode: Node = {
      id: `node-${Date.now()}`,
      type: 'workflowNode',
      position,
      data: {
        nodeType,
        label: config.label,
        params: { ...config.defaultParams },
      },
    };

    setNodes(nds => [...nds, newNode]);
  }, [setNodes]);

  // 更新节点参数
  const updateNodeParams = useCallback((nodeId: string, params: Record<string, unknown>) => {
    setNodes(nds =>
      nds.map(n =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, params } }
          : n
      )
    );
    setSelectedNode(prev =>
      prev && prev.id === nodeId
        ? { ...prev, data: { ...prev.data, params } }
        : prev
    );
  }, [setNodes]);

  // 保存工作流
  const handleSave = async () => {
    if (!workflowId) return;
    setSaving(true);
    try {
      const saveNodes = nodes.map(n => ({
        id: n.id,
        type: n.data.nodeType as string,
        label: n.data.label as string,
        params: n.data.params as Record<string, unknown>,
        position: n.position,
      }));
      const saveEdges = edges.map(e => ({
        id: e.id,
        source: e.source,
        target: e.target,
        source_handle: e.sourceHandle,
        target_handle: e.targetHandle,
      }));
      await workflowApi.update(workflowId, { nodes: saveNodes, edges: saveEdges });
    } catch (e) {
      alert(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  // 运行工作流
  const handleRun = async () => {
    if (!workflowId) return;
    setRunning(true);
    try {
      await handleSave();
      const res = await workflowApi.run(workflowId);
      const taskIds = (res.data?.task_ids as string[]) || [];
      // 加载任务状态
      const taskList = await workflowApi.getTasks(workflowId);
      setTasks(taskList);
      setShowTasks(true);
      // 轮询任务状态
      startPolling(taskIds);
    } catch (e) {
      alert(e instanceof Error ? e.message : '运行失败');
    } finally {
      setRunning(false);
    }
  };

  // 恢复工作流
  const handleResume = async () => {
    if (!workflowId) return;
    setRunning(true);
    try {
      await handleSave();
      await workflowApi.resume(workflowId);
      const wf = await workflowApi.get(workflowId);
      setWorkflow(wf);
      const taskList = await workflowApi.getTasks(workflowId);
      setTasks(taskList);
      setShowTasks(true);
      startPolling(taskList.map(t => t.id));
    } catch (e) {
      alert(e instanceof Error ? e.message : '恢复失败');
    } finally {
      setRunning(false);
    }
  };

  // 同步任务状态到画布节点和连线
  useEffect(() => {
    if (!tasks || tasks.length === 0) return;

    const taskMap = new Map<string, Task>();
    const runningNodes = new Set<string>();
    const completedNodes = new Set<string>();

    tasks.forEach(t => {
      if (t.node_id) {
        taskMap.set(t.node_id, t);
        if (t.status === 'running') runningNodes.add(t.node_id);
        if (t.status === 'completed') completedNodes.add(t.node_id);
      }
    });

    setNodes(nds => nds.map(n => {
      const task = taskMap.get(n.id);
      if (!task) return n;
      // 只有在数据发生变化时才更新，避免过度渲染
      if (n.data.taskStatus !== task.status || n.data.taskProgress !== task.progress) {
        return {
          ...n,
          data: {
            ...n.data,
            taskStatus: task.status,
            taskProgress: task.progress,
          }
        };
      }
      return n;
    }));

    setEdges(eds => eds.map(e => {
      const isTargetRunning = runningNodes.has(e.target);
      const isSourceCompleted = completedNodes.has(e.source);
      const isTargetPending = taskMap.get(e.target)?.status === 'pending';
      const isSourceRunning = runningNodes.has(e.source);

      const shouldAnimate = isTargetRunning || isSourceRunning || (isSourceCompleted && isTargetPending);
      
      // 判断是否需要更新，避免过度渲染
      const currentAnimated = !!e.animated;
      if (currentAnimated !== shouldAnimate) {
        return {
          ...e,
          animated: shouldAnimate,
          style: shouldAnimate ? { stroke: '#3b82f6', strokeWidth: 2 } : { stroke: '#cbd5e1', strokeWidth: 1 }
        };
      }
      return e;
    }));
  }, [tasks, setNodes, setEdges]);

  // 删除选中节点
  const handleDeleteNode = useCallback(() => {
    if (!selectedNode) return;
    setNodes(nds => nds.filter(n => n.id !== selectedNode.id));
    setEdges(eds => eds.filter(e => e.source !== selectedNode.id && e.target !== selectedNode.id));
    setSelectedNode(null);
  }, [selectedNode, setNodes, setEdges]);

  return (
    <div className="workflow-editor">
      {/* 左侧边栏 */}
      <div className="workflow-sidebar">
        <div className="workflow-sidebar-header">
          <div className="breadcrumb" style={{ marginBottom: 8 }}>
            <Link to={workflow ? `/projects/${workflow.project_id}` : '/'}>返回</Link>
          </div>
          <h3 style={{ fontSize: 16, fontWeight: 600 }}>{workflow?.name || '加载中...'}</h3>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button className="btn btn-sm btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
            {workflow?.status === 'paused' ? (
              <button 
                className="btn btn-sm" 
                style={{ background: '#f59e0b', borderColor: '#f59e0b', color: '#fff' }} 
                onClick={handleResume} 
                disabled={running}
              >
                {running ? '恢复中...' : '▶ 继续运行'}
              </button>
            ) : (
              <button 
                className="btn btn-sm" 
                style={{ background: 'var(--success)', borderColor: 'var(--success)', color: '#fff' }} 
                onClick={handleRun} 
                disabled={running || tasks.some(t => ['pending', 'running'].includes(t.status || ''))}
              >
                {running ? '提交中...' : tasks.some(t => ['pending', 'running'].includes(t.status || '')) ? '运作中...' : '▶ 运行'}
              </button>
            )}
            {tasks.length > 0 && (
              <button className="btn btn-sm" onClick={() => setShowTasks(!showTasks)}>
                任务 ({tasks.length})
              </button>
            )}
          </div>
        </div>

        <div className="tabs" style={{ padding: '0 12px' }}>
          <button className={`tab ${sidebarTab === 'palette' ? 'active' : ''}`} onClick={() => setSidebarTab('palette')}>
            节点
          </button>
          <button className={`tab ${sidebarTab === 'params' ? 'active' : ''}`} onClick={() => setSidebarTab('params')} disabled={!selectedNode}>
            参数
          </button>
        </div>

        <div className="workflow-sidebar-content">
          {sidebarTab === 'palette' && (
            <div>
              {Object.entries(NODE_TYPES_CONFIG).map(([type, config]) => (
                <div
                  key={type}
                  className="node-palette-item"
                  draggable
                  onDragStart={e => {
                    e.dataTransfer.setData('application/reactflow', type);
                    e.dataTransfer.effectAllowed = 'move';
                  }}
                >
                  <div className="node-palette-icon" style={{ background: config.color + '20' }}>
                    {config.icon}
                  </div>
                  <span>{config.label}</span>
                </div>
              ))}
              <p style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center', marginTop: 16 }}>
                拖拽节点到画布上开始编排
              </p>
            </div>
          )}

          {sidebarTab === 'params' && selectedNode && (
            <NodeParamsPanel
              node={selectedNode}
              onUpdate={updateNodeParams}
              onDelete={handleDeleteNode}
            />
          )}
        </div>
      </div>

      {/* 画布区域 */}
      <div className="workflow-canvas" ref={reactFlowRef} style={{ position: 'relative' }}>
        {workflow?.status === 'paused' && (
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10, padding: '8px 16px', background: 'rgba(239, 68, 68, 0.9)', color: '#fff', fontSize: 13, textAlign: 'center' }}>
            ⚠️ 工作流由于任务失败已暂停。请点击下方“任务”面板中的失败节点重新生成，确认成功后再点击左上角的“继续运行”。
          </div>
        )}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onDrop={onDrop}
          onDragOver={onDragOver}
          nodeTypes={nodeTypes}
          fitView
          deleteKeyCode="Delete"
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#2e3347" />
          <Controls />
          <MiniMap
            nodeColor={(n) => {
              const nt = n.data?.nodeType as NodeTypeKey;
              return NODE_TYPES_CONFIG[nt]?.color || '#6366f1';
            }}
            maskColor="rgba(0,0,0,0.5)"
          />
        </ReactFlow>

        {/* 任务监控面板 */}
        {showTasks && (
          <Panel position="bottom-center" style={{ width: '90%', maxWidth: 600 }}>
            <TaskMonitor tasks={tasks} onClose={() => setShowTasks(false)} />
          </Panel>
        )}
      </div>
    </div>
  );
}
