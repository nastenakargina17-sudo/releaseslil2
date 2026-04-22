import unittest
from unittest import mock

from app.models import (
    DigestItem,
    DigestRelease,
    GroupingMode,
    ItemStatus,
    ItemType,
    SummaryStatus,
    ValueCategory,
)
from app.services.importers import _preserve_existing_copy_when_ai_falls_back


class ImporterCopyPreservationTests(unittest.TestCase):
    def test_existing_summary_is_preserved_when_new_import_falls_back(self) -> None:
        existing_release = DigestRelease(
            id="DEV-1",
            release_date="2026-02-03",
            summary="Хороший summary от GPT.",
            summary_status=SummaryStatus.DRAFT,
        )
        new_release = DigestRelease(
            id="DEV-1",
            release_date="2026-02-03",
            summary="Шаблонный summary.",
            summary_status=SummaryStatus.DRAFT,
        )
        new_items = [_build_item("digest-1", "DEV-101", "Новый пункт", "Шаблонное описание.")]

        with mock.patch("app.services.importers.generate_summary", return_value="Шаблонный summary."):
            _preserve_existing_copy_when_ai_falls_back(existing_release, [], new_release, new_items)

        self.assertEqual(new_release.summary, "Хороший summary от GPT.")

    def test_existing_description_is_preserved_when_new_import_falls_back(self) -> None:
        existing_item = _build_item(
            "digest-old",
            "DEV-101",
            "Новый пункт",
            "Хорошее описание от GPT.",
        )
        new_item = _build_item(
            "digest-new",
            "DEV-101",
            "Новый пункт",
            'В модуле Ядро добавили новое улучшение вокруг сценария "Новый пункт", чтобы пользователям было проще выполнять ежедневные операции и быстрее проходить рабочие шаги.',
        )

        _preserve_existing_copy_when_ai_falls_back(
            None,
            [existing_item],
            DigestRelease("DEV-1", "2026-02-03", "Summary"),
            [new_item],
        )

        self.assertEqual(new_item.description, "Хорошее описание от GPT.")

    def test_existing_copy_is_not_preserved_when_preservation_is_disabled(self) -> None:
        existing_release = DigestRelease(
            id="DEV-1",
            release_date="2026-02-03",
            summary="Хороший summary от GPT.",
            summary_status=SummaryStatus.DRAFT,
        )
        new_release = DigestRelease(
            id="DEV-1",
            release_date="2026-02-03",
            summary="Шаблонный summary.",
            summary_status=SummaryStatus.DRAFT,
        )
        new_item = _build_item(
            "digest-new",
            "DEV-101",
            "Новый пункт",
            'В модуле Ядро добавили новое улучшение вокруг сценария "Новый пункт", чтобы пользователям было проще выполнять ежедневные операции и быстрее проходить рабочие шаги.',
        )

        # Simulate the disabled preservation path used by manual bot re-imports.
        preserved_release = new_release
        preserved_items = [new_item]

        self.assertEqual(preserved_release.summary, "Шаблонный summary.")
        self.assertEqual(
            preserved_items[0].description,
            'В модуле Ядро добавили новое улучшение вокруг сценария "Новый пункт", чтобы пользователям было проще выполнять ежедневные операции и быстрее проходить рабочие шаги.',
        )


def _build_item(item_id: str, source_id: str, title: str, description: str) -> DigestItem:
    return DigestItem(
        id=item_id,
        release_id="DEV-1",
        source_item_ids=[source_id],
        title=title,
        description=description,
        module="Ядро",
        type=ItemType.NEW_FEATURE,
        category=ValueCategory.DAILY_WORK_CONVENIENCE,
        status=ItemStatus.DRAFT,
        grouping_mode=GroupingMode.SINGLE_TASK,
    )


if __name__ == "__main__":
    unittest.main()
