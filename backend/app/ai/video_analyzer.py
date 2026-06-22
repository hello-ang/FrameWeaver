"""视频内容分析模块 - 场景检测、关键帧提取、人脸检测"""

import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings


@dataclass
class SceneBoundary:
    """场景切换点"""
    frame_index: int
    timestamp: float  # 秒
    confidence: float


@dataclass
class KeyFrame:
    """关键帧"""
    frame_index: int
    timestamp: float
    path: str
    score: float  # 画面质量分数


@dataclass
class FaceDetection:
    """人脸检测结果"""
    frame_index: int
    timestamp: float
    bbox: tuple  # (x, y, w, h)
    confidence: float


@dataclass
class VideoAnalysisResult:
    """视频分析结果"""
    success: bool
    duration: float = 0
    total_frames: int = 0
    fps: float = 0
    resolution: tuple = (0, 0)
    scene_boundaries: list[SceneBoundary] = field(default_factory=list)
    key_frames: list[KeyFrame] = field(default_factory=list)
    faces: list[FaceDetection] = field(default_factory=list)
    error: Optional[str] = None


def analyze_video(
    video_path: str,
    extract_keyframes: bool = True,
    detect_faces: bool = False,
    scene_threshold: float = 30.0,
    keyframe_count: int = 10,
    output_dir: Optional[str] = None,
) -> VideoAnalysisResult:
    """
    综合分析视频内容。

    Args:
        video_path: 视频文件路径
        extract_keyframes: 是否提取关键帧
        detect_faces: 是否检测人脸
        scene_threshold: 场景切换阈值
        keyframe_count: 最大关键帧数量
        output_dir: 关键帧输出目录

    Returns:
        VideoAnalysisResult
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return VideoAnalysisResult(success=False, error=f"无法打开视频: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = total_frames / fps if fps > 0 else 0

        result = VideoAnalysisResult(
            success=True,
            duration=duration,
            total_frames=total_frames,
            fps=fps,
            resolution=(width, height),
        )

        if not output_dir:
            output_dir = str(settings.OUTPUT_DIR / f"analysis_{uuid.uuid4().hex}")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 场景检测
        result.scene_boundaries = _detect_scenes(cap, fps, total_frames, scene_threshold)

        # 关键帧提取
        if extract_keyframes:
            result.key_frames = _extract_keyframes(
                cap, fps, total_frames, result.scene_boundaries,
                keyframe_count, output_dir
            )

        # 人脸检测
        if detect_faces:
            result.faces = _detect_faces(cap, fps, total_frames)

        return result

    except Exception as e:
        return VideoAnalysisResult(success=False, error=str(e))
    finally:
        cap.release()


def _detect_scenes(
    cap: cv2.VideoCapture,
    fps: float,
    total_frames: int,
    threshold: float,
) -> list[SceneBoundary]:
    """基于帧差的场景检测"""
    boundaries = []
    prev_gray = None
    sample_interval = max(1, int(fps / 2))  # 每秒采样2帧

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (64, 64))

            if prev_gray is not None:
                diff = cv2.absdiff(prev_gray, gray)
                score = np.mean(diff)

                if score > threshold:
                    timestamp = frame_idx / fps
                    boundaries.append(SceneBoundary(
                        frame_index=frame_idx,
                        timestamp=timestamp,
                        confidence=min(score / threshold, 1.0),
                    ))

            prev_gray = gray

        frame_idx += 1

    return boundaries


def _extract_keyframes(
    cap: cv2.VideoCapture,
    fps: float,
    total_frames: int,
    scene_boundaries: list[SceneBoundary],
    max_count: int,
    output_dir: str,
) -> list[KeyFrame]:
    """提取关键帧（场景切换点 + 均匀采样）"""
    key_frames = []

    # 从场景切换点取帧
    target_indices = [b.frame_index for b in scene_boundaries[:max_count]]

    # 补充均匀采样
    if len(target_indices) < max_count:
        interval = total_frames // max_count
        for i in range(max_count):
            idx = i * interval
            if idx not in target_indices:
                target_indices.append(idx)

    target_indices = sorted(set(target_indices))[:max_count]

    for frame_idx in target_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        timestamp = frame_idx / fps
        path = str(Path(output_dir) / f"keyframe_{frame_idx:06d}.jpg")
        cv2.imwrite(path, frame)

        # 计算画面清晰度分数
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        key_frames.append(KeyFrame(
            frame_index=frame_idx,
            timestamp=timestamp,
            path=path,
            score=float(laplacian_var),
        ))

    return key_frames


def _detect_faces(
    cap: cv2.VideoCapture,
    fps: float,
    total_frames: int,
) -> list[FaceDetection]:
    """人脸检测"""
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    faces = []
    sample_interval = max(1, int(fps))  # 每秒采样1帧
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            detected = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )

            for (x, y, w, h) in detected:
                faces.append(FaceDetection(
                    frame_index=frame_idx,
                    timestamp=frame_idx / fps,
                    bbox=(int(x), int(y), int(w), int(h)),
                    confidence=1.0,
                ))

        frame_idx += 1

        # 限制最大检测帧数以避免过长耗时
        if frame_idx > fps * 60:  # 最多分析60秒
            break

    return faces
