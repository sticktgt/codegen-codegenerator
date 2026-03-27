# codegenerator

`codegenerator` — отдельный проект для генерации Python-кода, генерации тестов и точечного `repair` по уже подготовленному структурированному запросу.

Проект используется как внешний генератор артефактов. Он получает request в JSON или YAML, вызывает локальные LLM через Ollama, разбирает ответ модели, нормализует результат и возвращает его в машиночитаемом виде.

## Текущая реализация

`codegenerator` выполняет следующие задачи:

1. принимает структурированный request из JSON или YAML;
2. строит prompt для planner, coder, test generator или repair;
3. вызывает соответствующую модель через Ollama;
4. разбирает raw-ответ модели;
5. нормализует операции и артефакты;
6. возвращает единый `GenerationResult`;
7. сохраняет trace, raw output и метаданные вызова.

## Основные режимы работы

### `generate`

Режим для генерации production-кода.

Последовательность:

1. загрузка `GenerationRequest`;
2. построение planner prompt;
3. вызов planner model;
4. построение coder prompt;
5. вызов coder model;
6. разбор ответа в `code_artifact`;
7. нормализация операции;
8. возврат `GenerationResult`.

Результат режима:

- ожидается `code_artifact`;
- `test_artifact` обычно отсутствует.

### `generate-test`

Режим для генерации теста для выбранного target.

Последовательность:

1. загрузка `GenerationRequest`;
2. построение planner prompt;
3. вызов planner model;
4. построение prompt для test generation;
5. вызов `test_generator_model`;
6. разбор ответа в `test_artifact`;
7. возврат `GenerationResult`.

Результат режима:

- `code_artifact = null`;
- возвращается только `test_artifact`.

### `repair`

Режим для исправления ранее полученного `code_artifact`.

`repair` используется при ошибках применения, ошибках проверок и других сценариях, когда уже есть артефакт, который нужно исправить.

Последовательность:

1. загрузка `RepairRequest`;
2. построение repair prompt;
3. вызов repair model;
4. разбор ответа;
5. возврат исправленного результата или структурированной ошибки.

## CLI

### Генерация production-кода

```bash
python -m codegenerator generate --request-file <request_file> --config <config_path>
```

### Генерация теста

```bash
python -m codegenerator generate-test --request-file <request_file> --config <config_path>
```

### Repair

```bash
python -m codegenerator repair --request-file <request_file> --config <config_path>
```

Формат request определяется по расширению файла:

- `.json` — JSON;
- `.yaml` и `.yml` — YAML.

Результат всех команд выводится в stdout в формате JSON.

## Входной контракт `GenerationRequest`

`GenerationRequest` используется для режимов `generate` и `generate-test`.

Структура:

```json
{
  "request_id": "generate-build_priority_label",
  "mode": "generate",
  "change_request": {
    "title": "...",
    "description": "...",
    "constraints": ["..."],
    "notes": ["..."]
  },
  "target": {
    "qualname": "support_app.services.report_service.build_priority_label",
    "file_path": "support_app/services/report_service.py",
    "operation": "replace_symbol"
  },
  "project_context": {
    "module_outline": [],
    "full_file_source": "",
    "target_symbol": {},
    "related_tests": [],
    "recommended_tests": []
  },
  "reference_context": {
    "reference_summary": {},
    "reference_artifacts": []
  },
  "generated_code_artifact": {},
  "options": {},
  "context_metrics": {}
}
```

### Поля `GenerationRequest`

#### `request_id`
Уникальный идентификатор запуска.

#### `mode`
Режим вызова:

- `generate`
- `generate_test`

#### `change_request`
Описание изменения.

Поля:

- `title` — короткий заголовок изменения;
- `description` — подробное описание требуемого поведения;
- `constraints` — ограничения;
- `notes` — дополнительные замечания.

#### `target`
Описание символа, который должен быть изменен.

Поля:

- `qualname`;
- `file_path`;
- `operation`.

#### `project_context`
Контекст по проекту.

Поля:

- `module_outline` — краткий список соседних символов модуля;
- `full_file_source` — полный исходник файла, если он включен;
- `target_symbol` — target со source-кодом;
- `related_tests` — связанные тесты;
- `recommended_tests` — рекомендуемые тесты.

#### `reference_context`
Контекст из reference library.

Поля:

- `reference_summary`;
- `reference_artifacts`.

#### `generated_code_artifact`
Дополнительное поле для связанных сценариев генерации.

#### `options`
Опции генерации.

#### `context_metrics`
Метрики размера request и его частей.

## Входной контракт `RepairRequest`

`RepairRequest` используется только для режима `repair`.

Структура:

```json
{
  "request_id": "repair-build_priority_label",
  "mode": "repair",
  "previous_generation_request_id": "generate-build_priority_label",
  "change_request": {
    "title": "...",
    "description": "...",
    "constraints": ["..."],
    "notes": ["..."]
  },
  "error_context": {
    "type": "apply_error",
    "summary": "...",
    "verification_summary": {}
  },
  "previous_artifact": {},
  "project_context": {},
  "reference_context": {},
  "options": {}
}
```

### Поля `RepairRequest`

- `request_id` — идентификатор repair-запуска;
- `mode` — всегда `repair`;
- `previous_generation_request_id` — идентификатор исходного запуска;
- `change_request` — исходный запрос на изменение;
- `error_context` — описание ошибки;
- `previous_artifact` — предыдущий артефакт;
- `project_context` — контекст проекта;
- `reference_context` — reference-контекст;
- `options` — дополнительные параметры.

