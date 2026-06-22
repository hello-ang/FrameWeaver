"""规划模型 API 客户端 - 负责剧本规划和提示词生成

支持任何 OpenAI 兼容 API，如 DeepSeek、GPT-4、Claude 等。
配置通过 PLANNING_* 环境变量设置。
"""

import logging
import re
import ssl
import time
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class PlanningError(Exception):
    """规划模型 API 调用异常"""
    pass


# 保留旧名称兼容
DeepSeekError = PlanningError


class PlanningClient:
    """规划模型 API 客户端（OpenAI 兼容）"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ):
        self.api_key = api_key or settings.PLANNING_API_KEY
        self.base_url = (base_url or settings.PLANNING_BASE_URL).rstrip("/")
        self.model = model or settings.PLANNING_MODEL
        self.timeout = timeout

        if not self.api_key:
            raise PlanningError("未配置 PLANNING_API_KEY，请在 .env 文件中设置")

    def _build_client(self) -> httpx.Client:
        """构建带 SSL 容错的 httpx 客户端"""
        # 创建宽松的 SSL 上下文，避免 SSL 握手失败
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        return httpx.Client(
            timeout=self.timeout,
            verify=ssl_ctx,
        )

    def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.8,
        max_tokens: int = 8192,
        model: str | None = None,
    ) -> str:
        """
        文本对话/生成，带自动重试。

        Args:
            messages: 消息列表 [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            model: 可选模型覆盖

        Returns:
            str: 模型生成的文本内容
        """
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}/chat/completions"
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                with self._build_client() as client:
                    resp = client.post(url, headers=headers, json=payload)

                if resp.status_code != 200:
                    raise DeepSeekError(
                        f"DeepSeek API 调用失败 [{resp.status_code}]: {resp.text[:500]}"
                    )

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content

            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"DeepSeek 连接失败(尝试 {attempt+1}/{max_retries}): {e}，{wait}s 后重试...")
                    time.sleep(wait)
                else:
                    logger.error(f"DeepSeek 连接失败，已重试 {max_retries} 次: {e}")

            except DeepSeekError:
                raise

            except Exception as e:
                last_error = e
                logger.error(f"DeepSeek 未知错误: {e}")
                break

        raise DeepSeekError(f"DeepSeek API 调用失败（已重试 {max_retries} 次）: {last_error}")

    @staticmethod
    def extract_json(text: str) -> str:
        """
        从模型输出中提取 JSON（可能被 ```json ... ``` 包裹）。

        Args:
            text: 模型原始输出

        Returns:
            str: 纯 JSON 字符串
        """
        text = text.strip()

        # 尝试 ```json ... ```
        pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 尝试找到最外层的 { ... }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return text


# 保留旧名称兼容
DeepSeekClient = PlanningClient


# 全局单例
_client: PlanningClient | None = None


def get_deepseek_client() -> PlanningClient:
    """获取规划模型客户端单例"""
    global _client
    if _client is None:
        _client = PlanningClient()
    return _client


def get_planning_client() -> PlanningClient:
    """获取规划模型客户端单例（新接口）"""
    return get_deepseek_client()
