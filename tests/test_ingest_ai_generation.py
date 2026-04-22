import unittest

from app.models import ItemType, SourceItem
from app.services.ingest import build_release
from app.services.openai_generation import (
    _build_item_descriptions_prompt,
    _build_item_repair_prompt,
    _build_item_rewrite_prompt,
    _build_summary_prompt,
    _build_summary_repair_prompt,
    _build_summary_rewrite_prompt,
    _cleanup_item_description_text,
    _cleanup_summary_text,
    _normalize_generated_text,
    _normalize_summary_number_words,
    _validate_item_description_text,
    _validate_summary_text,
)


class FakeCopyGenerator:
    def __init__(self, enabled: bool = True, should_fail: bool = False) -> None:
        self.enabled = enabled
        self.should_fail = should_fail

    def is_enabled(self) -> bool:
        return self.enabled

    def generate_summary(self, release, items):
        if self.should_fail:
            from app.services.openai_generation import OpenAIGenerationError

            raise OpenAIGenerationError("generation failed")
        return "Сгенерированное summary."

    def generate_item_descriptions(self, digest_items, item_sources):
        if self.should_fail:
            from app.services.openai_generation import OpenAIGenerationError

            raise OpenAIGenerationError("generation failed")
        return {
            item.id: f"Сгенерированное описание для {item.title}."
            for item in digest_items
            if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}
        }


class SummaryOnlyFailingGenerator(FakeCopyGenerator):
    def generate_summary(self, release, items):
        from app.services.openai_generation import OpenAIGenerationError

        raise OpenAIGenerationError("summary failed")


class RewriteFailingGenerator(FakeCopyGenerator):
    def _request_json(self, prompt, schema):
        from app.services.openai_generation import OpenAIGenerationError

        if "Отредактируй описания пунктов" in prompt:
            raise OpenAIGenerationError("rewrite failed")
        if schema["name"] == "release_summary":
            return {"summary": "Сгенерированное summary."}
        return {
            "items": [
                {"item_id": "item-1", "description": "Добавили полезную возможность."}
            ]
        }


