# codegenerator

`codegenerator` — отдельный проект для генерации production-кода, генерации тестов и точечного `repair` по уже подготовленному структурированному request.

Проект используется как внешний генератор артефактов. Он получает request в JSON или YAML, строит prompt для локальной LLM, вызывает модель через Ollama, разбирает ответ, нормализует результат и возвращает его в машиночитаемом виде.

Текущая реализация ориентирована прежде всего на Python и на работу с ограниченным context budget.

---

## Назначение проекта

`codegenerator` нужен как отдельный слой генерации, отделенный от orchestration и индексации.

Он не ищет место изменения в кодовой базе и не строит индекс проекта. Вместо этого он принимает уже подготовленный request и выполняет следующие задачи:

- применяет внутреннюю budget strategy;
- собирает prompt для planner, coder, repair или test generator;
- вызывает выбранную локальную модель;
- разбирает raw-ответ модели;
- нормализует `code_artifact` или `test_artifact`;
- возвращает единый `GenerationResult`;
- сохраняет trace, prompt, raw output и usage-метрики.

---

## Общая роль в связке с `codecollector`

В текущей связке:

1. `codecollector` подготавливает `GenerationRequest` или `RepairRequest`;
2. `codecollector` вызывает CLI `codegenerator`;
3. `codegenerator` выполняет генерацию или repair;
4. `codegenerator` возвращает JSON-результат;
5. `codecollector` применяет результат и запускает проверки.

Разделение ответственности здесь принципиальное:

- `codecollector` отвечает за **структурный состав контекста**;
- `codegenerator` отвечает за **prompt assembly, runtime budget и вызов модели**.

---

## Основные режимы работы

### `generate`

Режим для генерации production-кода.

Последовательность:

1. загрузка `GenerationRequest`;
2. применение budget strategy к request;
3. построение planner prompt;
4. вызов planner model;
5. построение coder prompt;
6. вызов coder model;
7. разбор ответа в `code_artifact`;
8. валидация canonical operation (`replace_symbol` или `insert_after_symbol`);
9. возврат `GenerationResult`.

Результат режима:

- ожидается `code_artifact`;
- `test_artifact` обычно отсутствует.

### `generate-test`

Режим для генерации теста для выбранного target.

Последовательность:

1. загрузка `GenerationRequest`;
2. применение budget strategy;
3. построение prompt для test generation;
4. при наличии `generated_code_artifact` использовать его как основной источник измененного production-кода;
5. при необходимости использовать `full_file_source`, `related_tests` и example test source;
6. вызвать `test_generator_model`;
7. разобрать ответ в `test_artifact`;
8. вернуть `GenerationResult`.

Результат режима:

- `code_artifact = null`;
- возвращается только `test_artifact`.

### `repair`

Режим для исправления ранее полученного артефакта.

Используется, когда уже есть сгенерированный `code_artifact`, который:

- не применился;
- не прошел проверки;
- содержит синтаксическую или структурную проблему.

Последовательность:

1. загрузка `RepairRequest`;
2. применение budget strategy для repair;
3. построение repair prompt;
4. вызов repair model;
5. разбор ответа;
6. возврат исправленного результата или структурированной ошибки.

---

## Внутренние функциональные блоки

### Budget strategy

`codegenerator` управляет runtime budget prompt.

Он работает с лимитами из `config.yaml` и решает:

- сколько user prompt можно передать модели;
- какие блоки сокращать первыми;
- какие блоки удалять в последнюю очередь;
- как вести себя в режимах `generate`, `generate-test` и `repair`.

Это текущий центр ответственности за реальное ужатие prompt.

### Prompt builder

Prompt builder собирает итоговые user prompt для разных режимов:

- planner;
- coder;
- repair;
- test generator.

На этом шаге учитываются:

- target code;
- module outline;
- related tests;
- full file source;
- reference artifacts;
- request description и constraints;
- служебные правила для модели.

Текущий принцип — prompts должны быть русскоязычными и максимально не смешивать языки без необходимости.

### Логика prompt для `generate-test`

В текущем состоянии логика формирования test prompt должна оставаться простой и поддерживаемой.

Базовые правила:

