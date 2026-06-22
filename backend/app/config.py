"""应用配置管理"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "FrameWeaver"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 路径配置
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    UPLOAD_DIR: Path = STORAGE_DIR / "uploads"
    OUTPUT_DIR: Path = STORAGE_DIR / "outputs"
    TEMP_DIR: Path = STORAGE_DIR / "temp"
    REFERENCES_DIR: Path = STORAGE_DIR / "references"

    # 公网访问地址（用于自托管图片，彻底替代外部图床）
    # 设置为你的公网地址，例如:
    #   http://你的公网IP:8000
    #   https://xxx.ngrok-free.app
    #   http://192.168.1.100:8000  (局域网)
    # 留空则回退到外部图床（不推荐）
    PUBLIC_BASE_URL: str = ""

    # 数据库配置
    DATABASE_URL: str = "sqlite:///./video_workflow.db"

    # Redis 配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # Celery 配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # AI 服务配置
    WHISPER_MODEL: str = "base"  # tiny, base, small, medium, large
    TTS_VOICE: str = "zh-CN-XiaoxiaoNeural"  # Edge-TTS 默认音色

    # ============================================================
    # AI 模型配置（按能力分离，支持任意 OpenAI 兼容 API）
    # ============================================================

    # 规划模型（剧本规划/分镜设计/提示词生成）
    # 示例: DeepSeek、GPT-4、Claude 等
    PLANNING_API_KEY: str = ""
    PLANNING_BASE_URL: str = "https://api.deepseek.com"
    PLANNING_MODEL: str = "deepseek-chat"

    # 图像生成模型（文生图/图生图）
    # 示例: Agnes Image、GPT-Image、FLUX 等
    IMAGE_API_KEY: str = ""
    IMAGE_BASE_URL: str = "https://apihub.agnes-ai.com"
    IMAGE_MODEL: str = "agnes-image-2.1-flash"       # 文生图模型
    IMG2IMG_MODEL: str = "agnes-image-2.0-flash"     # 图生图模型（可选，留空则使用 IMAGE_MODEL）

    # 视频生成模型（图生视频/文生视频）
    # 示例: Agnes Video、Seedance 2.0、Runway 等
    VIDEO_API_KEY: str = ""
    VIDEO_BASE_URL: str = "https://apihub.agnes-ai.com"
    VIDEO_MODEL: str = "agnes-video-v2.0"

    # ============================================================
    # 兼容旧配置（别名，逐步迁移）
    # ============================================================
    @property
    def AGNES_API_KEY(self) -> str:
        """兼容旧代码，优先使用 IMAGE_API_KEY"""
        return self.IMAGE_API_KEY or self.VIDEO_API_KEY

    @property
    def AGNES_API_BASE_URL(self) -> str:
        """兼容旧代码"""
        return self.IMAGE_BASE_URL

    @property
    def AGNES_VIDEO_MODEL(self) -> str:
        return self.VIDEO_MODEL

    @property
    def AGNES_IMAGE_MODEL(self) -> str:
        return self.IMAGE_MODEL

    @property
    def AGNES_IMG2IMG_MODEL(self) -> str:
        return self.IMG2IMG_MODEL or self.IMAGE_MODEL

    @property
    def AGNES_TEXT_MODEL(self) -> str:
        return self.PLANNING_MODEL

    @property
    def DEEPSEEK_API_KEY(self) -> str:
        return self.PLANNING_API_KEY

    @property
    def DEEPSEEK_BASE_URL(self) -> str:
        return self.PLANNING_BASE_URL

    @property
    def DEEPSEEK_MODEL(self) -> str:
        return self.PLANNING_MODEL

    # 文件上传限制
    MAX_UPLOAD_SIZE: int = 500 * 1024 * 1024  # 500MB

    # CORS 配置
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


settings = Settings()

# 确保存储目录存在
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
settings.REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
