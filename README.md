# codegenerator

`codegenerator` — отдельный узкий проект для генерации Python-кода, генерации тестов и точечного `repair` по уже подготовленному packet-контексту, который собирает `codecollector`.

Проект работает как внешний генератор артефактов: получает структурированный запрос, вызывает локальные LLM через Ollama, нормализует результат и возвращает его в машиночитаемом виде.

## Назначение

`codegenerator` принимает уже подготовленный запрос на генерацию, в котором есть:
- change request;
- выбранный target;
- контекст по коду проекта;
- reference artifacts;
- ограничения на изменение;
- runtime-опции генерации.

На выходе проект возвращает:
- `code_artifact` для production-кода;
- `test_artifact` для тестов, если вызван шаг генерации теста;
- `planner_result`;
- предупреждения;
- `trace_path` с подробным trace выполнения;
- структурированную ошибку, если генерация не удалась.

## За что отвечает проект

`codegenerator` отвечает за следующие задачи:
- принять структурированный request из JSON или YAML;
- построить prompt для planner / coder / test generator / repair;
- вызвать соответствующую модель через Ollama;
- разобрать raw-ответ модели;
- нормализовать операции и артефакты к каноническому формату;
- вернуть единый `GenerationResult`;
- сохранить trace, raw output и метаданные вызова для последующего анализа.

## Основные режимы работы

### `generate`
Шаг `generate` используется для генерации production-кода.

Последовательность:
1. загрузить `GenerationRequest`;
2. собрать planner prompt;
3. вызвать planner model;
4. собрать coder prompt;
5. вызвать coder model;
6. распарсить ответ в `code_artifact`;
7. нормализовать `operation`;
8. вернуть `GenerationResult`.

Результат этого шага:
- обязательно ожидается `code_artifact`;
- `test_artifact` обычно `null`, если тесты генерируются отдельным вызовом.

### `generate-test`
Шаг `generate-test` используется для генерации теста для уже выбранного target.

Последовательность:
1. загрузить `GenerationRequest`;
2. построить planner prompt и получить `planner_result`;
3. построить отдельный prompt для test generation;
4. вызвать `test_generator_model`;
5. распарсить ответ в `test_artifact`;
6. вернуть `GenerationResult`, где:
   - `code_artifact = null`;
   - `test_artifact` содержит новый тестовый файл.

Результат этого шага:
- возвращается только `test_artifact`;
- production-код не генерируется и не изменяется.

### `repair`
Шаг `repair` используется для исправления неудачного `code_artifact`, если предыдущая генерация:
- вернула синтаксически неверный код;
- привела к ошибке apply;
- не прошла verification, но есть артефакт, который можно исправить.

Последовательность:
1. загрузить `RepairRequest`;
2. собрать compact repair prompt;
3. вызвать repair model;
4. распарсить ответ;
5. вернуть исправленный `code_artifact` или структурированную ошибку.

## Форматы входа и выхода

## `GenerationRequest`
`GenerationRequest` — основной входной контракт для `generate` и `generate-test`.

Структура:

### `request_id: str`
Уникальный идентификатор запуска.

Пример:
```json
"request_id": "generate-build_priority_label"
```

### `mode: str`
Режим вызова:
- `generate`
- `generate_test`

### `change_request: object`
Описание бизнес-задачи.

Поля:
- `title: str` — короткий заголовок изменения;
- `description: str` — подробное описание требуемого поведения;
- `constraints: list[str]` — ограничения;
- `notes: list[str]` — дополнительные замечания.

Пример:
```json
"change_request": {
  "title": "Изменить отображение приоритета тикета",
  "description": "Сделать русскоязычную метку высокого приоритета в виде «Срочный приоритет».",
  "constraints": [
    "Не менять внешний контракт API",
    "Изменить только текст метки"
  ],
  "notes": []
}
```

### `target: object`
Описание конкретного символа, который нужно изменить.

Поля:
- `qualname: str` — полный qualname символа;
- `file_path: str` — путь к файлу;
- `operation: str` — каноническая операция.

