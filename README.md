# codegenerator

`codegenerator` — внешний генератор для `codecollector`, который принимает структурированный request, собирает prompt, вызывает локальную модель через Ollama и возвращает нормализованный результат генерации кода, теста или repair.

Проект не индексирует кодовую базу и не выбирает target самостоятельно. Его задача — корректно отработать уже подготовленный request и вернуть стабильный машиночитаемый результат.

---

## Назначение проекта

`codegenerator` нужен как отдельный слой генерации, отделенный от orchestration, поиска и применения patch.

Он решает следующие задачи:
- получает `GenerationRequest` или `RepairRequest`;
- применяет runtime budget strategy;
- собирает prompt для нужного режима;
- вызывает локальную модель через Ollama;
- разбирает raw-ответ модели;
- нормализует `code_artifact` или `test_artifact`;
- возвращает единый `GenerationResult`;
- сохраняет trace и usage-метрики.

Это позволяет держать генерацию отдельно от логики выбора target и отдельно от логики проверки итогового изменения.

---

## Роль в связке с codecollector

Текущий рабочий сценарий выглядит так:

1. `codecollector` подготавливает `GenerationRequest` или `RepairRequest`;
2. `codecollector` вызывает CLI `codegenerator`;
3. `codegenerator` собирает prompt и вызывает модель;
4. `codegenerator` возвращает JSON-результат;
5. `codecollector` применяет артефакт, запускает проверки и определяет итоговый статус run.

Разделение ответственности важно сохранять.

### За что отвечает `codecollector`
- индекс проекта;
- выбор target;
- сбор project context;
- подбор reference artifacts;
- применение patch;
- runtime verification;
- итоговый статус сценария.

### За что отвечает `codegenerator`
- budget strategy;
- prompt assembly;
- вызов модели;
- parsing и normalization ответа;
- trace генерации.

---

## Поддерживаемые режимы

### `generate`
Режим генерации production-кода.

Что делает:
- принимает `GenerationRequest`;
- строит prompt для генерации кода;
- вызывает модель;
- извлекает и нормализует `code_artifact`.

Ожидаемый результат:
- заполнен `code_artifact`;
- `test_artifact` обычно отсутствует.

Пример вызова:

```bash
python -m codegenerator generate --request-file /path/to/generation_request.json --config /path/to/config.yaml
```

### `generate-test`
Режим генерации тестового файла.

Что делает:
- принимает `GenerationRequest`;
- строит prompt для генерации теста;
- при наличии использует `generated_code_artifact` как основной источник измененного production-кода;
- использует project context и связанные тесты;
- извлекает и нормализует `test_artifact`.

Ожидаемый результат:
- `code_artifact = null`;
- заполнен `test_artifact`.

Пример вызова:

```bash
python -m codegenerator generate-test --request-file /path/to/generation_test_request.json --config /path/to/config.yaml
```

### `repair`
Режим исправления ранее сгенерированного артефакта.

Что делает:
- принимает `RepairRequest`;
- получает описание ошибки и предыдущий артефакт;
- строит repair prompt;
- вызывает модель;
- возвращает исправленный результат в том же формате `GenerationResult`.

Пример вызова:

```bash
python -m codegenerator repair --request-file /path/to/repair_request.json --config /path/to/config.yaml
```

---

## Как устроена генерация

### 1. Загрузка request
`codegenerator` читает request из JSON или YAML файла.

Поддерживаемые расширения:
- `.json`
- `.yaml`
- `.yml`

### 2. Применение budget strategy
На этом шаге определяется, какой объем контекста реально попадет в prompt.

`codegenerator` отвечает именно за runtime budget. Он не выбирает сам project context, но решает, как переданные блоки использовать при ограничении модели.

### 3. Сборка prompt
Prompt собирается отдельно для каждого режима:
- production generation;
- test generation;
- repair.

### 4. Вызов модели
Модель вызывается через Ollama с параметрами из `config.yaml`.

### 5. Разбор ответа
Ответ модели приводится к единому формату результата.

### 6. Trace и метрики
Сохраняются trace-файлы, prompt, raw output и usage-метрики.

---

