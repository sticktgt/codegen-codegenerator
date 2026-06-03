# codegenerator

`codegenerator` — внешний генератор кода для `codecollector`. Проект получает структурированный запрос, собирает prompt, вызывает модель через точку доступа, совместимую с Ollama, разбирает ответ, нормализует результат, сохраняет трассу выполнения и возвращает машинно-читаемый JSON.

`codegenerator` не применяет patch к проекту, не запускает проверки проекта и не принимает решение о merge. Эти действия выполняет `codecollector`.

## Назначение

`codegenerator` отвечает за:

- сбор prompt по structured request;
- планирование изменения;
- генерацию artifact основного кода;
- генерацию pytest artifact;
- repair ранее сгенерированного artifact по error context;
- advisory review после ошибки generated test;
- разбор raw output модели;
- нормализацию результата;
- сохранение prompt, raw output, parsed output и normalized output;
- сохранение usage metrics и context metrics.

## Основные режимы

### Generate

Команда:

```bash
python -m codegenerator generate \
  --request-file generation_request.json \
  --config config.yaml
```

Режим генерирует artifact основного кода.

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

Режим исправляет previous artifact на основе error context.

### Review generated-test failure

Команда:

```bash
python -m codegenerator review-generated-test-failure \
  --request-file generated_test_review_request.json \
  --config config.yaml
```

Режим возвращает advisory JSON для случая, когда проверки основного кода прошли, но generated test не прошел проверку.

## Входные запросы

`codegenerator` читает только данные из request. Он не индексирует проект и не читает исходный код проекта напрямую.

### GenerationRequest

`GenerationRequest` используется в режимах `generate` и `generate-test`.

Основные поля:

- `request_id`;
- `mode`;
- `change_request`;
- `target`;
- `project_context`;
- `reference_context`;
- `generated_code_artifact`;
- `options`.

`generated_code_artifact` используется в режиме `generate-test` как главный источник нового поведения основного кода.

### RepairRequest

`RepairRequest` используется в режиме `repair`.

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

`target` в `RepairRequest` сохраняет исходное место изменения. Repair должен исправлять previous artifact для того же target, а не выбирать новый target.

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

- `replace_symbol`;
- `insert_after_symbol`.

Поддерживаемые значения `insert_scope`:

- `module_body`;
- `class_body`.

### replace_symbol

Для `replace_symbol` результат содержит полный обновленный код существующего symbol.

Правила:

- не менять внешний контракт без явного требования;
- не возвращать соседние symbols;
- не использовать `insert_scope` как сценарий вставки;
- новые imports возвращать через `import_changes`.

### insert_after_symbol + module_body

Для вставки в тело модуля результат содержит только новый top-level function или class.

Правила:

- `code` начинается с `def`, `async def` или `class`;
- `insert_after` указывает anchor qualname;
- imports возвращаются через `import_changes`.

### insert_after_symbol + class_body

Для вставки в тело класса результат содержит только новый метод класса.

Правила:

- `code` начинается с `def` или `async def`;
- `parent_qualname` указывает класс;
- не возвращать class целиком;
- не менять anchor-symbol;
- imports возвращаются через `import_changes`.

## GenerationResult

Во всех режимах используется единый формат результата.

Основные поля:

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

Для режима `generate` основным результатом является `code_artifact`. Для режима `generate-test` основным результатом является `test_artifact`. Для режима `repair` возвращается исправленный `code_artifact` или структурированная ошибка. Для review возвращается advisory review JSON.

## CodeArtifact

`code_artifact` описывает изменение основного кода.

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

`import_changes` содержит imports, которые нужны generated code.

Новые import-строки не добавляются внутрь `code_artifact.code`.

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

Если имя используется в annotation, default value, decorator, context manager, helper call или теле функции, оно требует import, если такого import нет в target-файле. `from __future__ import annotations` не отменяет необходимость import для явно используемого имени.

## Project context

`project_context` содержит фактический контекст проекта, переданный `codecollector`.

Он может включать:

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
- allowed API surface;
- contract context;
- required contracts;
- required class members;
- reuse hints;
- reference context.

### Allowed API Surface

Allowed API Surface — компактный список разрешенных вызовов project dependencies и внутренних project contracts.

