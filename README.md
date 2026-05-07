# codegenerator

`codegenerator` — внешний генератор кода, тестов и repair-артефактов для `codecollector`. Он принимает структурированный request, собирает prompt, вызывает модель через Ollama-compatible endpoint и возвращает нормализованный JSON-результат.

`codegenerator` не индексирует проект, не выбирает target, не применяет patch и не запускает проверки проекта. Эти задачи выполняет `codecollector`.

---

## Назначение

Проект нужен как отдельный слой генерации между orchestration-слоем `codecollector` и LLM.

`codegenerator` выполняет следующие действия:

1. Загружает `GenerationRequest` или `RepairRequest` из JSON/YAML-файла.
2. Применяет runtime budget strategy.
3. Собирает prompt для режима `generate`, `generate-test` или `repair`.
4. Вызывает модель через Ollama-compatible endpoint.
5. Разбирает ответ модели.
6. Нормализует `code_artifact` или `test_artifact`.
7. Возвращает единый `GenerationResult`.
8. Сохраняет trace, prompt, raw response и usage-метрики.

---

## Роль в связке с codecollector

Текущий рабочий сценарий:

1. `codecollector` индексирует проект и выбирает target.
2. `codecollector` собирает project context и reference context.
3. `codecollector` формирует `GenerationRequest` или `RepairRequest`.
4. `codecollector` вызывает CLI `codegenerator`.
5. `codegenerator` собирает prompt и вызывает LLM.
6. `codegenerator` возвращает JSON-результат.
7. `codecollector` применяет `code_artifact`, запускает validation и определяет итоговый статус run.

### Ответственность codecollector

`codecollector` отвечает за:

- индекс проекта;
- поиск и выбор target;
- сбор project context;
- подбор reference artifacts;
- формирование request для генерации;
- применение patch;
- применение `import_changes` к production-файлам;
- runtime verification;
- repair orchestration;
- итоговый статус run.

### Ответственность codegenerator

`codegenerator` отвечает за:

- runtime budget strategy;
- prompt assembly;
- вызов LLM;
- parsing raw-ответа;
- normalization результата;
- возврат `GenerationResult`;
- trace и usage-метрики.

---

## Поддерживаемые режимы

### generate

Режим генерации production-кода.

Команда:

```bash
python -m codegenerator generate \
  --request-file /path/to/generation_request.json \
  --config /path/to/config.yaml
```

Результат:

- `code_artifact` заполнен;
- `test_artifact` обычно равен `null`.

### generate-test

Режим генерации тестового файла.

Команда:

```bash
python -m codegenerator generate-test \
  --request-file /path/to/generation_test_request.json \
  --config /path/to/config.yaml
```

Результат:

- `code_artifact` равен `null`;
- `test_artifact` заполнен.

Если в request передан `generated_code_artifact`, тест строится по сгенерированному production-коду, а не по исходной версии target.

### repair

Режим исправления ранее сгенерированного артефакта.

Команда:

```bash
python -m codegenerator repair \
  --request-file /path/to/repair_request.json \
  --config /path/to/config.yaml
```

Результат repair должен оставаться в общем формате `GenerationResult`.

---

## Входные данные

## GenerationRequest

`GenerationRequest` используется для режимов `generate` и `generate-test`.

Пример для `replace_symbol`:

```json
{
  "request_id": "generate-build_assignment_message",
  "mode": "generate",
  "change_request": {
    "title": "Изменить текст уведомления о назначении тикета",
    "description": "Сделать уведомление полностью на русском языке: Тикет <id> успешно назначен сотруднику <agent_name>.",
    "constraints": ["Не менять внешний контракт API"],
    "notes": []
  },
  "target": {
    "qualname": "support_app.services.notification_service.build_assignment_message",
    "file_path": "support_app/services/notification_service.py",
    "operation": "replace_symbol",
    "insert_scope": null,
    "expected_new_symbol_kind": "",
    "parent_qualname": ""
  },
  "project_context": {
    "module_outline": [],
    "full_file_source": "",
    "target_symbol": {},
    "related_tests": [],
    "recommended_tests": []
  },
  "reference_context": {
    "reference_artifacts": []
  },
  "generated_code_artifact": null,
  "options": {}
}
```

