# План: доработка Yandex Tracker MCP

## Статус и точка продолжения (обновлено 2026-07-01)

**Инфраструктура форка готова:**
- Форк `volkovidpm/yandex-tracker-mcp` (parent = aikts). Клон — `~/projects/mcp/yandex-tracker-mcp`.
  Remotes: `origin` (SSH, наш форк) + `upstream` (`https://github.com/aikts/yandex-tracker-mcp`).
- `gh` CLI поставлен через brew, залогинен как `volkovidpm` (SSH).
- Апстрим на 2026-07-01: последняя версия **0.7.2** (19 июня), main-HEAD = ровно тег 0.7.2,
  unreleased-коммитов сверху нет. Запуск `uvx …@latest` уже даёт 0.7.2.

**Сделано — фича 3 (вложения), ветка `feat/attachments` (запушена в origin, НЕ смержена в main):**
- Не писали с нуля — забрали из открытых апстрим-PR через cherry-pick:
  `issue_attachment_download` (PR #33) + `issue_add_attachment` (PR #34).
- PR отрезаны от базы 0.7.1 → cherry-pick только фичевых коммитов; конфликты (обе правки трогали
  `custom/client.py`, `caching/client.py`, `proto/issues.py`, `issue_write.py`, тесты, CHANGELOG)
  разрешены по принципу «оставить оба метода».
- Проверка зелёная: `uv run pytest` — **582 passed**, `mypy` чист, `ruff check`/`ruff format` чисто.
- Нюанс истории: `docs/IMPROVEMENT-PLAN.md` случайно попал в коммит #34 (`1d65017`) — косметика, на
  работу не влияет; при желании можно вынести отдельным коммитом.

**Сделано — фича 5 (поиск по нефильтруемому локальному полю), ветка `feat/attachments`:**
- Обнаружено на живой задаче (открытые тикеты Oldos в SUP): `issues_find`/`issues_count` с
  `SUP.organization: "Oldos"` падают 422 `Фильтр organization не существует` — подтверждено прямым
  curl к API, это ограничение самого Трекера (поле «Организация»/«Клиент» не зарегистрировано как
  фильтр), а не баг обёртки. Патчить синтаксис бесполезно.
- Добавлен tool `issues_find_by_local_field(queue, field_key, values, extra_query?, max_pages=50)` —
  резолвит id локального поля через `queues_get_local_fields`, постранично гоняет `issues_find` и
  сравнивает значение поля на стороне клиента (`issue.model_extra`, `extra="allow"` уже в `Issue`).
  Возвращает `{matches, pages_scanned, truncated}`. Read-only, под `check_queue_access`/
  `TRACKER_LIMIT_QUEUES`. Типы — `IssueLocalFieldMatch`/`IssuesByLocalFieldResult` (MCP-only, не
  сущности Трекера, по образцу `DownloadedIssueAttachment`).
- 6 новых тестов (`TestIssuesFindByLocalField`) + запись в `READ_ONLY_TOOL_NAMES`. Всего **621
  тестов зелёные** (было 613), mypy/ruff чисто. Проверено на живом Трекере (реальный TrackerClient,
  без mock) — нашёл все открытые тикеты Oldos в SUP, совпало с ручной выгрузкой.
- README/README_ru/manifest/CHANGELOG обновлены.

**Что дальше (по убыванию приоритета):**
1. Решить с Игорем: подключать форк в живой Claude Desktop сейчас (ради вложений + нового поиска)
   или после всех фич. Подключение — см. раздел «Выбранный формат», п.3 (правка
   `claude_desktop_config.json` + рестарт).
2. Смержить `feat/attachments` → `main` форка (тогда фичи копятся на main, конфиг смотрит на `@main`).
3. Писать оставшиеся фичи (в апстриме и открытых PR их нет): **1. доски/спринты**, **2. bulk**,
   **4. чек-листы на запись**. Начинать с фичи 1 (самая изолированная — новый протокол `boards.py`).

**Как проверять** (из репозитория): `uv sync` → `uv run pytest` / `task test`; типы+формат — `task check`.
Чеклист добавления тула и правила тестов — в репозиторном `CLAUDE.md`.

---

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

### 3. Вложения: скачивание/загрузка (read + write) — ✅ ГОТОВО (ветка feat/attachments, из PR #33/#34)
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

1. ~~Форк + клон + upstream-remote, локальный запуск из исходников (`uv run`).~~ ✅ сделано.
2. ~~Фича 3 (вложения) — download + upload.~~ ✅ забрана из PR #33/#34 (ветка feat/attachments).
3. Фича 1 (доски/спринты) — самая изолированная, новый протокол → отработать паттерн расширения.
4. Фича 4 (чек-листы write) — маленькая, в существующем issue-слое.
5. Фича 2 (bulk) — асинхронные операции + poll статуса.
6. Тесты, README-правки, переключение конфига на форк, PR-ы в апстрим.
