# Инструкции для агента: репозиторий codegenerator

## Назначение проекта

`codegenerator` — внешний генератор production-кода, тестов и repair-артефактов для `codecollector`.

Он принимает структурированный request, собирает prompt из переданного контекста, вызывает LLM через Ollama-compatible endpoint и возвращает нормализованный JSON-результат.

Поддерживаемые режимы:

- `generate` — генерация production-кода;
- `generate-test` — генерация тестового файла;
- `repair` — исправление ранее сгенерированного артефакта.

`codegenerator` не выбирает target, не применяет patch и не запускает проверки проекта. Это делает `codecollector`.

## Границы ответственности

### Делает codegenerator

- Загружает `GenerationRequest` и `RepairRequest`.
- Применяет runtime budget strategy.
- Собирает prompt из переданного context.
- Вызывает LLM.
- Парсит и нормализует ответ модели.
- Возвращает `GenerationResult`.
- Пишет trace и usage-метрики.

### Не делает codegenerator

- Не индексирует проект.
- Не выбирает target.
- Не строит граф связей проекта.
- Не применяет patch.
- Не применяет `import_changes`.
- Не запускает `compileall`, `pytest`, `ruff` или другие проверки проекта.
- Не определяет финальный статус run.
- Не выполняет project-level semantic validation.

Не переносить эти обязанности из `codecollector` в `codegenerator` без явной архитектурной причины.

## Основные файлы

- `config.yaml` — конфигурация моделей, prompt templates, trace и budget.
- `prompts/` — шаблоны prompt-ов.
- `codegenerator/models/` — модели request, result и artifact.
- `codegenerator/orchestration/` — реализация режимов `generate`, `generate-test`, `repair`.
- `codegenerator/prompts/` — сборка prompt.
- `codegenerator/generation/` — parsing и normalization результатов.
- `codegenerator/llm/` — клиент Ollama-compatible endpoint.
- `runs/` — trace-файлы вызовов модели.

## JSON-контракт

Сохраняй стабильный JSON-контракт CLI.

### GenerationRequest

Используется в `generate` и `generate-test`.

Важные поля:

- `request_id`;
- `mode`;
- `change_request`;
- `target`;
- `project_context`;
- `reference_context`;
- `generated_code_artifact`;
- `options`.

### RepairRequest

Используется в `repair`.

Важные поля:

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

Поле `target` в `RepairRequest` поддерживается и должно оставаться совместимым.

### GenerationResult

Во всех режимах возвращается единый формат:

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

## CodeArtifact

`code_artifact` описывает production-изменение.

Ключевые поля:

- `operation`;
- `target_qualname`;
- `target_file`;
- `code`;
- `insert_after`;
- `insert_scope`;
- `expected_new_symbol_kind`;
- `parent_qualname`;
- `import_changes`.

### import_changes

`import_changes` — часть production artifact.

LLM должна возвращать imports в `import_changes`, если generated code использует новые внешние имена.

Не добавляй import-строки внутрь `code_artifact.code`.

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

Если имя используется в type annotation, default value, decorator, context manager, helper call или теле функции, оно требует import, если его нет в target-файле.

`from __future__ import annotations` не является причиной пропускать import для явно использованного annotation type.

## Поддерживаемые операции

### replace_symbol

Правила:

- вернуть полный обновленный код существующего symbol;
- не менять внешний контракт без явного требования;
- не применять `insert_scope`;
- вернуть `import_changes`, если новые imports нужны.

### insert_after_symbol + module_body

Правила:

- вернуть только новый top-level function или class;
- `code` начинается с `def`, `async def` или `class`;
- `insert_after` указывает anchor qualname;
- imports идут в `import_changes`.

### insert_after_symbol + class_body

Правила:

- вернуть только новый метод класса `parent_qualname`;
- `code` начинается с `def` или `async def`;
- не возвращать class целиком;
- не менять anchor-symbol;
- imports идут в `import_changes`.

## Project context

### allowed_api_surface

`allowed_api_surface` — компактный список разрешенных вызовов.

Правила:

- если `Allowed API Surface` передан, методы зависимостей должны совпадать с ним по `access_path` и имени метода;
- нельзя придумывать похожие методы;
- нельзя придумывать методы получения всех сущностей, если они не видны в surface;
- если production contract требует аргумент, новый symbol должен принять этот аргумент явно или получить его из видимого контекста.

### contract_context

`contract_context` содержит связанные production-контракты: сигнатуры, import path, source excerpts и relation metadata.

Этот блок является частью фактического проектного контекста. Его нельзя трактовать как справочный пример с низким приоритетом.

## Prompt templates

Prompt templates должны быть на русском языке и описывать текущий контракт.

Правила:

- не добавлять инструкции под один demo-case;
- не хранить проектные знания в шаблонах;
- не дублировать длинные правила без необходимости;
- не зашивать большие части prompt в Python-код;
- изменяемые инструкции должны жить в `prompts/`;
- JSON-примеры в шаблонах нужно экранировать как `{{` и `}}`.

### Приоритеты coder prompt

Coder prompt должен следовать такому приоритету:

1. исходный пользовательский запрос;
2. `explicit_requirements`;
3. `preserve_literals`;
4. `planner_json`;
5. target и project context;
6. `Allowed API Surface`;
7. `contract_context`;
8. related tests;
9. reference artifacts.

Если `planner_json` противоречит `Allowed API Surface`, production contracts или видимым полям результата, coder должен следовать проектному контексту и правилам безопасности.

### explicit_requirements

`explicit_requirements` — только требования, которые прямо следуют из пользовательского запроса.

Пример:

```json
[
  "Метод должен называться export_ticket_ids",
  "Метод должен принимать параметр path: Path",
  "Метод должен записывать id всех тикетов в файл path",
  "По одному id на строку"
]
```

