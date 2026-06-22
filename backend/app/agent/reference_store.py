"""参考图存储管理 - 管理用户上传的角色/场景/关键帧参考图"""

import json
import logging
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# 存储目录
REF_DIR = settings.STORAGE_DIR / "references"
INDEX_FILE = REF_DIR / "index.json"


@dataclass
class ReferenceImage:
    """参考图条目"""
    id: str
    name: str           # 引用名，如 "炎龙侠"
    ref_type: str       # character / scene / keyframe
    url: str            # 图床公开URL
    local_path: str     # 本地路径


class ReferenceStore:
    """参考图存储管理器（JSON 文件持久化）"""

    def __init__(self):
        REF_DIR.mkdir(parents=True, exist_ok=True)
        self._refs: dict[str, ReferenceImage] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载"""
        if INDEX_FILE.exists():
            try:
                data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
                for item in data:
                    ref = ReferenceImage(**item)
                    self._refs[ref.id] = ref
            except Exception as e:
                logger.warning(f"加载参考图索引失败: {e}")

    def _save(self):
        """持久化到 JSON 文件"""
        data = [asdict(ref) for ref in self._refs.values()]
        INDEX_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, name: str, ref_type: str, url: str, local_path: str) -> ReferenceImage:
        """添加参考图"""
        ref = ReferenceImage(
            id=uuid.uuid4().hex[:12],
            name=name,
            ref_type=ref_type,
            url=url,
            local_path=local_path,
        )
        self._refs[ref.id] = ref
        self._save()
        return ref

    def list(self) -> list[ReferenceImage]:
        """返回所有参考图"""
        return list(self._refs.values())

    def get_by_name(self, name: str) -> Optional[ReferenceImage]:
        """按名称查找"""
        for ref in self._refs.values():
            if ref.name == name:
                return ref
        return None

    def get_by_id(self, ref_id: str) -> Optional[ReferenceImage]:
        return self._refs.get(ref_id)

    def delete(self, ref_id: str) -> bool:
        """删除参考图"""
        if ref_id in self._refs:
            ref = self._refs.pop(ref_id)
            # 尝试删除本地文件
            try:
                p = Path(ref.local_path)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
            self._save()
            return True
        return False


# 全局单例
_store: Optional[ReferenceStore] = None


def get_reference_store() -> ReferenceStore:
    global _store
    if _store is None:
        _store = ReferenceStore()
    return _store
