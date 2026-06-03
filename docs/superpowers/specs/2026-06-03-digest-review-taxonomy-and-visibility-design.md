# Digest Review Taxonomy And Visibility Design

## Goal

Reviewers need one shared model for classifying Tracker tasks and deciding how each task should appear in release materials. The review screen and digest generation should use the same assumptions, so a task's meaning does not change between import, review, and publication.

The current single task type mixes two decisions:

- what kind of change was made;
- whether the change should be shown to clients or kept in an internal overview.

This design separates those decisions into two fields.

## Core Model

Each digest item has two independent editorial fields.

### Change Type

`Change Type` answers: what did we actually do?

- `Новый функционал`: a new product capability, usually built for all or most clients.
- `Продуктовое улучшение`: an improvement to an existing product scenario or behavior.
- `Клиентская доработка`: work originally done for a specific client case. It is usually internal, but can be shown publicly when it demonstrates a capability that is useful more broadly.
- `Внутреннее изменение`: work on an internal tool, admin flow, or hidden system behavior. It can be public only when the client-facing effect is meaningful.
- `Техническая итерация`: infrastructure, code quality, preparatory, or technical platform work.
- `Исправление`: a fix for incorrect or broken behavior.

### Digest Visibility

`Digest Visibility` answers: where should this item appear?

- `Публичный дайджест`: the item appears on the client-facing digest page.
- `Внутренний обзор`: the item stays in the internal review/overview layer and is not shown to clients.

There is no `Не публиковать` visibility in this stage. Tasks that should not be considered for the digest are filtered out before digest review is formed.

## Default Visibility

Tracker import sets initial values, but reviewers can override them.

- `Новый функционал` defaults to `Публичный дайджест`.
- `Продуктовое улучшение` defaults to `Публичный дайджест`.
- `Клиентская доработка` defaults to `Внутренний обзор`.
- `Внутреннее изменение` defaults to `Внутренний обзор`.
- `Техническая итерация` defaults to `Внутренний обзор`.
- `Исправление` defaults to `Внутренний обзор`.

Public visibility is an editorial decision, not a property of the Tracker issue type. For example, a client-specific vacancy text generation feature can be promoted to the public digest if it is useful to show as a broader platform capability.

Bug fixes stay internal by default. If a fix closes a visible client pain, a reviewer may mark it public, but the client-facing copy should describe the improved stability or correctness of the scenario rather than advertise a bug.

## Review Screen

The review card remains a single form shape for all items. Visibility does not hide or show card fields. This keeps review simple and avoids separate forms for public and internal items.

The card should expose two controls:

- `Тип изменения`;
- `Видимость`.

The filter panel should also separate these dimensions:

- filter by change type;
- filter by digest visibility.

This lets reviewers quickly inspect combinations such as all public items, all client-specific work, or all client-specific work that remains internal.

## Description Rules

Description generation depends only on change type, not on visibility.

Descriptions are generated for:

- `Новый функционал`;
- `Продуктовое улучшение`;
- `Клиентская доработка`;
- `Внутреннее изменение`.

Descriptions are not generated for:

- `Техническая итерация`;
- `Исправление`.

This preserves the current behavior where technical iterations and bug fixes do not receive generated digest descriptions, while all broader product/client/internal changes can have editable copy.

## Tracker Import Mapping

Tracker import should populate the initial change type and visibility as a best guess. Manual review remains the source of truth after import.

Recommended mapping:

| Tracker signal | Change type | Visibility |
| --- | --- | --- |
| `type.key = osibkaS` | `Исправление` | `Внутренний обзор` |
| `story` with tag `Tech🔧` | `Техническая итерация` | `Внутренний обзор` |
| `story`, Product Development primary project, and `inTheReleaseDescription = Клиентский и внутренний` | `Новый функционал` | `Публичный дайджест` |
| `story`, `inTheReleaseDescription = Клиентский и внутренний`, and `Client Task`/`Клиентский запрос` component | `Клиентская доработка` | `Публичный дайджест` |
| `story`, `inTheReleaseDescription = Клиентский и внутренний`, and ordinary product component | `Продуктовое улучшение` | `Публичный дайджест` |
| `story` with `inTheReleaseDescription = Только внутренний` | `Внутреннее изменение` | `Внутренний обзор` |
| `story` with `inTheReleaseDescription = Нет` | excluded before the main digest review stage | excluded before the main digest review stage |

The mapping table may set a visibility that differs from the generic change-type default because it uses Tracker's explicit release-description signal. For example, `Клиентская доработка` generally defaults to internal, but a task already marked `Клиентский и внутренний` in Tracker can start as public and still be corrected during review.

The import should not overwrite a reviewed manual classification when an unchanged item is reimported. Existing preservation logic should be extended to include the new fields.

## Digest Rules

The public client digest is built from `Видимость = Публичный дайджест`, not directly from change type.

The public digest can include:

- new functionality;
- product improvements;
- client-specific work promoted as a broader capability;
- internal changes with a meaningful client-facing effect;
- fixes explicitly promoted by a reviewer.

Public section naming should stay client-friendly:

- `Что нового` for new functionality;
- `Что улучшили` for product improvements and public internal changes;
- `Клиентские сценарии` or `Новые возможности по запросам клиентов` for public client-specific work, if present;
- public fixes should appear as improvements, not as a `Баги` section.

The internal overview is built from `Видимость = Внутренний обзор`.

Internal overview grouping can use the working taxonomy:

- `Клиентские доработки`;
- `Внутренние изменения`;
- `Технические итерации`;
- `Исправления`.

## Out Of Scope

This design does not add a third publication state, change the set of fields shown on review cards, or redesign the client digest visual style.

This design also does not implement new Tracker fields. It uses currently observed Tracker signals first and keeps manual review as the correction layer.

## Testing Notes

Implementation should include focused coverage for:

- default Tracker mapping into change type and visibility;
- description generation for all change types, especially no generated descriptions for technical iterations and fixes;
- review updates preserving manual classification on unchanged reimport;
- digest generation using visibility as the publication gate;
- public fixes rendering as improvements rather than a bug section.