Правила:

- если surface передан, методы зависимостей должны совпадать с ним по `access_path` и имени метода;
- нельзя придумывать похожие методы dependency/helper objects;
- нельзя придумывать широкие методы получения всех сущностей, если они не видны в surface;
- если project contract принимает обязательный аргумент, generated symbol должен принять этот аргумент явно или получить его из видимого контекста;
- surface не запрещает standard library и обычные методы стандартных типов, если они нужны для задачи и не добавляют внешних зависимостей.

Пример:

```json
{
  "dependencies": [
    {
      "access_path": "self.storage",
      "type_name": "NoteStorage",
      "allowed_methods": [
        {
          "name": "save",
          "signature": "def save(self, note: Note) -> str:",
          "qualname": "note.note_storage.NoteStorage.save"
        }
      ]
    }
  ],
  "free_functions": []
}
```

### Contract context

`contract_context` содержит связанные production contracts: сигнатуры, import path, source excerpts и relation metadata.

Этот блок является фактическим project context. Его нельзя трактовать как справочный пример с низким приоритетом.

### Model surfaces

Model surfaces описывают видимые модели и их поля:

- имя;
- qualname;
- fields;
- constructor fields;
- required constructor fields;
- типы полей, если они видимы;
- source.

Model surfaces используются в generation, repair и generated-test generation.

### Same-class methods

Same-class methods — методы того же класса, что и target method.

Они используются как видимый контекст, чтобы generated code мог вызывать существующие методы того же класса вместо дублирования поведения или создания новых методов. Same-class methods являются soft context, если они не переданы как required contracts.

### Reuse hints

Reuse hints — подсказки по переиспользованию существующей проектной логики.

Они могут содержать:

- mode;
- confidence;
- reason;
- contracts.

Reuse hints являются soft context. Обязательные вызовы передаются отдельно через required contracts.

## Prompt assembly

Prompt builder собирает prompt из шаблонов и request.

Основные блоки prompt:

- правила режима;
- параметры target;
- пользовательский запрос;
- planner output;
- module outline;
- visible implementation facts;
- Allowed API Surface;
- model surfaces;
- same-class methods;
- reuse hints;
- target source;
- full file source;
- contract context;
- reference artifacts;
- previous artifact и error context для repair.

Тексты prompt находятся в директории `prompts/`. Python-код prompt builder отвечает за подстановку структурированных данных, форматирование блоков и ограничение размера prompt.

## Planner

Planner формирует компактный план изменения.

Planner должен:

- использовать только предоставленные target-данные;
- не придумывать файлы, symbols и import paths;
- учитывать requested operation;
- учитывать insert scope;
- учитывать Allowed API Surface;
- учитывать required contracts;
- не переносить старый target source в explicit requirements, если пользователь этого не требовал;
- сохранять только явно заданные пользовательские требования;
- для class replace планировать замену полного класса;
- для helper/dependency calls соблюдать видимые сигнатуры.

### explicit_requirements

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

### preserve_literals

`preserve_literals` содержит только значения, буквально написанные пользователем.

В `preserve_literals` не добавляются фрагменты старого кода, target source, related tests, planner wording или reference artifacts, если пользователь не написал эти значения явно.

## Coder

Coder генерирует production code artifact.

Правила:

- менять только указанный target;
- соблюдать operation;
- соблюдать insert scope;
- для `replace_symbol` вернуть полный обновленный symbol;
- для `insert_after_symbol` вернуть только новый symbol;
- не добавлять import-строки внутрь `code`;
- возвращать imports через `import_changes`;
- использовать только видимые project contracts;
- не придумывать методы dependency/helper objects;
- не создавать alias self-атрибуты, если виден существующий атрибут;
- при вызове project contract соблюдать видимую сигнатуру;
- при работе с моделью использовать видимые поля модели;
- при восстановлении модели из JSON, dict или файла приводить значения к видимым типам полей;
- если serialized field отсутствует, а у модели есть default, не передавать `None` вместо отсутствующего значения;
- использовать standard library, если это не добавляет внешних зависимостей и соответствует задаче.

## Generate test

Generate test создает pytest artifact для generated production code.

