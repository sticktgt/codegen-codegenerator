# codegenerator

`codegenerator` — внешний генератор кода для `codecollector`. Проект получает структурированный request, собирает prompt, вызывает модель через Ollama-compatible endpoint, разбирает ответ, нормализует результат, сохраняет trace и возвращает машинно-читаемый JSON.

`codegenerator` не применяет patch к проекту, не запускает проверки проекта и не принимает решение о merge. Эти действия выполняет `codecollector`.

## Роль проекта

`codegenerator` отвечает за:

- сбор prompt по structured request;
- планирование изменения;
- генерацию production code artifact;
- генерацию generated test artifact;
- repair предыдущего artifact по error context;
- advisory review после generated-test failure;
- разбор raw model output;
- нормализацию результата;
- trace prompt/raw output/parsed output;
- usage metrics.

## Основные режимы

### Generate

Команда:

```bash
python -m codegenerator generate \
  --request-file generation_request.json \
  --config config.yaml
```

Режим генерирует production code artifact.

### Generate test

Команда:

```bash
python -m codegenerator generate-test \
  --request-file generation_test_request.json \
  --config config.yaml
```

Режим генерирует pytest-файл для проверки generated production artifact.

### Repair

Команда:

```bash
python -m codegenerator repair \
  --request-file repair_request.json \
  --config config.yaml
```

Режим исправляет предыдущий generated artifact на основе error context.

### Review generated-test failure

Команда:

```bash
python -m codegenerator review-generated-test-failure \
  --request-file generated_test_review_request.json \
  --config config.yaml
```

Режим возвращает advisory JSON для случая, когда production checks прошли, но generated test failed.

## Generation request

`GenerationRequest` содержит:

- request id;
- mode;
- change request;
- target;
- project context;
- allowed API surface;
- contract context;
- reference context;
- required contracts;
- required class members;
- model surfaces;
- same-class methods;
- reuse hints;
- generated code artifact для test generation;
- options.

`codegenerator` считает request источником истины. Он не читает исходный проект напрямую.

## Target

Target описывает место изменения:

- `target_file`;
- `target_symbol`;
- `operation`;
- `insert_after`;
- `insert_scope`;
- `expected_new_symbol_kind`;
- `parent_qualname`.

Поддерживаемые операции:

- `replace_symbol` — заменить существующий symbol;
- `insert_after_symbol` — вставить новый symbol после anchor.

Поддерживаемые insert scope:

- `module_body`;
- `class_body`.

## Project context

Project context может содержать:

- module outline;
- target source;
- full file source;
- imports;
- related symbols;
- related tests;
- recommended tests;
- same-class methods;
- visible implementation facts;
- model surfaces;
- reuse hints.

### Same-class methods

Same-class methods — методы того же класса, что и target method.

Они передаются `codecollector` и используются как видимый контекст. Это помогает модели переиспользовать уже существующие helper-методы класса вместо дублирования поведения или выдумывания новых методов.

Same-class methods рендерятся в prompt компактно:

- сначала список имен методов;
- затем сигнатуры и короткие описания;
- затем короткие excerpts для релевантных методов, если они помещаются в бюджет.

### Reuse hints

Reuse hints — подсказки по переиспользованию существующей проектной логики.

Они могут содержать:

- режим подсказки;
- уверенность;
- причину;
- список методов или контрактов, которые стоит рассмотреть.

Reuse hints являются soft context. Они не являются обязательным требованием. Обязательные вызовы передаются отдельно как required contracts.

## Prompt assembly

Prompt builder собирает prompt из шаблонов и данных request.

Основные блоки prompt:

- правила режима;
- параметры target;
- пользовательский запрос;
- planner output;
- module outline;
- visible implementation facts;
- allowed API surface;
- model surfaces;
- same-class methods;
- reuse hints;
- target source;
- full file source;
- contract context;
- reference artifacts;
- previous artifact и error context для repair.

Тексты prompt находятся в директории `prompts/`. Код prompt builder отвечает за подстановку структурированных данных и ограничение размера prompt.

## Planner

Planner формирует компактный план изменения.

Planner должен:

- использовать только предоставленные target-данные;
- не придумывать файлы, symbols и import paths;
- учитывать requested operation;
- учитывать insert scope;
- учитывать allowed API surface;
- учитывать required contracts;
- не переносить старый target source в explicit requirements, если пользователь этого не требовал;
- сохранять только явно заданные пользовательские требования;
- для class replace планировать замену полного класса;
- для helper/dependency calls соблюдать видимые сигнатуры.

## Coder

Coder генерирует production code artifact.

Основные правила:

