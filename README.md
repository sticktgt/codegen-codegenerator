# codegenerator

`codegenerator` — внешний слой генерации для `codecollector`. Проект принимает структурированный JSON-запрос, собирает промпт по шаблонам, вызывает модель через Ollama-compatible endpoint, разбирает ответ модели и возвращает нормализованный JSON-результат.

`codegenerator` не индексирует проект, не выбирает target, не применяет patch и не запускает проверки проекта. Эти задачи выполняет `codecollector`.

## Назначение

`codegenerator` используется как отдельный слой между orchestration-слоем `codecollector` и LLM.

Основной сценарий работы:

1. `codecollector` индексирует проект, выбирает target и собирает проектный контекст.
2. `codecollector` формирует structured request и вызывает CLI `codegenerator`.
3. `codegenerator` собирает промпт по шаблонам, вызывает модель и нормализует ответ.
4. `codegenerator` возвращает результат в JSON-формате.
5. `codecollector` применяет результат в staging workspace, запускает проверки, выполняет repair при необходимости и определяет итоговый статус run.

## Границы ответственности

### Что делает codegenerator

- Загружает `GenerationRequest`, `RepairRequest` или request для advisory review.
- Применяет runtime budget strategy.
- Собирает промпт для выбранного режима.
- Вызывает LLM через Ollama-compatible endpoint.
- Парсит raw-ответ модели.
- Нормализует `code_artifact`, `test_artifact` или review result.
- Возвращает JSON-результат.
- Сохраняет trace, prompt, raw output и usage-метрики.

### Что не делает codegenerator

- Не индексирует проект.
- Не выбирает target.
- Не строит граф связей проекта.
- Не применяет patch.
- Не применяет `import_changes` к файлам.
- Не запускает `compileall`, `pytest`, `ruff` или другие проверки проекта.
- Не определяет финальный статус pipeline run.
- Не выполняет project-level semantic validation.

Project-level verification, orchestration repair и принятие решения остаются ответственностью `codecollector` и пользователя.

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

Режим генерации pytest-файла.

```bash
python -m codegenerator generate-test \
  --request-file /path/to/generation_test_request.json \
  --config /path/to/config.yaml
```

Обычно возвращает заполненный `test_artifact` и пустой `code_artifact`.

Если в request передан `generated_code_artifact`, тест строится по сгенерированному production-коду, а не по старой версии target. Старый `full_file_source` используется только как справочный контекст для импортов, стиля, окружающего кода и ранее существовавшего публичного поведения.

### repair

Режим исправления ранее сгенерированного артефакта после ошибки генерации, применения или проверки.

```bash
python -m codegenerator repair \
  --request-file /path/to/repair_request.json \
  --config /path/to/config.yaml
```

Repair возвращает результат в формате `GenerationResult`.

### review-generated-test-failure

Режим advisory review для случая, когда production-код прошел базовые проверки, но сгенерированный тест не прошел verification.

```bash
python -m codegenerator review-generated-test-failure \
  --request-file /path/to/generated_test_review_request.json \
  --config /path/to/config.yaml
```

Режим анализирует компактный контекст от `codecollector` и возвращает JSON-рекомендацию для человека. Он не изменяет код, не запускает repair и не принимает окончательное решение.

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
    },
    "required_contracts": [],
    "required_class_members": [],
    "model_surfaces": []
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

Поле `target` сохраняет operation, insert scope и parent class между generation и repair.

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

### Generated test failure review request

Request для `review-generated-test-failure` формируется `codecollector` и содержит компактный контекст:

- исходный CR;
- target;
- production artifact;
- production diff;
- generated test artifact;
- failed verification blocks;
- issues;
- фрагменты stdout/stderr;
- advisory warnings, например `possible_existing_method_contract_lost`.

Этот request не должен содержать весь context pack, большие related source excerpts и reference artifacts без необходимости.

## Project context

`project_context` — основной источник проектной информации для промпта.

Типичные блоки:

- `module_outline` — краткая структура модуля;
- `full_file_source` — исходник target-файла, если он передан;
- `target_symbol` — исходный target или anchor;
- `parent_symbol` — родительский symbol, если есть;
- `class_members` — методы и поля класса;
- `related_tests` — связанные тесты;
- `recommended_tests` — рекомендуемые тесты;
- `related_symbols` — связанные production symbols;
- `contract_context` — связанные production-контракты;
- `allowed_api_surface` — компактный список разрешенных вызовов;
- `required_contracts` — обязательные production-контракты;
- `required_class_members` — обязательные public members класса при замене класса;
- `model_surfaces` — видимые поля и аргументы конструкторов моделей.

### allowed_api_surface

