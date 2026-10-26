from __future__ import annotations

from uuid import uuid4

from app.domain.models import ScriptGenerateRequest, VideoScript
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "script_writing",
    "title": "视频脚本生成",
    "description": "把主题与要点扩写成可直接拍摄的多渠道短视频脚本，口播文案可转公众号文章。",
    "category": "pipeline",
    "version": "1.0.0",
    "builtin": True,
    "locked": True,
}


class ScriptWritingSkill:
    version = "1.0.0"

    def __init__(self, model):
        self.model = model

    async def run(
        self,
        request: ScriptGenerateRequest,
        *,
        extra_context: dict | None = None,
    ) -> VideoScript:
        payload = {
            "topic": request.topic,
            "channel": request.channel.value,
            "duration_seconds": request.duration_seconds,
            "audience": request.audience,
            "key_points": request.key_points,
            "tone": request.tone,
        }
        if extra_context:
            payload["context"] = extra_context
        result = await self.model.generate_structured(
            system=load_prompt("script"),
            user=compact_json(payload),
            response_model=VideoScript,
        )
        script = result.data
        # 模型只负责内容；标识、归属与来源由系统写入，杜绝客户端/模型伪造。
        script = script.model_copy(
            update={
                "id": str(uuid4()),
                "topic": request.topic,
                "channel": request.channel,
                "duration_seconds": request.duration_seconds,
                "audience": request.audience,
                "source": "model",
                "status": "draft",
                "task_id": None,
            }
        )
        return script