## Prompt assembly

В текущем состоянии prompt assembly должен оставаться простым и объяснимым.

### Основные принципы
- Не выбрасывать полезный контекст заранее, если он помещается в budget.
- Не подгонять prompt под один конкретный кейс.
- Сначала использовать фактический контекст проекта.
- Не заменять project context общим шаблоном.
- Не дублировать одни и те же правила в нескольких местах.

### Что особенно важно для `generate-test`
Порядок приоритета контекста:
1. `generated_code_artifact`, если он передан;
2. `target_symbol` и фактический измененный код;
3. `related_tests`;
4. `full_file_source`, если он реально нужен;
5. `example_test_source` только как дополнительный источник.

Это нужно, чтобы тесты по возможности повторяли реальные паттерны проекта и не выдумывали лишнее.

### Что не нужно делать
- Не превращать prompt в набор специальных инструкций ради одной ошибки.
- Не усиливать одну частную эвристику так, что она начинает мешать остальным сценариям.
- Не переносить в prompt проектные детали, которые должны приходить через request.

---

## Генерация тестов

Тестогенерация — отдельный режим с отдельными ограничениями.

Цель не в том, чтобы любой ценой получить «умный» тест. Цель — получить полезный и правдоподобный тест, который:
- использует реальные символы проекта;
- не придумывает несуществующие поля и сигнатуры;
- не требует несуществующих зависимостей;
- по возможности повторяет существующие тестовые паттерны проекта.

### Практические правила
- Если есть `related_tests`, они важнее шаблонного примера.
- Если есть `generated_code_artifact`, тест должен ориентироваться на него, а не на старую версию target.
- Если структура проекта неоднозначна, лучше быть проще, чем домысливать поведение.
- `example_test_source` — это fallback, а не основа генерации.

### Что важно помнить про budget в generate-test

Для `generate-test` качество результата заметно зависит от того, помещаются ли в prompt:
- актуальный измененный production-код;
- `related_tests`;
- нужная часть `full_file_source`;
- служебные инструкции шаблона.

Если общий лимит режима слишком мал или внутренние лимиты сборки prompt занижены, генератор начинает убирать полезные блоки контекста.  
Это может приводить не к синтаксическим ошибкам, а к более неприятным проблемам:
- неверные import path;
- неполный вызов конструктора project-модели;
- потеря обязательных аргументов;
- опора на шаблонный fallback вместо фактического project context.

Поэтому при разборе качества `generate-test` нужно смотреть не только на итоговый prompt size, но и на то, какие блоки были реально сохранены, а какие были урезаны в ходе budget strategy.

### Что считается плохим результатом
- придуманные поля модели;
- несуществующие аргументы конструктора;
- несуществующие импорты;
- тест, который не покрывает измененный символ;
- тест, который зависит от контракта, отсутствующего в project context.

---

## Repair

`repair` используется, когда уже есть артефакт, но его нужно исправить.

Типовые причины:
- синтаксическая ошибка;
- некорректная структура артефакта;
- артефакт не применился;
- артефакт не прошел проверки в `codecollector`.

### Что передается в repair
Обычно repair получает:
- исходный change request;
- предыдущий артефакт;
- описание ошибки;
- project context;
- reference context;
- служебные опции.

### Что важно сохранять
- repair должен чинить артефакт, а не менять смысл задачи;
- результат repair должен быть того же типа, что и исходный артефакт;
- по trace должно быть видно, что именно repair пытался исправить.

---

## Входные данные

## `GenerationRequest`

Используется для `generate` и `generate-test`.

Типовая структура:

```json
{
  "request_id": "generate-build_assignment_message",
  "mode": "generate",
  "change_request": {
    "title": "Изменить текст уведомления о назначении тикета",
    "description": "Сделать уведомление на русском языке.",
    "constraints": [
      "Не менять внешний контракт API"
    ],
    "notes": []
  },
  "target": {
    "qualname": "support_app.services.notification_service.build_assignment_message",
    "file_path": "support_app/services/notification_service.py",
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
  "generated_code_artifact": null,
  "options": {}
}
```