Правила:

- тестировать generated target, а не anchor;
- `generated_code_artifact` является главным источником нового поведения;
- related tests используются как источник стиля, если они не противоречат generated code;
- full file source и imports target-файла используются для импортов, сигнатур и окружающего контекста;
- reference artifacts используются только как дополнительный контекст;
- fake/stub должен реализовывать поля и методы, которые generated target или production contract source явно читает или вызывает;
- expected values должны следовать из generated code artifact, явных тестовых данных и видимого project context;
- если generated code artifact и старый source противоречат друг другу, используется generated code artifact;
- если модель восстановлена из JSON, dict или файла, expected values соответствуют видимым типам полей модели, а не сырым serialized strings;
- optional pytest plugin fixtures не используются;
- `mocker` не используется;
- imports теста включаются прямо в `test_artifact.source_code`;
- `import_changes` для нового test file в основном сценарии не используется.

Для class body method тест использует parent class как источник метода. Настоящий экземпляр parent class создается только если generated target требует реального конструктора. Если метод можно проверить через простые self-атрибуты или локальные fake/stub объекты, тест может вызывать method как unbound method через parent class.

## Repair

Repair исправляет previous artifact по error context.

Repair получает:

- previous artifact;
- исходный target;
- failed verification blocks;
- error issues;
- visible model surfaces;
- Allowed API Surface;
- contract context;
- same-class methods;
- suggested replacements для unknown self attributes и unknown self methods;
- full file excerpt, если он передан.

Repair должен:

- исправлять previous artifact, а не начинать новый сценарий с нуля;
- сохранять operation и insert scope;
- не менять смысл пользовательского запроса;
- не сохранять forbidden calls из error context;
- не заменять несуществующий метод другим несуществующим методом;
- использовать видимые методы того же класса, если они покрывают нужное поведение;
- использовать suggested replacements, если они переданы;
- добавлять `import_changes`, если исправление требует нового import;
- возвращать результат в формате `GenerationResult`.

### Repair planner

Repair planner возвращает JSON со строгой схемой:

- `status`;
- `repair_objective`;
- `allowed_calls_to_use`;
- `forbidden_calls`;
- `required_changes`;
- `reason`.

Все ключи обязательны. Имена ключей не переводятся и не переименовываются. В ответ не добавляются другие ключи.

Если error context содержит unknown dependency method, repair planner использует только методы, видимые в Allowed API Surface или contract context. Если безопасной видимой замены нет, repair planner возвращает статус, при котором repair не выполняет догадку.

## Review generated-test failure

Review generated-test failure возвращает advisory JSON.

Формат:

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
  "test_issues": [],
  "recommendation_summary": "...",
  "next_steps": []
}
```

Review оценивает, относится ли ошибка к основному коду, generated test, окружению запуска или недостатку контекста. Review не принимает окончательное решение о merge.

## Бюджеты prompt

Есть общий лимит режима и внутренние лимиты сборки.

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

При изменении лимитов проверяется trace: какие блоки вошли в prompt, какие были сокращены, какой итоговый размер prompt и какие usage metrics вернула модель.

## Trace и диагностика

Trace сохраняет:

- request;
- prompt;
- raw output;
- parsed output;
- normalized output;
- context metrics;
- trim steps;
- import changes count;
- usage metrics;
- parsing и normalization errors.

Полный prompt доступен в trace-файле соответствующего запуска. При разборе качества генерации проверяются фактические prompt blocks, raw output и normalized output.

## Конфигурация

Основной файл настроек — `config.yaml`.

Через конфигурацию задаются:

- точка доступа модели;
- имена моделей;
- timeout;
- generation options;
- prompt budget;
- trace settings;
- parser settings;
- normalization settings;
- пути prompt templates.

## Текущие ограничения

- Основной поддерживаемый язык проекта — Python.
- `codegenerator` зависит от полноты target и project context, полученных от `codecollector`.
- `codegenerator` не выполняет project-level semantic validation.
- Generated tests проходят внешнюю проверку в `codecollector` и могут быть отклонены.
- Reuse hints являются soft context, если они не переданы как required contracts.
- Prompt section trace представлен полным prompt, context metrics и trim steps.
