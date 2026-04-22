import json
import re
import time
from collections import Counter
from typing import Dict, Iterable, List, Optional

import httpx

from app.config import OpenAISettings
from app.models import DigestItem, DigestRelease, GroupingMode, ItemType, SourceItem
from app.review_utils import CATEGORY_LABELS


class OpenAIGenerationError(RuntimeError):
    pass


SUMMARY_SCHEMA = {
    "name": "release_summary",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
        },
        "required": ["summary"],
    },
}


ITEM_DESCRIPTIONS_SCHEMA = {
    "name": "release_item_descriptions",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "item_id": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["item_id", "description"],
                },
            },
        },
        "required": ["items"],
    },
}


class OpenAIReleaseCopyGenerator:
    def __init__(self, settings: OpenAISettings) -> None:
        self.settings = settings

    def is_enabled(self) -> bool:
        return bool(self.settings.api_key)

    def generate_summary(self, release: DigestRelease, items: List[DigestItem]) -> str:
        stats = _build_summary_stats(items)
        prompt = _build_summary_prompt(stats)
        payload = self._request_json(prompt, SUMMARY_SCHEMA)
        draft_summary = _cleanup_summary_text(
            _normalize_generated_text(str(payload.get("summary") or "").strip()),
            release.id,
        )
        summary = self._rewrite_summary(draft_summary, stats, release.id)
        summary = self._repair_summary_if_needed(summary, stats, release.id)
        if not summary:
            raise OpenAIGenerationError("OpenAI summary response is empty")
        return summary

    def generate_item_descriptions(
        self,
        digest_items: List[DigestItem],
        item_sources: Dict[str, List[SourceItem]],
    ) -> Dict[str, str]:
        eligible_items = [
            item for item in digest_items
            if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}
        ]
        if not eligible_items:
            return {}

        draft_descriptions: Dict[str, str] = {}
        for batch in _chunked(eligible_items, 8):
            batch_descriptions = self._generate_item_descriptions_batch(batch, item_sources)
            draft_descriptions.update(batch_descriptions)
        if not draft_descriptions:
            return {}
        try:
            rewritten = self._rewrite_item_descriptions(eligible_items, item_sources, draft_descriptions)
        except OpenAIGenerationError:
            rewritten = draft_descriptions
        return self._repair_item_descriptions_if_needed(eligible_items, item_sources, rewritten)

    def _rewrite_summary(self, draft_summary: str, stats: dict, release_id: str) -> str:
        prompt = _build_summary_rewrite_prompt(draft_summary, stats)
        payload = self._request_json(prompt, SUMMARY_SCHEMA)
        return _cleanup_summary_text(
            _normalize_generated_text(str(payload.get("summary") or "").strip()) or draft_summary,
            release_id,
        )

    def _repair_summary_if_needed(self, summary: str, stats: dict, release_id: str) -> str:
        reasons = _validate_summary_text(summary)
        if not reasons:
            return summary
        prompt = _build_summary_repair_prompt(summary, stats, reasons)
        try:
            payload = self._request_json(prompt, SUMMARY_SCHEMA)
        except OpenAIGenerationError:
            return summary
        repaired = _cleanup_summary_text(
            _normalize_generated_text(str(payload.get("summary") or "").strip()) or summary,
            release_id,
        )
        return repaired or summary

    def _generate_item_descriptions_batch(
        self,
        eligible_items: List[DigestItem],
        item_sources: Dict[str, List[SourceItem]],
    ) -> Dict[str, str]:
        item_by_id = {item.id: item for item in eligible_items}
        prompt = _build_item_descriptions_prompt(eligible_items, item_sources)
        payload = self._request_json(prompt, ITEM_DESCRIPTIONS_SCHEMA)
        descriptions: Dict[str, str] = {}
        for item_payload in payload.get("items", []):
            item_id = str(item_payload.get("item_id") or "").strip()
            item = item_by_id.get(item_id)
            description = _cleanup_item_description_text(
                _normalize_generated_text(str(item_payload.get("description") or "").strip()),
                item.type if item else None,
            )
            if item_id and description:
                descriptions[item_id] = description
        return descriptions

    def _rewrite_item_descriptions(
        self,
        eligible_items: List[DigestItem],
        item_sources: Dict[str, List[SourceItem]],
        draft_descriptions: Dict[str, str],
    ) -> Dict[str, str]:
        if not draft_descriptions:
            return draft_descriptions
        prompt = _build_item_rewrite_prompt(eligible_items, item_sources, draft_descriptions)
        payload = self._request_json(prompt, ITEM_DESCRIPTIONS_SCHEMA)
        rewritten: Dict[str, str] = {}
        item_by_id = {item.id: item for item in eligible_items}
        for item_payload in payload.get("items", []):
            item_id = str(item_payload.get("item_id") or "").strip()
            item = item_by_id.get(item_id)
            description = _cleanup_item_description_text(
                _normalize_generated_text(str(item_payload.get("description") or "").strip()),
                item.type if item else None,
            )
            if item_id and description:
                rewritten[item_id] = description
        return {item_id: rewritten.get(item_id, draft) for item_id, draft in draft_descriptions.items()}

    def _repair_item_descriptions_if_needed(
        self,
        eligible_items: List[DigestItem],
        item_sources: Dict[str, List[SourceItem]],
        descriptions: Dict[str, str],
    ) -> Dict[str, str]:
        invalid_items = []
        item_by_id = {item.id: item for item in eligible_items}
        for item_id, description in descriptions.items():
            reasons = _validate_item_description_text(description)
            if reasons:
                invalid_items.append((item_by_id[item_id], reasons))
        if not invalid_items:
            return descriptions
        for batch in _chunked(invalid_items, 6):
            prompt = _build_item_repair_prompt(batch, item_sources, descriptions)
            try:
                payload = self._request_json(prompt, ITEM_DESCRIPTIONS_SCHEMA)
            except OpenAIGenerationError:
                continue
            for item_payload in payload.get("items", []):
                item_id = str(item_payload.get("item_id") or "").strip()
                item = item_by_id.get(item_id)
                description = _cleanup_item_description_text(
                    _normalize_generated_text(str(item_payload.get("description") or "").strip()),
                    item.type if item else None,
                )
                if item_id and description:
                    descriptions[item_id] = description
        return descriptions

    def _request_json(self, prompt: str, schema: dict) -> dict:
        if not self.is_enabled():
            raise OpenAIGenerationError("OPENAI_API_KEY is not configured")

        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.settings.timeout_seconds) as client:
                    response = client.post(
                        "https://api.openai.com/v1/responses",
                        headers={
                            "Authorization": f"Bearer {self.settings.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.settings.model,
                            "input": [
                                {
                                    "role": "system",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": (
                                                "Ты пишешь тексты для релиз-дайджеста на русском языке. "
                                                "Пиши спокойно, делово, понятно и без маркетингового пафоса. "
                                                "Не придумывай факты, которых нет во входных данных. "
                                                "Используй только русский язык, кроме официальных названий продуктов и общепринятых терминов вроде AI."
                                            ),
                                        }
                                    ],
                                },
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": prompt,
                                        }
                                    ],
                                },
                            ],
                            "text": {
                                "format": {
                                    "type": "json_schema",
                                    "name": schema["name"],
                                    "schema": schema["schema"],
                                    "strict": True,
                                }
                            },
                        },
                    )
                    response.raise_for_status()
                    raw_text = _extract_response_text(response.json())
                    payload = json.loads(raw_text)
                    if not isinstance(payload, dict):
                        raise OpenAIGenerationError("OpenAI returned unexpected response shape")
                    return payload
            except (httpx.HTTPError, json.JSONDecodeError, OpenAIGenerationError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
                    continue
        raise OpenAIGenerationError(f"OpenAI request failed: {last_error}") from last_error


def _build_summary_stats(items: Iterable[DigestItem]) -> dict:
    ordered_items = [
        item
        for item in items
        if item.type in {
            ItemType.NEW_FEATURE,
            ItemType.CHANGE,
            ItemType.TECHNICAL_IMPROVEMENT,
            ItemType.BUGFIX,
        }
    ]
    type_counts = Counter(item.type.value for item in ordered_items)
    module_counts = Counter(item.module for item in ordered_items)
    new_feature_module_counts = Counter(
        item.module for item in ordered_items if item.type == ItemType.NEW_FEATURE
    )
    category_counts = Counter(
        CATEGORY_LABELS[item.category]
        for item in ordered_items
        if item.category is not None
    )

    return {
        "total_tasks": len(ordered_items),
        "type_counts": {
            "changes": type_counts[ItemType.CHANGE.value],
            "new_features": type_counts[ItemType.NEW_FEATURE.value],
            "technical_iterations": type_counts[ItemType.TECHNICAL_IMPROVEMENT.value],
            "bugs": type_counts[ItemType.BUGFIX.value],
        },
        "dominant_module": _stable_top_items(module_counts, limit=1),
        "top_new_feature_modules": _stable_top_items(new_feature_module_counts, limit=2),
        "top_categories": _stable_top_items(category_counts, limit=3),
    }


def _stable_top_items(counter: Counter, limit: int) -> List[dict]:
    ordered_pairs = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"name": name}
        for name, count in ordered_pairs[:limit]
    ]