### Основные поля
- `request_id` — идентификатор запуска;
- `mode` — `generate` или `generate_test`;
- `change_request` — описание изменения;
- `target` — target symbol и операция;
- `project_context` — контекст проекта;
- `reference_context` — reference artifacts;
- `generated_code_artifact` — уже сгенерированный production-код, если он нужен для теста;
- `options` — дополнительные опции.

## `RepairRequest`

Используется только для `repair`.

Обычно содержит:
- `request_id`;
- `mode`;
- `previous_generation_request_id`;
- `change_request`;
- `error_context`;
- `previous_artifact`;
- `project_context`;
- `reference_context`;
- `options`.

Главное отличие от `GenerationRequest` — наличие контекста ошибки и предыдущего артефакта.

---

## Выходной результат

Во всех режимах возвращается JSON.

Основные поля результата:
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
Обычно содержит:
- `operation`;
- `target_qualname`;
- `target_file`;
- `code`;
- `insert_after`.

### `test_artifact`
Обычно содержит:
- `file_path`;
- `source_code`.

### `llm_usage`
Позволяет понять стоимость и длительность генерации.

Типовые поля:
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

## Поддерживаемые операции артефакта

Сейчас поддерживаются две canonical operations:
- `replace_symbol`
- `insert_after_symbol`

### `replace_symbol`
Означает замену существующего symbol.

### `insert_after_symbol`
Означает вставку нового symbol после указанного anchor symbol.

Для `insert_after_symbol` важно:
- сохранить `insert_after`;
- вернуть только новый symbol;
- не добавлять module-level imports в сам артефакт, если внешний контракт ожидает только вставляемый код.

Любое другое значение операции считается ошибкой контракта.

---

## Конфигурация

Основной конфиг находится в `config.yaml`.

### Что в нем хранится
- параметры Ollama;
- модели для разных режимов;
- пути к prompt templates;
- настройки generation и repair;
- правила budget strategy;
- настройки trace и логирования.

### Важные разделы
#### `llm.ollama`
Содержит параметры вызова модели, например:
- `base_url`;
- `timeout_sec`;
- `temperature`;
- `num_ctx`;
- `num_predict`;
- `keep_alive`.

#### `codegenerator.prompts`
Содержит пути к prompt templates:
- `system_rules`;
- `planner_user_template`;
- `coder_user_template`;
- `repair_user_template`;
- `test_generator_user_template`;
- `test_generator_example`.

#### `codegenerator.models`
Определяет модели для:
- planner;
- coder;
- repair;
- test generation.

#### `codegenerator.trace`
Настройки trace:
- сохранять ли trace в файл;
- сохранять ли prompt;
- сохранять ли raw output;
- куда писать trace.


#### Лимиты prompt: общий budget и внутренние лимиты сборки

В текущей реализации у `codegenerator` есть два уровня ограничений prompt.

**1. Общий лимит режима**  
Задается в разделе `prompt_budget`:
- `generate_chars_limit`
- `generate_test_chars_limit`
- `repair_chars_limit`

Этот лимит определяет верхнюю границу prompt budget для соответствующего режима после вычета system prompt и служебного резерва.

**2. Внутренние лимиты сборки prompt**  
Задаются в разделе `generation`, например:
- `coder_prompt_target_chars`
- `coder_prompt_hard_limit`
- `repair_prompt_hard_limit`
- лимиты на reference artifacts, full file и другие контекстные блоки

Эти параметры управляют тем, сколько контекста и каких именно блоков будет реально использовано при сборке prompt внутри режима.

Важно: итоговый объем prompt определяется не одним числом, а сочетанием этих двух уровней.  
Даже если общий лимит режима увеличен, часть контекста все равно может быть урезана внутренними ограничениями сборки prompt.

Практически это означает:
- для `generate-test` недостаточно увеличить только `generate_test_chars_limit`, если внутренние лимиты по связанным блокам остаются слишком низкими;
- для единообразного поведения `generate`, `generate-test` и `repair` нужно синхронно смотреть и на `prompt_budget`, и на `generation`.


#### Практический ориентир для настройки лимитов