Пример для добавления метода в класс:

```json
{
  "request_id": "generate-TicketRepository",
  "mode": "generate",
  "change_request": {
    "title": "Добавить метод экспорта id тикетов",
    "description": "Добавить в класс TicketRepository метод export_ticket_ids(self, path: Path), который записывает id всех тикетов в файл path, по одному id на строку",
    "constraints": [],
    "notes": []
  },
  "target": {
    "qualname": "support_app.storage.ticket_repository.TicketRepository",
    "file_path": "support_app/storage/ticket_repository.py",
    "operation": "insert_after_symbol",
    "insert_scope": "class_body",
    "expected_new_symbol_kind": "method",
    "parent_qualname": "support_app.storage.ticket_repository.TicketRepository"
  },
  "project_context": {
    "module_outline": [],
    "full_file_source": "...",
    "target_symbol": {},
    "parent_symbol": {},
    "class_members": [],
    "related_tests": [],
    "recommended_tests": []
  },
  "reference_context": {
    "reference_artifacts": []
  },
  "generated_code_artifact": null,
  "options": {}
}
```

## RepairRequest

`RepairRequest` используется только для режима `repair`.

Типовая структура:

```json
{
  "request_id": "repair-TicketRepository",
  "mode": "repair",
  "previous_generation_request_id": "generate-TicketRepository",
  "change_request": {
    "title": "Добавить метод экспорта id тикетов",
    "description": "Добавить в класс TicketRepository метод export_ticket_ids(self, path: Path), который записывает id всех тикетов в файл path, по одному id на строку",
    "constraints": [],
    "notes": []
  },
  "target": {
    "qualname": "support_app.storage.ticket_repository.TicketRepository",
    "file_path": "support_app/storage/ticket_repository.py",
    "operation": "insert_after_symbol",
    "insert_scope": "class_body",
    "expected_new_symbol_kind": "method",
    "parent_qualname": "support_app.storage.ticket_repository.TicketRepository"
  },
  "error_context": {
    "type": "verification_failed",
    "summary": "Verification failed after apply",
    "verification_summary": {}
  },
  "previous_artifact": {},
  "project_context": {},
  "reference_context": {},
  "options": {}
}
```

`target` в `RepairRequest` является допустимым полем. Оно используется для сохранения operation, insert scope и parent class между обычной генерацией и repair.

---

## Выходной результат

Все режимы возвращают JSON с общей структурой `GenerationResult`.

Основные поля:

- `request_id` — идентификатор запуска;
- `status` — `ok` или `error`;
- `code_artifact` — production artifact;
- `test_artifact` — test artifact;
- `planner_result` — результат planner-а для production-кода;
- `test_planner_result` — результат planner-а для теста;
- `warnings` — предупреждения генератора;
- `trace_path` — путь к trace-файлу;
- `llm_usage` — usage-метрики;
- `error_type` — тип ошибки, если есть;
- `message` — сообщение ошибки, если есть.

## CodeArtifact

`code_artifact` содержит production-код и метаданные применения.

Основные поля:

```json
{
  "operation": "replace_symbol | insert_after_symbol",
  "target_qualname": "string",
  "target_file": "string",
  "code": "string",
  "insert_after": "string | null",
  "insert_scope": "module_body | class_body | null",
  "expected_new_symbol_kind": "function | class | method | string",
  "parent_qualname": "string",
  "import_changes": []
}
```

### import_changes

`import_changes` — часть `code_artifact`. Пользователь не задает отдельную import-операцию. LLM возвращает import changes вместе с реализацией, потому что нужные imports зависят от выбранного кода.

Поддерживаемый минимальный формат:

```json
{
  "action": "add_from_import",
  "module": "pathlib",
  "names": ["Path"]
}
```

Также поддерживается форма:

```json
{
  "action": "add_import",
  "module": "json"
}
```

Правила для production-кода:

- import-строки не должны попадать внутрь поля `code`;
- если новый или измененный код использует имя из внешнего модуля, нужно вернуть его в `import_changes`;
- это относится к именам в теле функции, type annotations, default values, decorators, context managers и helper calls;
- `from __future__ import annotations` не является причиной пропускать import для явно использованного annotation type;
- если imports не нужны, `import_changes` должен быть пустым массивом.

Пример `code_artifact` с import:

```json
{
  "operation": "insert_after_symbol",
  "target_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "target_file": "support_app/storage/ticket_repository.py",
  "insert_after": "support_app.storage.ticket_repository.TicketRepository",
  "insert_scope": "class_body",
  "expected_new_symbol_kind": "method",
  "parent_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "code": "def export_ticket_ids(self, path: Path) -> None:\n    path.write_text(...)\n",
  "import_changes": [
    {
      "action": "add_from_import",
      "module": "pathlib",
      "names": ["Path"]
    }
  ]
}
```

`codecollector` применяет `import_changes` к production-файлу и показывает результат в обычном diff.

## TestArtifact

`test_artifact` обычно содержит новый тестовый файл:

```json
{
  "file_path": "tests/test_generated_generate_test_TicketRepository.py",
  "source_code": "..."
}
```

Для нового test file все imports включаются прямо в `source_code`. `import_changes` для test artifact не используется в текущем основном сценарии.

---

## Поддерживаемые операции

## replace_symbol

`replace_symbol` заменяет существующий symbol.

Правила:

- `code` должен содержать полный обновленный код существующего symbol;
- внешний контракт нельзя менять без явного требования;
- `insert_scope` для этой операции не применяется и должен быть пустым или `null`;
- `import_changes` можно использовать, если новая реализация требует imports.

Пример результата:

```json
{
  "operation": "replace_symbol",
  "target_qualname": "support_app.services.notification_service.build_assignment_message",
  "target_file": "support_app/services/notification_service.py",
  "code": "def build_assignment_message(ticket: Ticket, agent_name: str) -> str:\n    ...",
  "insert_after": null,
  "insert_scope": null,
  "expected_new_symbol_kind": "",
  "parent_qualname": "",
  "import_changes": []
}
```

## insert_after_symbol

`insert_after_symbol` добавляет новый symbol после anchor.

### module_body

`module_body` используется для top-level function или class.

Правила:

- `code` должен содержать только новый top-level symbol;
- `code` должен начинаться с `def`, `async def` или `class`;
- `insert_after` должен указывать anchor symbol;
- импорт-строки должны идти в `import_changes`, а не в `code`.

Пример:

```json
{
  "operation": "insert_after_symbol",
  "target_qualname": "support_app.services.notification_service.build_assignment_message",
  "target_file": "support_app/services/notification_service.py",
  "insert_after": "support_app.services.notification_service.build_assignment_message",
  "insert_scope": "module_body",
  "expected_new_symbol_kind": "function",
  "parent_qualname": "",
  "code": "def format_ticket_label(ticket_id: str) -> str:\n    return f\"Ticket {ticket_id}\"",
  "import_changes": []
}
```

### class_body

`class_body` используется для добавления метода в существующий класс.

Правила:

- `code` должен содержать только новый метод;
- `code` должен начинаться с `def` или `async def`;
- внешний отступ класса можно не добавлять;
- `parent_qualname` должен указывать класс;
- `expected_new_symbol_kind` обычно равен `method`;
- `code` не должен содержать class целиком;
- import-строки должны идти в `import_changes`.

Пример:

```json
{
  "operation": "insert_after_symbol",
  "target_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "target_file": "support_app/storage/ticket_repository.py",
  "insert_after": "support_app.storage.ticket_repository.TicketRepository",
  "insert_scope": "class_body",
  "expected_new_symbol_kind": "method",
  "parent_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "code": "def export_ticket_ids(self, path: Path) -> None:\n    ...",
  "import_changes": [
    {
      "action": "add_from_import",
      "module": "pathlib",
      "names": ["Path"]
    }
  ]
}
```

---

## Planner result