`allowed_api_surface` — компактная и консервативная поверхность разрешенных вызовов. Она помогает planner, coder и repair не придумывать методы зависимостей.

Правила использования:

- если `allowed_api_surface` передан, методы зависимостей должны совпадать с ним по `access_path` и имени метода;
- нельзя заменять отсутствующий метод похожим именем;
- нельзя придумывать широкий метод получения всех сущностей, если он не виден в surface;
- если видимый production-контракт требует аргумент, новый symbol должен принять этот аргумент явно или получить его из видимого контекста.

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

### Обязательные production-контракты

Если в request передан блок `required_contracts`, planner, coder и repair prompt считают его обязательным structural constraint. Generated production code должен вызвать перечисленные production-контракты и не должен заменять их ручной реализацией бизнес-логики в API/adapter-слое.

Этот блок не является источником новых contracts: он только фиксирует contracts, уже выбранные `codecollector` из видимого project context и `allowed_api_surface`.

### Обязательные члены класса

Если в request передан блок `required_class_members`, planner, coder и repair prompt считают его обязательным structural constraint для `replace_symbol` класса.

Generated class должен сохранить все members с `required=true`. Если существующий метод содержит заглушку или `NotImplementedError`, его нужно реализовать, а не удалять из класса.

Этот блок формируется `codecollector` из текущего public surface класса и не является просьбой добавить новые методы.

### Поверхности моделей

Если в request передан блок `model_surfaces`, planner, coder, repair и generate-test prompt считают его источником допустимых полей и аргументов конструктора для видимых project models.

Генератор не должен использовать похожие alias-поля, если их нет в `fields` или `constructor_fields`.

Пример: для модели с полем `topic` нельзя использовать `title`, если `title` не указан в `model_surfaces`.

### Contract attribute requirements

Если в request передан блок `contract_attribute_requirements`, generate-test prompt использует его как обязательный источник полей, которые должны быть доступны на fake/stub или project model objects, передаваемых в production contract.

Если используется реальная project model, test generator должен передавать только видимые `constructor_fields`. Если требуемое поле не является constructor field, его нужно задать после создания объекта или использовать локальный fake/stub.

## Выходной результат

Все режимы генерации и repair возвращают `GenerationResult`.

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

### Review result

`review-generated-test-failure` возвращает JSON с advisory-рекомендацией.

Основные поля:

- `verdict`;
- `confidence`;
- `production_code_quality`;
- `generated_test_quality`;
- `should_keep_production_code`;
- `recommended_action`;
- `reasons`;
- `production_risks`;
- `test_issues`.

Допустимые значения `verdict`:

- `production_likely_ok_test_likely_bad`;
- `production_likely_bad_test_valid`;
- `both_uncertain`;
- `environment_or_import_issue`;
- `insufficient_context`.

Review является advisory. Он не меняет код и не принимает решение за пользователя.

## Операции

### replace_symbol

Заменяет существующий symbol.

Правила:

- `code` содержит полный обновленный код существующего symbol;
- внешний контракт не меняется без явного требования;
- `insert_scope` не применяется;
- `import_changes` можно вернуть, если реализация требует imports.

Если target symbol является классом:

- `code` должен содержать полное новое определение этого же класса;
- нельзя возвращать только top-level helper-functions, свободные функции или отдельные методы;
- имя класса, публичные поля и существующие публичные методы сохраняются, если пользователь явно не просит переименовать или удалить их;
- новое поведение модели или класса добавляется внутрь класса, если пользователь явно не попросил вынести его в свободные функции.

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

Для `replace_symbol` class-target planner должен планировать замену самого класса, а не добавление внешних helper-функций вместо методов класса.

## Coder

Coder генерирует production artifact.

Он должен:

- соблюдать operation;
- соблюдать insert scope;
- не менять anchor;
- возвращать imports через `import_changes`;
- использовать только видимые dependency methods;
- не подставлять фиктивные literals вместо обязательных аргументов;
- если возвращает dict из результата production-контракта, использовать только видимые поля результата;
- если target является class и operation=`replace_symbol`, вернуть полное определение класса;
- не заменять class-target набором свободных функций, если пользователь явно не попросил свободные функции.

## Repair planner

Repair planner подготавливает короткий план исправления перед repair-кодером.

Ожидаемые поля:

- `status`;
- `repair_objective`;
- `allowed_calls_to_use`;
- `forbidden_calls`;
- `required_changes`;
- `reason`.

Рекомендуемая формулировка строгой схемы для промпта:

