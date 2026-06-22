"""Celery 应用配置"""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "video_workflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    # 序列化配置
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 任务执行配置
    task_track_started=True,
    task_time_limit=3600,          # 单个任务最大执行时间 1小时
    task_soft_time_limit=3000,     # 软超时 50分钟
    worker_max_tasks_per_child=50, # Worker 处理50个任务后重启

    # 重试配置
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # 结果过期
    result_expires=86400,  # 24小时

    # 任务路由
    task_routes={
        "app.workers.tasks.process_video": {"queue": "video"},
        "app.workers.tasks.run_ai_task": {"queue": "ai"},
        "app.workers.tasks.generate_subtitle": {"queue": "ai"},
        "app.workers.tasks.synthesize_voice": {"queue": "ai"},
    },
)

# 自动发现任务
celery_app.autodiscover_tasks(["app.workers"])