def _build_summary_prompt(stats: dict) -> str:
    return (
        "Сгенерируй summary для релиз-дайджеста.\n\n"
        "Портрет читателя:\n"
        "- HR-директор\n"
        "- руководитель подбора\n"
        "- операционный директор\n"
        "- CEO / COO\n"
        "- ИТ и цифровая трансформация\n"
        "- безопасность и закупки\n"
        "- рекрутер\n"
        "- нанимающий менеджер\n"
        "- другие внутренние пользователи ATS\n\n"
        "Что важно для читателя:\n"
        "- что изменилось в процессе подбора\n"
        "- где был основной фокус релиза\n"
        "- как это влияет на скорость, удобство, прозрачность и предсказуемость работы\n"
        "- что это даёт в ежедневной работе, а не только на уровне системы\n\n"
        "Требования:\n"
        "- Язык: русский.\n"
        "- Стиль: спокойный, деловой, продуктовый, без пафоса и канцелярита.\n"
        "- Формат: 1-2 абзаца.\n"
        "- Первый абзац должен начинаться с общего смыслового вывода о релизе, а не со статистики.\n"
        "- Второй абзац может содержать факты и числа, если они действительно помогают понять релиз.\n"
        "- Не выдумывай факты.\n"
        "- Не перечисляй больше 2 модулей и больше 3 категорий.\n"
        "- Не упоминай ключ релиза, дату релиза или сам факт даты в тексте summary.\n"
        "- Если упоминаешь модули-лидеры по новым фичам, называй только модули без чисел и без количества фич по каждому модулю.\n"
        "- Когда перечисляешь типы задач, сначала говори о новых функциях и изменениях, затем о технических итерациях и багфикcах.\n"
        "- Не делай баги главным смысловым акцентом summary, даже если их больше всего.\n"
        "- Если новых фич нет, не упоминай модули-лидеры по новым фичам.\n"
        "- Если категорий мало, используй только доступные.\n"
        "- Summary должно звучать как обзор сверху, а не как технический лог.\n\n"
        "Чего нельзя делать:\n"
        "- Не начинай текст с фраз вроде: \"В релизе ... было завершено ... задач\".\n"
        "- Не превращай summary в сухую сводку чисел.\n"
        "- Не перечисляй подряд все типы, модули и категории без смыслового вывода.\n"
        "- Не используй формулировки, похожие на лог выгрузки или статусный отчет.\n\n"
        "Логика генерации:\n"
        "- Определи доминирующий модуль по общему количеству задач и используй его как основной фокус релиза.\n"
        "- Определи 1-2 доминирующие ценности по top_categories и опиши их мягко, без процентов и сухой аналитики.\n"
        "- Сначала объясни смысл релиза для процесса подбора, затем дай компактную фактуру.\n"
        "- Если багов много, это можно упомянуть, но не делай их главным тезисом summary.\n\n"
        "Предпочтительная структура:\n"
        "- Абзац 1: основной фокус релиза через доминирующий модуль и смысл для пользователей.\n"
        "- Абзац 2: компактная статистика по типам в порядке: новые функции, изменения, технические итерации, баги; затем модули с новыми возможностями и 1-2 главные ценности.\n\n"
        f"Данные для генерации: {json.dumps(stats, ensure_ascii=False)}\n\n"
        "Нужно обязательно учесть:\n"
        "- доминирующий модуль,\n"
        "- общий смысловой вывод по релизу,\n"
        "- общее количество задач,\n"
        "- количества по типам: изменения, новые фичи, технические итерации, баги,\n"
        "- названия топ-2 модулей по количеству новых фич, но без чисел по модулям,\n"
        "- топ-3 категории по общему количеству задач.\n"
    )


