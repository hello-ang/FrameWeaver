"""配音合成模块 - 基于 Edge-TTS 文字转语音"""

import uuid
import asyncio
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import edge_tts

from app.config import settings


@dataclass
class VoiceOption:
    """语音选项"""
    name: str
    locale: str
    gender: str
    short_name: str


@dataclass
class VoiceSynthesisResult:
    """配音合成结果"""
    success: bool
    audio_path: str = ""
    duration: float = 0
    voice_name: str = ""
    error: Optional[str] = None


# 常用中文语音
CHINESE_VOICES = [
    VoiceOption("晓晓", "zh-CN", "Female", "zh-CN-XiaoxiaoNeural"),
    VoiceOption("云希", "zh-CN", "Male", "zh-CN-YunxiNeural"),
    VoiceOption("云扬", "zh-CN", "Male", "zh-CN-YunyangNeural"),
    VoiceOption("晓涵", "zh-CN", "Female", "zh-CN-XiaohanNeural"),
    VoiceOption("晓墨", "zh-CN", "Female", "zh-CN-XiaomoNeural"),
]

# 常用英文语音
ENGLISH_VOICES = [
    VoiceOption("Jenny", "en-US", "Female", "en-US-JennyNeural"),
    VoiceOption("Guy", "en-US", "Male", "en-US-GuyNeural"),
    VoiceOption("Aria", "en-US", "Female", "en-US-AriaNeural"),
]


async def list_voices(locale_filter: Optional[str] = None) -> list[VoiceOption]:
    """列出可用的语音"""
    voices = await edge_tts.list_voices()
    result = []

    for v in voices:
        if locale_filter and not v["Locale"].startswith(locale_filter):
            continue
        result.append(VoiceOption(
            name=v["ShortName"],
            locale=v["Locale"],
            gender=v["Gender"],
            short_name=v["ShortName"],
        ))

    return result


async def _synthesize(
    text: str,
    voice: str,
    output_path: str,
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
) -> float:
    """内部合成方法"""
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )
    await communicate.save(output_path)

    # 获取音频时长
    try:
        import ffmpeg
        probe = ffmpeg.probe(output_path)
        duration = float(probe.get("format", {}).get("duration", 0))
    except Exception:
        duration = 0

    return duration


def synthesize_voice(
    text: str,
    voice: Optional[str] = None,
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
    output_dir: Optional[str] = None,
) -> VoiceSynthesisResult:
    """
    文字转语音。

    Args:
        text: 要转换的文字
        voice: 语音名称 (如 zh-CN-XiaoxiaoNeural)
        rate: 语速调整 (如 "+20%", "-10%")
        volume: 音量调整
        pitch: 音调调整
        output_dir: 输出目录

    Returns:
        VoiceSynthesisResult
    """
    if not voice:
        voice = settings.TTS_VOICE

    if not output_dir:
        output_dir = str(settings.OUTPUT_DIR / f"voice_{uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_path = str(Path(output_dir) / "voice.mp3")

    try:
        duration = asyncio.run(
            _synthesize(text, voice, output_path, rate, volume, pitch)
        )

        return VoiceSynthesisResult(
            success=True,
            audio_path=output_path,
            duration=duration,
            voice_name=voice,
        )

    except Exception as e:
        return VoiceSynthesisResult(
            success=False,
            error=f"语音合成失败: {str(e)}"
        )


def synthesize_voice_batch(
    texts: list[str],
    voice: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> list[VoiceSynthesisResult]:
    """批量文字转语音"""
    if not voice:
        voice = settings.TTS_VOICE

    if not output_dir:
        output_dir = str(settings.OUTPUT_DIR / f"voice_batch_{uuid.uuid4().hex}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    results = []
    for i, text in enumerate(texts):
        output_path = str(Path(output_dir) / f"voice_{i:03d}.mp3")

        try:
            duration = asyncio.run(
                _synthesize(text, voice, output_path)
            )
            results.append(VoiceSynthesisResult(
                success=True,
                audio_path=output_path,
                duration=duration,
                voice_name=voice,
            ))
        except Exception as e:
            results.append(VoiceSynthesisResult(
                success=False,
                error=f"第 {i+1} 段合成失败: {str(e)}"
            ))

    return results