`planner_result` — промежуточный план generation-режима. Он помогает coder prompt сохранить пользовательское намерение.

Основные поля:

- `operation`;
- `target_file`;
- `target_symbol`;
- `intent_summary`;
- `constraints`;
- `reference_symbol`;
- `insert_scope`;
- `expected_new_symbol_kind`;
- `parent_qualname`;
- `explicit_requirements`;
- `preserve_literals`.

### explicit_requirements

`explicit_requirements` содержит только требования, которые прямо следуют из пользовательского запроса:

- что нужно создать или изменить;
- явно указанные имена symbols;
- сигнатуры;
- параметры;
- ожидаемые строки результата;
- явно заданное поведение.

Пример:

```json
"explicit_requirements": [
  "Метод должен называться export_ticket_ids",
  "Метод должен принимать параметр path: Path",
  "Метод должен записывать id всех тикетов в файл path",
  "Один id на строку"
]
```

### preserve_literals

`preserve_literals` содержит только значения, буквально написанные пользователем в title, description или constraints.

В это поле можно включать:

- имена symbols;
- сигнатуры;
- параметры;
- форматы строк;
- строки результата;
- другие литералы, которые нельзя переименовывать или переинтерпретировать.

Нельзя добавлять в `preserve_literals` фрагменты старого кода, target source, related tests, planner wording или reference artifacts, если пользователь не написал эти значения явно.

Если пользователь просит изменить текст, строку, формат или поведение, старое значение из текущего кода не должно попадать в `preserve_literals`.

---

## Prompt assembly

Prompt assembly должен оставаться простым и объяснимым.

Основные правила:

- prompt templates пишутся на русском языке;
- пользовательский запрос имеет приоритет над reference artifacts;
- `explicit_requirements` и `preserve_literals` должны быть видны coder-у и test-generator-у;
- reference artifacts используются как вторичный источник стиля и паттернов;
- длинные правила не должны дублироваться без необходимости;
- template-текст хранится в `prompts/`, а не зашивается в Python-код;
- примеры JSON внутри template должны экранировать фигурные скобки как `{{` и `}}`, потому что шаблоны рендерятся через Python `.format(...)`.

## Приоритеты coder prompt

Coder prompt должен опираться на контекст в таком порядке:

1. исходный пользовательский запрос;
2. `explicit_requirements`;
3. `preserve_literals`;
4. `planner_json`;
5. target symbol и project context;
6. related tests;
7. reference artifacts.

Reference artifacts не имеют приоритета над явно указанными именами, сигнатурами и литералами из пользовательского запроса.

## Приоритеты test prompt

Test prompt должен опираться на контекст в таком порядке:

1. `generated_code_artifact`, если он передан;
2. target symbol и фактический измененный код;
3. `explicit_requirements` и пользовательский запрос;
4. related tests;
5. full file source;
6. reference artifacts;
7. example test source как fallback.

Если `operation=insert_after_symbol`, `target_symbol` в test prompt должен указывать новый symbol, который нужно тестировать, а не anchor.

Если `insert_scope=class_body`, тест должен импортировать parent class, создать экземпляр и вызвать метод через экземпляр. Метод не должен импортироваться как top-level function.

---

## Budget strategy

В `codegenerator` есть два уровня ограничений prompt.

### Общий лимит режима

Задается в разделе `prompt_budget`:

- `generate_chars_limit`;
- `generate_test_chars_limit`;
- `repair_chars_limit`.

Эти значения задают общий бюджет режима с учетом system prompt и служебного резерва.

### Внутренние лимиты сборки

Задаются в разделах `generation` и `prompt_assembly`:

- `coder_prompt_target_chars`;
- `coder_prompt_hard_limit`;
- `coder_max_full_file_chars`;
- `coder_max_reference_chars`;
- `test_prompt_reference_chars`;
- `test_planner_full_file_chars`;
- `test_planner_related_tests_chars`;
- `test_planner_related_tests_per_item_chars`;
- другие лимиты отдельных блоков.

Итоговый prompt определяется сочетанием общего лимита и внутренних лимитов.

