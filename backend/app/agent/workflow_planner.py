"""工作流自动编排器 - 将 AgentPlan 转换为可执行的五阶段工作流 DAG

五阶段流程:
  Stage 1: 角色设定图生成 (character_design)
  Stage 2a: 分镜首帧生成 (first_frame, 仅第一个分镜，后续分镜复用上一分镜尾帧)
  Stage 2b: 分镜尾帧生成 (last_frame, 所有分镜)
  Stage 3: 图生视频 (image_to_video, keyframes模式: 首帧+尾帧)
  Stage 4: 拼接 + 配音 + 字幕
"""

import uuid
from typing import Optional

from app.agent.agent_core import AgentPlan


class WorkflowPlanner:
    """
    将 AgentPlan（分镜计划）转换为工作流 nodes + edges 定义。
    生成的工作流可以直接通过现有的 workflow_service 执行。
    """

    def build_workflow_definition(
        self,
        plan: AgentPlan,
        project_id: Optional[str] = None,
    ) -> dict:
        """
        将 AgentPlan 转换为五阶段工作流定义（nodes + edges）。

        自动编排逻辑:
        1. 为每个角色创建角色设定图节点 (image_generation)
        2a. 为每个分镜创建首帧生成节点 (image_generation, 仅依赖场景角色图)
        2b. 为每个分镜创建尾帧生成节点 (image_generation, 仅依赖场景角色图)
        3. 为每个分镜创建图生视频节点 (image_to_video keyframes模式, 依赖首帧+尾帧)
        4. 创建视频拼接节点 + 配音 + 字幕

        Args:
            plan: AgentPlan
            project_id: 所属项目ID

        Returns:
            dict: {"name", "description", "nodes": [...], "edges": [...], "project_id"}
        """
        nodes = []
        edges = []

        # 构建角色名到节点ID的映射（用于动态角色引用）
        character_name_to_node_id = {}
        character_name_to_index = {}

        # 布局参数
        x_start = 100
        y_start = 100
        x_spacing = 350
        y_spacing = 150

        # ============================================================
        # Stage 1: 角色设定图节点（每角色 1 张综合设定图）
        # ============================================================
        character_node_ids = []
        for i, char in enumerate(plan.characters):
            node_id = f"char_{i:03d}"
            character_node_ids.append(node_id)
            character_name_to_node_id[char.name] = node_id
            character_name_to_index[char.name] = i

            # 合并所有视角描述为一张综合设定图 prompt
            combined_prompt = char.image_prompt
            extra_parts = []
            if char.three_view_prompt:
                extra_parts.append(char.three_view_prompt)
            if char.expression_prompt:
                extra_parts.append(char.expression_prompt)
            if char.accessory_prompt:
                extra_parts.append(char.accessory_prompt)
            if extra_parts:
                combined_prompt = (
                    f"SINGLE composite character design sheet with multiple views on one image: "
                    f"{combined_prompt}; "
                    + "; ".join(extra_parts)
                    + ". All views of the SAME character on a single white background sheet."
                )

            nodes.append({
                "id": node_id,
                "type": "image_generation",
                "label": f"角色设定: {char.name}",
                "position": {"x": x_start, "y": y_start + i * y_spacing},
                "params": {
                    "prompt": combined_prompt,
                    "action": "character_design",
                    "character_name": char.name,
                    "character_index": i,
                    "provided_url": char.provided_url,
                },
            })

        # ============================================================
        # Stage 1b: 场景环境设计节点
        # ============================================================
        scene_design_node_ids = []  # 与 scenes 等长
        stage1b_x = x_start + int(x_spacing * 0.5)
        for i, scene in enumerate(plan.scenes):
            env_prompt = scene.environment_prompt or ""
            # 安全追加：确保环境图不包含人物
            no_people = "NO PEOPLE, NO CHARACTERS, empty scene, no figures, no silhouettes"
            if env_prompt and no_people.lower() not in env_prompt.lower():
                env_prompt = env_prompt.rstrip(". ,") + f", {no_people}"
            node_id = f"scene_design_{i:03d}"
            scene_design_node_ids.append(node_id)

            nodes.append({
                "id": node_id,
                "type": "image_generation",
                "label": f"场景设计 {i + 1}: {(scene.environment_prompt_cn or scene.prompt_cn)[:20]}",
                "position": {"x": stage1b_x, "y": y_start + i * y_spacing},
                "params": {
                    "prompt": env_prompt,
                    "action": "scene_design",
                    "scene_index": i,
                    "prompt_cn": scene.environment_prompt_cn or scene.prompt_cn,
                },
            })

            # 角色设计 → 场景设计（角色先完成再生成场景）
            for char_nid in character_node_ids:
                edges.append({
                    "id": f"edge_{char_nid}_{node_id}",
                    "source": char_nid,
                    "target": node_id,
                })

        # Stage 1b -> Stage 2 的 x 偏移
        stage2_x = stage1b_x + x_spacing

        # ============================================================
        # Stage 2a: 分镜首帧节点（链式帧复用：只有 scene 0 需要首帧）
        # ============================================================
        first_frame_node_ids = []  # 与 scenes 等长，但 scene>0 的元素为 None
        for i, scene in enumerate(plan.scenes):
            use_chain = getattr(scene, 'use_chain_frame', True) and i > 0
            if use_chain:
                # 链式复用：不创建首帧节点，使用上一个分镜的尾帧
                first_frame_node_ids.append(None)
                continue

            node_id = f"first_frame_{i:03d}"
            first_frame_node_ids.append(node_id)

            # 首帧 prompt: 使用 first_frame_prompt，回退到 prompt
            frame_prompt = scene.first_frame_prompt or scene.prompt

            nodes.append({
                "id": node_id,
                "type": "image_generation",
                "label": f"首帧 {i + 1}: {scene.prompt_cn[:20]}",
                "position": {"x": stage2_x, "y": y_start + i * y_spacing},
                "params": {
                    "prompt": frame_prompt,
                    "action": "first_frame",
                    "scene_index": i,
                    "width": plan.width,
                    "height": plan.height,
                    "negative_prompt": plan.global_negative_prompt,
                    "style": plan.global_style,
                    "prompt_cn": scene.first_frame_prompt_cn or scene.prompt_cn,
                    "scene_characters": scene.scene_characters,
                },
            })

            # 动态角色引用：连接该场景的角色设定图节点
            for char_name in scene.scene_characters:
                char_nid = character_name_to_node_id.get(char_name)
                if char_nid:
                    edges.append({
                        "id": f"edge_{char_nid}_{node_id}",
                        "source": char_nid,
                        "target": node_id,
                    })

            # 场景设计图依赖：连接场景设计节点
            if i < len(scene_design_node_ids):
                edges.append({
                    "id": f"edge_{scene_design_node_ids[i]}_{node_id}",
                    "source": scene_design_node_ids[i],
                    "target": node_id,
                })

        # Stage 2b: 分镜尾帧节点（与首帧并列，稍微偏移）
        stage2b_x = stage2_x + int(x_spacing * 0.6)
        last_frame_node_ids = []
        for i, scene in enumerate(plan.scenes):
            node_id = f"last_frame_{i:03d}"
            last_frame_node_ids.append(node_id)

            # 尾帧 prompt: 使用 last_frame_prompt
            last_prompt = scene.last_frame_prompt or scene.first_frame_prompt or scene.prompt

            nodes.append({
                "id": node_id,
                "type": "image_generation",
                "label": f"尾帧 {i + 1}: {scene.prompt_cn[:20]}",
                "position": {"x": stage2b_x, "y": y_start + i * y_spacing},
                "params": {
                    "prompt": last_prompt,
                    "action": "last_frame",
                    "scene_index": i,
                    "width": plan.width,
                    "height": plan.height,
                    "negative_prompt": plan.global_negative_prompt,
                    "style": plan.global_style,
                    "prompt_cn": scene.last_frame_prompt_cn or scene.prompt_cn,
                    "scene_characters": scene.scene_characters,
                },
            })

            # 动态角色引用：连接该场景的角色设定图节点
            for char_name in scene.scene_characters:
                char_nid = character_name_to_node_id.get(char_name)
                if char_nid:
                    edges.append({
                        "id": f"edge_{char_nid}_{node_id}",
                        "source": char_nid,
                        "target": node_id,
                    })

            # 场景设计图依赖
            if i < len(scene_design_node_ids):
                edges.append({
                    "id": f"edge_{scene_design_node_ids[i]}_{node_id}",
                    "source": scene_design_node_ids[i],
                    "target": node_id,
                })

        # Stage 2 -> Stage 3 的 x 偏移
        stage3_x = stage2b_x + x_spacing

        # ============================================================
        # Stage 3: 图生视频节点 (keyframes 模式: 首帧+尾帧)
        # 链式帧复用：scene>0 的首帧来自 scene[i-1] 的尾帧节点
        # ============================================================
        scene_node_ids = []
        for i, scene in enumerate(plan.scenes):
            node_id = f"scene_{i:03d}"
            scene_node_ids.append(node_id)

            # 动作 prompt: 加入风格和运镜
            full_prompt = scene.prompt
            style = plan.global_style
            camera = scene.camera_motion or plan.global_camera_motion
            if style and style != "cinematic":
                full_prompt += f", {style} style"
            if camera and camera != "static":
                full_prompt += f", {camera} camera movement"

            nodes.append({
                "id": node_id,
                "type": "image_to_video",
                "label": f"视频 {i + 1}: {scene.prompt_cn[:20]}",
                "position": {"x": stage3_x, "y": y_start + i * y_spacing},
                "params": {
                    "text": full_prompt,
                    "api_provider": "agnes",
                    "scene_index": i,
                    "duration": scene.duration,
                    "width": plan.width,
                    "height": plan.height,
                    "negative_prompt": plan.global_negative_prompt,
                    "style": plan.global_style,
                    "camera_motion": camera,
                    "prompt_cn": scene.prompt_cn,
                    "mode": "keyframes",  # 首帧+尾帧模式
                    "dialogue": getattr(scene, 'dialogue', ''),
                    "dialogue_speaker": getattr(scene, 'dialogue_speaker', ''),
                },
            })

            # 首帧来源：scene 0 用 first_frame 节点，scene>0 用上一分镜的 last_frame 节点
            ff_node_id = first_frame_node_ids[i]  # scene>0 时为 None
            if ff_node_id:
                edges.append({
                    "id": f"edge_{ff_node_id}_{node_id}",
                    "source": ff_node_id,
                    "target": node_id,
                })
            elif i > 0 and last_frame_node_ids[i - 1]:
                # 链式复用：上一分镜的尾帧作为本分镜的首帧
                prev_lf_id = last_frame_node_ids[i - 1]
                edges.append({
                    "id": f"edge_chain_{prev_lf_id}_{node_id}",
                    "source": prev_lf_id,
                    "target": node_id,
                })

            # 尾帧 -> 当前视频
            edges.append({
                "id": f"edge_{last_frame_node_ids[i]}_{node_id}",
                "source": last_frame_node_ids[i],
                "target": node_id,
            })

        # ============================================================
        # Stage 4: 拼接 + 后期
        # ============================================================
        stage4_x = stage3_x + x_spacing

        # 4.1 视频拼接节点
        concat_node_id = None
        if len(scene_node_ids) > 1:
            concat_node_id = f"concat_{uuid.uuid4().hex[:6]}"
            concat_y = y_start + (len(scene_node_ids) * y_spacing) // 2
            nodes.append({
                "id": concat_node_id,
                "type": "video_processing",
                "label": "视频拼接",
                "position": {"x": stage4_x, "y": concat_y},
                "params": {
                    "action": "concat",
                    "scene_count": len(scene_node_ids),
                },
            })

            for sid in scene_node_ids:
                edges.append({
                    "id": f"edge_{sid}_{concat_node_id}",
                    "source": sid,
                    "target": concat_node_id,
                })

        upstream_id = concat_node_id if concat_node_id else scene_node_ids[0]
        next_x = stage4_x + x_spacing

        # 4.2 配音合成（可选）
        # 如果全局 voiceover_text 为空但有分镜台词，自动从分镜台词汇总
        voiceover_text = plan.voiceover_text
        if not voiceover_text:
            scene_dialogues = [s.dialogue for s in plan.scenes if getattr(s, 'dialogue', '')]
            if scene_dialogues:
                voiceover_text = '\n'.join(scene_dialogues)

        voice_node_id = None
        if plan.enable_voiceover and voiceover_text:
            voice_node_id = f"voice_{uuid.uuid4().hex[:6]}"
            nodes.append({
                "id": voice_node_id,
                "type": "voice_synthesis",
                "label": "配音合成",
                "position": {"x": next_x, "y": y_start + 50},
                "params": {
                    "text": voiceover_text,
                    "voice": plan.voiceover_voice,
                    "rate": "+0%",
                    "volume": "+0%",
                    "pitch": "+0Hz",
                },
            })

            edges.append({
                "id": f"edge_{upstream_id}_{voice_node_id}",
                "source": upstream_id,
                "target": voice_node_id,
            })
            next_x += x_spacing

        # 4.3 字幕生成（可选）
        subtitle_node_id = None
        if plan.enable_subtitle:
            subtitle_node_id = f"subtitle_{uuid.uuid4().hex[:6]}"
            nodes.append({
                "id": subtitle_node_id,
                "type": "subtitle_generation",
                "label": "自动字幕",
                "position": {"x": next_x, "y": y_start + 100},
                "params": {
                    "language": "zh",
                    "whisper_task": "transcribe",
                },
            })

            prev_id = voice_node_id if voice_node_id else upstream_id
            edges.append({
                "id": f"edge_{prev_id}_{subtitle_node_id}",
                "source": prev_id,
                "target": subtitle_node_id,
            })

        return {
            "name": plan.title or plan.user_request[:50],
            "description": f"AI 智能体自动生成 - {plan.user_request[:100]}",
            "project_id": project_id,
            "nodes": nodes,
            "edges": edges,
        }

    @staticmethod
    def _get_scene_character_node_ids(
        scene_characters: list[str],
        name_to_node_id: dict[str, str],
        all_char_node_ids: list[str],
    ) -> list[str]:
        """
        根据场景角色名列表，返回对应的角色节点ID。
        如果 scene_characters 为空，则返回所有角色节点（兼容旧数据）。
        """
        if not scene_characters:
            # 没有指定场景角色时，默认使用所有角色（向后兼容）
            return all_char_node_ids

        result = []
        for char_name in scene_characters:
            node_id = name_to_node_id.get(char_name)
            if node_id:
                result.append(node_id)

        # 如果找不到任何匹配的角色，回退到所有角色
        return result if result else all_char_node_ids
