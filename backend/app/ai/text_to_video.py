"""文生视频模块 - 支持 Agnes AI / Mock 等多种提供商"""

import re
import uuid
import subprocess
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class Scene:
    """分镜场景"""
    index: int
    description: str
    duration: float = 5.0  # 默认5秒
    style: str = "cinematic"
    camera_motion: str = "static"
    output_path: str = ""
    video_id: str = ""


@dataclass
class TextToVideoResult:
    """文生视频结果"""
    success: bool
    scenes: list[Scene] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    video_ids: list[str] = field(default_factory=list)
    error: Optional[str] = None


def parse_script_to_scenes(script: str, default_duration: float = 5.0) -> list[Scene]:
    """
    将文字脚本解析为分镜场景列表。

    支持的脚本格式:
    - 每行一个场景描述
    - 使用 --- 分隔场景
    - 支持 [duration=Xs] 标注时长
    - 支持 [style=xxx] 标注风格
    - 支持 [camera=xxx] 标注镜头运动
    """
    scenes = []
    parts = script.split("---") if "---" in script else script.strip().split("\n")

    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue

        duration = default_duration
        style = "cinematic"
        camera_motion = "static"

        duration_match = re.search(r"\[duration=([\d.]+)s?\]", part)
        if duration_match:
            duration = float(duration_match.group(1))
            part = re.sub(r"\[duration=[\d.]+s?\]", "", part)

        style_match = re.search(r"\[style=(\w+)\]", part)
        if style_match:
            style = style_match.group(1)
            part = re.sub(r"\[style=\w+\]", "", part)

        motion_match = re.search(r"\[camera=(\w+)\]", part)
        if motion_match:
            camera_motion = motion_match.group(1)
            part = re.sub(r"\[camera=\w+\]", "", part)

        scenes.append(Scene(
            index=i,
            description=part.strip(),
            duration=duration,
            style=style,
            camera_motion=camera_motion,
        ))

    return scenes


def _duration_to_frames(duration: float, fps: int = 24) -> int:
    """将时长(秒)转换为合法的帧数（满足 8n+1 且 ≤ 441）"""
    raw_frames = int(duration * fps)
    # 调整为满足 8n+1 的最接近值
    n = (raw_frames - 1) // 8
    frames = 8 * n + 1
    # 上限 441
    return min(frames, 441)


def generate_video_from_text(
    text: str,
    output_dir: Optional[str] = None,
    api_provider: str = "agnes",
    api_key: Optional[str] = None,
    on_progress: Optional[Callable] = None,
) -> TextToVideoResult:
    """
    根据文字描述生成视频片段。

    Args:
        text: 文字脚本或场景描述
        output_dir: 输出目录
        api_provider: API 提供商 (agnes/mock)
        api_key: API 密钥
        on_progress: 进度回调 fn(scene_index, progress, status)

    Returns:
        TextToVideoResult
    """
    if not output_dir:
        output_dir = str(settings.OUTPUT_DIR / f"t2v_{uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    scenes = parse_script_to_scenes(text)

    if api_provider == "agnes":
        return _agnes_generate(scenes, output_dir, api_key, on_progress)
    elif api_provider == "mock":
        return _mock_generate(scenes, output_dir)
    else:
        return TextToVideoResult(success=False, error=f"不支持的API提供商: {api_provider}")


def _agnes_generate(
    scenes: list[Scene],
    output_dir: str,
    api_key: Optional[str],
    on_progress: Optional[Callable],
) -> TextToVideoResult:
    """使用 Agnes AI Video V2.0 API 生成视频"""
    from app.ai.agnes_client import AgnesClient, AgnesAPIError

    try:
        client = AgnesClient(api_key=api_key) if api_key else AgnesClient()
    except AgnesAPIError as e:
        return TextToVideoResult(success=False, error=str(e))

    output_paths = []
    video_ids = []

    for scene in scenes:
        # 构建增强的 prompt（加入风格和镜头描述）
        prompt = scene.description
        if scene.style and scene.style != "cinematic":
            prompt += f", {scene.style} style"
        if scene.camera_motion and scene.camera_motion != "static":
            prompt += f", {scene.camera_motion} camera movement"

        num_frames = _duration_to_frames(scene.duration)

        try:
            # 1. 创建视频生成任务（带 503 重试）
            import time as _time
            create_resp = None
            for _attempt in range(3):
                try:
                    create_resp = client.create_video(
                        prompt=prompt,
                        num_frames=num_frames,
                        frame_rate=24,
                    )
                    break
                except Exception as _e:
                    _err = str(_e).lower()
                    if any(kw in _err for kw in ["503", "繁忙", "busy", "service unavailable"]):
                        _time.sleep(15 * (_attempt + 1))
                    else:
                        raise
            if not create_resp:
                raise Exception("视频 API 多次返回 503，请稍后重试")

            video_id = create_resp.get("video_id", "")
            task_id = create_resp.get("task_id", "")
            scene.video_id = video_id
            video_ids.append(video_id)

            if on_progress:
                on_progress(scene.index, 10, "submitted")

            # 2. 轮询等待生成完成（使用 video_id 查询，避免排队问题）
            def progress_cb(progress: int, status: str):
                if on_progress:
                    on_progress(scene.index, 10 + int(progress * 0.8), status)

            result = client.wait_for_video(
                video_id=video_id,
                poll_interval=5.0,
                max_wait=600.0,
                on_progress=progress_cb,
            )

            if on_progress:
                on_progress(scene.index, 95, "downloading")

            # 3. 下载生成的视频
            video_url = result.get("remixed_from_video_id", "")
            if not video_url:
                return TextToVideoResult(
                    success=False,
                    error=f"场景 {scene.index}: 未获取到视频下载地址"
                )

            output_path = str(Path(output_dir) / f"scene_{scene.index:03d}.mp4")
            client.download_video(video_url, output_path)
            scene.output_path = output_path
            output_paths.append(output_path)

            if on_progress:
                on_progress(scene.index, 100, "completed")

        except AgnesAPIError as e:
            return TextToVideoResult(
                success=False,
                scenes=scenes,
                output_paths=output_paths,
                video_ids=video_ids,
                error=f"场景 {scene.index} 生成失败: {str(e)}",
            )
        except Exception as e:
            return TextToVideoResult(
                success=False,
                scenes=scenes,
                output_paths=output_paths,
                video_ids=video_ids,
                error=f"场景 {scene.index} 处理异常: {str(e)}",
            )

    return TextToVideoResult(
        success=True,
        scenes=scenes,
        output_paths=output_paths,
        video_ids=video_ids,
    )


def _mock_generate(scenes: list[Scene], output_dir: str) -> TextToVideoResult:
    """模拟视频生成（开发测试用）"""
    output_paths = []
    for scene in scenes:
        output_path = str(Path(output_dir) / f"scene_{scene.index:03d}.mp4")
        try:
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                f"color=c=black:s=1280x720:d={scene.duration},drawtext=text='{scene.description[:30]}':fontsize=24:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
                "-f", "lavfi", "-i", f"anullsrc=d={scene.duration}",
                "-c:v", "libx264", "-c:a", "aac",
                "-t", str(scene.duration),
                "-pix_fmt", "yuv420p",
                output_path,
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            scene.output_path = output_path
            output_paths.append(output_path)
        except Exception as e:
            return TextToVideoResult(success=False, error=f"生成场景 {scene.index} 失败: {str(e)}")

    return TextToVideoResult(success=True, scenes=scenes, output_paths=output_paths)
