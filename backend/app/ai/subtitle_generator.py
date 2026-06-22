"""自动字幕生成模块 - 基于 Whisper 语音识别"""

import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import whisper

from app.config import settings


@dataclass
class SubtitleSegment:
    """字幕段落"""
    index: int
    start: float  # 开始时间(秒)
    end: float    # 结束时间(秒)
    text: str


@dataclass
class SubtitleResult:
    """字幕生成结果"""
    success: bool
    language: str = ""
    segments: list[SubtitleSegment] = field(default_factory=list)
    srt_path: str = ""
    ass_path: str = ""
    error: Optional[str] = None


def generate_subtitle(
    video_path: str,
    model_name: Optional[str] = None,
    language: Optional[str] = None,
    output_dir: Optional[str] = None,
    task: str = "transcribe",  # transcribe 或 translate
) -> SubtitleResult:
    """
    从视频中提取语音并生成字幕。

    Args:
        video_path: 视频/音频文件路径
        model_name: Whisper 模型名 (tiny/base/small/medium/large)
        language: 语言代码 (zh/en/ja 等)，None 为自动检测
        output_dir: 输出目录
        task: transcribe=转录原文, translate=翻译为英文

    Returns:
        SubtitleResult
    """
    if not model_name:
        model_name = settings.WHISPER_MODEL

    if not output_dir:
        output_dir = str(settings.OUTPUT_DIR / f"subtitle_{uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
        # 加载 Whisper 模型
        model = whisper.load_model(model_name)

        # 转录
        result = model.transcribe(
            video_path,
            language=language,
            task=task,
            verbose=False,
        )

        detected_language = result.get("language", language or "unknown")

        # 解析段落
        segments = []
        for i, seg in enumerate(result.get("segments", [])):
            segments.append(SubtitleSegment(
                index=i + 1,
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            ))

        if not segments:
            return SubtitleResult(success=False, error="未检测到任何语音内容")

        # 生成 SRT 文件
        srt_path = str(Path(output_dir) / "subtitle.srt")
        _write_srt(segments, srt_path)

        # 生成 ASS 文件
        ass_path = str(Path(output_dir) / "subtitle.ass")
        _write_ass(segments, ass_path)

        return SubtitleResult(
            success=True,
            language=detected_language,
            segments=segments,
            srt_path=srt_path,
            ass_path=ass_path,
        )

    except Exception as e:
        return SubtitleResult(success=False, error=f"字幕生成失败: {str(e)}")


def _format_timestamp(seconds: float, srt_format: bool = True) -> str:
    """格式化时间戳"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)

    if srt_format:
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    else:
        centis = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _write_srt(segments: list[SubtitleSegment], output_path: str):
    """写入 SRT 字幕文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"{seg.index}\n")
            f.write(f"{_format_timestamp(seg.start)} --> {_format_timestamp(seg.end)}\n")
            f.write(f"{seg.text}\n\n")


def _write_ass(segments: list[SubtitleSegment], output_path: str):
    """写入 ASS 字幕文件"""
    header = """[Script Info]
Title: Auto Generated Subtitle
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,10,10,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        for seg in segments:
            start = _format_timestamp(seg.start, srt_format=False)
            end = _format_timestamp(seg.end, srt_format=False)
            text = seg.text.replace("\n", "\\N")
            f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")
