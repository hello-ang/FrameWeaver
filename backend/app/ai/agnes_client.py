"""AI 模型 API 统一客户端

支持文生视频、图生视频、文生图、文本生成等能力。
通过环境变量配置，支持任意 OpenAI 兼容 API。

- 图像生成: IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL, IMG2IMG_MODEL
- 视频生成: VIDEO_API_KEY, VIDEO_BASE_URL, VIDEO_MODEL
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AgnesAPIError(Exception):
    """AI 模型 API 调用异常"""
    def __init__(self, message: str, status_code: int = 0, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AgnesClient:
    """AI 模型 API 客户端（支持图像和视频生成）
    
    根据操作类型自动选择对应的 API 配置：
    - 图像生成: IMAGE_API_KEY, IMAGE_BASE_URL
    - 视频生成: VIDEO_API_KEY, VIDEO_BASE_URL
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 180.0,
    ):
        # 默认使用图像配置，视频操作时会切换
        self.api_key = api_key or settings.IMAGE_API_KEY
        self.base_url = (base_url or settings.IMAGE_BASE_URL).rstrip("/")
        self.timeout = timeout

        if not self.api_key:
            raise AgnesAPIError("未配置 IMAGE_API_KEY 或 VIDEO_API_KEY，请在 .env 文件中设置")

        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_video_config(self) -> tuple[str, str, dict]:
        """获取视频 API 配置"""
        api_key = settings.VIDEO_API_KEY or settings.IMAGE_API_KEY
        base_url = (settings.VIDEO_BASE_URL or settings.IMAGE_BASE_URL).rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return api_key, base_url, headers

    def _get_image_config(self) -> tuple[str, str, dict]:
        """获取图像 API 配置"""
        api_key = settings.IMAGE_API_KEY
        base_url = settings.IMAGE_BASE_URL.rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return api_key, base_url, headers

    # ========== 视频生成 ==========

    def create_video(
        self,
        prompt: str,
        image: str | list[str] | None = None,
        mode: str | None = None,
        width: int = 1152,
        height: int = 768,
        num_frames: int = 121,
        frame_rate: int = 24,
        negative_prompt: str | None = None,
        seed: int | None = None,
    ) -> dict:
        """
        创建视频生成任务。

        Args:
            prompt: 视频内容文本描述
            image: 图片URL（单个字符串=图生视频，列表=多图/关键帧）
            mode: 生成模式 (ti2vid / keyframes)
            width: 视频宽度，默认 1152
            height: 视频高度，默认 768
            num_frames: 帧数，须 ≤ 441 且满足 8n+1
            frame_rate: 帧率 1-60，默认 24
            negative_prompt: 负向提示词
            seed: 随机种子

        Returns:
            dict: 包含 video_id, task_id, status 等信息
        """
        # 使用视频专用配置
        _, video_base_url, video_headers = self._get_video_config()

        payload = {
            "model": settings.VIDEO_MODEL,
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }

        # 图生视频：单张图片放顶层
        if isinstance(image, str):
            payload["image"] = image
        # 多图/关键帧：放 extra_body
        elif isinstance(image, list) and image:
            extra_body = {"image": image}
            if mode:
                extra_body["mode"] = mode
            payload["extra_body"] = extra_body

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            payload["seed"] = seed

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{video_base_url}/v1/videos",
                headers=video_headers,
                json=payload,
            )

        if resp.status_code != 200:
            raise AgnesAPIError(
                f"创建视频任务失败: {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    def query_video_by_video_id(
        self,
        video_id: str,
        model_name: str | None = None,
    ) -> dict:
        """
        使用 video_id 查询视频生成结果（推荐方式）。

        Args:
            video_id: 视频ID
            model_name: 可选，显式指定模型名

        Returns:
            dict: 包含 status, progress, remixed_from_video_id(完成后为视频URL) 等
        """
        # 使用视频专用配置
        _, video_base_url, video_headers = self._get_video_config()

        params = {"video_id": video_id}
        if model_name:
            params["model_name"] = model_name

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{video_base_url}/agnesapi",
                headers=video_headers,
                params=params,
            )

        if resp.status_code != 200:
            raise AgnesAPIError(
                f"查询视频结果失败: {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    def query_video_by_task_id(self, task_id: str) -> dict:
        """
        使用 task_id 查询视频生成结果（兼容旧方式）。

        Args:
            task_id: 任务ID

        Returns:
            dict: 包含 status, progress 等
        """
        # 使用视频专用配置
        _, video_base_url, video_headers = self._get_video_config()

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{video_base_url}/v1/videos/{task_id}",
                headers=video_headers,
            )

        if resp.status_code != 200:
            raise AgnesAPIError(
                f"查询视频结果失败: {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    def wait_for_video(
        self,
        video_id: str,
        poll_interval: float = 5.0,
        max_wait: float = 600.0,
        on_progress: callable = None,
    ) -> dict:
        """
        轮询等待视频生成完成。

        Args:
            video_id: 视频ID
            poll_interval: 轮询间隔（秒），建议 5s
            max_wait: 最大等待时间（秒）
            on_progress: 进度回调函数 fn(progress: int, status: str)

        Returns:
            dict: 最终的视频结果

        Raises:
            AgnesAPIError: 超时或任务失败
        """
        start_time = time.time()

        while time.time() - start_time < max_wait:
            result = self.query_video_by_video_id(video_id)
            status = result.get("status", "")
            progress = result.get("progress", 0)

            if on_progress:
                on_progress(progress, status)

            if status == "completed":
                return result
            elif status == "failed":
                error_msg = result.get("error", "视频生成失败")
                raise AgnesAPIError(f"视频生成失败: {error_msg}")

            time.sleep(poll_interval)

        raise AgnesAPIError(
            f"视频生成超时（等待超过 {max_wait} 秒）"
        )

    def download_video(self, video_url: str, output_path: str) -> str:
        """
        下载生成的视频文件到本地，带重试机制。

        Args:
            video_url: 视频URL（remixed_from_video_id 字段）
            output_path: 本地保存路径

        Returns:
            str: 保存的文件路径
        """
        max_retries = 3
        last_err = None
        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=300.0) as client:
                    resp = client.get(video_url, follow_redirects=True)
                    resp.raise_for_status()

                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                return output_path
            except Exception as e:
                last_err = e
                time.sleep(5)

        raise AgnesAPIError(f"下载视频失败(重试{max_retries}次): {last_err}")

    # ========== 图片生成 ==========

    def generate_image(
        self,
        prompt: str,
        size: str = "1024x768",
        image_urls: list[str] | None = None,
        return_base64: bool = False,
    ) -> dict:
        """
        生成图片（文生图 / 图生图）。

        Args:
            prompt: 图片描述提示词
            size: 输出尺寸，如 "1024x768"
            image_urls: 图生图输入图片URL列表（放 extra_body）
            return_base64: 是否返回 Base64 格式

        Returns:
            dict: 包含 data[0].url 或 data[0].b64_json
        """
        # 使用图像专用配置
        _, image_base_url, image_headers = self._get_image_config()

        payload = {
            "prompt": prompt,
            "size": size,
        }

        extra_body = {}
        if image_urls:
            # 图生图模式
            img2img_model = settings.IMG2IMG_MODEL or settings.IMAGE_MODEL
            payload["model"] = img2img_model
            payload["tags"] = ["img2img"]
            extra_body["image"] = image_urls
            extra_body["response_format"] = "url"
            logger.info(f"img2img 模式: {img2img_model}，{len(image_urls)} 张参考图")
        else:
            # 文生图模式
            payload["model"] = settings.IMAGE_MODEL
            if return_base64:
                extra_body["response_format"] = "b64_json"
            else:
                extra_body["response_format"] = "url"

        if extra_body:
            payload["extra_body"] = extra_body

        with httpx.Client(timeout=max(self.timeout, 300.0)) as client:
            resp = client.post(
                f"{image_base_url}/v1/images/generations",
                headers=image_headers,
                json=payload,
            )

        if resp.status_code != 200:
            raise AgnesAPIError(
                f"图片生成失败: {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    # ========== 文本生成（用于脚本扩写等） ==========

    def chat_completion(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        文本对话/生成（OpenAI 兼容接口）。

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名，默认 agnes-2.0-flash
            temperature: 采样温度
            max_tokens: 最大生成 token 数

        Returns:
            str: 模型生成的文本内容
        """
        payload = {
            "model": model or settings.AGNES_TEXT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers,
                json=payload,
            )

        if resp.status_code != 200:
            raise AgnesAPIError(
                f"文本生成失败: {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json()
        return data["choices"][0]["message"]["content"]

    # ========== 文件上传 ==========

    @staticmethod
    def get_public_url_for_local_file(file_path: str) -> str | None:
        """
        如果配置了 PUBLIC_BASE_URL，将本地文件路径转换为公网可访问的 URL。
        
        文件必须位于 storage/ 目录下才能被静态文件服务访问。
        支持的路径:
          - storage/references/xxx.png -> {PUBLIC_BASE_URL}/storage/references/xxx.png
          - storage/uploads/xxx.png   -> {PUBLIC_BASE_URL}/storage/uploads/xxx.png
          - storage/outputs/xxx.png   -> {PUBLIC_BASE_URL}/storage/outputs/xxx.png
        
        Returns:
            公网 URL 或 None（未配置 PUBLIC_BASE_URL 或文件不在 storage 目录下）
        """
        if not settings.PUBLIC_BASE_URL:
            return None
        
        from pathlib import Path as _Path
        fp = _Path(file_path).resolve()
        storage_dir = settings.STORAGE_DIR.resolve()
        
        try:
            rel_path = fp.relative_to(storage_dir)
            # 转为 POSIX 路径格式（正斜杠）
            url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/storage/{rel_path.as_posix()}"
            return url
        except ValueError:
            return None

    @staticmethod
    def file_to_data_uri(file_path: str) -> str:
        """
        将本地图片文件转换为 base64 data URI。
        
        这样图片数据直接嵌入 API 请求中，Agnes 服务器不需要从任何外部 URL 下载图片。
        完全不依赖图床、公网IP、内网穿透。
        
        Args:
            file_path: 本地图片文件路径
            
        Returns:
            str: data:image/png;base64,... 格式的 data URI
        """
        import base64
        from pathlib import Path as _Path

        fp = _Path(file_path)
        if not fp.exists():
            raise AgnesAPIError(f"文件不存在: {file_path}")
        
        suffix = fp.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        mime_type = mime_map.get(suffix, "image/png")
        
        image_data = fp.read_bytes()
        b64 = base64.b64encode(image_data).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"

    @staticmethod
    def bytes_to_data_uri(image_data: bytes, filename: str = "image.png") -> str:
        """将内存中的图片数据转换为 base64 data URI。"""
        import base64
        from pathlib import Path as _Path
        
        suffix = _Path(filename).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        mime_type = mime_map.get(suffix, "image/png")
        
        b64 = base64.b64encode(image_data).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"

    @staticmethod
    def upload_image(file_path: str) -> str:
        """
        将本地图片转为 Agnes API 可用的图片引用。

        优先级:
        1. 自托管（PUBLIC_BASE_URL 已配置）→ 直接返回本地静态文件 URL
        2. Base64 Data URI（零配置，推荐）→ 图片直接嵌入请求，不依赖任何外部服务
        3. 外部图床（最终回退）→ catbox.moe / litterbox

        Args:
            file_path: 本地图片文件路径

        Returns:
            str: 图片 URL 或 data URI
        """
        from pathlib import Path as _Path
        import logging
        _logger = logging.getLogger(__name__)

        fp = _Path(file_path)
        if not fp.exists():
            raise AgnesAPIError(f"文件不存在: {file_path}")

        # 检测正确的 MIME type
        suffix = fp.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
        mime_type = mime_map.get(suffix, "image/png")

        # catbox.moe 需要 User-Agent 否则会 412
        _upload_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        # ===== 方式1: 自托管（PUBLIC_BASE_URL） =====
        public_url = AgnesClient.get_public_url_for_local_file(file_path)
        if public_url:
            _logger.info(f"使用自托管 URL: {public_url}")
            return public_url

        # ===== 方式2: Base64 Data URI（零配置，推荐） =====
        try:
            data_uri = AgnesClient.file_to_data_uri(file_path)
            _logger.info(f"使用 base64 data URI (大小: {len(data_uri)//1024}KB)")
            return data_uri
        except Exception as e:
            _logger.warning(f"Base64 转换失败: {e}")

        # ===== 方式3: 外部图床（最终回退） =====
        _logger.warning("Base64 转换失败，尝试外部图床...")

        # 尝试 catbox.moe
        try:
            with httpx.Client(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    resp = client.post(
                        "https://catbox.moe/user/api.php",
                        data={"reqtype": "fileupload"},
                        files={"fileToUpload": (fp.name, f, mime_type)},
                        headers=_upload_headers,
                    )
                if resp.status_code == 200:
                    url = resp.text.strip()
                    if url.startswith("http"):
                        _logger.info(f"catbox.moe 上传成功: {url}")
                        return url
        except Exception as e:
            _logger.debug(f"catbox.moe 上传失败: {e}")

        # 尝试 litterbox.catbox.moe（临时图床，72小时过期）
        try:
            with httpx.Client(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    resp = client.post(
                        "https://litterbox.catbox.moe/resources/internals/api.php",
                        data={"reqtype": "fileupload", "time": "72h"},
                        files={"fileToUpload": (fp.name, f, mime_type)},
                        headers=_upload_headers,
                    )
                if resp.status_code == 200:
                    url = resp.text.strip()
                    if url.startswith("http"):
                        _logger.info(f"litterbox 上传成功: {url}")
                        return url
        except Exception as e:
            _logger.debug(f"litterbox 上传失败: {e}")

        raise AgnesAPIError(f"图片上传失败: {file_path}")

    @staticmethod
    def upload_image_data(image_data: bytes, filename: str = "ref.png") -> str | None:
        """
        将内存中的图片数据转为 Agnes API 可用的引用。
        
        优先上传到图床获取公网 URL（Agnes img2img 需要可下载的 URL），
        回退到 base64 data URI。
        """
        import logging
        from pathlib import Path as _Path
        _logger = logging.getLogger(__name__)

        # 根据文件扩展名检测正确的 MIME type
        suffix = _Path(filename).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        mime_type = mime_map.get(suffix, "image/png")

        # 方式1: 保存到本地 + 自托管（如果有公网地址）
        if settings.PUBLIC_BASE_URL:
            try:
                import uuid as _uuid
                local_name = f"tmp_{_uuid.uuid4().hex[:8]}_{filename}"
                local_path = settings.REFERENCES_DIR / local_name
                local_path.write_bytes(image_data)
                public_url = AgnesClient.get_public_url_for_local_file(str(local_path))
                if public_url:
                    _logger.info(f"图片数据已保存并自托管: {public_url}")
                    return public_url
            except Exception as e:
                _logger.debug(f"本地自托管失败: {e}")

        # catbox.moe 需要 User-Agent 否则会 412
        _ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        # 方式2: catbox.moe（稳定图床）
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    "https://catbox.moe/user/api.php",
                    data={"reqtype": "fileupload"},
                    files={"fileToUpload": (filename, image_data, mime_type)},
                    headers=_ua,
                )
            if resp.status_code == 200:
                url = resp.text.strip()
                if url.startswith("http"):
                    _logger.info(f"catbox.moe 上传成功: {url[:80]}")
                    return url
            else:
                _logger.warning(f"catbox.moe 上传失败 ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            _logger.debug(f"catbox.moe 上传失败: {e}")

        # 方式3: litterbox (临时图床)
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    "https://litterbox.catbox.moe/resources/internals/api.php",
                    data={"reqtype": "fileupload", "time": "72h"},
                    files={"fileToUpload": (filename, image_data, mime_type)},
                    headers=_ua,
                )
            if resp.status_code == 200:
                url = resp.text.strip()
                if url.startswith("http"):
                    _logger.info(f"litterbox 上传成功: {url[:80]}")
                    return url
        except Exception as e:
            _logger.debug(f"litterbox 上传失败: {e}")

        # 最终回退: Base64 Data URI
        try:
            data_uri = AgnesClient.bytes_to_data_uri(image_data, filename)
            _logger.info(f"图床均失败，回退 base64 data URI (大小: {len(data_uri)//1024}KB)")
            return data_uri
        except Exception as e:
            _logger.debug(f"Base64 转换也失败: {e}")

        return None


# 便捷单例
_client: AgnesClient | None = None


def get_agnes_client() -> AgnesClient:
    """获取 AI 模型 API 客户端单例（支持图像和视频生成）"""
    global _client
    if _client is None:
        _client = AgnesClient()
    return _client
