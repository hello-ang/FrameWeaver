# FrameWeaver - PRD 文档

## 产品概述

FrameWeaver 是一个基于 Python 的视频生成与处理工具，提供可视化的工作流编辑器，让用户通过拖拽节点和配置参数来编排复杂的视频处理流水线。

## 核心功能

### 1. 项目管理
- 创建、编辑、删除项目
- 项目内管理所有媒体资源和工作流
- 项目状态管理（活跃/归档）

### 2. 工作流编辑器
- 可视化节点编辑器（拖拽、连接）
- 支持的节点类型：
  - 文生视频：文字描述生成视频片段
  - 视频分析：场景检测、关键帧提取、人脸检测
  - 自动字幕：Whisper 语音识别生成 SRT/ASS
  - 配音合成：Edge-TTS 文字转语音
  - 图生视频：静态图片转视频（含动态效果）
  - 视频处理：裁剪、拼接、转码
  - 音频处理：混音、格式转换、淡入淡出
- 节点参数配置面板
- 工作流保存和加载

### 3. 任务监控
- 实时任务进度显示（WebSocket 推送）
- 任务状态：待处理 / 运行中 / 完成 / 失败 / 已取消
- 任务日志查看
- 任务取消操作

### 4. 媒体资源管理
- 上传视频/音频/图片/字幕文件
- 媒体预览（视频播放器、图片查看器）
- 自动提取媒体元数据（分辨率、时长、编码等）
- 文件下载和管理

## 技术架构

| 组件 | 技术 |
|------|------|
| 前端 | React + Vite + ReactFlow |
| 后端 API | FastAPI (Python 3.11+) |
| 任务引擎 | Celery + Redis |
| AI 服务 | Whisper / Edge-TTS / OpenCV |
| 视频处理 | FFmpeg + ffmpeg-python |
| 数据库 | SQLite (开发) / PostgreSQL (生产) |

## 项目结构

```
视频工作流/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 配置管理
│   │   ├── database.py          # 数据库配置
│   │   ├── models/              # 数据模型
│   │   ├── api/                 # REST API 路由
│   │   ├── services/            # 业务逻辑服务
│   │   ├── ai/                  # AI 能力模块
│   │   └── workers/             # Celery Worker
│   ├── storage/                 # 文件存储
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                    # React 前端
└── docker-compose.yml
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/projects | 创建项目 |
| GET | /api/projects | 项目列表 |
| GET | /api/projects/{id} | 项目详情 |
| PUT | /api/projects/{id} | 更新项目 |
| DELETE | /api/projects/{id} | 删除项目 |
| POST | /api/workflows | 创建工作流 |
| GET | /api/workflows | 工作流列表 |
| POST | /api/workflows/{id}/run | 执行工作流 |
| GET | /api/tasks/{id} | 任务状态 |
| POST | /api/tasks/{id}/cancel | 取消任务 |
| POST | /api/media/upload | 上传媒体 |
| GET | /api/media/{id} | 获取媒体 |
| WS | /api/tasks/ws/{id} | 实时任务推送 |

## 快速启动

```bash
# 1. 启动 Redis
docker-compose up -d redis

# 2. 安装后端依赖
cd backend
pip install -r requirements.txt

# 3. 启动后端 API
uvicorn app.main:app --reload --port 8000

# 4. 启动 Celery Worker
docker start redis
celery -A app.workers.celery_app worker --pool=solo --loglevel=info
celery -A app.workers.celery_app worker --loglevel=info

# 5. 启动前端
cd frontend
npm install
npm run dev
```
