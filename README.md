# codegenerator

`codegenerator` — внешний генератор production-кода, тестов и repair-артефактов для `codecollector`.

Проект принимает структурированный JSON-запрос, собирает prompt по шаблонам, вызывает модель через Ollama-compatible endpoint и возвращает нормализованный JSON-результат. `codegenerator` не индексирует проект, не выбирает target, не применяет patch и не запускает проверки проекта. Эти задачи выполняет `codecollector`.

## Назначение

`codegenerator` используется как отдельный слой генерации между orchestration-слоем `codecollector` и LLM.

Основной сценарий работы:

1. `codecollector` индексирует проект и выбирает target.
2. `codecollector` собирает `project_context`, `reference_context` и request.
3. `codecollector` вызывает CLI `codegenerator`.
4. `codegenerator` собирает prompt, вызывает модель и нормализует ответ.
5. `codegenerator` возвращает `GenerationResult`.
6. `codecollector` применяет артефакт, запускает проверки и определяет итоговый статус run.

## Границы ответственности

### Что делает codegenerator

- Загружает `GenerationRequest` или `RepairRequest`.
- Применяет runtime budget strategy.
- Собирает prompt для выбранного режима.
- Вызывает LLM через Ollama-compatible endpoint.
- Парсит raw-ответ модели.
- Нормализует `code_artifact` или `test_artifact`.
- Возвращает единый `GenerationResult`.
- Сохраняет trace, prompt, raw output и usage-метрики.

### Что не делает codegenerator

- Не индексирует проект.
- Не выбирает target.
- Не строит граф связей проекта.
- Не применяет patch.
- Не применяет `import_changes` к файлам.
- Не запускает `compileall`, `pytest`, `ruff` или другие проверки проекта.
- Не определяет финальный статус run.
- Не выполняет project-level semantic validation.

Project-level verification и orchestration repair остаются ответственностью `codecollector`.

## Поддерживаемые режимы

### generate

Режим генерации production-кода.

```bash
python -m codegenerator generate \
  --request-file /path/to/generation_request.json \
  --config /path/to/config.yaml
```

Обычно возвращает заполненный `code_artifact` и пустой `test_artifact`.

### generate-test

Режим генерации тестового файла.

```bash
python -m codegenerator generate-test \
  --request-file /path/to/generation_test_request.json \
  --config /path/to/config.yaml
```

Обычно возвращает заполненный `test_artifact` и пустой `code_artifact`.

Если в request передан `generated_code_artifact`, тест строится по сгенерированному production-коду, а не по исходной версии target.

### repair

Режим исправления ранее сгенерированного артефакта после ошибки генерации, применения или проверки.

```bash
python -m codegenerator repair \
  --request-file /path/to/repair_request.json \
  --config /path/to/config.yaml
```

Repair возвращает результат в том же формате `GenerationResult`.

## Входные данные

### GenerationRequest

`GenerationRequest` используется в режимах `generate` и `generate-test`.

Ключевые поля:

- `request_id` — идентификатор запроса;
- `mode` — режим работы;
- `change_request` — исходное пользовательское требование;
- `target` — выбранный target и операция;
- `project_context` — проектный контекст;
- `reference_context` — справочные артефакты;
- `generated_code_artifact` — ранее сгенерированный production-код для режима `generate-test`;
- `options` — дополнительные опции.