Пример:
```json
"target": {
  "qualname": "support_app.services.report_service.build_priority_label",
  "file_path": "support_app/services/report_service.py",
  "operation": "replace_symbol"
}
```

### `project_context: object`
Контекст по самому проекту.

Поля:
- `module_outline: list[object]` — краткий список соседних символов модуля;
- `full_file_source: str` — полный исходник файла, если он был включен;
- `target_symbol: object` — основной target со source-кодом;
- `related_tests: list[object]` — найденные связанные тесты;
- `recommended_tests: list[str]` — список qualname или путей рекомендуемых тестов.

#### `module_outline`
Каждый элемент содержит:
- `qualname`
- `kind`
- `name`
- `docstring`

#### `target_symbol`
Содержит:
- `qualname`
- `name`
- `kind`
- `docstring`
- `source`
- `truncated: bool`

#### `related_tests`
Каждый элемент содержит:
- `qualname`
- `file_path`
- `source`
- `truncated: bool`

### `reference_context: object`
Контекст из reference library.

Поля:
- `reference_summary: object`
- `reference_artifacts: list[object]`

#### `reference_summary`
Содержит:
- `count`
- `titles`
- `content_modes`

#### `reference_artifacts`
Каждый reference artifact содержит:
- `artifact_id`
- `title`
- `artifact_type`
- `usage_mode`
- `content_mode`
- `why_selected`
- `source_path`
- `content`
- `selected_span`
- `truncated`

### `options: object`
Опции генерации.

Сейчас используются, например:
- `generate_test_mode`

Возможные значения:
- `never`
- `if_missing`
- `always`

### `context_metrics: object`
Метрики итогового request для контроля размера контекста.

Поля:
- `target_source_chars`
- `target_source_truncated`
- `full_file_chars`
- `full_file_included`
- `related_tests_count`
- `related_test_chars`
- `reference_artifacts_count`
- `reference_chars`
- `request_chars`
- `request_chars_limit`

Эти поля используются для логирования и анализа prompt budget.

## `RepairRequest`
`RepairRequest` используется только для `repair`.

Структура:

### `request_id: str`
Идентификатор repair-запуска.

### `mode: str`
Всегда `repair`.

### `previous_generation_request_id: str`
Идентификатор исходного generate-запроса.

### `change_request: object`
Тот же объект, что и в `GenerationRequest`.

### `error_context: object`
Описание ошибки, которая привела к repair.

Поля:
- `type`
- `summary`
- `verification_summary`

`verification_summary` обычно включает:
- `failed_checks`
- `repairable`
- `messages`
- `stage`

### `previous_artifact: object`
Сломанный или неприменимый `code_artifact`, который нужно исправить.

Поля:
- `operation`
- `target_qualname`
- `target_file`
- `code`
- `insert_after`

### `project_context: object`
Тот же project context, что используется в обычной генерации, но в компактной форме.

### `reference_context: object`
Урезанный reference context, достаточный для repair.

### `options: object`
Дополнительные runtime-опции repair.

## `GenerationResult`
Единый результат для `generate`, `generate-test` и `repair`.

Поля:
- `request_id: str`
- `status: str` — `ok` или `error`
- `code_artifact: object | null`
- `test_artifact: object | null`
- `planner_result: object | null`
- `warnings: list[str]`
- `trace_path: str | null`
- `error_type: str | null`
- `message: str | null`

### `code_artifact`
Содержит:
- `operation`
- `target_qualname`
- `target_file`
- `code`
- `insert_after`

### `test_artifact`
Содержит:
- `file_path`
- `source_code`

## Канонические операции

Во внешнем контракте используются symbol-level операции:
- `replace_symbol`
- `add_symbol`
- `insert_after_symbol`

### `replace_symbol`
Заменяет существующий symbol целиком.

Используется, когда target уже найден, и модель должна вернуть новую полную реализацию именно этого symbol.

### `add_symbol`
Добавляет новый symbol в файл.

Используется для генерации новой функции, класса или другого top-level элемента, если target еще не существует.

### `insert_after_symbol`
Вставляет новый symbol после уже существующего symbol.

