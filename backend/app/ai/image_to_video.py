"""图生视频模块 - 支持 Agnes AI / FFmpeg 本地处理"""

import uuid
import subprocess
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class ImageToVideoResult:
    """图生视频结果"""
    success: bool
    output_path: str = ""
    video_id: str = ""
    video_url: str = ""
    duration: float = 0
    error: Optional[str] = None


def image_to_video(
    image_path: str | None = None,
    image_url: str | None = None,
    image_paths: list[str] | None = None,
    prompt: str = "",
    duration: float = 5.0,
    fps: int = 24,
    mode: str = "i2v",  # i2v(单图) / multi(多图) / keyframes(关键帧)
    zoom_effect: str = "none",  # FFmpeg 本地模式用
    api_provider: str = "agnes",  # agnes / local
    api_key: Optional[str] = None,
    on_progress: Optional[Callable] = None,
    output_path: Optional[str] = None,
) -> ImageToVideoResult:
    """
    将图片转换为视频。

    支持两种模式:
    - agnes: 调用 Agnes AI Video V2.0 API（高质量 AI 动画化）
    - local: 使用 FFmpeg 本地处理（zoom/pan 效果）

    Args:
        image_path: 单张图片本地路径
        image_url: 单张图片URL（Agnes API 用）
        image_paths: 多张图片路径（多图/关键帧模式）
        prompt: 视频描述提示词
        duration: 视频时长(秒)
        fps: 帧率
        mode: i2v=单图转视频, multi=多图视频, keyframes=关键帧动画
        zoom_effect: FFmpeg 本地效果 (none/zoom_in/zoom_out/pan_left/pan_right)
        api_provider: API 提供商
        api_key: API 密钥
        on_progress: 进度回调 fn(progress, status)
        output_path: 输出路径

    Returns:
        ImageToVideoResult
    """
    if api_provider == "agnes":
        return _agnes_image_to_video(
            image_url=image_url,
            image_paths=image_paths,
            prompt=prompt,
            duration=duration,
            fps=fps,
            mode=mode,
            api_key=api_key,
            on_progress=on_progress,
            output_path=output_path,
        )
    else:
        return _local_image_to_video(
            image_path=image_path,
            duration=duration,
            fps=fps,
            zoom_effect=zoom_effect,
            output_path=output_path,
        )


def _agnes_image_to_video(
    image_url: str | None,
    image_paths: list[str] | None,
    prompt: str,
    duration: float,
    fps: int,
    mode: str,
    api_key: Optional[str],
    on_progress: Optional[Callable],
    output_path: Optional[str],
) -> ImageToVideoResult:
    """使用 Agnes AI Video V2.0 生成图生视频"""
    from app.ai.agnes_client import AgnesClient, AgnesAPIError

    try:
        client = AgnesClient(api_key=api_key) if api_key else AgnesClient()
    except AgnesAPIError as e:
        return ImageToVideoResult(success=False, error=str(e))

    # 计算帧数
    raw_frames = int(duration * fps)
    n = (raw_frames - 1) // 8
    num_frames = min(8 * n + 1, 441)

    # 构建请求参数
    image_param = None
    extra_mode = None

    if mode == "i2v" and image_url:
        # 单图转视频：image 放顶层
        image_param = image_url
    elif mode in ("multi", "keyframes") and image_paths:
        # 多图/关键帧：image 放列表，通过 extra_body 传递
        image_param = image_paths
        if mode == "keyframes":
            extra_mode = "keyframes"
    elif image_url:
        image_param = image_url
    else:
        return ImageToVideoResult(
            success=False,
            error="未提供有效的图片输入（需要 image_url 或 image_paths）"
        )

    if on_progress:
        on_progress(5, "submitting")

    try:
        # 带重试的视频创建，处理 503 服务器繁忙
        import time as _time
        import logging as _logging
        _logger = _logging.getLogger(__name__)
        create_resp = None
        for _attempt in range(3):
            try:
                create_resp = client.create_video(
                    prompt=prompt or "Animate the image with smooth natural motion",
                    image=image_param,
                    mode=extra_mode,
                    num_frames=num_frames,
                    frame_rate=fps,
                )
                break
            except AgnesAPIError as _e:
                _err = str(_e).lower()
                if any(kw in _err for kw in ["503", "繁忙", "busy", "service unavailable", "overloaded"]):
                    _wait = 15 * (_attempt + 1)
                    _logger.warning(f"视频生成 API 503 繁忙(尝试 {_attempt+1}/3)，{_wait}s 后重试: {_e}")
                    _time.sleep(_wait)
                else:
                    raise
        if create_resp is None:
            return ImageToVideoResult(success=False, error="视频生成 API 多次返回 503，请稍后重试")

        video_id = create_resp.get("video_id", "")
        if on_progress:
            on_progress(15, "queued")

        # 轮询等待完成
        def progress_cb(progress: int, status: str):
            if on_progress:
                on_progress(15 + int(progress * 0.75), status)

        result = client.wait_for_video(
            video_id=video_id,
            poll_interval=5.0,
            max_wait=600.0,
            on_progress=progress_cb,
        )

        if on_progress:
            on_progress(95, "downloading")

        # 下载视频
        video_url = result.get("remixed_from_video_id", "")
        if not video_url:
            return ImageToVideoResult(
                success=False,
                video_id=video_id,
                error="未获取到视频下载地址",
            )

        if not output_path:
            output_path = str(settings.OUTPUT_DIR / f"i2v_{uuid.uuid4().hex}.mp4")

        client.download_video(video_url, output_path)

        if on_progress:
            on_progress(100, "completed")

        return ImageToVideoResult(
            success=True,
            output_path=output_path,
            video_id=video_id,
            video_url=video_url,
            duration=duration,
        )

    except AgnesAPIError as e:
        return ImageToVideoResult(success=False, error=str(e))
    except Exception as e:
        return ImageToVideoResult(success=False, error=f"图生视频异常: {str(e)}")


