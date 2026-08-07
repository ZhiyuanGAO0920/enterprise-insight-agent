"""上下文管理器 — V3 功能 (P0-2)。

跨分析会话管理多轮对话状态。
受 FEATURE_MULTI_TURN 环境变量控制。

架构：
  第 1 层：会话 —— 完整对话历史（Redis）
  第 2 层：上下文窗口 —— 最近 3 轮对话用于 LLM 注入
  第 3 层：实体记忆 —— 对话中提到的具体实体
"""

import json
import re
import time
from typing import Optional

from app.config import get_settings
from app.database.redis import get_redis

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SESSION_PREFIX = "session:"     # Redis 键前缀
MAX_TURNS = 10                   # 保留的最大对话轮数
CONTEXT_WINDOW = 3               # 作为上下文注入的最近轮数
SESSION_TTL = 8 * 3600           # 8 小时（与 JWT TTL 匹配）
MAX_ENTITIES = 20                # 记忆的最大实体数


# ---------------------------------------------------------------------------
# 实体抽取（独立函数，无需异步）
# ---------------------------------------------------------------------------


def extract_entities_from_report(report: str) -> list[dict]:
    """从报告文本中提取关键实体（会员、门店）。

    用于填充实体记忆，以便像"查看他的所有消费记录"这样的追问
    可以将"他"解析为具体的会员。

    返回包含 name、type、detail 键的实体字典列表。
    """
    if not report:
        return []

    # 剥离 Markdown 格式（加粗、斜体），使正则能匹配干净的文本
    # 例如 "**胡勇**（会员ID: 4898）" → "胡勇（会员ID: 4898）"
    clean_report = re.sub(r'\*\*([^*]+)\*\*', r'\1', report)
    clean_report = re.sub(r'\*([^*]+)\*', r'\1', clean_report)

    entities: list[dict] = []
    seen: set[str] = set()
    # 不应被视为人名的通用词汇
    generic_words = {
        "会员", "客户", "门店", "数据", "记录", "结果", "分析", "报告",
        "增长", "下降", "趋势", "排名", "消费", "退款", "销售",
    }
    # 可能混入实体名称的中文虚词/语法字符
    _function_chars = set("是是否为的最更在和与或及到对让向比高大这那有店门")

    def _clean_name(raw: str) -> str:
        """从名称中去除开头的虚词以及末尾的"的"。"""
        while raw and raw[0] in _function_chars:
            raw = raw[1:]
        # Also strip trailing 的 (common grammar particle)
        while raw and raw[-1] == '的':
            raw = raw[:-1]
        return raw

    # --- 会员匹配模式 ---

    # 模式 1a：以"是/为"为前缀，名称后跟（会员ID: 数字）
    for m in re.finditer(r'(?:是|为)\s*([一-鿿]{2,3})（会员ID[：:\s]*(\d+)）', clean_report):
        name = _clean_name(m.group(1))
        if name in generic_words or len(name) < 2:
            continue
        member_id = m.group(2)
        key = f"member:{member_id}"
        if key not in seen:
            seen.add(key)
            entities.append({
                "name": name,
                "type": "member",
                "detail": f"会员ID: {member_id}",
            })

    # 模式 1b：标点符号或开头之后，名称后跟（会员ID: 数字）
    for m in re.finditer(r'(?:^|[，,。！？\s])([一-鿿]{2,3})（会员ID[：:\s]*(\d+)）', clean_report):
        name = _clean_name(m.group(1))
        if name in generic_words or len(name) < 2:
            continue
        member_id = m.group(2)
        key = f"member:{member_id}"
        if key not in seen:
            seen.add(key)
            entities.append({
                "name": name,
                "type": "member",
                "detail": f"会员ID: {member_id}",
            })

    # 模式 2：独立的"会员ID: 4898"（文本中没有名字）
    for m in re.finditer(r'会员ID[：:]\s*(\d+)', clean_report):
        member_id = m.group(1)
        key = f"member:{member_id}"
        if key not in seen:
            seen.add(key)
            entities.append({
                "name": f"会员{member_id}",
                "type": "member",
                "detail": f"会员ID: {member_id}",
            })

    # --- 门店匹配模式 ---

    # 模式 3："旗舰店040" —— 中文前缀 + 店 + 数字
    # 数字后缀是门店标识符的强信号
    for m in re.finditer(r'([一-鿿]{2,4}店\d{2,4})', clean_report):
        name = _clean_name(m.group(1))
        if name not in seen and len(name) >= 4:
            seen.add(name)
            entities.append({
                "name": name,
                "type": "store",
                "detail": name,
            })

    # 限制实体数量以避免膨胀
    if len(entities) > 10:
        entities = entities[:10]

    return entities


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


