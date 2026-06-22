"""AI 智能体核心引擎 - 使用 DeepSeek 思考模型规划视频创作工作流"""

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

from app.ai.deepseek_client import get_deepseek_client, DeepSeekClient, DeepSeekError

logger = logging.getLogger(__name__)

# =========================================================
# 数据结构
# =========================================================

@dataclass
class CharacterDesign:
    """角色设定"""
    name: str  # 角色名称
    description: str  # 中文角色描述
    image_prompt: str  # 英文主肖像 prompt
    three_view_prompt: str = ""  # 英文三视图 prompt (front/side/back)
    expression_prompt: str = ""  # 英文表情图 prompt (multiple expressions)
    accessory_prompt: str = ""  # 英文饰品/装备拆解 prompt
    image_url: str = ""  # 生成后的图片URL
    provided_url: str = ""  # 用户上传的参考图URL（非空时跳过生成）


@dataclass
class ScenePlan:
    """单个分镜计划"""
    index: int
    prompt: str  # 英文动作/运动描述（用于图生视频阶段）
    prompt_cn: str  # 中文原始描述
    duration: float  # 秒
    first_frame_prompt: str = ""  # 首帧英文 prompt（静态画面描述）
    first_frame_prompt_cn: str = ""  # 首帧中文画面描述
    last_frame_prompt: str = ""  # 尾帧英文 prompt（动作结束定格画面）
    last_frame_prompt_cn: str = ""  # 尾帧中文画面描述
    camera_motion: str = "static"  # 运镜（AI 自由决定）
    scene_characters: list[str] = field(default_factory=list)  # 本场景出现的角色名列表
    time_breakdown: str = ""  # 秒级时间线描述
    dialogue: str = ""  # 本场景台词/旁白文本（中文）
    dialogue_speaker: str = ""  # 台词说话人描述（如 "角色A" 或 "旁白"）
    use_chain_frame: bool = True  # 是否使用链式帧复用（scene>0 时首帧=上一个分镜的尾帧）
    environment_prompt: str = ""  # 英文环境设计 prompt（场景环境参考图）
    environment_prompt_cn: str = ""  # 中文环境设计描述


@dataclass
class AgentPlan:
    """智能体工作流计划"""
    plan_id: str = ""
    user_request: str = ""
    title: str = ""
    total_duration: float = 0
    characters: list[CharacterDesign] = field(default_factory=list)
    scenes: list[ScenePlan] = field(default_factory=list)
    # 全局锁定参数（所有分镜统一）
    global_style: str = "cinematic"  # 画面风格
    global_negative_prompt: str = "blur, distortion, low quality, deformed, mutated hands, fused fingers, bad anatomy, missing limbs, extra people, extra characters, additional figures, text, watermark, signature, cross-eyed, asynchronous lips, inconsistent appearance, character swap, identity drift, morphing features"
    global_camera_motion: str = "static"  # 默认运镜（分镜可覆盖）
    width: int = 1152
    height: int = 768
    # 配音/字幕
    enable_voiceover: bool = True
    enable_subtitle: bool = True
    voiceover_text: str = ""  # 全局配音文本
    voiceover_voice: str = "zh-CN-YunxiNeural"
    status: str = "draft"  # draft / confirmed / running / completed / failed
    workflow_id: Optional[str] = None
    project_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AgentPlan":
        characters = [CharacterDesign(
            name=c.get("name", ""),
            description=c.get("description", ""),
            image_prompt=c.get("image_prompt", ""),
            three_view_prompt=c.get("three_view_prompt", ""),
            expression_prompt=c.get("expression_prompt", ""),
            accessory_prompt=c.get("accessory_prompt", ""),
            image_url=c.get("image_url", ""),
            provided_url=c.get("provided_url", ""),
        ) for c in data.get("characters", [])]
        scenes = [ScenePlan(
            index=s.get("index", 0),
            prompt=s.get("prompt", ""),
            prompt_cn=s.get("prompt_cn", ""),
            duration=float(s.get("duration", 10)),
            first_frame_prompt=s.get("first_frame_prompt", ""),
            first_frame_prompt_cn=s.get("first_frame_prompt_cn", ""),
            last_frame_prompt=s.get("last_frame_prompt", ""),
            last_frame_prompt_cn=s.get("last_frame_prompt_cn", ""),
            camera_motion=s.get("camera_motion", "static"),
            scene_characters=s.get("scene_characters", []),
            time_breakdown=s.get("time_breakdown", ""),
            dialogue=s.get("dialogue", ""),
            dialogue_speaker=s.get("dialogue_speaker", ""),
            use_chain_frame=s.get("use_chain_frame", True),
            environment_prompt=s.get("environment_prompt", ""),
            environment_prompt_cn=s.get("environment_prompt_cn", ""),
        ) for s in data.get("scenes", [])]
        return cls(
            plan_id=data.get("plan_id", str(uuid.uuid4())),
            user_request=data.get("user_request", ""),
            title=data.get("title", ""),
            total_duration=data.get("total_duration", 0),
            characters=characters,
            scenes=scenes,
            global_style=data.get("global_style", "cinematic"),
            global_negative_prompt=data.get("global_negative_prompt", "blur, distortion, low quality, deformed"),
            global_camera_motion=data.get("global_camera_motion", "static"),
            width=data.get("width", 1152),
            height=data.get("height", 768),
            enable_voiceover=data.get("enable_voiceover", True),
            enable_subtitle=data.get("enable_subtitle", True),
            voiceover_text=data.get("voiceover_text", ""),
            voiceover_voice=data.get("voiceover_voice", "zh-CN-YunxiNeural"),
            status=data.get("status", "draft"),
            workflow_id=data.get("workflow_id"),
            project_id=data.get("project_id"),
            error=data.get("error"),
        )


