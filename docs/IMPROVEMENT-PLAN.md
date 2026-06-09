# План: доработка Yandex Tracker MCP

## Контекст

Игорь (PM в Intensa) использует MCP-сервер Яндекс.Трекера в Claude Code / Claude Desktop.
Изначальный запрос: «доработать MCP, чтобы он подхватывал описание задач» (минимум) и
«добавить полезные возможности синхронизации с Трекером» (максимум).

Разведка показала, что используемый MCP — **сторонний PyPI-пакет `yandex-tracker-mcp`**
([aikts/yandex-tracker-mcp](https://github.com/aikts/yandex-tracker-mcp)), запускается через
`uvx …@latest`, установлена версия 0.7.2. Живёт в кэше uv, не как локальный репозиторий.

Конфиг запуска (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```
"yandex-tracker": {
  "command": "/bin/sh",
  "args": ["-c", "set -a; . \"$HOME/.config/intensa/tracker.env\"; exec /Users/igorvolkov/.local/bin/uvx --python 3.12 yandex-tracker-mcp@latest"]
}
```

**Задача-минимум снята.** В актуальной версии `issue_get` отдаёт `description` по умолчанию
(`include_description=True`), а кастомные/локальные поля проходят через passthrough
(`extra="allow"` в модели `Issue`). Проверено эмпирически на живой OLDOS-551 — полный markdown
описания и все локальные поля (`planfaktkoplate`, `otsenkadljaklienta`, `willUseAI` и пр.)
приходят. Раньше MCP «не видел описание» из-за старой версии — сейчас это не так.
Нюанс: в `issues_find` описание по умолчанию выключено (`include_description=False`, чтобы не
раздувать контекст) — включается флагом. Отдельная доработка ради описания не нужна.

Остаётся **максимум** — 4 группы возможностей, которых в пакете нет (подтверждено пользователем):
доски/спринты, массовые операции, вложения (скачивание/загрузка), чек-листы на запись.

## Что пакет уже умеет (38 tools, не трогаем)

- **Чтение issue:** `issue_get`, `issue_get_comments`, `issue_get_links`, `issue_get_worklogs`,
  `issue_get_attachments` (только метаданные), `issue_get_checklist`, `issue_get_transitions`,
  `issue_get_changelog`, `issues_find`, `issues_count`.
- **Запись issue:** `issue_create`, `issue_update`, `issue_move`, `issue_close`,
  `issue_execute_transition`, `issue_add_comment` / `update` / `delete`, `issue_add_link` /
  `delete`, worklog CRUD.
- **Справочники:** очереди, поля (глобальные/очереди), статусы, типы, приоритеты, резолюции, юзеры,
  версии очереди.

## Выбранный формат: форк + апстрим-PR (одобрено)

Причина выбора против companion-MCP: новые фичи тесно завязаны на существующий HTTP-клиент,
pydantic-модели, гард read-only и обработку org-id — в форке всё переиспользуется; companion
дублировал бы ~150 строк auth/клиента и не давал бы общих типов.

1. Форкнуть в `volkovidpm/yandex-tracker-mcp`, клонировать в `~/projects/yandex-tracker-mcp`,
   добавить апстрим-remote (`git remote add upstream https://github.com/aikts/yandex-tracker-mcp`).
2. Реализовать фичи отдельными коммитами/ветками (по одной группе на ветку — удобно для PR).
3. Переключить запуск на форк: в `claude_desktop_config.json` заменить
   `yandex-tracker-mcp@latest` на
   `uvx --from git+https://github.com/volkovidpm/yandex-tracker-mcp@main yandex-tracker-mcp`
   (обёртка с `. "$HOME/.config/intensa/tracker.env"` сохраняется без изменений).
4. Открыть PR-ы в апстрим. Если вмержат — вернуться на `@latest`, форк-запуск убрать.
   Пока нет — работаем с форка, периодически `git rebase upstream/main`.

## Аутентификация (для справки при реализации)

- Env (из `~/.config/intensa/tracker.env`): `TRACKER_TOKEN` (OAuth), `TRACKER_CLOUD_ORG_ID`.
- Заголовки: `Authorization: OAuth <token>`, `X-Cloud-Org-ID: <id>` (или `X-Org-ID` для не-облачных).
- База: `https://api.tracker.yandex.net`. Сборка заголовков — `TrackerClient._build_headers(auth)`.

## Архитектура: точки расширения

Каждая новая операция трогает существующие слои (следовать текущему паттерну пакета):

- **Протокол** — интерфейс в `mcp_tracker/tracker/proto/*.py` (`issues.py`; для досок — новый `boards.py`).
- **Реализация** — HTTP-вызов в `mcp_tracker/tracker/custom/client.py` через `self._session`
  (`ClientSession` с `base_url`) + `await self._build_headers(auth)`.
- **Кэш-обёртка** — зеркальный метод в `mcp_tracker/tracker/caching/client.py` (read — с кэшем,
  write — passthrough).
- **Типы** — pydantic-модели в `mcp_tracker/tracker/proto/types/*.py` (наследовать `BaseTrackerEntity`,
  использовать `NoneExcludedField` / алиасы camelCase→snake_case как в существующих моделях).
- **Tools** — регистрация в `mcp_tracker/mcp/tools/*.py`. Read-tools — в группы, регистрируемые всегда;
  write-tools — в группы под условием `if not settings.tracker_read_only` внутри `register_all_tools`
  (`mcp/tools/__init__.py`). Для issue-scoped вызовов — `check_issue_access(settings, issue_id)`.
- **Новая группа протокола (boards)** — прокинуть в `AppContext` (lifespan в `mcp/server.py`) как
  `.boards`, по аналогии с `.issues` / `.queues` / `.users`.

## Объём по фичам

> Точные пути/параметры endpoint-ов сверить с доками Яндекс.Трекера при реализации:
> https://yandex.cloud/ru/docs/tracker/about-api

### 1. Доски и спринты (read)
- Новый протокол `tracker/proto/boards.py` + реализация в клиенте + `mcp/tools/board.py`.
- Endpoints: `GET /v2/boards`, `/v2/boards/{id}`, `/v2/boards/{id}/columns`,
  `/v2/boards/{id}/sprints`, `/v2/sprints/{id}`.
- Tools: `boards_list`, `board_get`, `board_get_sprints`, `sprint_get`.
  Задачи спринта — через существующий `issues_find` с YQL `Sprint: "<name>"`.
- Типы: `Board`, `BoardColumn`, `Sprint`.
- Read-only гард не применяется (только чтение); `check_issue_access` неприменим (доски вне очередей).

### 2. Массовые операции (write, гард read-only)
- В issues-протокол + `mcp/tools/issue_write.py`.
- Endpoints: `POST /v2/bulkchange/_update`, `/_transition`, `/_move`;
  статус — `GET /v2/bulkchange/{id}`.
- Tools: `issues_bulk_update`, `issues_bulk_transition`, `issues_bulk_move`,
  `bulkchange_get_status`. Операции асинхронные — возвращают id bulk-операции.
- Типы: `BulkChangeStatus`.

### 3. Вложения: скачивание/загрузка (read + write)
- В issues-протокол.
- Скачивание (read): `GET /v2/issues/{id}/attachments/{attId}/{filename}` → бинарь.
  Tool `issue_download_attachment(issue_id, attachment_id, save_to_path?)` — сохраняет файл
  (по умолчанию в scratchpad-директорию), возвращает путь + метаданные. **Base64 не отдаём**
  (риск раздуть контекст большими файлами).
- Загрузка (write, гард read-only): `POST /v2/issues/{id}/attachments` (multipart/form-data).
  Tool `issue_add_attachment(issue_id, file_path)`.

### 4. Чек-листы на запись (write, гард read-only)
- В issues-протокол + `mcp/tools/issue_write.py`.
- Endpoints: `POST /v2/issues/{id}/checklistItems` (добавить),
  `PATCH …/{itemId}` (текст / checked / assignee / deadline),
  `DELETE …/{itemId}` (удалить).
- Tools: `issue_add_checklist_item`, `issue_update_checklist_item`, `issue_delete_checklist_item`.
- Чтение уже есть (`issue_get_checklist`); переиспользовать тип `ChecklistItem`.

## Верификация

- Локально из форка: `uv run` + MCP Inspector (`mcp dev`) — прогнать каждый новый tool на реальной
  задаче (песочная OLDOS-* или тестовая очередь).
- Read-only: с `TRACKER_READ_ONLY=true` write-tools (bulk, checklist-write, upload) не должны
  регистрироваться; read-tools (доски, download) — должны.
- Тесты пакета: `pytest` (в репозитории есть CI) — добавить кейсы по образцу существующих.
- Финальная проверка: переключить `claude_desktop_config.json` на форк-запуск, перезапустить клиент,
  вызвать новые tools из Claude Code на живом Трекере.

## Порядок работ (предлагаемый)

1. Форк + клон + upstream-remote, локальный запуск оригинала из исходников (`uv run`).
2. Фича 1 (доски/спринты) — самая изолированная, новый протокол → отработать паттерн расширения.
3. Фича 4 (чек-листы write) — маленькая, в существующем issue-слое.
4. Фича 3 (вложения) — download, затем upload (multipart).
5. Фича 2 (bulk) — асинхронные операции + poll статуса.
6. Тесты, README-правки, переключение конфига на форк, PR-ы в апстрим.