def _local_image_to_video(
    image_path: str | None,
    duration: float,
    fps: int,
    zoom_effect: str,
    output_path: Optional[str],
) -> ImageToVideoResult:
    """使用 FFmpeg 本地将图片转为视频（带动态效果）"""
    if not image_path or not Path(image_path).exists():
        return ImageToVideoResult(success=False, error="图片文件不存在")

    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"i2v_{uuid.uuid4().hex}.mp4")

    total_frames = int(duration * fps)

    zoompan_filters = {
        "none": f"scale=1920:1080,loop=loop={total_frames}:size=1:start=0",
        "zoom_in": f"scale=2560:1440,zoompan=z='min(zoom+0.001,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1920x1080:fps={fps}",
        "zoom_out": f"scale=2560:1440,zoompan=z='if(eq(on,1),1.5,max(zoom-0.001,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1920x1080:fps={fps}",
        "pan_left": f"scale=2560:1440,zoompan=z=1.3:x='if(eq(on,1),0,min(x+2,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1920x1080:fps={fps}",
        "pan_right": f"scale=2560:1440,zoompan=z=1.3:x='if(eq(on,1),iw-iw/zoom,max(x-2,0))':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1920x1080:fps={fps}",
    }

    vf = zoompan_filters.get(zoom_effect, zoompan_filters["none"])

    try:
        if zoom_effect == "none":
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", image_path,
                "-f", "lavfi", "-i", f"anullsrc=d={duration}",
                "-c:v", "libx264", "-t", str(duration),
                "-pix_fmt", "yuv420p", "-vf", "scale=1920:1080",
                "-r", str(fps), "-c:a", "aac", "-shortest",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", image_path,
                "-f", "lavfi", "-i", f"anullsrc=d={duration}",
                "-c:v", "libx264", "-vf", vf,
                "-t", str(duration), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return ImageToVideoResult(
                success=False,
                error=f"FFmpeg 错误: {result.stderr[-500:]}",
            )

        return ImageToVideoResult(
            success=True,
            output_path=output_path,
            duration=duration,
        )
    except Exception as e:
        return ImageToVideoResult(success=False, error=str(e))


def images_to_slideshow(
    image_paths: list[str],
    prompt: str = "",
    duration_per_image: float = 3.0,
    transition: str = "fade",
    fps: int = 24,
    api_provider: str = "agnes",
    api_key: Optional[str] = None,
    on_progress: Optional[Callable] = None,
    output_path: Optional[str] = None,
) -> ImageToVideoResult:
    """
    将多张图片合成为幻灯片视频。

    Args:
        image_paths: 图片路径列表
        prompt: 视频描述（Agnes 模式）
        duration_per_image: 每张图片时长
        transition: 转场效果 (fade/slide/none)
        fps: 帧率
        api_provider: agnes 或 local
        api_key: API 密钥
        on_progress: 进度回调
        output_path: 输出路径

    Returns:
        ImageToVideoResult
    """
    if not image_paths:
        return ImageToVideoResult(success=False, error="没有输入图片")

    if api_provider == "agnes" and len(image_paths) >= 2:
        # 使用 Agnes 多图模式
        return image_to_video(
            image_paths=image_paths,
            prompt=prompt or "Create a smooth slideshow with transitions between the images",
            duration=duration_per_image * len(image_paths),
            fps=fps,
            mode="multi",
            api_provider="agnes",
            api_key=api_key,
            on_progress=on_progress,
            output_path=output_path,
        )

    # 本地 FFmpeg 模式
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"slideshow_{uuid.uuid4().hex}.mp4")

    total_duration = duration_per_image * len(image_paths)

    try:
        if transition == "none" or len(image_paths) == 1:
            list_file = str(settings.TEMP_DIR / f"slideshow_{uuid.uuid4().hex}.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                for p in image_paths:
                    f.write(f"file '{Path(p).resolve()}'\n")
                    f.write(f"duration {duration_per_image}\n")
                f.write(f"file '{Path(image_paths[-1]).resolve()}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", list_file,
                "-f", "lavfi", "-i", f"anullsrc=d={total_duration}",
                "-c:v", "libx264", "-vf", "scale=1920:1080,format=yuv420p",
                "-c:a", "aac", "-shortest",
                output_path,
            ]
        else:
            inputs = []
            for p in image_paths:
                inputs.extend(["-loop", "1", "-t", str(duration_per_image), "-i", p])

            n = len(image_paths)
            filter_parts = []
            for i in range(n):
                filter_parts.append(f"[{i}:v]scale=1920:1080,setsar=1[v{i}]")

            current = "[v0]"
            offset = duration_per_image - 0.5
            for i in range(1, n):
                next_v = f"[v{i}]"
                out = f"[xf{i}]" if i < n - 1 else ""
                filter_parts.append(
                    f"{current}{next_v}xfade=transition={transition}:duration=0.5:offset={offset}{out}"
                )
                current = out
                offset += duration_per_image - 0.5

            filter_complex = ";".join(filter_parts)

            cmd = ["ffmpeg", "-y"] + inputs + [
                "-f", "lavfi", "-i", f"anullsrc=d={total_duration}",
                "-filter_complex", filter_complex,
                "-map", current.strip("[]") if current != "[v0]" else "0:v",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return ImageToVideoResult(
                success=False,
                error=f"FFmpeg 错误: {result.stderr[-500:]}",
            )

        return ImageToVideoResult(
            success=True,
            output_path=output_path,
            duration=total_duration,
        )
    except Exception as e:
        return ImageToVideoResult(success=False, error=str(e))
