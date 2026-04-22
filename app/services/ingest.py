from collections import defaultdict
import re
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

from app.models import (
    DigestItem,
    DigestRelease,
    GroupingMode,
    ItemType,
    SourceItem,
    SummaryStatus,
    ValueCategory,
)
from app.review_utils import CATEGORY_LABELS, default_item_category, default_item_status, sanitize_digest_title, should_collect_description
from app.services.openai_generation import OpenAIGenerationError, OpenAIReleaseCopyGenerator


def build_release(
    source_items: Iterable[SourceItem],
    release_id: str,
    release_date: str,
    copy_generator: Optional[OpenAIReleaseCopyGenerator] = None,
) -> tuple[DigestRelease, List[DigestItem]]:
    items = list(source_items)
    grouped: Dict[str, List[SourceItem]] = defaultdict(list)
    singles: List[SourceItem] = []

    for item in items:
        if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE} and item.parent_epic_id:
            grouped[item.parent_epic_id].append(item)
        else:
            singles.append(item)

    digest_items: List[DigestItem] = []
    digest_item_sources: Dict[str, List[SourceItem]] = {}

    for epic_id, epic_items in grouped.items():
        digest_item = _build_epic_digest_item(release_id, epic_id, epic_items)
        digest_items.append(digest_item)
        digest_item_sources[digest_item.id] = list(epic_items)

    for source_item in singles:
        digest_item = _build_single_digest_item(release_id, source_item)
        digest_items.append(digest_item)
        digest_item_sources[digest_item.id] = [source_item]

    release = DigestRelease(
        id=release_id,
        release_date=release_date,
        summary=generate_summary(digest_items),
        summary_status=SummaryStatus.DRAFT,
    )

    if copy_generator and copy_generator.is_enabled():
        _enrich_release_with_ai_copy(copy_generator, release, digest_items, digest_item_sources)
    return release, digest_items


def generate_summary(items: List[DigestItem]) -> str:
    release_items = [
        item for item in items
        if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE, ItemType.BUGFIX, ItemType.TECHNICAL_IMPROVEMENT}
    ]
    if not release_items:
        return "В этом релизе собраны обновления, которые помогают поддерживать стабильную и предсказуемую работу системы."

    total = len(release_items)
    new_features = sum(1 for item in release_items if item.type == ItemType.NEW_FEATURE)
    changes = sum(1 for item in release_items if item.type == ItemType.CHANGE)
    technical = sum(1 for item in release_items if item.type == ItemType.TECHNICAL_IMPROVEMENT)
    bugfixes = sum(1 for item in release_items if item.type == ItemType.BUGFIX)

    dominant_module = _top_names((item.module for item in release_items), limit=1)
    top_categories = _top_names(
        (
            CATEGORY_LABELS[item.category]
            for item in release_items
            if item.category is not None
        ),
        limit=2,
    )

    focus_parts = []
    if dominant_module:
        focus_parts.append(f"Основные изменения сосредоточены в модуле {dominant_module[0]}")
    else:
        focus_parts.append("Основные изменения сосредоточены в ключевых сценариях подбора")

    if top_categories:
        category_phrase = _join_names(top_categories)
        focus_parts.append(
            f"и направлены на { _category_focus_phrase(category_phrase) }"
        )
    else:
        focus_parts.append("и направлены на повышение удобства и предсказуемости работы")

    first_paragraph = " ".join(focus_parts) + "."
    second_paragraph = (
        f"Всего в релиз вошло {total} задач: {new_features} новых функций, {changes} изменений, "
        f"{technical} технических итераций и {bugfixes} исправлений."
    )
    return f"{first_paragraph}\n\n{second_paragraph}"


def _build_epic_digest_item(release_id: str, epic_id: str, epic_items: List[SourceItem]) -> DigestItem:
    primary = epic_items[0]
    item_type = primary.type
    title = sanitize_digest_title(primary.parent_epic_title or primary.title)
    category = default_item_category(item_type)
    description = _fallback_description_from_sources(item_type, primary.module, title, epic_items, category)
    return DigestItem(
        id=f"digest-{uuid4().hex[:10]}",
        release_id=release_id,
        source_item_ids=[item.id for item in epic_items],
        title=title,
        description=description,
        module=primary.module,
        type=item_type,
        category=category,
        status=default_item_status(item_type),
        tracker_urls=[item.url for item in epic_items],
        grouping_mode=GroupingMode.EPIC_GROUP,
    )


def _build_single_digest_item(release_id: str, source_item: SourceItem) -> DigestItem:
    title = sanitize_digest_title(source_item.title)
    description = ""
    category = default_item_category(source_item.type)
    if should_collect_description(source_item.type):
        description = _fallback_description_from_sources(
            source_item.type,
            source_item.module,
            title,
            [source_item],
            category,
        )
    return DigestItem(
        id=f"digest-{uuid4().hex[:10]}",
        release_id=release_id,
        source_item_ids=[source_item.id],
        title=title,
        description=description,
        module=source_item.module,
        type=source_item.type,
        category=category,
        status=default_item_status(source_item.type),
        tracker_urls=[source_item.url],
        grouping_mode=GroupingMode.SINGLE_TASK,
    )