def _build_summary_rewrite_prompt(draft_summary: str, stats: dict) -> str:
    return (
        "Отредактируй summary релиза.\n\n"
        "Нужно сохранить только факты из черновика и статистики, но улучшить стиль, грамматику и структуру.\n"
        "Пиши для HR-директора, руководителя подбора, рекрутера, нанимающего менеджера и других пользователей ATS.\n"
        "Требования:\n"
        "- Язык: русский.\n"
        "- Тон: спокойный, деловой, уверенный.\n"
        "- Не упоминай ключ релиза и дату.\n"
        "- Не делай баги главным акцентом текста.\n"
        "- Если перечисляешь типы задач, порядок должен быть такой: новые функции, изменения, технические итерации, баги.\n"
        "- Все количества и числа в summary пиши цифрами, не словами.\n"
        "- Не указывай численные подсчеты по модулям.\n"
        "- Доминирующий модуль используй как смысловой фокус, а не как сухой справочник.\n"
        "- Покажи, что изменения значат для процесса подбора и повседневной работы.\n"
        "- Убери канцелярит, сухую отчетность и грамматические ошибки.\n"
        "- Не добавляй новых фактов.\n\n"
        f"Статистика: {json.dumps(stats, ensure_ascii=False)}\n"
        f"Черновик: {json.dumps(draft_summary, ensure_ascii=False)}\n"
    )