class IngestAIGenerationTests(unittest.TestCase):
    def test_build_release_uses_ai_copy_when_generator_is_available(self) -> None:
        release, items = build_release(
            _sample_source_items(),
            release_id="2026-05",
            release_date="2026-05-31",
            copy_generator=FakeCopyGenerator(),
        )

        self.assertEqual(release.summary, "Сгенерированное summary.")
        described_items = [item for item in items if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}]
        self.assertTrue(described_items)
        self.assertTrue(all(item.description.startswith("Сгенерированное описание") for item in described_items))

    def test_build_release_falls_back_to_default_copy_on_ai_error(self) -> None:
        release, items = build_release(
            _sample_source_items(),
            release_id="2026-05",
            release_date="2026-05-31",
            copy_generator=FakeCopyGenerator(should_fail=True),
        )

        self.assertIn("В этом релизе сфокусировались", release.summary)
        described_items = [item for item in items if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}]
        self.assertTrue(described_items)
        self.assertTrue(all(item.description for item in described_items))
        self.assertTrue(all("Сгенерированное описание" not in item.description for item in described_items))

    def test_item_descriptions_can_still_be_generated_when_summary_fails(self) -> None:
        release, items = build_release(
            _sample_source_items(),
            release_id="2026-05",
            release_date="2026-05-31",
            copy_generator=SummaryOnlyFailingGenerator(),
        )

        self.assertIn("В этом релизе сфокусировались", release.summary)
        described_items = [item for item in items if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}]
        self.assertTrue(all(item.description.startswith("Сгенерированное описание") for item in described_items))

    def test_release_candidates_do_not_get_auto_descriptions(self) -> None:
        release, items = build_release(
            _sample_source_items(include_candidate=True),
            release_id="2026-05",
            release_date="2026-05-31",
            copy_generator=FakeCopyGenerator(),
        )

        candidate = next(item for item in items if item.type == ItemType.RELEASE_CANDIDATE)
        self.assertEqual(candidate.description, "")
        self.assertNotIn("Кандидаты", release.summary)

    def test_summary_prompt_requests_non_log_style(self) -> None:
        release, _ = build_release(
            _sample_source_items(),
            release_id="2026-05",
            release_date="2026-05-31",
        )

        stats = {
            "total_tasks": 3,
            "type_counts": {
                "changes": 1,
                "new_features": 1,
                "technical_iterations": 0,
                "bugs": 1,
            },
            "top_new_feature_modules": [{"name": "Релизы"}],
            "top_categories": [{"name": "Удобство ежедневной работы"}],
        }
        prompt = _build_summary_prompt(stats)

        self.assertIn("Первый абзац должен начинаться с общего смыслового вывода", prompt)
        self.assertIn("Не начинай текст с фраз", prompt)
        self.assertIn("Не упоминай ключ релиза, дату релиза", prompt)
        self.assertIn("без чисел по модулям", prompt)
        self.assertIn("сначала говори о новых функциях и изменениях", prompt)

    def test_item_prompt_requests_reduction_of_technical_noise(self) -> None:
        source_items = _sample_source_items()
        _, items = build_release(
            source_items,
            release_id="2026-05",
            release_date="2026-05-31",
        )
        eligible_items = [item for item in items if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}]
        item_sources = {item.id: [source] for item, source in zip(eligible_items, source_items[:len(eligible_items)])}

        prompt = _build_item_descriptions_prompt(eligible_items, item_sources)

        self.assertIn("избегай внутренних технических терминов", prompt)
        self.assertIn("Не делай текст похожим на changelog для разработчиков", prompt)

    def test_rewrite_prompts_enforce_editor_pass_rules(self) -> None:
        stats = {
            "total_tasks": 3,
            "type_counts": {
                "changes": 1,
                "new_features": 1,
                "technical_iterations": 0,
                "bugs": 1,
            },
            "top_new_feature_modules": [{"name": "Релизы"}],
            "top_categories": [{"name": "Удобство ежедневной работы"}],
        }
        summary_prompt = _build_summary_rewrite_prompt("Черновой summary", stats)
        self.assertIn("Не делай баги главным акцентом текста", summary_prompt)
        self.assertIn("порядок должен быть такой: новые функции, изменения, технические итерации, баги", summary_prompt)
        repair_summary_prompt = _build_summary_repair_prompt("Плохой summary", stats, ["канцелярит"])
        self.assertIn("Исправь summary релиза", repair_summary_prompt)

        source_items = _sample_source_items()
        _, items = build_release(source_items, release_id="2026-05", release_date="2026-05-31")
        eligible_items = [item for item in items if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}]
        item_sources = {item.id: [source] for item, source in zip(eligible_items, source_items[:len(eligible_items)])}
        rewrite_prompt = _build_item_rewrite_prompt(
            eligible_items,
            item_sources,
            {item.id: "Черновое описание" for item in eligible_items},
        )
        self.assertIn("Для feature обычно лучше начинать с того, что появилось", rewrite_prompt)
        self.assertIn("Не делай текст похожим на технический changelog", rewrite_prompt)
        repair_item_prompt = _build_item_repair_prompt(
            [(eligible_items[0], ["слишком шаблонно"])],
            item_sources,
            {eligible_items[0].id: "Черновое описание"},
        )
        self.assertIn("Исправь описания пунктов релиза", repair_item_prompt)

    def test_generated_text_normalization_removes_cjk_symbols(self) -> None:
        normalized = _normalize_generated_text("Соблюдение法律 152-ФЗ и порядок обработки данных.")
        self.assertEqual(normalized, "Соблюдение 152-ФЗ и порядок обработки данных.")

    def test_summary_cleanup_removes_release_key_and_module_counts(self) -> None:
        cleaned = _cleanup_summary_text(
            "Релиз DEV-47111 сосредоточен на стабильности. Наиболее заметными новыми функциями стали обновления в модулях \"Искусственный интеллект\" (2 новых функции) и \"Конфигуратор\" (1 новая функция).",
            "DEV-47111",
        )
        self.assertNotIn("DEV-47111", cleaned)
        self.assertNotIn("(2 новых функции)", cleaned)
        self.assertNotIn("(1 новая функция)", cleaned)

    def test_summary_cleanup_fixes_duplicate_release_phrase(self) -> None:
        cleaned = _cleanup_summary_text(
            "В данном В этом релизе основное внимание уделено удобству использования.",
            "DEV-47111",
        )
        self.assertEqual(cleaned, "В этом релизе основное внимание уделено удобству использования.")

    def test_summary_number_words_are_normalized_to_digits(self) -> None:
        normalized = _normalize_summary_number_words(
            "В summary есть три изменения, десять технических итераций и четыре новых функции."
        )
        self.assertEqual(
            normalized,
            "В summary есть 3 изменения, 10 технических итераций и 4 новых функции.",
        )

    def test_item_cleanup_rewrites_banned_openings(self) -> None:
        feature_text = _cleanup_item_description_text("Внедрили новую вкладку для оценки кандидатов.", ItemType.NEW_FEATURE)
        change_text = _cleanup_item_description_text("Реализована история согласий.", ItemType.CHANGE)
        self.assertTrue(feature_text.startswith("Добавили"))
        self.assertTrue(change_text.startswith("Обновили"))

    def test_validators_detect_bad_copy_patterns(self) -> None:
        summary_issues = _validate_summary_text("В данном в этом релизе реализовано много задач.")
        item_issues = _validate_item_description_text(
            "Реализована доработка. Это помогает в ежедневной работе и это позволяет улучшить процесс."
        )
        self.assertTrue(summary_issues)
        self.assertTrue(item_issues)


def _sample_source_items(include_candidate: bool = False):
    items = [
        SourceItem(
            id="REL-1",
            url="https://tracker.yandex.ru/REL-1",
            title="Новая форма согласования",
            description="Добавить новый сценарий согласования",
            module="Релизы",
            type=ItemType.NEW_FEATURE,
        ),
        SourceItem(
            id="REL-2",
            url="https://tracker.yandex.ru/REL-2",
            title="Изменить экран статусов",
            description="Сделать статусы релиза понятнее",
            module="Релизы",
            type=ItemType.CHANGE,
        ),
        SourceItem(
            id="REL-3",
            url="https://tracker.yandex.ru/REL-3",
            title="Исправить сохранение",
            description="Исправление ошибки сохранения",
            module="Релизы",
            type=ItemType.BUGFIX,
        ),
    ]
    if include_candidate:
        items.append(
            SourceItem(
                id="REL-4",
                url="https://tracker.yandex.ru/REL-4",
                title="Скрытая задача для ревью",
                description="Пока не решили, выносить ли в релиз.",
                module="Релизы",
                type=ItemType.RELEASE_CANDIDATE,
            )
        )
    return items


if __name__ == "__main__":
    unittest.main()