# =========================================================
# 系统提示词 - 面向 DeepSeek 强推理模型
# =========================================================

AGENT_SYSTEM_PROMPT = """你是一个专业的AI视频短剧导演和编剧。用户会用自然语言描述想要的视频，你需要像真正的爽剧导演一样，深入思考每一个细节，输出一份极其精确、专业且符合短剧快节奏逻辑的制作计划。

## 你的核心职责（短剧导演向）
1. **深度理解用户意图**：分析主题、爽点、情感基调、时长、分辨率等。
2. **角色设计**：为每个角色生成极其详细的外貌设定，确保跨分镜视觉一致性。
3. **分镜规划（极速节奏）**：
   - **每个分镜的 duration 必须使用以下有效档位**（基于 Agnes Video V2.0 API 的 num_frames 约束）：
     - **5 秒**（推荐，121 帧）
     - **10 秒**（241 帧）
     - **15 秒**（361 帧）
   - **禁止使用任意秒数**（如 3s、4s、6s、7s、8s 等）！
   - **镜头数量由总时长决定，不是固定的！** 你必须根据用户指定的 total_duration 计算：
     - 15秒视频 → 3 个镜头（5s×3）
     - 30秒视频 → 6 个镜头（5s×6）或 3 个镜头（10s×3）
     - 60秒视频 → 12 个镜头（5s×12）或 6 个镜头（10s×6）
   - **所有分镜的 duration 总和必须严格等于 total_duration**！
   - 短剧快节奏建议用 5 秒/镜头；抒情/氛围场景可用 10 秒或 15 秒。
4. **防崩坏设计**：利用特定的镜头语言（过肩、特写、背影）和动作空间隔离，掩饰 AI 视频模型对口型和近身肉搏的物理缺陷。
5. **链式帧设计**：第一个分镜需要首帧+尾帧，后续分镜只需尾帧（首帧复用上一镜尾帧）。
6. **分镜台词创作**：为每个分镜创作独立的台词或旁白，用于后期配音。

## AI 短剧专属导演规范（极其重要！）

### 1. 规避对口型 (Lip-Sync) 缺陷
AI 视频模型目前无法精准对口型，如果正脸特写且有大段台词，会极其出戏。
- 当 `dialogue` 有大段台词时，画面**必须避免**说话者的正脸近景说话状态。
- **替代镜头**：强制使用 `Over-the-shoulder shot` (过肩镜头，拍听者或只露说者背影)、`Reaction shot` (反应镜头，拍倾听者的表情)、或者是说话者的 `Hand close-up` (手部/武器特写)。

### 2. 短剧爽感镜头语言
- **情绪爆发/高光时刻**：强制使用 `Extreme close-up` (极近特写：如愤怒紧咬的牙关、锐利的眼神、握紧的拳头)。
- **两人对话/对峙**：强制使用 `Over-the-shoulder shot` 或 `Low-angle tracking shot`，增加压迫感。
- **动作打斗**：使用 `Dynamic whip pan` (快速摇摄) 或 `Fast tracking shot`。

### 3. 动作空间隔离（防角色串色与融合）
- AI 极容易在近身纠缠时把两人的特征融合。
- **严禁**设计“扭打在一起”、“紧紧拥抱”、“近距离锁喉”等过度纠缠的动作。
- **必须空间隔离**：描述动作时要有明确的左右/远近关系，例如：“LEFT: 角色A挥出剑气; RIGHT: 角色B在5米外被震退倒地”。

## Agnes 视频模型技术约束
- **视频时长必须使用固定档位**（num_frames 须满足 8n+1 且 <= 441，24fps）：
  - **5 秒** = 121 帧（推荐）
  - **10 秒** = 241 帧
  - **15 秒** = 361 帧
  - 最长 18 秒 = 441 帧（不推荐，质量下降）
- 支持分辨率: 1152x768(横屏), 768x1152(竖屏), 1024x1024(方形), 1920x1080(1080p)。
- 避免: "blur", "shake", "fast motion"。

## 输出 JSON 格式（严格遵守！）

你必须返回严格的 JSON，不要输出任何其他内容。

```json
{
  "title": "短剧标题",
  "total_duration": 15,
  "global_style": "cinematic",
  "global_negative_prompt": "blur, distortion, low quality, deformed, mutated hands, fused fingers, bad anatomy, missing limbs, extra people, text, watermark, signature, cross-eyed, asynchronous lips, character swap",
  "global_camera_motion": "static",
  "width": 768,
  "height": 1152,
  "characters": [
    {
      "name": "角色名称",
      "description": "中文：极其详细的角色外貌、服装、气质描述",
      "image_prompt": "English: close-up half-body portrait shot, [详细外貌], professional concept art",
      "three_view_prompt": "English: character turnaround reference sheet, front side back views...",
      "expression_prompt": "English: expression reference sheet, grid of 6 expressions...",
      "accessory_prompt": "English: equipment and accessories breakdown sheet..."
    }
  ],
  "scenes": [
    {
      "index": 0,
      "scene_characters": ["角色A", "角色B"],
      "time_breakdown": "0-2s: 远景建立; 2-4s: 角色A入画",
      "first_frame_prompt": "English: EXACTLY 2 characters... [极详尽画面描述，声明左右位置]",
      "first_frame_prompt_cn": "中文：[静态画面中文描述]",
      "last_frame_prompt": "English: EXACTLY 2 characters... [尾帧画面描述]",
      "last_frame_prompt_cn": "中文：[尾帧中文描述]",
      "prompt": "English: [动作描述，注意空间隔离]，smooth cinematic motion",
      "prompt_cn": "中文：[分镜动作描述]",
      "duration": 4,
      "camera_motion": "Over-the-shoulder shot, slow dolly in",
      "environment_prompt": "English: detailed environment concept art, wide establishing shot, [architecture/terrain/weather/lighting], NO PEOPLE, NO CHARACTERS, empty scene, cinematic atmosphere, concept art style",
      "environment_prompt_cn": "中文：环境描述",
      "dialogue": "角色A：你以为你能逃脱吗？",
      "dialogue_speaker": "角色A",
      "use_chain_frame": true
    }
  ],
  "enable_voiceover": true,
  "voiceover_text": "汇总的短剧台词...",
  "voiceover_voice": "zh-CN-YunxiNeural",
  "enable_subtitle": true
}
```

## 首尾帧 prompt 原则（决定图片质量的核心！）
1. **英文提示词字段**：全英文。150-300 词。包含数量、外貌绑定、站位、环境、光影、风格词。
2. **中文提示词字段**：全中文。极度详尽的画面翻译，用于前端给用户展示脑补。
3. **角色数量与身份**：开头必写 `EXACTLY N characters in the scene.` 并指出身份。
4. **特征绑定防混淆**：必须将角色的名字和它的具体特征（衣服颜色、发型）死死绑定，并在动作中指名道姓！绝不含糊！

## 链式帧复用（无缝转场）
- 第 1 个分镜（index=0）：需首帧 + 尾帧。
- 第 2 个及之后（index>0）：只需尾帧！首帧自动复用上一镜尾帧。`first_frame_prompt` 留空。

## 动态角色引用
- `scene_characters` 必须只包含该场景真正出现的角色名。多余的角色不要写，防混入画面。

## 场景环境设计图规则（environment_prompt）
- 环境设计图是纯场景环境参考图，**严禁出现任何人物、角色、人物剪影或人物影子**！
- prompt 末尾必须加 `NO PEOPLE, NO CHARACTERS, empty scene, no figures, no silhouettes`
- 只描述建筑、地形、天气、光影、氛围、道具等环境元素
- 这张图是给后续分镜做背景一致性参考用的，人物会在分镜画面中单独添加

## 角色设定图规则（image_prompt 为主，其他三个视角为辅助）
- `image_prompt` 是主设定图 prompt，必须是最详细、最完整的角色外貌描述
- `three_view_prompt`、`expression_prompt`、`accessory_prompt` 会在代码中被合并到 `image_prompt` 后面，作为一张综合设定图生成
- 因此每个 prompt 不要重复描述相同的特征，各自侧重不同角度即可
"""


