"""视频处理服务 - 基于 FFmpeg 和 MoviePy"""

import os
import uuid
from pathlib import Path
from typing import Optional

import ffmpeg

from app.config import settings


def trim_video(
    input_path: str,
    start_time: float,
    end_time: float,
    output_path: Optional[str] = None,
) -> str:
    """视频裁剪"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"trim_{uuid.uuid4().hex}.mp4")

    (
        ffmpeg
        .input(input_path, ss=start_time, t=end_time - start_time)
        .output(output_path, c="copy")
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def concat_videos(input_paths: list[str], output_path: Optional[str] = None) -> str:
    """视频拼接"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"concat_{uuid.uuid4().hex}.mp4")

    # 创建临时文件列表
    list_file = str(settings.TEMP_DIR / f"concat_{uuid.uuid4().hex}.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for path in input_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    (
        ffmpeg
        .input(list_file, format="concat", safe=0)
        .output(output_path, c="copy")
        .overwrite_output()
        .run(quiet=True)
    )

    # 清理临时文件
    os.unlink(list_file)
    return output_path


def transcode_video(
    input_path: str,
    output_format: str = "mp4",
    resolution: Optional[str] = None,
    bitrate: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """视频转码"""
    if not output_path:
        name = f"transcode_{uuid.uuid4().hex}.{output_format}"
        output_path = str(settings.OUTPUT_DIR / name)

    stream = ffmpeg.input(input_path)
    kwargs = {}

    if resolution:
        kwargs["s"] = resolution  # e.g. "1920x1080"
    if bitrate:
        kwargs["video_bitrate"] = bitrate

    (
        stream
        .output(output_path, **kwargs)
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def extract_audio(input_path: str, output_path: Optional[str] = None) -> str:
    """从视频中提取音频"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"audio_{uuid.uuid4().hex}.mp3")

    (
        ffmpeg
        .input(input_path)
        .output(output_path, vn=None, acodec="libmp3lame", ab="192k")
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def merge_audio_video(
    video_path: str,
    audio_path: str,
    output_path: Optional[str] = None,
    loop: bool = False,
) -> str:
    """将音频合并到视频"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"merged_{uuid.uuid4().hex}.mp4")

    video_stream = ffmpeg.input(video_path)
    audio_stream = ffmpeg.input(audio_path)

    if loop:
        audio_stream = ffmpeg.input(audio_path, stream_loop=-1)

    (
        ffmpeg
        .output(
            video_stream,
            audio_stream,
            output_path,
            vcodec="copy",
            acodec="aac",
            shortest=None,
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def burn_subtitle(
    video_path: str,
    subtitle_path: str,
    output_path: Optional[str] = None,
    style: Optional[str] = None,
) -> str:
    """将字幕烧录到视频"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"subtitled_{uuid.uuid4().hex}.mp4")

    # 转义路径中的特殊字符
    safe_sub_path = subtitle_path.replace("\\", "/").replace(":", "\\:")

    vf_filter = f"subtitles={safe_sub_path}"
    if style:
        vf_filter += f":force_style='{style}'"

    (
        ffmpeg
        .input(video_path)
        .output(output_path, vf=vf_filter, acodec="copy")
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def generate_thumbnail(
    input_path: str,
    time: float = 0,
    size: str = "320x180",
    output_path: Optional[str] = None,
) -> str:
    """生成视频缩略图"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"thumb_{uuid.uuid4().hex}.jpg")

    (
        ffmpeg
        .input(input_path, ss=time)
        .output(output_path, vframes=1, s=size)
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def get_video_info(input_path: str) -> dict:
    """获取视频详细信息"""
    probe = ffmpeg.probe(input_path)
    video_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "video"), None
    )
    audio_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "audio"), None
    )

    return {
        "duration": float(probe.get("format", {}).get("duration", 0)),
        "size": int(probe.get("format", {}).get("size", 0)),
        "bitrate": int(probe.get("format", {}).get("bit_rate", 0)),
        "video": {
            "codec": video_stream.get("codec_name") if video_stream else None,
            "width": int(video_stream["width"]) if video_stream else None,
            "height": int(video_stream["height"]) if video_stream else None,
            "fps": eval(video_stream.get("r_frame_rate", "0")) if video_stream else 0,
        } if video_stream else None,
        "audio": {
            "codec": audio_stream.get("codec_name") if audio_stream else None,
            "sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else None,
            "channels": audio_stream.get("channels") if audio_stream else None,
        } if audio_stream else None,
    }


def adjust_volume(
    input_path: str,
    volume: float = 1.0,
    output_path: Optional[str] = None,
) -> str:
    """调整音频音量"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"volume_{uuid.uuid4().hex}.mp3")

    (
        ffmpeg
        .input(input_path)
        .output(output_path, filter=f"volume={volume}")
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path
