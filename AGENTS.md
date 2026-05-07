# Инструкции для агента: репозиторий codegenerator

## Назначение проекта

`codegenerator` — внешний генератор для `codecollector`. Он принимает структурированный request, собирает prompt, вызывает модель через Ollama-compatible endpoint и возвращает нормализованный JSON-результат.

Поддерживаемые режимы:

- `generate` — генерация production-кода;
- `generate-test` — генерация тестового файла;
- `repair` — исправление ранее сгенерированного артефакта.

`codegenerator` не выбирает target, не применяет patch и не запускает проверки проекта. Это делает `codecollector`.

---

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
- Не выбирает target в проекте.
- Не строит граф связей проекта.
- Не применяет patch.
- Не применяет `import_changes` к файлам.
- Не запускает compile, pytest или другие проверки проекта.
- Не определяет финальный статус run.

Не переносить эти обязанности из `codecollector` в `codegenerator` без явной архитектурной причины.

---

## Основные файлы

- `config.yaml` — конфигурация моделей, prompt templates, trace и budget.
- `prompts/` — шаблоны prompt-ов.
- `codegenerator/models/` — модели request/result/artifact.
- `codegenerator/orchestration/` — реализация режимов `generate`, `generate-test`, `repair`.
- `codegenerator/prompts/` — сборка prompt.
- `codegenerator/generation/` — parsing и normalization результатов.
- `codegenerator/llm/` — клиент Ollama-compatible endpoint.
- `runs/` — trace-файлы вызовов модели.

---

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

---

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

Важно: если имя используется в type annotation, default value, decorator, context manager, helper call или теле функции, оно также требует import, если его нет в target-файле.

`from __future__ import annotations` не является причиной пропускать import для явно использованного annotation type.

---

## Поддерживаемые операции

### replace_symbol

Заменяет существующий symbol.

Правила:

- вернуть полный обновленный код symbol;
- не менять внешний контракт без явного требования;
- `insert_scope` не применяется;
- `import_changes` можно вернуть, если новая реализация требует imports.

### insert_after_symbol + module_body

Добавляет top-level function или class после anchor.

Правила:

- вернуть только новый top-level symbol;
- `code` начинается с `def`, `async def` или `class`;
- `insert_after` указывает anchor;
- imports идут в `import_changes`, не в `code`.

### insert_after_symbol + class_body

Добавляет метод в существующий class.

Правила:

- вернуть только новый метод;
- `code` начинается с `def` или `async def`;
- не возвращать class целиком;
- `parent_qualname` указывает родительский class;
- `expected_new_symbol_kind` обычно равен `method`;
- imports идут в `import_changes`, не в `code`.

---

## Prompt templates

Prompt templates должны быть на русском языке и описывать только текущий контракт.

### Общие правила

- Не добавлять инструкции под один demo-case.
- Не хранить проектные знания в шаблонах.
- Не дублировать длинные правила без необходимости.
- Не зашивать в Python-код большие части prompt.
- Все изменяемые инструкции должны жить в `prompts/`.
- JSON-примеры в шаблонах нужно экранировать как `{{` и `}}`, потому что шаблоны рендерятся через Python `.format(...)`.

### Приоритеты для coder prompt

Coder prompt должен следовать такому приоритету:

1. исходный пользовательский запрос;
2. `explicit_requirements`;
3. `preserve_literals`;
4. `planner_json`;
5. target и project context;
6. related tests;
7. reference artifacts.

Reference artifacts не имеют приоритета над явно указанными пользователем именами, сигнатурами, параметрами и форматами строк.

### explicit_requirements

`explicit_requirements` — список требований, которые прямо следуют из пользовательского запроса.

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

`preserve_literals` — только значения, буквально написанные пользователем в title, description или constraints.

Не добавлять в `preserve_literals` фрагменты старого кода, target source, related tests, planner wording или reference artifacts, если пользователь не написал эти значения явно.

Если пользователь просит изменить текст или формат, не сохранять старое значение из текущего кода как `preserve_literals`.

---

## Generate-test

`generate-test` создает новый тестовый файл.

Правила:

- все imports теста включаются прямо в `test_artifact.source_code`;
- `generated_code_artifact` является основным источником нового production-кода;
- related tests являются основным источником стиля тестов проекта;
- full file source и imports target-файла помогают не придумывать сигнатуры;
- reference artifacts используются только как дополнительный контекст;
- если `insert_scope=class_body`, тест импортирует parent class и вызывает method через экземпляр;
- test prompt не должен строить тест вокруг anchor вместо нового symbol.

Не добавлять `import_changes` для нового test file в текущем основном сценарии.

---

## Repair

`repair` исправляет предыдущий артефакт после ошибки.

Правила:

- repair получает `error_context` и `previous_artifact`;
- repair сохраняет operation, insert scope и parent class;
- repair не должен менять смысл пользовательского запроса;
- repair возвращает результат в том же формате `GenerationResult`.

Если меняется структура `RepairRequest`, обновляй `codegenerator/models/requests.py`, README и AGENTS.

---

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
- `test_prompt_reference_chars`;
- `test_planner_full_file_chars`;
- `test_planner_related_tests_chars`;
- `test_planner_related_tests_per_item_chars`.

Итоговый prompt зависит от обоих уровней. Если меняешь лимит, проверь trace: какие блоки сохранены, какие урезаны, какой итоговый prompt size.

Не увеличивай лимиты только ради одной локальной ошибки, если проблему можно решить более точным prompt или структурой request.

---

## Trace и логирование

Trace должен помогать агенту понять, что реально произошло.

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

При разборе качества генерации всегда проверяй не только итоговый JSON, но и фактические prompt blocks, вошедшие в trace.

---

## Правила изменения проекта

Перед правкой:

1. Определи, меняешь prompt, normalization, request model или orchestration.
2. Проверь, не относится ли задача к `codecollector`.
3. Не переносить в `codegenerator` проверку project semantics.
4. Не добавлять скрытые special cases.
5. Не ломать CLI-контракт.

После правки:

1. Проверить `py_compile` измененных Python-файлов.
2. Проверить хотя бы один `generate` или `generate-test` trace.
3. Проверить, что prompt templates не содержат неэкранированные JSON-фигурные скобки.
4. Обновить README, если изменилась структура request/result, prompt assembly, budget или trace.

---

## Что не делать

- Не подгонять prompt под один конкретный пример.
- Не добавлять project-specific константы в код.
- Не дублировать одну тему в нескольких местах.
- Не добавлять imports в `code_artifact.code`.
- Не заставлять `codegenerator` применять patch или запускать pytest.
- Не менять формат JSON без обновления интеграции с `codecollector`.

---

## Практический ориентир

Хорошая правка в `codegenerator`:

- улучшает воспроизводимость результата;
- объяснима по trace;
- не ломает CLI и JSON-контракт;
- не смешивает ответственность `codegenerator` и `codecollector`;
- не ухудшает другие режимы ради одного случая.