def _build_summary_repair_prompt(summary: str, stats: dict, reasons: List[str]) -> str:
    return (
        "Исправь summary релиза так, чтобы оно строго соответствовало требованиям.\n\n"
        "Сделай только редактуру: не добавляй новых фактов и не меняй смысл.\n"
        "Требования:\n"
        "- Спокойный, деловой, продуктовый русский язык.\n"
        "- Без канцелярита и без слов: реализовано, функционал, произведены изменения.\n"
        "- Без ключа релиза и даты.\n"
        "- Числа только цифрами.\n"
        "- Не делать баги главным акцентом.\n"
        "- Не считать фичи по модулям.\n\n"
        f"Статистика: {json.dumps(stats, ensure_ascii=False)}\n"
        f"Проблемы текущего текста: {json.dumps(reasons, ensure_ascii=False)}\n"
        f"Текущий текст: {json.dumps(summary, ensure_ascii=False)}\n"
    )


def _build_item_descriptions_prompt(
    digest_items: List[DigestItem],
    item_sources: Dict[str, List[SourceItem]],
) -> str:
    items_payload = []
    for item in digest_items:
        source_items = item_sources.get(item.id, [])
        items_payload.append(
            {
                "item_id": item.id,
                "item_type": "feature" if item.type == ItemType.NEW_FEATURE else "change",
                "module": item.module,
                "category": CATEGORY_LABELS[item.category] if item.category else None,
                "digest_title": item.title,
                "grouping_mode": item.grouping_mode.value,
                "source_tasks": [
                    {
                        "title": source_item.title,
                        "description": source_item.description,
                    }
                    for source_item in source_items
                ],
            }
        )

    return (
        "Сгенерируй короткие описания пунктов релиз-дайджеста.\n\n"
        "Портрет читателя:\n"
        "- рекрутер\n"
        "- нанимающий менеджер\n"
        "- руководитель подбора\n"
        "- HR-директор\n"
        "- внутренние пользователи ATS\n\n"
        "Что важно читателю:\n"
        "- что именно изменилось или появилось\n"
        "- как это повлияет на ежедневную работу\n"
        "- что стало проще, быстрее, понятнее или предсказуемее\n\n"
        "Требования:\n"
        "- Язык: русский.\n"
        "- Стиль: продуктовый, понятный, спокойный.\n"
        "- Без маркетингового пафоса, без канцелярита.\n"
        "- Используй только title и description исходных задач.\n"
        "- Не выдумывай факты, которых нет во входных данных.\n"
        "- Длина каждого описания: 2-4 коротких предложения. Допустимо 1-2 абзаца.\n"
        "- Не используй списки.\n"
        "- Не дублируй буквально текст задачи.\n"
        "- Не используй слова: реализовано, функционал, доработка, произведены изменения.\n"
        "- По возможности избегай внутренних технических терминов, названий инфраструктуры, аббревиатур и служебных деталей.\n"
        "- Если в исходной задаче много технического шума, оставь только ту часть, которая объясняет пользовательский или бизнес-смысл.\n"
        "- Не делай текст похожим на changelog для разработчиков.\n"
        "- Пиши только на русском языке; не вставляй фрагменты на других языках, кроме официальных названий продуктов.\n"
        "- Не акцентируй внимание на внутренних технологиях вроде Redis, S3, коллекций, токенов и служебных ограничений, если это не ключевая пользовательская ценность.\n"
        "- Для feature объясни, что появилось и чем это помогает / кому полезно / что упрощает.\n"
        "- Для change объясни, что изменилось и что стало проще / понятнее / быстрее, либо какую проблему уменьшили.\n"
        "- Убирай технический шум и переводи формулировки в продуктовый язык.\n\n"
        "Логика описания:\n"
        "- Сначала понятно назови изменение человеческим языком.\n"
        "- Потом коротко объясни, что это значит для клиента.\n"
        "- Можно опираться на категорию ценности, но не подменяй ей реальное содержание задачи.\n"
        "- Формулировки должны быть живыми и различаться между пунктами.\n"
        "- Не заканчивай подряд несколько пунктов одной и той же конструкцией.\n\n"
        "Предпочтительные формулировки:\n"
        "- Для feature: сначала что появилось, затем чем это полезно.\n"
        "- Для change: сначала что изменилось, затем что это меняет в работе.\n"
        "- Не используй один и тот же шаблон для всех пунктов.\n\n"
        f"Пункты для генерации: {json.dumps(items_payload, ensure_ascii=False)}\n"
    )