- ничего не выбрасывать из prompt заранее, если бюджет это позволяет;
- сначала использовать фактический контекст проекта, а не пример;
- `generated_code_artifact` важнее исходного target source, если тест строится по уже измененному коду;
- `related_tests` передаются как основной образец проектного стиля тестов;
- `example_test_source` используется как fallback, а не как доминирующий источник;
- урезание контекста выполняется не каскадом из нескольких отдельных фаз, а одной простой стадией, только если блоки не помещаются в бюджет;
- заранее не оптимизировать prompt под один конкретный demo-тест или конкретную функцию.

Идея текущего состояния — сохранить баланс между качеством и простотой поддержки. Лучше получить неидеальный тест, чем слишком сложную и трудно сопровождаемую систему сборки prompt.

### Gateway / Ollama client

Слой вызова модели отвечает за:

- вызов локального Ollama endpoint;
- передачу модели, температуры и runtime options;
- сбор usage-метрик;
- возврат raw response.

### Parser и normalization

После ответа модели `codegenerator`:

- извлекает JSON;
- валидирует поля результата;
- нормализует тип операции;
- формирует единый `GenerationResult`.

### Trace и логи

Для каждого вызова могут сохраняться:

- шаги budget и trimming;
- готовый prompt;
- raw output модели;
- parsed output;
- usage-метрики;
- trace path в `runs/`.

Для `generate-test` дополнительно полезно логировать:

- какие источники реально вошли в test prompt;
- использовался ли `generated_code_artifact`;
- использовались ли `related_tests`;
- использовался ли `example_test_source`;
- был ли включен `full_file_source`;
- какие блоки были урезаны из-за budget.

Такое логирование нужно прежде всего для отладки неудачных тестов и для сравнения поведения на разных моделях.

---

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

---

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
    "reference_artifacts": []
  },
  "generated_code_artifact": {},
  "options": {}  
}
```

### Основные поля `GenerationRequest`

#### `request_id`
Уникальный идентификатор запуска.

#### `mode`
Режим вызова:

- `generate`;
- `generate_test`.

#### `change_request`
Описание изменения.

Поля:

- `title`;
- `description`;
- `constraints`;
- `notes`.

#### `target`
Описание символа, который должен быть изменен.

Поля:

- `qualname`;
- `file_path`;
- `operation`.

#### `project_context`
Контекст по проекту.

Поля:

- `module_outline`;
- `full_file_source`;
- `target_symbol`;
- `related_tests`;
- `recommended_tests`.

#### `reference_context`
Контекст из reference library.

Поля:

- `reference_artifacts`.

#### `generated_code_artifact`
Дополнительное поле для связанных сценариев генерации. В `generate-test` содержит уже сгенерированный production-код, который используется как основной target source для генерации теста.

#### `options`
Опции генерации.

#### `context_metrics`
Служебные метрики budget/trimming, которые формируются внутри `codegenerator` и сохраняются в trace. Не являются обязательной частью внешнего request-контракта.

---

## Входной контракт `RepairRequest`

`RepairRequest` используется только для режима `repair`.

Основные поля:

- `request_id`;
- `mode`;
- `previous_generation_request_id`;
- `change_request`;
- `error_context`;
- `previous_artifact`;
- `project_context`;
- `reference_context`;
- `options`.

### Важные поля `RepairRequest`

#### `error_context`
Описывает, почему исходный артефакт нужно исправить.

Обычно содержит:

- тип ошибки;
- краткую summary;
- failed checks;
- messages;
- stage.

#### `previous_artifact`
Ранее сгенерированный артефакт, который требуется исправить.

---

## Выходной контракт `GenerationResult`

Во всех режимах проект возвращает единый JSON-результат.

Основные поля:

- `request_id`;
- `status`;
- `code_artifact`;
- `test_artifact`;
- `planner_result`;
- `warnings`;
- `trace_path`;
- `llm_usage`;
- `error_type`;
- `message`.

### `code_artifact`

Для production-кода обычно содержит:

- `operation`;
- `target_qualname`;
- `target_file`;
- `code`;
- `insert_after`.

### `test_artifact`

Для тестогенерации обычно содержит:

- `file_path`;
- `source_code`.

### `llm_usage`

Содержит агрегированные метрики вызова модели, например:

- `calls`;
- `prompt_tokens`;
- `output_tokens`;
- `total_tokens`;
- `duration_sec`;
- `total_duration_sec`;
- `load_duration_sec`;
- `prompt_eval_duration_sec`;
- `eval_duration_sec`.

---

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
- budget и trimming policy для разных режимов.

### `codegenerator.defaults`

Default constraints, которые могут добавляться к request.

### `codegenerator.trace`

Настройки trace и логирования:

- `save_to_file`;
- `show_prompts`;
- `show_raw_llm_output`;
- `output_dir`.

---

## Переопределение конфигурации через environment variables

`config.py`:

- читает `config.yaml`;
- переопределяет существующие значения через переменные окружения с префиксом проекта;
- позволяет добавлять новые ключи через env без изменения загрузчика.

Примеры:

- `RS__LLM__OLLAMA__BASE_URL=http://127.0.0.1:11434`
- `RS__CODEGENERATOR__MODELS__CODER_MODEL=qwen2.5-coder:14b-instruct-q4_K_M`
- `RS__CODEGENERATOR__TRACE__OUTPUT_DIR=runs`