Если общий лимит режима увеличен, но внутренние лимиты остаются низкими, значимые части контекста все равно могут быть урезаны.

## Runtime trimming

При нехватке бюджета `codegenerator` может уменьшать:

- `module_outline`;
- `related_tests`;
- `full_file_source`;
- reference artifacts;
- другие контекстные блоки.

Trace показывает, какие блоки были сохранены или урезаны.

---

## Генерация тестов

Цель `generate-test` — получить полезный pytest-файл, который проверяет измененный или добавленный функционал.

Правила:

- для нового test file все imports включаются прямо в `source_code`;
- `related_tests` считаются основным источником тестового стиля проекта;
- `generated_code_artifact` используется как основной источник измененного production-кода;
- тест не должен придумывать поля, сигнатуры и зависимости;
- тест не должен проверять anchor вместо нового symbol;
- тест не должен подменять пользовательское требование поведением старого кода;
- `pytest` импортируется только если реально используется.

Пример test artifact:

```json
{
  "file_path": "tests/test_generated_generate_test_TicketRepository.py",
  "source_code": "from pathlib import Path\n\nfrom support_app.storage.ticket_repository import TicketRepository\n\n..."
}
```

---

## Repair

`repair` используется, когда артефакт нужно исправить после ошибки генерации, применения или проверки.

Repair request содержит:

- исходный change request;
- target;
- error context;
- previous artifact;
- project context;
- reference context;
- options.

Repair должен:

- исправлять предыдущий артефакт;
- сохранять operation и insert scope;
- сохранять смысл пользовательского запроса;
- не изобретать новый сценарий изменения;
- возвращать результат в том же общем формате `GenerationResult`.

---

## Конфигурация

Основной файл конфигурации — `config.yaml`.

Ключевые разделы:

### llm.ollama

Параметры Ollama-compatible endpoint:

- `base_url`;
- `api_key`;
- `timeout_sec`;
- `temperature`;
- `num_ctx`;
- `num_predict`;
- `keep_alive`.

### codegenerator.prompts

Пути к prompt templates:

- `system_rules`;
- `planner_user_template`;
- `coder_user_template`;
- `repair_user_template`;
- `test_planner_user_template`;
- `test_generator_user_template`.

### codegenerator.models

Имена моделей для:

- planner;
- coder;
- repair;
- test planner;
- test generator.

### generation

Параметры генерации, тестогенерации и repair:

- `repair_enabled`;
- `max_repair_attempts`;
- `test_generation_mode`;
- `coder_prompt_target_chars`;
- `coder_prompt_hard_limit`;
- `coder_max_reference_artifacts`;
- `coder_max_reference_chars`;
- `coder_max_full_file_chars`;
- `repair_prompt_hard_limit`;
- `repair_max_reference_chars`;
- `test_prompt_reference_chars`.

### prompt_budget

Общие лимиты режимов:

- `generate_chars_limit`;
- `generate_test_chars_limit`;
- `repair_chars_limit`;
- `min_user_prompt_chars`;
- `user_prompt_reserve_chars`.

### prompt_assembly

Внутренние лимиты отдельных блоков prompt assembly.

### trace

Настройки trace:

- сохранять ли trace;
- сохранять ли prompt;
- сохранять ли raw output;
- директория trace-файлов.

---

## Логирование и trace

Trace должен позволять восстановить:

- request;
- prompt;
- raw response;
- parsed response;
- usage-метрики;
- контекстные блоки, попавшие в prompt;
- trim log;
- ошибки parsing или normalization.

Полезные поля логов:

- режим вызова;
- `request_id`;
- модель;
- `prompt_chars`;
- `system_chars`;
- `user_chars`;
- token usage;
- duration;
- context metrics;
- trim steps;
- `import_changes_count`.

---

## Структура проекта

### `config.yaml`

Основная конфигурация проекта.

### `prompts/`

Шаблоны prompt-ов для режимов `generate`, `generate-test` и `repair`.

### `runs/`

Trace-файлы и логи вызовов модели.

### `examples/`

Примеры request-файлов.

### `codegenerator/orchestration/`