def _build_item_rewrite_prompt(
    digest_items: List[DigestItem],
    item_sources: Dict[str, List[SourceItem]],
    draft_descriptions: Dict[str, str],
) -> str:
    items_payload = []
    for item in digest_items:
        source_items = item_sources.get(item.id, [])
        items_payload.append(
            {
                "item_id": item.id,
                "item_type": "feature" if item.type == ItemType.NEW_FEATURE else "change",
                "draft_description": draft_descriptions.get(item.id, ""),
                "source_tasks": [
                    {
                        "title": source_item.title,
                        "description": source_item.description,
                    }
                    for source_item in source_items
                ],
            }
        )

    return (
        "Отредактируй описания пунктов релиз-дайджеста.\n\n"
        "Нужно сохранить факты из черновика и исходных задач, но улучшить стиль.\n"
        "Требования:\n"
        "- Спокойный, продуктовый, понятный русский язык.\n"
        "- Исправь грамматику и шероховатости.\n"
        "- Убери слишком технические детали, если они не важны для бизнес-смысла.\n"
        "- Не используй слова: реализовано, функционал, доработка, произведены изменения.\n"
        "- Пиши для рекрутера, нанимающего менеджера, руководителя подбора и HR-директора.\n"
        "- Не используй один и тот же шаблон из пункта в пункт.\n"
        "- Для feature обычно лучше начинать с того, что появилось, но не обязательно всегда со слова \"Добавили\".\n"
        "- Для change обычно лучше начинать с сути изменения, но избегай однотипных заходов во всех пунктах.\n"
        "- Не придумывай новые факты.\n"
        "- Не делай текст похожим на технический changelog.\n\n"
        f"Пункты для редактуры: {json.dumps(items_payload, ensure_ascii=False)}\n"
    )


