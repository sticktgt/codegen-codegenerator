# codegenerator

`codegenerator` — отдельный узкий проект для генерации Python-кода и опционально тестов по готовому packet-контексту, который собирает `codecollector`.

## Назначение

Проект принимает уже подготовленный запрос на генерацию:
- change request;
- выбранный target;
- context по коду проекта;
- reference artifacts;
- ограничения на изменение.

На выходе `codegenerator` возвращает:
- `code_artifact`;
- опциональный `test_artifact`;
- trace выполнения planner/coder/repair.

## Что делает

### `generate`
Шаг `generate`:
- загружает `GenerationRequest` из JSON или YAML;
- собирает planner prompt из файловых шаблонов;
- вызывает planner model;
- собирает coder prompt;
- вызывает coder model;
- нормализует `operation` к каноническим symbol-level операциям;
- возвращает `GenerationResult`.

### `repair`
Шаг `repair`:
- загружает `RepairRequest`;
- строит repair prompt;
- вызывает repair model;
- пытается разобрать raw LLM response в структурированный artifact;
- при неудаче возвращает структурированную ошибку, а не валит процесс.

## Граница ответственности

`codegenerator` отвечает только за генерацию артефактов.

Он не:
- индексирует проект;
- не ищет target;
- не управляет staging workspace проекта;
- не принимает решение о полном repair-loop по результатам проектных тестов.

Эти части остаются в `codecollector`.

## Форматы входа и выхода

### `GenerationRequest`
Содержит:
- `change_request`;
- `target`;
- `project_context`;
- `reference_context`;
- `options`.

### `RepairRequest`
Содержит:
- контекст предыдущей генерации;
- описание ошибки/валидации;
- previous artifact;
- project/reference context для повторной генерации.

### `GenerationResult`
Возвращает:
- `status`;
- `code_artifact`;
- `test_artifact`;
- `planner_result`;
- `warnings`;
- `trace_path`;
- `error_type` / `message` при неуспехе.

## Канонические операции

Во внешнем контракте используются symbol-level операции:
- `replace_symbol`
- `add_symbol`
- `insert_after_symbol`

Если модель возвращает варианты вроде `replace_function`, они нормализуются внутри `codegenerator`.

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
Модели для шагов:
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

### `codegenerator.defaults`
Default constraints, которые добавляются к request.

### `codegenerator.trace`
Настройки trace/logging:
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
├── orchestration/    # generate / repair service
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
- prompt-и planner/coder/repair;
- raw response модели;
- parsed result;
- timing/meta;
- итоговый `trace_path` в результате.

## CLI

```bash
python -m codegenerator generate --request-file examples/generation_request.json
python -m codegenerator repair --request-file examples/repair_request.json
```

Поддерживаются оба формата request-файлов:
- JSON
- YAML

## ADR

### ADR-001. `codegenerator` — отдельный узкий генератор
Проект отвечает только за генерацию артефактов по уже подготовленному packet-контексту.

### ADR-002. Решение о repair-loop принимает `codecollector`
`codegenerator` выполняет одиночный `repair`, но не владеет project-level циклом повторных попыток.

### ADR-003. Каноническая операция — symbol-level
Во внешнем контракте используются `replace_symbol`, `add_symbol`, `insert_after_symbol`.

### ADR-004. Prompt templates хранятся в файлах
Шаблоны prompt-ов не захардкоживаются в Python-коде и подгружаются из `config.yaml`.

## Repair

`repair` получает исходный change request, previous artifact, summary ошибки apply/verification и project/reference context. Repair prompt должен исправить ошибку и сохранить requested change, а не откатывать target к исходной реализации.