def generate_fallback_item_description(
    item_type: ItemType,
    module: str,
    title: str,
    category: Optional[ValueCategory],
    source_descriptions: List[str],
) -> str:
    lead = _build_lead_sentence(item_type, title, source_descriptions)
    benefit = _build_benefit_sentence(item_type, module, category, source_descriptions)
    if benefit:
        return f"{lead} {benefit}"
    return lead


def _fallback_description_from_sources(
    item_type: ItemType,
    module: str,
    title: str,
    source_items: List[SourceItem],
    category: Optional[ValueCategory],
) -> str:
    return generate_fallback_item_description(
        item_type,
        module,
        title,
        category,
        [_clean_source_description(item.description) for item in source_items if item.description.strip()],
    )


def _build_lead_sentence(item_type: ItemType, title: str, source_descriptions: List[str]) -> str:
    title_phrase = _normalize_title_for_sentence(title)
    context = _pick_context_phrase(source_descriptions)
    if item_type == ItemType.NEW_FEATURE:
        if context:
            return f"Появилась возможность {context}."
        return f"Добавили {title_phrase}."
    if context:
        return f"Обновили сценарий {context}."
    return f"Обновили {title_phrase}."


def _build_benefit_sentence(
    item_type: ItemType,
    module: str,
    category: Optional[ValueCategory],
    source_descriptions: List[str],
) -> str:
    hint = _pick_benefit_hint(source_descriptions)
    if hint:
        return hint
    category_hint = _category_sentence(category)
    if category_hint:
        return category_hint
    if item_type == ItemType.NEW_FEATURE:
        return f"Это помогает быстрее решать повседневные задачи в модуле {module}."
    return f"Так работать с модулем {module} становится проще и понятнее."


def _pick_context_phrase(source_descriptions: List[str]) -> str:
    for description in source_descriptions:
        sentence = _first_sentence(description)
        if not sentence:
            continue
        cleaned = _trim_intro(sentence)
        if len(cleaned.split()) >= 3:
            return cleaned.rstrip(".")
    return ""


def _pick_benefit_hint(source_descriptions: List[str]) -> str:
    benefit_markers = ("позвол", "помога", "упроща", "ускор", "сниж", "делает", "даёт", "дает")
    for description in source_descriptions:
        for sentence in _split_sentences(description):
            lowered = sentence.lower()
            if any(marker in lowered for marker in benefit_markers):
                normalized = _normalize_sentence(sentence)
                if normalized:
                    return normalized
    return ""


def _category_sentence(category: Optional[ValueCategory]) -> str:
    mapping = {
        ValueCategory.TIME_SAVING: "Это помогает сократить время на рутинные действия.",
        ValueCategory.ERROR_REDUCTION: "Это помогает снизить количество ручных ошибок.",
        ValueCategory.CLARITY_TRANSPARENCY: "Так процесс становится понятнее и прозрачнее для команды.",
        ValueCategory.DAILY_WORK_CONVENIENCE: "Это делает повседневную работу с системой удобнее.",
        ValueCategory.BETTER_CONTROL: "Это даёт больше контроля над процессом и результатом.",
        ValueCategory.LESS_COMMUNICATION_OVERHEAD: "Это помогает сократить лишние согласования и уточнения.",
    }
    return mapping.get(category, "")


def _category_focus_phrase(category_phrase: str) -> str:
    lowered = category_phrase.lower()
    if "удобство" in lowered or "эконом" in lowered:
        return f"повышение {category_phrase.lower()}"
    return category_phrase.lower()


def _normalize_title_for_sentence(title: str) -> str:
    normalized = sanitize_digest_title(title).strip()
    if normalized:
        return normalized[0].lower() + normalized[1:]
    return "обновление"


def _clean_source_description(description: str) -> str:
    cleaned = re.sub(r"\s+", " ", (description or "").strip())
    return cleaned


def _first_sentence(text: str) -> str:
    sentences = _split_sentences(text)
    return sentences[0] if sentences else ""


def _split_sentences(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def _trim_intro(sentence: str) -> str:
    trimmed = re.sub(
        r"^(добавить|добавили|изменить|изменили|обновить|обновили|исправить|исправили|сделать|сделали|реализовать|реализовали)\s+",
        "",
        sentence.strip(),
        flags=re.IGNORECASE,
    )
    return _normalize_phrase(trimmed)


def _normalize_sentence(sentence: str) -> str:
    normalized = _normalize_phrase(sentence)
    if not normalized:
        return ""
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized[0].upper() + normalized[1:]


def _normalize_phrase(text: str) -> str:
    normalized = text.strip(" .,:;")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _top_names(values: Iterable[str], limit: int) -> List[str]:
    counts: Dict[str, int] = {}
    for value in values:
        key = (value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, _ in ordered[:limit]]


def _join_names(values: List[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + f" и {values[-1]}"


def _enrich_release_with_ai_copy(
    copy_generator: OpenAIReleaseCopyGenerator,
    release: DigestRelease,
    digest_items: List[DigestItem],
    digest_item_sources: Dict[str, List[SourceItem]],
) -> None:
    try:
        release.summary = copy_generator.generate_summary(release, digest_items)
    except OpenAIGenerationError:
        pass

    try:
        generated_descriptions = copy_generator.generate_item_descriptions(digest_items, digest_item_sources)
    except OpenAIGenerationError:
        return

    for item in digest_items:
        generated_description = generated_descriptions.get(item.id)
        if generated_description and should_collect_description(item.type):
            item.description = generated_description