class ContextManager:
    """管理单个会话的多轮对话上下文。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.settings = get_settings()
        # V4.6.1: 实例级缓存 —— 一次请求内 is_followup / get_context_for_llm /
        # resolve_references 各调一次 _load() 会重复 GET 同一份 Redis session 数据，
        # 首读后缓存，后续复用（跨请求是新实例，天然拿到最新数据）。
        self._data: dict = {}
        self._loaded = False

    # ---- Redis 辅助方法 ----

    async def _load(self) -> dict:
        """从 Redis 加载会话数据（实例内只读一次，后续复用）。"""
        if self._loaded:
            return self._data
        if not self.settings.feature_multi_turn:
            self._loaded = True
            self._data = {}
            return self._data
        r = get_redis()
        raw = await r.get(f"{SESSION_PREFIX}{self.session_id}")
        self._data = json.loads(raw) if raw else {}
        self._loaded = True
        return self._data

    async def _save(self, data: dict) -> None:
        """将会话数据保存到 Redis。"""
        if not self.settings.feature_multi_turn:
            return
        r = get_redis()
        await r.setex(
            f"{SESSION_PREFIX}{self.session_id}",
            SESSION_TTL,
            json.dumps(data, ensure_ascii=False),
        )

    # ---- 核心操作 ----

    async def get_session_user_id(self) -> int | None:
        """返回会话的拥有者 user_id，用于权限验证。

        Returns:
            创建会话时绑定的 user_id，如果会话不存在或 feature 被禁用则返回 None。
        """
        data = await self._load()
        return data.get("user_id")

    async def add_turn(self, question: str, report: str,
                       entities: Optional[list[dict]] = None,
                       summary: str = "") -> None:
        """记录一个已完成的对话轮次。

        同时更新对话历史和实体记忆，使追问能够
        引用之前提到的实体（会员、门店）。
        """
        if not self.settings.feature_multi_turn:
            return

        data = await self._load()

        # 对话历史
        history = data.get("history", [])
        history.append({
            "question": question,
            "summary": summary or report[:300],
            "entities": entities or [],
            "timestamp": time.time(),
        })
        # 只保留最近的轮次
        if len(history) > MAX_TURNS:
            history = history[-MAX_TURNS:]

        # 实体列表：按最近使用排序，用于代词消解
        entity_list: list[dict] = data.get("entity_list", [])
        if entities:
            now = time.time()
            for ent in entities:
                # 去重：如果同名同类型存在，则更新时间戳
                exists = False
                for existing in entity_list:
                    if (existing.get("name") == ent.get("name") and
                            existing.get("type") == ent.get("type")):
                        existing["timestamp"] = now
                        existing["detail"] = ent.get("detail", existing.get("detail", ""))
                        exists = True
                        break
                if not exists:
                    entity_list.append({**ent, "timestamp": now})
            # 裁剪到最大实体数，保留最近的
            if len(entity_list) > MAX_ENTITIES:
                entity_list = sorted(
                    entity_list, key=lambda e: e.get("timestamp", 0), reverse=True
                )[:MAX_ENTITIES]

        # 实体记忆字典：供前端展示（名称 → 信息映射）
        entity_memory: dict = {}
        for ent in entity_list:
            entity_memory[ent.get("name", "")] = {
                "type": ent.get("type", ""),
                "detail": ent.get("detail", ""),
            }

        data["history"] = history
        data["entity_list"] = entity_list
        data["entity_memory"] = entity_memory
        data["turn_count"] = data.get("turn_count", 0) + 1
        await self._save(data)

    async def get_context_for_llm(self) -> str:
        """生成简洁的上下文摘要，用于注入 LLM 提示词。

        如果功能被禁用或没有上下文，返回空字符串。
        包含对话历史和已知实体，使 LLM 即使在没有
        显式正则消解的情况下也能解析代词引用（例如"他" → "胡勇"）。
        """
        if not self.settings.feature_multi_turn:
            return ""

        data = await self._load()
        history = data.get("history", [])
        entity_list = data.get("entity_list", [])

        if not history and not entity_list:
            return ""

        lines: list[str] = []

        # ---- 对话历史 ----
        if history:
            recent = history[-CONTEXT_WINDOW:]
            lines.append("## 对话上下文（前几轮讨论）")
            for i, turn in enumerate(recent):
                q = turn.get("question", "")
                s = turn.get("summary", "")[:150]
                lines.append(f"- 第{i+1}轮：用户问「{q}」，分析结论：{s}")

        # ---- 已知实体 ----
        if entity_list:
            # 按名称去重以便展示
            seen_names: set[str] = set()
            unique_entities: list[dict] = []
            for ent in entity_list:
                name = ent.get("name", "")
                if name not in seen_names:
                    seen_names.add(name)
                    unique_entities.append(ent)

            if unique_entities:
                lines.append("\n## 已知实体（前几轮对话中提到的）")
                for ent in unique_entities:
                    ent_type = ent.get("type", "")
                    name = ent.get("name", "")
                    detail = ent.get("detail", "")
                    if ent_type == "member":
                        lines.append(f"- 会员：{name}（{detail}）")
                    elif ent_type == "store":
                        lines.append(f"- 门店：{name}")
                    else:
                        lines.append(f"- {name}（{detail}）")

        lines.append("\n请基于以上上下文回答当前问题。如果当前问题包含代词（他/她/它/这个/那个/该/其），请根据「已知实体」和对话历史将其解析为具体实体。确保回答的连贯性。")
        return "\n".join(lines)

    async def resolve_references(self, question: str) -> str:
        """使用实体记忆解析代词引用。

        示例：
          "查看他的所有消费记录" + 实体(胡勇, member)
            → "查看胡勇（会员ID: 4898）的所有消费记录"
          "那家店退款率呢" + 实体(旗舰店040, store)
            → "旗舰店040退款率呢"
        """
        if not self.settings.feature_multi_turn:
            return question

        data = await self._load()
        entity_list: list[dict] = data.get("entity_list", [])
        if not entity_list:
            return question

        # 按时间戳排序，最近的在前面
        sorted_entities = sorted(
            entity_list, key=lambda e: e.get("timestamp", 0), reverse=True
        )

        resolved = question

        # ---- 指向会员的代词 ----
        member_pronouns = r'(他|她|这位会员|该会员|这个会员|该客户|这位客户|这名会员|那位会员)'
        if re.search(member_pronouns, resolved):
            for ent in sorted_entities:
                if ent.get("type") == "member":
                    name = ent.get("name", "")
                    detail = ent.get("detail", "")
                    if detail and detail != name:
                        replacement = f'{name}（{detail}）'
                    else:
                        replacement = name
                    resolved = re.sub(member_pronouns, lambda _: replacement, resolved, count=1)
                    break

        # ---- 指向门店的代词 ----
        store_pronouns = r'(这家店|该门店|这个门店|那个门店|该店|那家店|这家门店|那个店)'
        if re.search(store_pronouns, resolved):
            for ent in sorted_entities:
                if ent.get("type") == "store":
                    replacement = ent.get("name", ent.get("detail", ""))
                    resolved = re.sub(store_pronouns, lambda _: replacement, resolved, count=1)
                    break

        # ---- 通用 / 模糊代词（任意实体类型） ----
        # 使用负向前瞻排除「其」作为复合词组成部分的情况（其他/其中/其实/其余等）
        generic_pronouns = r'(它|其(?!他|中|实|余|间|次|它|一|二|三|四|五|六|七|八|九|十))'
        if re.search(generic_pronouns, resolved):
            if sorted_entities:
                ent = sorted_entities[0]  # 最近使用的实体
                if ent.get("type") == "member":
                    name = ent.get("name", "")
                    detail = ent.get("detail", "")
                    if detail and detail != name:
                        replacement = f'{name}（{detail}）'
                    else:
                        replacement = name
                else:
                    replacement = ent.get("name", ent.get("detail", ""))
                if replacement:
                    resolved = re.sub(generic_pronouns, lambda _: replacement, resolved, count=1)

        return resolved

    async def is_followup(self, question: str) -> bool:
        """启发式判断：基于关键词检测问题是否为追问。"""
        followup_patterns = [
            r'(他|她|它|其)',                         # 引用先前实体的代词
            r'(那个|这个|那家|这家)',                   # 指示性引用
            r'(这位|该|那名)',                         # 特指引用
            r'(呢|吗|吧)$',                           # 句末语气词
            r'^(再|继续|进一步|具体|接着)',             # 延续性标记
            r'^(那|那么)',                             # 以"那/那么"开头的问题
        ]
        for pattern in followup_patterns:
            if re.search(pattern, question):
                return True
        # 短问题：很可能是追问
        return len(question) <= 4

    async def get_entity_memory(self) -> dict:
        """返回当前实体记忆字典（供前端展示）。

        格式：{name: {type, detail}, ...}
        """
        data = await self._load()
        return data.get("entity_memory", {})

    async def get_history(self) -> list[dict]:
        """返回对话历史。"""
        data = await self._load()
        return data.get("history", [])


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


async def create_session(user_id: int) -> str:
    """创建新的对话会话并返回 session_id。"""
    import uuid
    session_id = uuid.uuid4().hex[:16]
    r = get_redis()
    data = {
        "user_id": user_id,
        "history": [],
        "entity_list": [],
        "entity_memory": {},
        "turn_count": 0,
        "created_at": time.time(),
    }
    await r.setex(
        f"{SESSION_PREFIX}{session_id}",
        SESSION_TTL,
        json.dumps(data, ensure_ascii=False),
    )
    return session_id