def _build_item_repair_prompt(
    invalid_items: List[tuple[DigestItem, List[str]]],
    item_sources: Dict[str, List[SourceItem]],
    draft_descriptions: Dict[str, str],
) -> str:
    items_payload = []
    for item, reasons in invalid_items:
        items_payload.append(
            {
                "item_id": item.id,
                "item_type": "feature" if item.type == ItemType.NEW_FEATURE else "change",
                "problems": reasons,
                "draft_description": draft_descriptions.get(item.id, ""),
                "source_tasks": [
                    {
                        "title": source_item.title,
                        "description": source_item.description,
                    }
                    for source_item in item_sources.get(item.id, [])
                ],
            }
        )
    return (
        "Исправь описания пунктов релиза.\n\n"
        "Нужно переписать только проблемные тексты так, чтобы они стали естественными и соответствовали правилам.\n"
        "Требования:\n"
        "- Русский, спокойный, продуктовый язык.\n"
        "- Не использовать слова: реализовано, функционал, доработка, произведены изменения.\n"
        "- Не писать однотипными штампами.\n"
        "- Не делать текст слишком общим и пустым.\n"
        "- Пиши для рекрутера, нанимающего менеджера, руководителя подбора и HR-директора.\n"
        "- Объясняй, что произошло и что это значит для клиента.\n"
        "- Для feature по возможности сначала показывай, что появилось, а затем пользу.\n"
        "- Для change по возможности сначала показывай, что изменилось, а затем эффект в работе.\n"
        "- Не придумывай новые факты.\n"
        "- Не вставляй технический шум, если он не важен пользователю.\n\n"
        f"Проблемные пункты: {json.dumps(items_payload, ensure_ascii=False)}\n"
    )