Пример запроса для добавления метода в класс:

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
    "recommended_tests": [],
    "related_symbols": [],
    "allowed_api_surface": {},
    "contract_context": {
      "related_symbols": [],
      "previous_changes": []
    }
  },
  "reference_context": {
    "reference_artifacts": []
  },
  "generated_code_artifact": null,
  "options": {}
}
```

### RepairRequest

`RepairRequest` используется в режиме `repair`.

Ключевые поля:

- `request_id`;
- `mode`;
- `previous_generation_request_id`;
- `change_request`;
- `target`;
- `error_context`;
- `previous_artifact`;
- `project_context`;
- `reference_context`;
- `options`.

Пример:

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

Поле `target` в `RepairRequest` является частью текущего контракта. Оно сохраняет operation, insert scope и parent class между generation и repair.

## Project context

`project_context` — основной источник проектной информации для prompt-а.

Типичные блоки:

- `module_outline` — краткая структура модуля;
- `full_file_source` — полный исходник target-файла, если он передан;
- `target_symbol` — исходный target или anchor;
- `parent_symbol` — родительский symbol, если есть;
- `class_members` — методы и поля класса;
- `related_tests` — связанные тесты;
- `recommended_tests` — рекомендуемые тесты;
- `related_symbols` — связанные production symbols;
- `contract_context` — связанные production-контракты;
- `allowed_api_surface` — компактный список разрешенных вызовов.

### allowed_api_surface

`allowed_api_surface` — компактная, консервативная поверхность разрешенных вызовов. Она помогает planner, coder и repair не придумывать методы зависимостей.

Пример:

```json
{
  "dependencies": [
    {
      "access_path": "self.service",
      "type_name": "TicketService",
      "source": "target_or_parent_init",
      "allowed_methods": [
        {
          "name": "assign_ticket",
          "signature": "def assign_ticket(self, ticket_id: str, agent_name: str) -> str:",
          "qualname": "support_app.services.ticket_service.TicketService.assign_ticket"
        }
      ],
      "origin_examples": [
        {
          "access_path": "self.service",
          "method": "assign_ticket",
          "example": "self.service.assign_ticket",
          "line": "19"
        }
      ]
    }
  ],
  "free_functions": [
    {
      "name": "build_agent_summary",
      "signature": "def build_agent_summary(agent_name: str, tickets: list[Ticket]) -> AgentSummary:",
      "qualname": "support_app.services.report_service.build_agent_summary",
      "origin_qualname": "support_app.api.controllers.TicketController.agent_summary_endpoint"
    }
  ]
}
```

Правила использования:

- если `Allowed API Surface` передан, методы зависимостей должны совпадать с ним по `access_path` и имени метода;
- нельзя заменять отсутствующий метод похожим именем;
- нельзя придумывать широкий метод получения всех сущностей, если он не виден в surface;
- если видимый production-контракт требует аргумент, новый symbol должен принять этот аргумент явно или получить его из видимого контекста.

### contract_context

`contract_context` содержит связанные production symbols, выбранные `codecollector`.

Обычно включает:

- `qualname`;
- `file_path`;
- `module_name`;
- `name`;
- `kind`;
- `signature`;
- `docstring`;
- `source_excerpt`;
- relation metadata;
- `origin_qualname`.

`contract_context` считается частью фактического проектного контекста. Его сигнатуры, import path и source excerpts используются как источник истины для вызовов соседних компонентов.

## Выходной результат

Все режимы возвращают `GenerationResult`.

Поля:

- `request_id`;
- `status`;
- `code_artifact`;
- `test_artifact`;
- `planner_result`;
- `test_planner_result`;
- `warnings`;
- `trace_path`;
- `llm_usage`;
- `error_type`;
- `message`.

### CodeArtifact

`code_artifact` описывает production-изменение.

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

`import_changes` описывает imports, которые должен применить `codecollector`.

Поддерживаемые формы:

```json
{
  "action": "add_from_import",
  "module": "pathlib",
  "names": ["Path"]
}
```

```json
{
  "action": "add_import",
  "module": "json"
}
```

Правила:

- imports не добавляются внутрь `code_artifact.code`;
- если новое имя используется в теле функции, type annotation, default value, decorator, context manager или helper call, оно должно быть отражено в `import_changes`;
- `from __future__ import annotations` не является причиной пропускать import для явно использованного annotation type;
- если imports не нужны, `import_changes` должен быть пустым массивом.

### TestArtifact

`test_artifact` содержит новый тестовый файл.

```json
{
  "file_path": "tests/test_generated_generate_test_TicketRepository.py",
  "source_code": "..."
}
```

Все imports теста включаются прямо в `source_code`. `import_changes` для test artifact не используется.

## Операции

### replace_symbol

Заменяет существующий symbol.

Правила:

- `code` содержит полный обновленный код существующего symbol;
- внешний контракт не меняется без явного требования;
- `insert_scope` не применяется;
- `import_changes` можно вернуть, если реализация требует imports.

### insert_after_symbol + module_body

Добавляет top-level function или class после anchor.

Правила:

- `code` содержит только новый top-level symbol;
- `code` начинается с `def`, `async def` или `class`;
- `insert_after` указывает anchor;
- imports идут в `import_changes`, не в `code`.

### insert_after_symbol + class_body

Добавляет метод в существующий class.

Правила:

- `code` содержит только новый метод;
- `code` начинается с `def` или `async def`;
- не возвращается class целиком;
- `parent_qualname` указывает родительский class;
- `expected_new_symbol_kind` обычно равен `method`;
- imports идут в `import_changes`, не в `code`.

## Planner

Planner готовит промежуточный план для generation-режима.

Ожидаемые поля:

- `status`;
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

`explicit_requirements` содержит только требования, которые прямо следуют из пользовательского запроса.

`preserve_literals` содержит только значения, буквально написанные пользователем в `title`, `description` или `constraints`.

Нельзя добавлять в `preserve_literals` фрагменты старого кода, target source, related tests, planner wording или reference artifacts, если пользователь не написал эти значения явно.

## Repair planner

Repair planner подготавливает короткий план исправления перед repair-кодером.

Ожидаемые поля:

- `status`;
- `repair_objective`;
- `allowed_calls_to_use`;
- `forbidden_calls`;
- `required_changes`;
- `reason`.

Рекомендуемая формулировка строгой схемы для prompt-а:

```text
JSON должен содержать только следующие ключи верхнего уровня: "status", "repair_objective", "allowed_calls_to_use", "forbidden_calls", "required_changes", "reason". Все эти ключи обязательны. Не добавляй другие ключи, не переименовывай ключи, не переводи имена ключей, не добавляй пробелы в начале или конце имени ключа, не используй похожие или сокращенные варианты. Имя каждого ключа должно совпадать с указанным списком посимвольно.
```

Repair planner должен возвращать `repairable`, если ошибочный широкий сценарий можно заменить безопасным параметризованным видимым контрактом. `not_repairable` возвращается только если исправление требует нового production contract, нового dependency method, нового import path или несуществующего поля результата.

## Prompt assembly

Prompt assembly должен быть объяснимым по trace.

Общие правила:

- prompt templates пишутся на русском языке;
- шаблоны лежат в `prompts/`;
- большие части prompt не зашиваются в Python-код;
- JSON-примеры внутри templates экранируются как `{{` и `}}`, потому что используется Python `.format(...)`;
- reference artifacts используются только как дополнительный ориентир;
- contract context и allowed API surface имеют приоритет над reference artifacts.

### Приоритеты coder prompt

Coder должен опираться на контекст в таком порядке:

1. пользовательский запрос;
2. `explicit_requirements`;
3. `preserve_literals`;
4. `planner_json`;
5. target symbol и project context;
6. allowed API surface;
7. contract context;
8. related tests;
9. reference artifacts.

Если `planner_json` противоречит `Allowed API Surface`, production contracts или видимым полям результата, coder должен следовать проектному контексту и правилам безопасности.

### Приоритеты test prompt

Test generator должен опираться на контекст в таком порядке:

1. `generated_code_artifact`;
2. target source;
3. пользовательский запрос и `explicit_requirements`;
4. related tests;
5. contract context;
6. full file source;
7. reference artifacts.

Если `insert_scope=class_body`, тест импортирует parent class, создает экземпляр и вызывает метод через экземпляр.

Если fake/stub объект передается в target-код или production contract, fake/stub должен реализовать поля, которые target или contract source явно читает. Если в request передан `contract_attribute_requirements`, этот блок считается обязательным источником полей для test data.

## Generate-test

`generate-test` создает новый pytest-файл.

Правила:

- все imports находятся внутри `test_artifact.source_code`;
- related tests определяют стиль тестов;
- contract context задает production-сигнатуры и import path;
- `contract_attribute_requirements` задает поля, которые должны быть доступны на fake/stub или project model objects, передаваемых в production contract;
- тест не должен закреплять вызов production symbol с меньшим числом обязательных аргументов;
- optional pytest plugin fixtures не используются;
- `pytest` импортируется только если реально используется;
- тест не проверяет anchor вместо нового symbol;
- тест не должен придумывать поля, сигнатуры, зависимости и expected values.

Пример:

```python
from pathlib import Path