## Выходной контракт `GenerationResult`

На выходе `codegenerator` возвращает JSON следующего вида:

```json
{
  "request_id": "generate-build_priority_label",
  "status": "ok",
  "code_artifact": {},
  "test_artifact": null,
  "planner_result": {},
  "warnings": [],
  "trace_path": "runs/...json",
  "error_type": null,
  "message": null
}
```

Поля результата:

- `request_id` — идентификатор запуска;
- `status` — итоговый статус;
- `code_artifact` — production-артефакт;
- `test_artifact` — тестовый артефакт;
- `planner_result` — промежуточный результат planner;
- `warnings` — предупреждения;
- `trace_path` — путь к trace-файлу;
- `error_type` — тип ошибки;
- `message` — текст сообщения.

## Канонические операции

Во внешнем контракте используются symbol-level операции:

- `replace_symbol`
- `add_symbol`
- `insert_after_symbol`

### `replace_symbol`
Заменяет существующий symbol целиком.

### `add_symbol`
Добавляет новый symbol в файл.

### `insert_after_symbol`
Вставляет новый symbol после уже существующего symbol.

### Нормализация операций

Если модель возвращает варианты вроде:

- `replace_function`
- `replace_method`
- `insert_after_function`

они нормализуются внутри `codegenerator` к каноническим операциям symbol-level контракта.

## Контекст, который использует `codegenerator`

`codegenerator` не занимается поиском по проекту. Он работает только с тем структурированным контекстом, который уже подготовил `codecollector`, и затем дополнительно сокращает его до допустимого prompt budget.

### Контекст для `generate`

В prompt могут входить:

- `change_request.title`;
- `change_request.description`;
- `constraints`;
- `target.qualname`;
- `target.file_path`;
- `target.operation`;
- `module_outline`;
- `target_symbol.source`;
- `target_symbol.docstring`;
- `related_tests`;
- reference artifacts;
- default constraints из конфигурации.

### Контекст для `generate-test`

В prompt для генерации теста могут входить:

- `change_request`;
- `constraints`;
- `target`;
- `target_symbol.source`;
- planner result;
- `module_outline`;
- `related_tests`;
- reference artifacts;
- example test block из prompt templates.

### Контекст для `repair`

В repair prompt могут входить:

- исходный `change_request`;
- `constraints`;
- `previous_artifact.code`;
- error summary;
- target source;
- project context в компактной форме;
- compact reference context.

## Конфигурация

Основной конфиг хранится в `config.yaml`.

### `llm.ollama`
Определяет параметры вызова Ollama:

- `base_url`;
- `timeout_sec`;
- `think`;
- `temperature`;
- `num_ctx`;
- `num_predict`;
- `keep_alive`;
- `options.*`.

### `codegenerator.prompts`
Пути к prompt templates:

- `system_rules`;
- `planner_user_template`;
- `coder_user_template`;
- `repair_user_template`;
- `test_generator_user_template`;
- `test_generator_example`.

### `codegenerator.models`
Модели для разных шагов:

- `planner_model`;
- `coder_model`;
- `test_generator_model`;
- `repair_model`.

### `codegenerator.generation`
Runtime-параметры генерации:

- `repair_enabled`;
- `max_repair_attempts`;
- `test_generation_mode`;
- `test_generator_max_example_tests`;
- лимиты budget для prompt trimming.

### `codegenerator.defaults`
Default constraints, которые добавляются к request.

### `codegenerator.trace`
Настройки trace и логирования:

- `save_to_file`;
- `show_prompts`;
- `show_raw_llm_output`;
- `output_dir`.

## Переопределение конфигурации через environment variables

`config.py`:

- читает `config.yaml`;
- переопределяет существующие значения через переменные окружения с префиксом проекта;
- позволяет добавлять новые ключи через env без изменения самого загрузчика.

Примеры:

- `RS__LLM__OLLAMA__BASE_URL=http://127.0.0.1:11434`
- `RS__CODEGENERATOR__MODELS__CODER_MODEL=qwen2.5-coder:14b-instruct-q4_K_M`
- `RS__CODEGENERATOR__TRACE__OUTPUT_DIR=runs`

## Структура проекта

### `config.yaml`
Основная конфигурация проекта.

### `prompts/`
Промпты и шаблоны для planner, coder, test generation и repair.

### `runs/`
Логи и trace-файлы запусков генерации.

### `examples/`
Примеры request-файлов для запуска.

## Взаимодействие с `codecollector`

`codegenerator` не ищет место изменения в проекте и не индексирует кодовую базу. Он получает уже подготовленный request, выполняет генерацию или repair и возвращает структурированный результат.

В текущей связке:

1. `codecollector` подготавливает `GenerationRequest` или `RepairRequest`;
2. `codecollector` вызывает CLI `codegenerator`;
3. `codegenerator` возвращает `GenerationResult` в JSON;
4. `codecollector` применяет результат и запускает проверки.

## Плановые изменения и следующие шаги

Возможные направления дальнейшего развития:

- расширение поддержки языков;
- перенос внешнего вызова с CLI на API с сохранением JSON-контракта;
- более детальный учет метрик вызовов моделей;
- развитие prompt budget и trace-метрик.
