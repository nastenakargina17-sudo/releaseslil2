from app.models import ItemType, SourceItem


def sample_source_items() -> list[SourceItem]:
    return [
        SourceItem(
            id="REL-101",
            url="https://tracker.example.com/REL-101",
            title="Новый сценарий согласования релиза",
            description="Добавить пользовательский сценарий согласования релиза",
            module="Релизы",
            type=ItemType.NEW_FEATURE,
            parent_epic_id="REL-100",
            parent_epic_title="Улучшение процесса согласования релизов",
        ),
        SourceItem(
            id="REL-102",
            url="https://tracker.example.com/REL-102",
            title="Обновить отображение статусов согласования",
            description="Сделать статусы релиза более понятными",
            module="Релизы",
            type=ItemType.CHANGE,
            parent_epic_id="REL-100",
            parent_epic_title="Улучшение процесса согласования релизов",
        ),
        SourceItem(
            id="SUP-201",
            url="https://tracker.example.com/SUP-201",
            title="Исправить ошибку сохранения фильтров",
            description="Исправление ошибки при сохранении фильтра",
            module="Отчеты",
            type=ItemType.BUGFIX,
        ),
        SourceItem(
            id="OPS-310",
            url="https://tracker.example.com/OPS-310",
            title="Оптимизировать фоновые задачи синхронизации",
            description="Техническая доработка фоновых задач",
            module="Интеграции",
            type=ItemType.TECHNICAL_IMPROVEMENT,
        ),
    ]

