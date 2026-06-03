# AGENTS.md для codegenerator

Этот файл предназначен для LLM-агентов и разработчиков, которые меняют код, конфигурацию, prompt-шаблоны или документацию `codegenerator`.

Документ фиксирует текущее состояние проекта и правила сопровождения.

## Роль проекта

`codegenerator` — внешний генератор production code artifacts, generated test artifacts, repair artifacts и advisory review для `codecollector`.

Проект принимает structured request, собирает prompt, вызывает модель через точку доступа, совместимую с Ollama, нормализует ответ и возвращает JSON-результат.

`codegenerator` не выбирает target, не применяет patch, не запускает project-level checks и не принимает решение о merge. Эти задачи выполняет `codecollector`.

## Границы ответственности

### `codegenerator` делает

- Загружает `GenerationRequest` и `RepairRequest`.
- Применяет runtime budget strategy.
- Собирает prompt из переданного context.
- Вызывает модель.
- Парсит raw output.
- Нормализует результат.
- Возвращает `GenerationResult`.
- Пишет trace и usage metrics.
- Выполняет advisory review generated-test failure.

### `codegenerator` не делает

- Не индексирует проект.
- Не выбирает target.
- Не строит граф связей проекта.
- Не применяет patch.
- Не применяет `import_changes`.
- Не запускает `compileall`, `pytest`, `ruff` или другие проверки проекта.
- Не определяет финальный статус run.
- Не выполняет project-level semantic validation.

Не переносить обязанности `codecollector` в `codegenerator` без явной архитектурной причины.

## Основные файлы

- `config.yaml` — конфигурация моделей, prompt templates, trace и budget.
- `prompts/` — шаблоны prompt-ов.
- `codegenerator/models/` — модели request, result и artifact.
- `codegenerator/orchestration/` — режимы `generate`, `generate-test`, `repair`, review.
- `codegenerator/prompts/` — сборка prompt.
- `codegenerator/generation/` — parsing и normalization результатов.
- `codegenerator/llm/` — клиент точки доступа модели.
- `runs/` — trace-файлы вызовов модели.

## JSON-контракт

Сохраняй стабильный JSON-контракт CLI.

### GenerationRequest

Используется в `generate` и `generate-test`.

Основные поля:

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

Основные поля:

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

Поле `target` поддерживается и должно оставаться совместимым.

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

Основные поля:

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

LLM возвращает imports в `import_changes`, если generated code использует новые внешние имена.

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

Если имя используется в annotation, default value, decorator, context manager, helper call или теле функции, оно требует import, если такого import нет в target-файле.

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

### Allowed API Surface

Allowed API Surface — компактный список разрешенных вызовов.

Правила:

- если surface передан, методы зависимостей должны совпадать с ним по `access_path` и имени метода;
- нельзя придумывать похожие методы;
- нельзя придумывать методы получения всех сущностей, если они не видны в surface;
- если production contract требует аргумент, новый symbol должен принять этот аргумент явно или получить его из видимого контекста;
- standard library не запрещается самим фактом отсутствия в Allowed API Surface.

### Contract context

`contract_context` содержит связанные production contracts: сигнатуры, import path, source excerpts и relation metadata.

Этот блок является фактическим project context. Его нельзя трактовать как reference artifact с низким приоритетом.

### Same-class methods

Same-class methods — видимые методы того же класса, что и target method.

Они используются как контекст для переиспользования существующего поведения. Они не являются обязательными, если не переданы как required contracts.

### Reuse hints

Reuse hints являются soft context. Они помогают выбрать существующую проектную логику, но не являются hard requirement.

## Prompt templates

Prompt templates должны быть на русском языке и описывать текущий контракт.

Правила:

- не добавлять инструкции под один demo-case;
- не хранить проектные знания в шаблонах;
- не дублировать длинные правила без необходимости;
- не зашивать большие части prompt в Python-код;
- изменяемые инструкции должны жить в `prompts/`;
- JSON-примеры в шаблонах нужно экранировать как `{{` и `}}`.

## Приоритеты prompt

Coder prompt следует такому приоритету:

1. исходный пользовательский запрос;
2. `explicit_requirements`;
3. `preserve_literals`;
4. `planner_json`;
5. target и project context;
6. Allowed API Surface;
7. contract context;
8. related tests;
9. reference artifacts.

Если `planner_json` противоречит Allowed API Surface, production contracts или видимым полям результата, coder следует проектному контексту и правилам безопасности.

## explicit_requirements

`explicit_requirements` содержит только требования, которые прямо следуют из пользовательского запроса.

Пример:

```json
[
  "Метод должен называться export_ticket_ids",
  "Метод должен принимать параметр path: Path",
  "Метод должен записывать id всех тикетов в файл path",
  "По одному id на строку"
]
```

## preserve_literals

`preserve_literals` содержит только значения, буквально написанные пользователем.

Нельзя добавлять в `preserve_literals` фрагменты старого кода, target source, related tests, planner wording или reference artifacts, если пользователь не написал эти значения явно.

## Generate test

`generate-test` создает новый pytest-файл.

Правила:

- все imports теста включаются прямо в `test_artifact.source_code`;
- `generated_code_artifact` является главным источником нового поведения;
- related tests используются как источник стиля, если не противоречат generated code;
- full file source и imports target-файла помогают не придумывать сигнатуры;
- reference artifacts используются как дополнительный контекст;
- тест проверяет generated target, а не anchor;
- fake/stub реализует поля и методы, которые target или production contract source явно читает или вызывает;
- expected values в assert следуют из target source, явно заданных тестовых данных и видимого контекста;
- optional pytest plugin fixtures не используются;
- `mocker` не используется;
- `import_changes` для нового test file в текущем основном сценарии не используется.

## Repair

`repair` исправляет previous artifact после ошибки.

Правила:

- repair получает `error_context` и `previous_artifact`;
- repair сохраняет operation, insert scope и parent class;
- repair не меняет смысл пользовательского запроса;
- repair использует Allowed API Surface, contract context, same-class methods и suggested replacements;
- repair не заменяет неизвестный метод другим неизвестным методом;
- repair возвращает результат в формате `GenerationResult`.

### Repair planner

Repair planner возвращает JSON со строгой схемой:

- `status`;
- `repair_objective`;
- `allowed_calls_to_use`;
- `forbidden_calls`;
- `required_changes`;
- `reason`.

JSON содержит только эти ключи верхнего уровня. Все ключи обязательны. Имена ключей не переводятся и не переименовываются.

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

Если меняешь лимит, проверь trace: какие блоки сохранены, какие сокращены, какой итоговый размер prompt.

Не увеличивай лимиты только ради одной локальной ошибки, если проблему можно решить более точной структурой request или prompt.

## Trace и логирование

Trace должен помогать понять, что реально произошло.

В trace важны:

- request;
- prompt;
- raw output;
- parsed output;
- normalized output;
- usage;
- context metrics;
- trim steps;
- `import_changes_count`;
- ошибки parsing и normalization.

При разборе качества генерации проверяй не только итоговый JSON, но и фактические prompt blocks, вошедшие в trace.

## Правила изменения проекта

Перед правкой:

1. Определи, меняешь prompt, normalization, request model или orchestration.
2. Проверь, не относится ли задача к `codecollector`.
3. Не переноси в `codegenerator` project-level semantic validation.
4. Не добавляй hidden special cases.
5. Не ломай CLI-контракт.

После правки:

1. Проверь `py_compile` измененных Python-файлов.
2. Проверь хотя бы один trace нужного режима.
3. Проверь, что prompt templates не содержат неэкранированные JSON-фигурные скобки.
4. Обнови README, если изменилась структура request/result, prompt assembly, budget или trace.

## Документация

Документация проекта должна:

- быть на русском языке;
- описывать только актуальное состояние проекта;
- не содержать changelog;
- не описывать историю изменений;
- не ссылаться на предыдущие версии;
- фиксировать фактический CLI, JSON-контракт, режимы, trace, конфигурацию и ограничения;
- быть понятной разработчику, агенту и аналитику.

## Ограничения текущего режима

- Основной поддерживаемый язык проекта — Python.
- `codegenerator` зависит от полноты контекста, переданного `codecollector`.
- `codegenerator` не выполняет project-level semantic validation.
- Generated tests проходят внешнюю semantic/relevance validation в `codecollector`.
- Reuse hints являются soft context, если они не переданы как required contracts.
- Trace показывает полный prompt, context metrics и trim steps.

## Что не делать

Не нужно:

- подгонять prompt под один конкретный пример;
- добавлять project-specific константы в код;
- дублировать одну тему в нескольких местах;
- добавлять imports в `code_artifact.code`;
- заставлять `codegenerator` применять patch;
- заставлять `codegenerator` запускать pytest;
- менять формат JSON без обновления интеграции с `codecollector`;
- переносить обязанности `codecollector` в `codegenerator`.

## Практический ориентир

Хорошая правка в `codegenerator`:

- улучшает воспроизводимость результата;
- объяснима по trace;
- не ломает CLI и JSON-контракт;
- не смешивает ответственность `codegenerator` и `codecollector`;
- не ухудшает другие режимы ради одного случая.
