"""音频处理服务"""

import uuid
from pathlib import Path
from typing import Optional

import ffmpeg

from app.config import settings


def mix_audio(
    input_paths: list[str],
    weights: Optional[list[float]] = None,
    output_path: Optional[str] = None,
) -> str:
    """混合多段音频"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"mix_{uuid.uuid4().hex}.mp3")

    if not weights:
        weights = [1.0] * len(input_paths)

    inputs = [ffmpeg.input(p) for p in input_paths]

    filter_parts = []
    for i, (inp, weight) in enumerate(zip(inputs, weights)):
        filter_parts.append(f"[{i}]volume={weight}[a{i}]")

    mix_inputs = "".join(f"[a{i}]" for i in range(len(inputs)))
    filter_parts.append(f"{mix_inputs}amix=inputs={len(inputs)}:duration=longest[out]")

    filter_complex = ";".join(filter_parts)

    (
        ffmpeg
        .input("pipe:", format="lavfi", i="anullsrc")  # dummy input
        .output(output_path, filter_complex=filter_complex, map="[out]")
        .overwrite_output()
        .run(quiet=True, input=b"")
    )
    return output_path


def convert_audio_format(
    input_path: str,
    output_format: str = "mp3",
    output_path: Optional[str] = None,
) -> str:
    """音频格式转换"""
    if not output_path:
        name = f"convert_{uuid.uuid4().hex}.{output_format}"
        output_path = str(settings.OUTPUT_DIR / name)

    (
        ffmpeg
        .input(input_path)
        .output(output_path)
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def trim_audio(
    input_path: str,
    start_time: float,
    end_time: float,
    output_path: Optional[str] = None,
) -> str:
    """音频裁剪"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"trim_{uuid.uuid4().hex}.mp3")

    (
        ffmpeg
        .input(input_path, ss=start_time, t=end_time - start_time)
        .output(output_path, acodec="copy")
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def get_audio_duration(input_path: str) -> float:
    """获取音频时长"""
    probe = ffmpeg.probe(input_path)
    return float(probe.get("format", {}).get("duration", 0))


def add_fade(
    input_path: str,
    fade_in: float = 0,
    fade_out: float = 0,
    output_path: Optional[str] = None,
) -> str:
    """添加淡入淡出效果"""
    if not output_path:
        output_path = str(settings.OUTPUT_DIR / f"fade_{uuid.uuid4().hex}.mp3")

    duration = get_audio_duration(input_path)
    filters = []

    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        start = max(0, duration - fade_out)
        filters.append(f"afade=t=out:st={start}:d={fade_out}")

    if not filters:
        return input_path

    filter_str = ",".join(filters)
    (
        ffmpeg
        .input(input_path)
        .output(output_path, af=filter_str)
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path
