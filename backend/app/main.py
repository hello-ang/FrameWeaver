"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.api import projects, workflows, tasks, media, agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    init_db()
    yield
    # 关闭时清理资源
    pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI视频生成与处理工作流平台",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务 - 媒体文件访问
app.mount("/storage/uploads", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="uploads")
app.mount("/storage/outputs", StaticFiles(directory=str(settings.OUTPUT_DIR)), name="outputs")
app.mount("/storage/references", StaticFiles(directory=str(settings.REFERENCES_DIR)), name="references")

# 注册路由
app.include_router(projects.router, prefix="/api/projects", tags=["项目管理"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["工作流"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["任务管理"])
app.include_router(media.router, prefix="/api/media", tags=["媒体文件"])
app.include_router(agent.router, prefix="/api/agent", tags=["AI智能体"])


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }


@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/health/services")
async def services_health_check():
    """
    检查所有外部服务的连通性：
    - Agnes AI API
    - Redis
    - Celery
    """
    results = {}

    # 1. Agnes AI API 连通性
    try:
        from app.ai.agnes_client import get_agnes_client
        from app.config import settings
        client = get_agnes_client()
        has_key = bool(settings.AGNES_API_KEY)
        # 简单检测: 发送一个轻量级 chat 请求
        if has_key:
            client.chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
            results["agnes_api"] = {
                "status": "ok",
                "message": "Agnes AI API 连通",
                "model": settings.AGNES_TEXT_MODEL,
            }
        else:
            results["agnes_api"] = {
                "status": "error",
                "message": "AGNES_API_KEY 未配置",
            }
    except Exception as e:
        results["agnes_api"] = {
            "status": "error",
            "message": f"连接失败: {str(e)[:100]}",
        }

    # 2. Redis 连通性
    try:
        import redis as redis_lib
        r = redis_lib.Redis.from_url(settings.CELERY_BROKER_URL)
        r.ping()
        results["redis"] = {"status": "ok", "message": "Redis 连通"}
    except Exception as e:
        results["redis"] = {
            "status": "error",
            "message": f"Redis 连接失败: {str(e)[:100]}",
        }

    # 3. Celery 状态
    try:
        from app.workers.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=3.0)
        active = inspect.active()
        if active is not None:
            results["celery"] = {
                "status": "ok",
                "message": f"Celery 运行中 ({len(active)} 个 worker)",
            }
        else:
            results["celery"] = {
                "status": "warning",
                "message": "Celery 无响应 (worker 可能未启动)",
            }
    except Exception as e:
        results["celery"] = {
            "status": "error",
            "message": f"Celery 检查失败: {str(e)[:100]}",
        }

    # 汇总状态
    all_ok = all(r["status"] == "ok" for r in results.values())
    return {
        "overall": "healthy" if all_ok else "degraded",
        "services": results,
    }