# =========================================================
# 智能体核心
# =========================================================

class AgentCore:
    """AI 智能体核心 - 使用 DeepSeek 思考模型分析用户需求并生成工作流计划"""

    def __init__(self):
        self._plans: dict[str, AgentPlan] = {}  # 内存缓存

    def plan_from_user_request(self, user_message: str, references: list[dict] | None = None) -> AgentPlan:
        """
        使用 DeepSeek 分析用户输入，生成工作流计划。
        references: 用户上传的参考图列表 [{name, ref_type, url}]
        """
        try:
            client = get_deepseek_client()
        except DeepSeekError as e:
            return AgentPlan(
                plan_id=str(uuid.uuid4()),
                user_request=user_message,
                status="failed",
                error=f"无法连接 DeepSeek 服务: {e}",
            )

        # 构建系统提示词
        system_prompt = AGENT_SYSTEM_PROMPT
        if references:
            ref_info_lines = []
            for ref in references:
                ref_name = ref.get("name", "")
                ref_type = ref.get("ref_type", "")
                ref_url = ref.get("url", "")
                type_cn = {"character": "角色", "scene": "场景", "keyframe": "关键帧"}.get(ref_type, ref_type)
                ref_info_lines.append(f"- [{type_cn}] \"{ref_name}\" (URL: {ref_url})")
            ref_section = (
                "\n\n## 用户提供的参考图（极其重要！）\n"
                "以下角色/场景/关键帧已有参考图：\n"
                + "\n".join(ref_info_lines)
                + "\n\n对于 characters 中已有参考图的角色：\n"
                "- 仍然必须生成详细的 image_prompt！用英文详细描述该参考图中角色的外貌、服装、颜色、武器、体型、发型等所有视觉特征。这个描述会在后续生成帧时与参考图一起使用，确保角色一致性。\n"
                "- 添加 \"provided_url\" 字段，填入上方给出的对应 URL\n"
                "- 其他角色正常生成 image_prompt\n"
                "- 在分镜的 scene_characters 中照常列出该角色名\n"
                "\n对于场景/关键帧参考图，将其 URL 记在脑中，"
                "在对应的 first_frame_prompt / last_frame_prompt 中参考该图描述。\n"
            )
            system_prompt = system_prompt + ref_section

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            response_text = client.chat_completion(
                messages=messages,
                temperature=0.8,
                max_tokens=8192,
            )
        except DeepSeekError as e:
            return AgentPlan(
                plan_id=str(uuid.uuid4()),
                user_request=user_message,
                status="failed",
                error=f"DeepSeek 分析失败: {e}",
            )

        plan = self._parse_ai_response(response_text, user_message)

        # 自动匹配参考图：如果 DeepSeek 没有给角色设置 provided_url，根据角色名自动匹配
        if references and plan.status != "failed":
            char_refs = [r for r in references if r.get("ref_type") == "character"]
            if char_refs:
                for char in plan.characters:
                    if char.provided_url:
                        continue  # DeepSeek 已设置，跳过
                    # 模糊匹配角色名与参考图名
                    for ref in char_refs:
                        ref_name = ref.get("name", "")
                        if not ref_name:
                            continue
                        # 精确匹配 或 子串匹配
                        if (char.name == ref_name
                                or char.name in ref_name
                                or ref_name in char.name
                                or ref_name in char.description):
                            char.provided_url = ref.get("url", "")
                            logger.info(f"自动匹配参考图: 角色 '{char.name}' ← 参考图 '{ref_name}' ({char.provided_url[:60]})")
                            break

        return plan

    def adjust_plan(self, plan_id: str, adjustments: list[dict]) -> AgentPlan:
        """根据用户微调修改已有计划"""
        plan = self._plans.get(plan_id)
        if not plan:
            return AgentPlan(
                plan_id=plan_id,
                status="failed",
                error="计划不存在或已过期",
            )

        for adj in adjustments:
            # 全局参数调整
            if "global_style" in adj:
                plan.global_style = adj["global_style"]
            if "global_camera_motion" in adj:
                plan.global_camera_motion = adj["global_camera_motion"]
            if "global_negative_prompt" in adj:
                plan.global_negative_prompt = adj["global_negative_prompt"]
            if "width" in adj:
                plan.width = int(adj["width"])
            if "height" in adj:
                plan.height = int(adj["height"])
            if "voiceover_text" in adj:
                plan.voiceover_text = adj["voiceover_text"]
            if "voiceover_voice" in adj:
                plan.voiceover_voice = adj["voiceover_voice"]

            # 分镜级别调整
            idx = adj.get("scene_index", -1)
            if 0 <= idx < len(plan.scenes):
                scene = plan.scenes[idx]
                if "prompt_cn" in adj:
                    scene.prompt_cn = adj["prompt_cn"]
                if "prompt" in adj:
                    scene.prompt = adj["prompt"]
                if "first_frame_prompt" in adj:
                    scene.first_frame_prompt = adj["first_frame_prompt"]
                if "last_frame_prompt" in adj:
                    scene.last_frame_prompt = adj["last_frame_prompt"]
                if "duration" in adj:
                    scene.duration = float(adj["duration"])
                if "camera_motion" in adj:
                    scene.camera_motion = adj["camera_motion"]
                if "scene_characters" in adj:
                    scene.scene_characters = adj["scene_characters"]
                if "time_breakdown" in adj:
                    scene.time_breakdown = adj["time_breakdown"]
                if "dialogue" in adj:
                    scene.dialogue = adj["dialogue"]
                if "dialogue_speaker" in adj:
                    scene.dialogue_speaker = adj["dialogue_speaker"]

        plan.total_duration = sum(s.duration for s in plan.scenes)
        plan.status = "draft"

        self._plans[plan_id] = plan
        return plan

    def get_plan(self, plan_id: str) -> Optional[AgentPlan]:
        return self._plans.get(plan_id)

    def cache_plan(self, plan: AgentPlan):
        self._plans[plan.plan_id] = plan

    def _parse_ai_response(self, text: str, user_message: str) -> AgentPlan:
        """解析 DeepSeek 返回的 JSON，支持自动修复"""
        plan_id = str(uuid.uuid4())

        data = None
        try:
            json_str = DeepSeekClient.extract_json(text)
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            # 第一次解析失败，尝试用 json_repair 自动修复
            logger.warning(f"JSON 标准解析失败，尝试自动修复: {e}")
            try:
                from json_repair import repair_json
                repaired = repair_json(text, return_objects=True)
                if isinstance(repaired, dict) and repaired.get("scenes"):
                    data = repaired
                    logger.info("JSON 自动修复成功")
                else:
                    raise ValueError(f"修复结果无效: {type(repaired)}")
            except Exception as repair_err:
                logger.error(f"DeepSeek 响应解析失败(修复也失败): {repair_err}\n原始文本: {text[:1000]}")
                return AgentPlan(
                    plan_id=plan_id,
                    user_request=user_message,
                    status="failed",
                    error=f"AI 返回格式异常，请重试: {e}",
                )

        # 构建角色列表
        characters = []
        for c in data.get("characters", []):
            characters.append(CharacterDesign(
                name=c.get("name", "未命名角色"),
                description=c.get("description", ""),
                image_prompt=c.get("image_prompt", ""),
                three_view_prompt=c.get("three_view_prompt", ""),
                expression_prompt=c.get("expression_prompt", ""),
                accessory_prompt=c.get("accessory_prompt", ""),
                provided_url=c.get("provided_url", ""),
            ))

        scenes = []
        for s in data.get("scenes", []):
            scenes.append(ScenePlan(
                index=s.get("index", len(scenes)),
                prompt=s.get("prompt", ""),
                prompt_cn=s.get("prompt_cn", ""),
                duration=float(s.get("duration", 10)),
                first_frame_prompt=s.get("first_frame_prompt", ""),
                first_frame_prompt_cn=s.get("first_frame_prompt_cn", ""),
                last_frame_prompt=s.get("last_frame_prompt", ""),
                last_frame_prompt_cn=s.get("last_frame_prompt_cn", ""),
                camera_motion=s.get("camera_motion", data.get("global_camera_motion", "static")),
                scene_characters=s.get("scene_characters", []),
                time_breakdown=s.get("time_breakdown", ""),
                dialogue=s.get("dialogue", ""),
                dialogue_speaker=s.get("dialogue_speaker", ""),
                use_chain_frame=s.get("use_chain_frame", True),
                environment_prompt=s.get("environment_prompt", ""),
                environment_prompt_cn=s.get("environment_prompt_cn", ""),
            ))

        # 场景时长校验：
        # 1. 将每个分镜的 duration 对齐到 Agnes API 支持的有效档位
        # 2. 验证总和是否匹配 total_duration
        VALID_DURATIONS = [5.0, 10.0, 15.0]  # Agnes API 有效时长档位（24fps）
        target_total = float(data.get("total_duration", 0))

        def snap_to_valid_duration(d: float) -> float:
            """将任意时长对齐到最近的有效档位"""
            return min(VALID_DURATIONS, key=lambda v: abs(v - d))

        for scene in scenes:
            scene.duration = snap_to_valid_duration(scene.duration)

        current_total = sum(s.duration for s in scenes)

        # 验证时长总和是否匹配目标
        if target_total > 0 and abs(current_total - target_total) > 1.0:
            logger.warning(
                f"分镜时长总和 ({current_total}s) 与目标总时长 ({target_total}s) 不匹配！"
                f"当前 {len(scenes)} 个分镜，建议调整分镜数量或时长档位。"
            )

        global_w = int(data.get("width", 1152))
        global_h = int(data.get("height", 768))

        plan = AgentPlan(
            plan_id=plan_id,
            user_request=user_message,
            title=data.get("title", user_message[:50]),
            total_duration=sum(s.duration for s in scenes),
            characters=characters,
            scenes=scenes,
            global_style=data.get("global_style", "cinematic"),
            global_negative_prompt=data.get("global_negative_prompt", "blur, distortion, low quality, deformed, mutated hands, fused fingers, bad anatomy, missing limbs, extra people, text, watermark, signature, cross-eyed, asynchronous lips, inconsistent appearance, character swap"),
            global_camera_motion=data.get("global_camera_motion", "static"),
            width=global_w,
            height=global_h,
            enable_voiceover=data.get("enable_voiceover", True),
            enable_subtitle=data.get("enable_subtitle", True),
            voiceover_text=data.get("voiceover_text", ""),
            voiceover_voice=data.get("voiceover_voice", "zh-CN-YunxiNeural"),
            status="draft",
        )

        self._plans[plan_id] = plan
        return plan


# 全局单例
_agent: Optional[AgentCore] = None


def get_agent() -> AgentCore:
    global _agent
    if _agent is None:
        _agent = AgentCore()
    return _agent