- менять только указанный target;
- соблюдать operation;
- соблюдать insert scope;
- для `replace_symbol` вернуть полный обновленный symbol;
- для `insert_after_symbol` вернуть только новый symbol;
- не добавлять import-строки внутрь `code`;
- возвращать import changes отдельно;
- использовать только видимые project contracts;
- не придумывать методы dependency/helper objects;
- не создавать alias self-атрибуты, если виден существующий атрибут;
- при вызове project contract соблюдать видимую сигнатуру;
- при работе с моделью использовать видимые поля модели;
- при восстановлении модели из JSON/dict/файла приводить значения к видимым типам полей;
- если serialized field отсутствует, а у модели есть default, не передавать `None` вместо отсутствующего значения;
- использовать стандартную библиотеку Python, если это не добавляет внешних зависимостей и соответствует задаче.

## Repair

Repair исправляет previous artifact по error context.

Repair получает:

- previous artifact;
- исходный target;
- failed verification blocks;
- error issues;
- visible model surfaces;
- allowed API surface;
- contract context;
- same-class methods;
- suggested replacements для неизвестных self-атрибутов/методов;
- full file excerpt, если он передан.

Repair должен:

- исправлять previous artifact, а не начинать новый сценарий с нуля;
- не сохранять forbidden calls из error context;
- не заменять несуществующий метод другим несуществующим методом;
- использовать видимые методы того же класса, если они покрывают нужную часть поведения;
- использовать suggested replacements, если они переданы;
- добавлять import changes, если исправление требует нового import;
- сохранять operation и insert scope;
- возвращать результат в формате GenerationResult.

## Generate test

Generate test строит pytest artifact для generated production code.

Основные правила:

- тестировать generated target, а не anchor;
- для class body method создавать экземпляр parent class по видимой сигнатуре конструктора;
- не использовать constructor keyword arguments, которых нет в видимом конструкторе;
- не использовать optional pytest plugin fixtures;
- не использовать `mocker`;
- использовать стандартную библиотеку Python для временных файлов, директорий, дат, строк и коллекций;
- не придумывать поля моделей;
- expected values должны следовать из generated code artifact и видимого контекста;
- если generated code artifact и старый source противоречат друг другу, generated code artifact является главным источником истины;
- если модель восстановлена из JSON/dict/файла, expected values должны соответствовать видимым типам полей модели, а не сырым сериализованным строкам.

Generated tests могут быть отклонены `codecollector` на semantic/relevance checks. Отклоненный test artifact не является решением о качестве production code.

## Review generated-test failure

Review получает компактный request и возвращает advisory JSON.

Формат review:

```json
{
  "verdict": "production_likely_ok_test_likely_bad",
  "confidence": 0.85,
  "production_code_quality": "...",
  "generated_test_quality": "...",
  "should_keep_production_code": "yes",
  "recommended_action": "keep_production_code_exclude_test",
  "reasons": [],
  "production_risks": [],
  "test_issues": []
}
```

Review не принимает окончательное решение. Он помогает человеку оценить ситуацию, когда generated test failed.

## Output format

Основной результат возвращается как `GenerationResult`.

Для production generation результат может содержать:

- request id;
- status;
- code artifact;
- import changes;
- warnings;
- error type;
- message;
- trace path;
- usage metrics.

Для test generation результат содержит test artifact.

Для repair результат содержит исправленный code artifact или ошибку.

Для review результат содержит advisory review JSON.

## Trace

Trace сохраняет:

- prompt;
- raw model output;
- parsed output;
- normalized output;
- context metrics;
- usage metrics;
- errors parsing/normalization.

Полный prompt доступен в trace-файле соответствующего запуска. Trace используется для диагностики того, какие context blocks реально попали в запрос к модели.

## Конфигурация

Основной файл настроек — `config.yaml`.

Через конфигурацию задаются:

- Ollama-compatible endpoint;
- model names;
- timeout;
- generation options;
- prompt budget;
- trace settings;
- parser/normalization settings.

## Текущие ограничения

- Основной язык — Python.
- Качество generated tests нестабильно.
- Generated tests часто ошибаются в constructor kwargs project classes.
- Generated tests могут использовать optional pytest fixtures, которые затем отклоняются `codecollector`.
- Reuse hints являются soft context и не гарантируют выбор правильного метода.
- Planner может предложить неидеальное reuse-направление.
- Repair может исправить локальную ошибку, но выбрать не лучший existing helper, если контекст неполный или обрезан.
- Prompt section trace пока ограничен полным prompt и context metrics; нет отдельного списка всех включенных/обрезанных секций.

## Ближайшие доработки

- Улучшить generated-test construction context для project classes.
- Добавить section-level prompt trace: секции, размеры, included/truncated status, key symbols.
- Улучшить использование same-class methods в repair без превращения soft hints в hard constraints.
- Улучшить выбор reuse hints на этапе analyze.
- Добавить более строгую нормализацию generated test review output.
- Снизить зависимость generated tests от optional pytest plugins.
- Вынести новые русскоязычные prompt fragments из кода в шаблоны там, где это еще не сделано.