Используется, когда нужно сохранить расположение кода рядом с конкретной существующей точкой.

### Нормализация операций
Если модель возвращает варианты вроде:
- `replace_function`
- `replace_method`
- `insert_after_function`

они нормализуются внутри `codegenerator` к каноническим операциям symbol-level контракта.

## Подход к формированию контекста при вызове LLM

### Общий принцип
`codegenerator` не занимается поиском по проекту. Он использует только тот packet-контекст, который уже подготовил `codecollector`, и затем дополнительно сжимает его до безопасного prompt budget для локальной модели.

Контекст формируется отдельно для трех случаев:
- `generate`
- `generate-test`
- `repair`

Во всех случаях размер проверяется до отправки запроса в LLM. Для этого используются:
- `context_metrics.request_chars`
- runtime budget из конфигурации генерации
- trimming reference artifacts и необязательных блоков

### Контекст для `generate`
В `generate` включается:
- `change_request.title`
- `change_request.description`
- `constraints`
- `target.qualname`
- `target.file_path`
- `target.operation`
- `module_outline`
- `target_symbol.source`
- `target_symbol.docstring`
- `related_tests`, если они есть
- reference artifacts
- default constraints из конфигурации

#### Что включается обязательно
- change request
- target
- target source
- planner result

#### Что включается опционально
- `full_file_source`
- `related_tests`
- reference artifacts

#### Где проверяется размер
Размер контролируется перед вызовом coder model.
Основные метрики пишутся в лог и trace:
- `prompt_chars`
- `system_chars`
- `user_chars`

#### Как обрезается контекст
Если контекст становится слишком большим:
1. по умолчанию не включается `full_file_source`;
2. reference artifacts передаются не целиком, а как snippet или trimmed content;
3. большие reference snippets укорачиваются;
4. используется краткий `module_outline`, а не полный код соседних функций.

Цель — держать coder prompt в пределах budget локальной модели.

### Контекст для `generate-test`
В `generate-test` включается:
- `change_request`
- `constraints`
- `target`
- `target_symbol.source`
- planner result
- `module_outline`
- `related_tests`, если есть
- reference artifacts
- example test block из prompt templates

#### Особенность
Этот режим не должен тащить production context тяжелее, чем нужно для генерации теста.

#### Где проверяется размер
Размер проверяется перед вызовом `test_generator_model`.
Логируются:
- `prompt_chars`
- `system_chars`
- `user_chars`

#### Как обрезается контекст
Если prompt слишком большой:
1. сохраняется target source;
2. сохраняется planner result;
3. сохраняется минимальный module outline;
4. reference context сокращается первым;
5. example test block может быть урезан или упрощен.

### Контекст для `repair`
В `repair` включается:
- исходный `change_request`
- constraints
- `previous_artifact.code`
- error summary
- target source
- planner-independent project context
- компактный reference context

#### Основной принцип repair
Repair должен исправить артефакт, не теряя requested change.

Поэтому prompt строится вокруг:
- исходного требования;
- сломанного кода;
- причины ошибки;
- компактного target context.

#### Где проверяется размер
Размер контролируется перед вызовом repair model.

#### Как обрезается контекст
В repair-контекст не включаются тяжелые необязательные блоки, если они не нужны:
- полный файл не передается по умолчанию;
- reference artifacts урезаются до минимума;
- используются только краткие блоки project context.

#### Практическое правило
Repair prompt может быть чуть больше обычного coder prompt, но должен оставаться в пределах безопасного лимита локальной модели. Для маломощных CPU-only стендов лучше держать его заметно ниже общего hard-limit `num_ctx`.

## Конфигурация

Основной конфиг хранится в `config.yaml`.

### `llm.ollama`
Определяет параметры вызова Ollama:
- `base_url`
- `timeout_sec`
- `think`
- `temperature`
- `num_ctx`
- `num_predict`
- `keep_alive`
- `options.*`

### `codegenerator.prompts`
Пути к prompt templates:
- `system_rules`
- `planner_user_template`
- `coder_user_template`
- `repair_user_template`
- `test_generator_user_template`
- `test_generator_example`