Если требуется повысить устойчивость генерации на более сложных примерах, имеет смысл выравнивать лимиты по всем режимам единообразно:
- `generate`
- `generate-test`
- `repair`

При такой настройке важно синхронно проверять:
- общий budget режима;
- внутренние hard/target limits;
- лимиты на reference artifacts и full file context.

Иначе можно получить ситуацию, когда общий лимит уже увеличен, но значимые части prompt все еще урезаются внутренними ограничениями без явной необходимости.

## Логирование и trace

Логи и trace нужны не только для фиксации факта вызова модели, но и для разбора качества генерации.

Что полезно видеть:
- какой режим вызван;
- какой request обработан;
- какие блоки реально вошли в prompt;
- использовался ли `full_file_source`;
- использовались ли `related_tests`;
- использовался ли `generated_code_artifact`;
- использовался ли `example_test_source`;
- какие блоки были урезаны;
- итоговый размер prompt;
- usage-метрики модели.

Для неудачных generated test это особенно важно.

---

## Структура проекта

### `config.yaml`
Основная конфигурация проекта.

### `prompts/`
Шаблоны prompt-ов для всех режимов.

### `runs/`
Trace-файлы, логи и артефакты вызовов модели.

### `examples/`
Примеры request-файлов.

### `orchestration/`
Основная логика режимов `generate`, `generate-test`, `repair`.

### `context/`
Budget strategy и работа с контекстом.

### `llm/`
Клиент вызова Ollama.

### `parsers/` и `normalization/`
Разбор и нормализация ответа модели.

---

## Текущие ограничения

На текущем этапе:
- основная поддержка — Python;
- модели вызываются локально через Ollama;
- качество генерации зависит от модели и размера prompt;
- `generate-test` особенно чувствителен к качеству project context;
- часть сценариев требует `repair`;
- проект работает как внешний генератор, а не как самостоятельный orchestration-слой.

---

## Что считается текущим рабочим сценарием

Текущий рабочий сценарий:
- получить request от `codecollector`;
- собрать prompt с учетом budget;
- вызвать модель;
- вернуть нормализованный JSON-результат;
- сохранить trace.

Именно это состояние нужно считать актуальным при изменениях документации и кода.

---

## Практические примеры

### Пример для replace_symbol
Из `codecollector` приходит request на замену существующей функции. `codegenerator` должен вернуть новый `code_artifact` с операцией `replace_symbol` и кодом только для этой функции.

### Пример для insert_after_symbol
Из `codecollector` приходит request на добавление новой dataclass после существующего класса-якоря. `codegenerator` должен вернуть `insert_after_symbol`, указать anchor symbol и вернуть только новый класс.

### Пример для generate-test
Если production-код уже сгенерирован, тест должен строиться по `generated_code_artifact`, а не по исходной версии функции. Это особенно важно для сценариев, где после генерации изменился текст сообщения, сигнатура или возвращаемое значение.

---

## Что не нужно делать

- Не подгонять prompt под один demo-case.
- Не переносить проектные знания из `codecollector` в код генератора.
- Не усложнять budget strategy ради одной ошибки.
- Не хранить проектно-зависимые константы в коде, если они могут прийти через request или config.
- Не дублировать одни и те же инструкции в нескольких шаблонах.

---

## TODO

### Ближайшие направления
- улучшать качество `generate-test` без усложнения базовой архитектуры;
- улучшать диагностику причин неудачной генерации тестов;
- развивать budget strategy, сохраняя простоту и воспроизводимость;
- повышать устойчивость `generate`, чтобы реже требовался `repair`.

### Среднесрочные направления
- точнее работать с библиотечным и проектным окружением;
- расширять поддержку других языков;
- сохранить JSON-контракт при возможном переходе с CLI на локальный сервис.

---

## Итог

`codegenerator` в текущем состоянии — это внешний генератор кода, тестов и repair-артефактов, который получает уже подготовленный структурированный request, управляет runtime budget, вызывает локальную модель, нормализует результат и возвращает его в стабильном машиночитаемом формате.

Его задача — делать генерацию воспроизводимой, управляемой и пригодной для использования внутри orchestration-слоя `codecollector`.