---

## Структура проекта

### `config.yaml`
Основная конфигурация проекта.

### `prompts/`
Промпты и шаблоны для planner, coder, repair и test generation.

### `runs/`
Логи и trace-файлы запусков генерации.

### `examples/`
Примеры request-файлов для запуска.

### `orchestration/`
Основная orchestration-логика режимов `generate`, `generate-test`, `repair`.

### `context/`
Budget strategy и работа с контекстом.

### `llm/`
Вызов Ollama и gateway к модели.

### `parsers/` и `normalization/`
Разбор и нормализация ответа модели.

---

## Текущие ограничения

На текущем этапе проект имеет следующие ограничения:

- основная поддержка — Python;
- модели вызываются локально через Ollama;
- качество генерации зависит от конкретной модели и размера prompt;
- `generate-test` особенно чувствителен к качеству target-контекста и правилам prompt;
- часть сценариев `generate` все еще может потребовать отдельный `repair`;
- проект рассчитан на работу как внешний генератор, а не как самостоятельный индексатор кодовой базы.

---

## Что считается текущим рабочим сценарием

Текущий рабочий сценарий:

- получить `GenerationRequest` или `RepairRequest` от `codecollector`;
- собрать prompt с учетом budget;
- вызвать локальную модель;
- вернуть нормализованный JSON-результат;
- сохранить trace вызова.

Именно этот сценарий сейчас считается основным и должен сохраняться при дальнейших изменениях, даже если внешний способ вызова будет позже переведен с CLI на локальный API.

---

## Поддерживаемые операции code artifact

Текущие canonical operations:

- `replace_symbol` — заменить существующий symbol;
- `insert_after_symbol` — вставить новый symbol после указанного anchor symbol.

Любое значение операции, отличное от `replace_symbol` и `insert_after_symbol`, считается ошибкой контракта.

Для `insert_after_symbol` генератор должен вернуть:

- `operation = "insert_after_symbol"`;
- `insert_after = <qualname anchor-symbol>`;
- `code` содержит только новый class/function symbol без module-level imports.

---

## Актуальные направления развития

Текущие направления развития:

- дальнейшее улучшение budget strategy;
- улучшение качества `generate-test` на малых моделях;
- развитие правил против «додумывания» поведения в тестах;
- усиление устойчивости `generate` без обязательного repair;
- расширение поддержки других языков;
- переход от CLI-вызова к локальному сервису или API с сохранением JSON-контракта.

---

## TODO

### По генерации тестов

- продолжить улучшение качества `generate-test` после перехода на более мощные модели;
- сохранить простую и прозрачную логику формирования test prompt;
- не допускать чрезмерного усложнения trimming policy ради одного частного кейса;
- отдельно развивать диагностику причин неудачной генерации тестов через trace и логи.

### По библиотекам и дополнительному контексту

- отдельно доработать работу с дополнительными библиотеками и reference-контекстом;
- точнее управлять тем, какие вспомогательные примеры действительно полезны модели;
- сохранить общее, а не кейс-специфичное наполнение prompt.

### По архитектуре

- сохранить текущий JSON-контракт между `codecollector` и `codegenerator`;
- при переходе с CLI на локальный сервис не менять семантику `GenerationRequest`, `RepairRequest` и `GenerationResult`;
- постепенно расширять language-agnostic часть генератора без усложнения текущего Python-first сценария.

---

## Итог

`codegenerator` в текущем состоянии — это внешний генератор кода и тестов, который принимает уже подготовленный структурированный request, управляет budget prompt, вызывает локальную LLM, нормализует результат и возвращает его в стабильном машиночитаемом формате.

Его основная роль — сделать генерацию воспроизводимой, контролируемой и пригодной для использования внутри orchestration-слоя `codecollector`.