from support_app.storage.ticket_repository import TicketRepository


def test_export_ticket_ids_writes_ids_one_per_line(tmp_path: Path) -> None:
    repository = TicketRepository()
    export_path = tmp_path / "ticket_ids.txt"

    repository.export_ticket_ids(export_path)

    assert export_path.exists()
```

## Budget strategy

Есть два уровня budget.

### Общий лимит режима

Раздел `prompt_budget`:

- `generate_chars_limit`;
- `generate_test_chars_limit`;
- `repair_chars_limit`;
- `min_user_prompt_chars`;
- `user_prompt_reserve_chars`.

### Внутренние лимиты сборки

Разделы `generation` и `prompt_assembly`:

- `coder_prompt_target_chars`;
- `coder_prompt_hard_limit`;
- `coder_max_full_file_chars`;
- `coder_max_reference_chars`;
- `coder_max_contract_symbols`;
- `coder_max_contract_symbol_chars`;
- `repair_max_contract_symbols`;
- `repair_max_contract_symbol_chars`;
- `test_prompt_contract_symbols`;
- `test_prompt_contract_symbol_chars`;
- `test_prompt_reference_chars`;
- `prompt_assembly.generate_block_chars.contract_attribute_requirements`;
- `test_planner_full_file_chars`;
- `test_planner_related_tests_chars`;
- `test_planner_related_tests_per_item_chars`.

Если общий лимит увеличен, но внутренние лимиты остаются низкими, важный контекст всё равно может быть урезан.

Trace показывает, какие блоки сохранены, какие урезаны и какой итоговый prompt size.

## Trace и диагностика

Trace должен позволять восстановить:

- request;
- prompt;
- raw response;
- parsed response;
- usage;
- context metrics;
- trim steps;
- ошибки parsing или normalization.

При разборе качества генерации важно смотреть не только итоговый JSON, но и фактический prompt, который получила модель.

## Текущие проблемы и направления развития

Текущие ограничения:

- primary coder иногда строит широкий сценарий получения всех сущностей, даже если `Allowed API Surface` такого метода не содержит;
- repair planner может ошибаться в схеме JSON-ответа, если prompt недостаточно строго задает ключи;
- repair может исправлять ошибку частично, если planner предлагает не тот безопасный контракт;
- generate-test чувствителен к полноте related tests, full file source и contract context;
- target selection выполняет `codecollector`, поэтому качество генерации зависит от корректного выбора target до вызова `codegenerator`.

Ближайшие направления улучшения:

- сделать `Allowed API Surface` обязательным и защищенным блоком planner/coder prompt;
- валидировать `repair_planner_result` по строгой схеме до вызова repair coder;
- предотвращать передачу в coder planner-инструкций, которые содержат неразрешенные dependency methods;
- уменьшить влияние reference artifacts на планирование production-кода;
- улучшить генерацию тестов через явное описание атрибутов, которые production-контракт читает у fake/stub объектов;
- анализировать trace перед каждым изменением prompt или budget.

## Структура проекта

- `config.yaml` — конфигурация моделей, budget, prompt templates и trace;
- `prompts/` — шаблоны prompt-ов;
- `codegenerator/models/` — request/result/artifact модели;
- `codegenerator/orchestration/` — режимы `generate`, `generate-test`, `repair`;
- `codegenerator/prompts/` — загрузка и сборка prompt;
- `codegenerator/generation/` — parsing и normalization результатов;
- `codegenerator/llm/` — клиент Ollama-compatible endpoint;
- `runs/` — trace-файлы вызовов модели.

## Что не нужно делать

- Не подгонять prompt под один demo-case.
- Не переносить project semantics validation из `codecollector` в `codegenerator`.
- Не добавлять проектно-зависимые константы в Python-код.
- Не добавлять import-строки внутрь `code_artifact.code`.
- Не менять JSON-контракт без обновления интеграции и документации.
- Не увеличивать budget только ради одной локальной ошибки, если проблему можно решить более точной структурой request или prompt.

## Итог

`codegenerator` — слой генерации и нормализации LLM-ответа. Проект должен оставаться предсказуемым, объяснимым по trace и отделенным от поиска, применения patch и проверки проекта, которые выполняет `codecollector`.



### Repair и contract attribute requirements

Repair prompt получает тот же структурный контекст, что и generation, включая `allowed_api_surface`, `contract_context` и при наличии `contract_attribute_requirements`. Блок `contract_attribute_requirements` используется только как дополнительная подсказка о видимых полях моделей и contract-source reads; repair не должен придумывать новые поля или alias-имена.

