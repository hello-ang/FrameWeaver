"""分镜规划器 - 将用户需求拆解为可视化分镜脚本"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StoryboardScene:
    """分镜场景"""
    index: int
    prompt: str  # 英文 prompt
    prompt_cn: str  # 中文描述
    duration: float
    style: str = "cinematic"
    camera_motion: str = "static"
    negative_prompt: str = ""
    width: int = 1152
    height: int = 768

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "prompt": self.prompt,
            "prompt_cn": self.prompt_cn,
            "duration": self.duration,
            "style": self.style,
            "camera_motion": self.camera_motion,
            "negative_prompt": self.negative_prompt,
            "width": self.width,
            "height": self.height,
        }


class StoryboardPlanner:
    """
    分镜规划器：将 AgentPlan 中的场景列表转换为 StoryboardScene 列表，
    供前端可视化展示和用户微调。
    """

    def plan_scenes(self, agent_plan) -> list[StoryboardScene]:
        """
        从 AgentPlan 生成分镜列表。

        Args:
            agent_plan: AgentPlan 实例

        Returns:
            list[StoryboardScene]
        """
        scenes = []
        for sp in agent_plan.scenes:
            scenes.append(StoryboardScene(
                index=sp.index,
                prompt=sp.prompt,
                prompt_cn=sp.prompt_cn,
                duration=sp.duration,
                style=sp.style,
                camera_motion=sp.camera_motion,
                negative_prompt=sp.negative_prompt,
                width=sp.width,
                height=sp.height,
            ))
        return scenes

    def estimate_total_duration(self, scenes: list[StoryboardScene]) -> float:
        """计算总时长"""
        return sum(s.duration for s in scenes)

    def validate_scenes(self, scenes: list[StoryboardScene]) -> list[str]:
        """
        验证分镜是否符合 Agnes 模型约束。

        Returns:
            错误信息列表，空列表表示全部合法
        """
        errors = []
        for s in scenes:
            # 帧数验证：duration * 24 帧，须满足 8n+1 且 <= 441
            raw_frames = int(s.duration * 24)
            n = (raw_frames - 1) // 8
            frames = 8 * n + 1
            if frames > 441:
                errors.append(
                    f"分镜 {s.index}: 时长 {s.duration}s 超出模型上限（最长约 18 秒）"
                )
            if s.duration < 1:
                errors.append(f"分镜 {s.index}: 时长不能小于 1 秒")

        return errors