### `codegenerator.models`
Модели для разных шагов:
- `planner_model`
- `coder_model`
- `test_generator_model`
- `repair_model`

### `codegenerator.generation`
Runtime-параметры генерации:
- `repair_enabled`
- `max_repair_attempts`
- `test_generation_mode`
- `test_generator_max_example_tests`
- лимиты budget для prompt trimming

### `codegenerator.defaults`
Default constraints, которые добавляются к request.

### `codegenerator.trace`
Настройки trace и логирования:
- `save_to_file`
- `show_prompts`
- `show_raw_llm_output`
- `output_dir`

## Конфиг и environment variables

`config.py`:
- читает `config.yaml`;
- переопределяет существующие значения через переменные окружения `RS__...`;
- позволяет добавлять новые ключи через env без правки Python-кода.

Примеры:
- `RS__LLM__OLLAMA__BASE_URL=http://192.168.50.165:18081`
- `RS__CODEGENERATOR__MODELS__CODER_MODEL=qwen2.5-coder:14b-instruct-q4_K_M`
- `RS__CODEGENERATOR__TRACE__OUTPUT_DIR=runs`

## Структура проекта

```text
codegenerator/
├── api/              # CLI и service layer
├── generation/       # planner / coder / repair / test generation
├── llm/              # Ollama client и gateway
├── models/           # request/result/artifact models
├── orchestration/    # generate / repair / generate-test service
├── parsing/          # JSON parsing и normalization
├── prompts/          # prompt loader и шаблоны
├── trace/            # trace store
├── validation/       # локальные lightweight checks
├── config.py         # загрузка config + env overrides
├── logger.py         # единый логгер
└── __main__.py       # entrypoint
```

## Trace и logging

Для каждого запуска сохраняются:
- prompt-и planner/coder/test-generator/repair;
- raw response модели;
- parsed result;
- timing/meta;
- итоговый `trace_path` в результате.

В логах особенно важны:
- `prompt_chars`
- `system_chars`
- `user_chars`
- `prompt_tokens`
- `output_tokens`
- `duration`

Это позволяет тюнить prompt budget под локальные модели.

## CLI

```bash
python -m codegenerator generate --request-file examples/generation_request.json
python -m codegenerator generate-test --request-file examples/generation_request.json
python -m codegenerator repair --request-file examples/repair_request.json
```

Поддерживаются оба формата request-файлов:
- JSON
- YAML

## ADR

### ADR-001. `codegenerator` — отдельный узкий генератор
Проект отвечает за генерацию артефактов по уже подготовленному packet-контексту.

### ADR-002. `generate`, `generate-test` и `repair` — отдельные режимы
Генерация production-кода, генерация теста и repair выполняются отдельными вызовами, чтобы не перегружать локальные модели одним комбинированным запросом.

### ADR-003. Внешний контракт — symbol-level
Во внешнем контракте используются `replace_symbol`, `add_symbol`, `insert_after_symbol`.

### ADR-004. Prompt templates хранятся в файлах
Шаблоны prompt-ов не захардкоживаются в Python-коде и подгружаются из `config.yaml`.

### ADR-005. Budget-first подход для локальных моделей
Контекст должен сокращаться до безопасного budget до вызова модели. Полный контекст проекта не передается автоматически.

## Возможные следующие действия и оптимизации

Возможные следующие шаги развития:
- добавить более точный budget estimator не только по символам, но и по токенам;
- разделить reference trimming для `generate`, `generate-test` и `repair` еще агрессивнее;
- добавить отдельные prompt templates для разных типов target:
  - pure function
  - service method
  - class method
  - generated test;
- улучшить нормализацию операций и ввести более точную обработку `add_symbol` / `insert_after_symbol` сценариев;
- добавить lightweight post-parse checks для `test_artifact` до возврата результата;
- сохранять отдельные compact prompt snapshots для easier debug на CPU-only стендах;
- добавить адаптивные budgets под конкретную модель;
- добавить более строгую проверку semantic consistency между `change_request`, `planner_result` и `code_artifact`.