Основная логика режимов.

### `codegenerator/prompts/`

Загрузка и сборка prompt templates.

### `codegenerator/llm/`

Клиент Ollama-compatible endpoint.

### `codegenerator/generation/`

Планирование, parsing и normalization generation/test artifacts.

### `codegenerator/models/`

Модели request/result/artifact.

---

## Текущие ограничения

- Основная поддержка — Python.
- Модели вызываются через Ollama-compatible endpoint.
- Качество результата зависит от модели, prompt и входного context.
- `generate-test` чувствителен к качеству `related_tests` и `full_file_source`.
- `import_changes` применяется только к production artifact; новые test files включают imports прямо в `source_code`.
- `codegenerator` не выполняет project verification.

---

## Практические примеры

### replace_symbol

Запрос: изменить текст уведомления.

Ожидаемый production artifact:

```json
{
  "operation": "replace_symbol",
  "target_qualname": "support_app.services.notification_service.build_assignment_message",
  "target_file": "support_app/services/notification_service.py",
  "code": "def build_assignment_message(ticket: Ticket, agent_name: str) -> str:\n    return f\"Тикет {ticket.ticket_id} успешно назначен сотруднику {agent_name}.\"",
  "insert_after": null,
  "insert_scope": null,
  "expected_new_symbol_kind": "",
  "parent_qualname": "",
  "import_changes": []
}
```

### insert_after_symbol + class_body

Запрос: добавить метод в класс.

Ожидаемый production artifact:

```json
{
  "operation": "insert_after_symbol",
  "target_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "target_file": "support_app/storage/ticket_repository.py",
  "insert_after": "support_app.storage.ticket_repository.TicketRepository",
  "insert_scope": "class_body",
  "expected_new_symbol_kind": "method",
  "parent_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "code": "def format_ticket_label(self, ticket_id: str) -> str:\n    return f\"Ticket {ticket_id}\"",
  "import_changes": []
}
```

### insert_after_symbol + import_changes

Запрос: добавить метод с `Path` в сигнатуре.

Ожидаемый production artifact:

```json
{
  "operation": "insert_after_symbol",
  "target_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "target_file": "support_app/storage/ticket_repository.py",
  "insert_after": "support_app.storage.ticket_repository.TicketRepository",
  "insert_scope": "class_body",
  "expected_new_symbol_kind": "method",
  "parent_qualname": "support_app.storage.ticket_repository.TicketRepository",
  "code": "def export_ticket_ids(self, path: Path) -> None:\n    ...",
  "import_changes": [
    {
      "action": "add_from_import",
      "module": "pathlib",
      "names": ["Path"]
    }
  ]
}
```

### generate-test

Если production artifact добавил `TicketRepository.export_ticket_ids`, тест должен импортировать `TicketRepository`, создать экземпляр и вызвать метод через экземпляр:

```python
from pathlib import Path

from support_app.storage.ticket_repository import TicketRepository


def test_export_ticket_ids_writes_ids_one_per_line(tmp_path: Path) -> None:
    repository = TicketRepository()
    export_path = tmp_path / "ticket_ids.txt"

    repository.export_ticket_ids(export_path)

    assert export_path.exists()
```

---

## Что не нужно делать

- Не подгонять prompt под один demo-case.
- Не переносить проектные знания из `codecollector` в `codegenerator`.
- Не усложнять budget strategy ради одной локальной ошибки.
- Не хранить проектно-зависимые константы в Python-коде, если они могут прийти через request или config.
- Не дублировать одну и ту же инструкцию в нескольких prompt templates без необходимости.
- Не добавлять import-строки внутрь `code_artifact.code`.
- Не менять JSON-контракт без синхронного обновления документации и интеграции с `codecollector`.

---

## Итог

`codegenerator` — внешний генератор кода, тестов и repair-артефактов. Он работает с уже подготовленным request, управляет prompt budget, вызывает LLM, нормализует результат и возвращает стабильный JSON. Проект должен оставаться предсказуемым, объяснимым по trace и независимым от логики поиска, применения patch и проверки проекта. 