### preserve_literals

`preserve_literals` — только значения, буквально написанные пользователем.

Нельзя добавлять в `preserve_literals` фрагменты старого кода, target source, related tests, planner wording или reference artifacts, если пользователь не написал эти значения явно.

## Generate-test

`generate-test` создает новый тестовый файл.

Правила:

- все imports теста включаются прямо в `test_artifact.source_code`;
- `generated_code_artifact` является основным источником нового production-кода;
- related tests являются основным источником стиля тестов проекта;
- full file source и imports target-файла помогают не придумывать сигнатуры;
- reference artifacts используются только как дополнительный контекст;
- если `insert_scope=class_body`, тест импортирует parent class и вызывает method через экземпляр;
- test prompt не должен строить тест вокруг anchor вместо нового symbol;
- fake/stub должен реализовывать поля, которые target или production contract source явно читает;
- expected values в assert должны следовать из target source и явно заданных тестовых данных.

Не добавлять `import_changes` для нового test file в текущем основном сценарии.

## Repair

`repair` исправляет previous artifact после ошибки.

Правила:

- repair получает `error_context` и `previous_artifact`;
- repair сохраняет operation, insert scope и parent class;
- repair не должен менять смысл пользовательского запроса;
- repair возвращает результат в формате `GenerationResult`.

### repair planner

Repair planner должен возвращать JSON со строгой схемой:

- `status`;
- `repair_objective`;
- `allowed_calls_to_use`;
- `forbidden_calls`;
- `required_changes`;
- `reason`.

Рекомендуемая формулировка для шаблона:

```text
JSON должен содержать только следующие ключи верхнего уровня: "status", "repair_objective", "allowed_calls_to_use", "forbidden_calls", "required_changes", "reason". Все эти ключи обязательны. Не добавляй другие ключи, не переименовывай ключи, не переводи имена ключей, не добавляй пробелы в начале или конце имени ключа, не используй похожие или сокращенные варианты. Имя каждого ключа должно совпадать с указанным списком посимвольно.
```

Если меняется структура `RepairRequest`, обновляй модели request, README и AGENTS.

## Budget strategy

Есть два уровня ограничений.

### Общий лимит режима

Раздел `prompt_budget`:

- `generate_chars_limit`;
- `generate_test_chars_limit`;
- `repair_chars_limit`.

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
- `test_prompt_reference_chars`;
- `test_prompt_contract_symbols`;
- `test_prompt_contract_symbol_chars`;
- `test_planner_full_file_chars`;
- `test_planner_related_tests_chars`;
- `test_planner_related_tests_per_item_chars`.

Если меняешь лимит, проверь trace: какие блоки сохранены, какие урезаны, какой итоговый prompt size.

Не увеличивай лимиты только ради одной локальной ошибки, если проблему можно решить более точным prompt или структурой request.

## Trace и логирование

Trace должен помогать понять, что реально произошло.

В trace важны:

- request;
- prompt;
- raw output;
- parsed output;
- usage;
- context metrics;
- trim steps;
- `import_changes_count`;
- ошибки parsing/normalization.

При разборе качества генерации проверяй не только итоговый JSON, но и фактические prompt blocks, вошедшие в trace.

## Текущие проблемы и направления дальнейших изменений

Текущие проблемы:

- primary coder может строить широкий сценарий получения всех сущностей, даже если `Allowed API Surface` такого метода не содержит;
- planner иногда переносит в `explicit_requirements` элементы, которые не были явно указаны пользователем;
- repair planner чувствителен к строгой схеме JSON и может вернуть ошибочные имена ключей, если prompt недостаточно точен;
- repair может исправить ошибку частично, если planner предлагает не тот безопасный контракт;
- generate-test чувствителен к полноте `related_tests`, `full_file_source` и `contract_context`;
- выбор target выполняет `codecollector`, поэтому качество генерации зависит от качества анализа и target selection.

Направления дальнейших изменений:

- сделать `Allowed API Surface` обязательным и защищенным блоком planner/coder prompt;
- валидировать `repair_planner_result` по строгой схеме до вызова repair coder;
- предотвращать передачу в coder planner-инструкций с неразрешенными dependency methods;
- уменьшить влияние reference artifacts на планирование production-кода;
- улучшить генерацию тестов через явное описание атрибутов, которые production-контракт читает у fake/stub объектов;
- анализировать trace перед каждым изменением prompt или budget.

## Правила изменения проекта

Перед правкой:

1. Определи, меняешь prompt, normalization, request model или orchestration.
2. Проверь, не относится ли задача к `codecollector`.
3. Не переноси в `codegenerator` проверку project semantics.
4. Не добавляй скрытые special cases.
5. Не ломай CLI-контракт.

После правки:

1. Проверь `py_compile` измененных Python-файлов.
2. Проверь хотя бы один `generate` или `generate-test` trace.
3. Проверь, что prompt templates не содержат неэкранированные JSON-фигурные скобки.
4. Обнови README, если изменилась структура request/result, prompt assembly, budget или trace.

## Что не делать

- Не подгонять prompt под один конкретный пример.
- Не добавлять project-specific константы в код.
- Не дублировать одну тему в нескольких местах.
- Не добавлять imports в `code_artifact.code`.
- Не заставлять `codegenerator` применять patch или запускать pytest.
- Не менять формат JSON без обновления интеграции с `codecollector`.

## Практический ориентир

Хорошая правка в `codegenerator`:

- улучшает воспроизводимость результата;
- объяснима по trace;
- не ломает CLI и JSON-контракт;
- не смешивает ответственность `codegenerator` и `codecollector`;
- не ухудшает другие режимы ради одного случая.