def _extract_response_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]

    output = payload.get("output") or []
    text_chunks: List[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                text_chunks.append(text_value)
    if text_chunks:
        return "\n".join(text_chunks).strip()
    raise OpenAIGenerationError("OpenAI response did not contain text output")


def _normalize_generated_text(text: str) -> str:
    normalized = re.sub(r"[\u4e00-\u9fff]+", "", text)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _cleanup_summary_text(text: str, release_id: str) -> str:
    cleaned = text
    cleaned = re.sub(rf"\b{re.escape(release_id)}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:\d{1,2}\s+[а-яё]+\s+\d{4}\s+года|\d{4}-\d{2}-\d{2})\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"Релиз\s*[A-ZА-Я0-9-]*\s*", "В этом релизе ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"который состоялся\s*,?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:В данном\s+)+(?:В этом\s+)+(?:В этом\s+)?релизе", "В этом релизе", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:В представленном\s+)+(?:В этом\s+)+(?:В этом\s+)?релизе", "В этом релизе", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:В данном\s+)+релизе", "В этом релизе", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:В представленном\s+)+релизе", "В этом релизе", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:В этом\s+){2,}релизе", "В этом релизе", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Наиболее заметными новыми функциями стали обновления в модулях", "Среди модулей с новыми функциями выделяются", cleaned)
    cleaned = re.sub(r'"\s*\((?:\d+[^)]*)\)', '"', cleaned)
    cleaned = re.sub(r"\((?:\d+[^)]*задач[^)]*)\)", "", cleaned)
    cleaned = _normalize_summary_number_words(cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    cleaned = re.sub(r"[ ]{2,}", " ", cleaned)
    return cleaned.strip()


def _cleanup_item_description_text(text: str, item_type: Optional[ItemType]) -> str:
    cleaned = text
    start_replacements = [
        (r"^Реализован[аоы]?\s+", "Добавили " if item_type == ItemType.NEW_FEATURE else "Обновили "),
        (r"^Реализовали\s+", "Добавили " if item_type == ItemType.NEW_FEATURE else "Обновили "),
        (r"^Внедрена\s+", "Добавили " if item_type == ItemType.NEW_FEATURE else "Обновили "),
        (r"^Внедрено\s+", "Добавили " if item_type == ItemType.NEW_FEATURE else "Обновили "),
        (r"^Внедрили\s+", "Добавили " if item_type == ItemType.NEW_FEATURE else "Обновили "),
        (r"^Доработан[аоы]?\s+", "Добавили " if item_type == ItemType.NEW_FEATURE else "Обновили "),
        (r"^Доработали\s+", "Добавили " if item_type == ItemType.NEW_FEATURE else "Обновили "),
        (r"^Улучшен[аоы]?\s+", "Обновили "),
        (r"^Улучшили\s+", "Обновили "),
    ]
    for pattern, replacement in start_replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\bфункционал\b", "возможность", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bдоработк[аеиоуы]\b", "обновление", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bпроизведены изменения\b", "обновили", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[ ]{2,}", " ", cleaned)
    return cleaned.strip()


def _normalize_summary_number_words(text: str) -> str:
    replacements = {
        "ноль": "0",
        "один": "1",
        "одна": "1",
        "одно": "1",
        "одну": "1",
        "два": "2",
        "две": "2",
        "три": "3",
        "четыре": "4",
        "пять": "5",
        "шесть": "6",
        "семь": "7",
        "восемь": "8",
        "девять": "9",
        "десять": "10",
        "одиннадцать": "11",
        "двенадцать": "12",
    }
    normalized = text
    for source, target in replacements.items():
        normalized = re.sub(rf"\b{source}\b", target, normalized, flags=re.IGNORECASE)
    return normalized


def _validate_summary_text(text: str) -> List[str]:
    issues: List[str] = []
    lowered = text.lower()
    banned_fragments = [
        "реализовано",
        "произведено",
        "произведены изменения",
        "функционал",
        "в данном в этом релизе",
    ]
    for fragment in banned_fragments:
        if fragment in lowered:
            issues.append(f"Есть запрещенная или неудачная формулировка: {fragment}")
    if "баг" in lowered and ("нов" not in lowered and "измен" not in lowered):
        issues.append("Слишком сильный акцент на багах без достаточного акцента на новых возможностях и изменениях")
    return issues


def _validate_item_description_text(text: str) -> List[str]:
    issues: List[str] = []
    lowered = text.lower()
    banned_fragments = [
        "реализовано",
        "реализована",
        "функционал",
        "доработка",
        "произведены изменения",
    ]
    for fragment in banned_fragments:
        if fragment in lowered:
            issues.append(f"Есть запрещенная формулировка: {fragment}")
    generic_fragments = [
        "это помогает",
        "это позволяет",
        "что позволяет",
        "что помогает",
        "в ежедневной работе",
    ]
    generic_count = sum(1 for fragment in generic_fragments if fragment in lowered)
    if generic_count >= 2:
        issues.append("Текст звучит слишком шаблонно и общо")
    if len(text.split()) < 8:
        issues.append("Текст слишком короткий и может быть слишком общим")
    return issues


def _chunked(items: List, size: int) -> List[List]:
    return [items[index:index + size] for index in range(0, len(items), size)]