```text
JSON должен содержать только следующие ключи верхнего уровня: "status", "repair_objective", "allowed_calls_to_use", "forbidden_calls", "required_changes", "reason". Все эти ключи обязательны. Не добавляй другие ключи, не переименовывай ключи, не переводи имена ключей, не добавляй пробелы в начале или конце имени ключа, не используй похожие или сокращенные варианты. Имя каждого ключа должно совпадать с указанным списком посимвольно.
```

Repair planner должен возвращать `repairable`, если ошибочный широкий сценарий можно заменить безопасным параметризованным видимым контрактом. `not_repairable` возвращается только если исправление требует нового production contract, нового dependency method, нового import path или несуществующего поля результата.

## Repair

Repair получает previous artifact и error context.

Он должен:

- исправлять previous artifact;
- не генерировать новый сценарий с нуля;
- сохранять operation и insert scope;
- не заменять недоступный широкий сценарий другим широким методом;
- использовать видимый параметризованный контракт;
- возвращать результат в формате `GenerationResult`;
- если repair исправляет class-target, результат должен оставаться полным определением класса;
- если previous artifact вернул внешние функции вместо class-target, repair должен исправить это на полное определение класса.

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

Если передан `generated_code_artifact`:

- именно он является главным источником истины для теста;
- старый `full_file_source` используется как справочный контекст для импортов, стиля, окружающего кода и старых публичных контрактов;
- если `generated_code_artifact` и старый `full_file_source` противоречат друг другу по полям, constructor kwargs, методам или ключам dict, тест должен использовать `generated_code_artifact`.

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

## Review generated-test failure

`review-generated-test-failure` анализирует ситуацию, когда production-код прошел базовые проверки, а generated test не прошел verification.

Режим получает компактный контекст от `codecollector`:

- исходный CR;
- target;
- production artifact;
- production diff;
- generated test;
- failed verification blocks;
- issues;
- stdout/stderr excerpts;
- advisory warnings.

Режим не должен получать весь context pack, большие related source excerpts или reference artifacts без необходимости.

Review должен различать:

- generated test плохой;
- generated test валидный и нашел production regression;
- ошибка окружения или import path;
- недостаточно контекста;
- ситуация неясна.

Результат review не является автоматическим решением.

## Prompt assembly

Prompt assembly должен быть объяснимым по trace.

Общие правила:

- prompt templates пишутся на русском языке;
- шаблоны лежат в `prompts/`;
- большие части промпта не зашиваются в Python-код;
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

Если `planner_json` противоречит `allowed_api_surface`, production contracts или видимым полям результата, coder должен следовать проектному контексту и правилам безопасности.

### Приоритеты test prompt

Test generator должен опираться на контекст в таком порядке:

1. `generated_code_artifact`;
2. target source;
3. пользовательский запрос и `explicit_requirements`;
4. related tests;
5. contract context;
6. full file source;
7. reference artifacts.

Если `generated_code_artifact` и `full_file_source` противоречат друг другу, тест должен использовать `generated_code_artifact`.

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

## Текущие ограничения

- Primary coder может сгенерировать код, который требует repair.
- Repair может изменить public API шире, чем требуется запросом.
- Generate-test чувствителен к полноте и непротиворечивости контекста.
- Review generated-test failure является advisory и не заменяет решение пользователя.
- Качество результата зависит от target selection и project context, подготовленных `codecollector`.

## Структура проекта

- `config.yaml` — конфигурация моделей, budget, prompt templates и trace;
- `prompts/` — шаблоны промптов;
- `codegenerator/models/` — request/result/artifact модели;
- `codegenerator/orchestration/` — режимы `generate`, `generate-test`, `repair`, `review-generated-test-failure`;
- `codegenerator/prompts/` — загрузка и сборка промптов;
- `codegenerator/generation/` — parsing и normalization результатов;
- `codegenerator/llm/` — клиент Ollama-compatible endpoint;
- `runs/` — trace-файлы вызовов модели.

## Что не нужно делать

- Не подгонять промпт под один demo-case.
- Не переносить project semantics validation из `codecollector` в `codegenerator`.
- Не добавлять project-specific константы в Python-код.
- Не добавлять import-строки внутрь `code_artifact.code`.
- Не менять JSON-контракт без обновления интеграции и документации.
- Не увеличивать budget только ради одной локальной ошибки, если проблему можно решить более точной структурой request или prompt.

## Итог

`codegenerator` — слой генерации, repair, test generation и advisory review. Проект должен оставаться предсказуемым, объяснимым по trace и отделенным от поиска, применения patch и проверки проекта, которые выполняет `codecollector`.     .     .  # Прошу обратить внимание, что этот файл может содержать незавершённую строку из-за копирования: в конце есть лишние точки/пробелы, их нужно удалить при правке файла.     # Если нужно, я могу подготовить чистую версию README.md отдельным файлом.  
