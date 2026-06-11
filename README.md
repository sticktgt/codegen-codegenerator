# codegenerator

`codegenerator` — внешний генератор JSON-артефактов для `codecollector`. Он получает структурированный request-файл, собирает prompt, вызывает модель через совместимую с Ollama точку доступа, разбирает ответ, нормализует metadata, сохраняет trace и возвращает машинно-читаемый результат.

`codegenerator` не индексирует проект, не применяет изменения к файлам проекта, не запускает проверки проекта и не принимает решение о применении. Эти действия выполняет `codecollector`.

## Назначение

`codegenerator` используется в цепочке выполнения `codecollector` для четырёх задач:

1. Генерация производственного code artifact.
2. Генерация pytest-файла для code artifact.
3. Repair ранее сгенерированного code artifact по диагностике.
4. Advisory review ситуации, когда производственный код прошёл проверки, а generated test не прошёл.

## Основные возможности

- Сбор prompt по структурированному запросу.
- Планирование изменения производственного кода.
- Генерация code artifact.
- Генерация test artifact.
- Repair code artifact по диагностике.
- Advisory review ошибки generated test.
- Разбор JSON-ответов модели.
- Восстановление JSON из частично шумного ответа.
- Нормализация operation, координат, import changes и metadata artifact.
- Сохранение prompt, raw response, parsed response, normalized response и usage.
- Сохранение trace-файлов для анализа качества генерации.

## Режимы CLI

### Генерация производственного кода

```bash
python -m codegenerator generate \
  --request-file generation_request.json \
  --config config.yaml
```

Режим возвращает `code_artifact`.

### Генерация теста

```bash
python -m codegenerator generate-test \
  --request-file generation_test_request.json \
  --config config.yaml
```

Режим возвращает `test_artifact`.

### Repair производственного кода

```bash
python -m codegenerator repair \
  --request-file repair_request.json \
  --config config.yaml
```

Режим возвращает исправленный `code_artifact` или структурированную ошибку.

### Advisory review generated test failure

```bash
python -m codegenerator review-generated-test-failure \
  --request-file generated_test_review_request.json \
  --config config.yaml
```

Режим возвращает advisory JSON для ручной оценки ситуации, когда production artifact прошёл проверки, а generated test не прошёл.

## Входные данные

`codegenerator` читает только request-файл. Исходный код проекта, контекст, контракты, разрешённые вызовы и диагностику подготавливает `codecollector`.

Основные входные данные:

- пользовательский запрос;
- target file;
- target qualname;
- requested operation;
- insert scope;
- parent qualname;
- expected new symbol kind;
- module outline;
- source code целевого символа;
- related symbols;
- related tests;
- recommended tests;
- allowed API surface;
- contract context;
- model surfaces;
- previous artifact для repair;
- diagnostics для repair;
- generated test failure details для advisory review.

## Code artifact

`code_artifact` описывает изменение производственного кода:

```json
{
  "operation": "replace_symbol",
  "target_qualname": "editor.editor_window.EditorWindow.open_note",
  "target_file": "editor/editor_window.py",
  "code": "def open_note(self):\n    ...",
  "insert_after": null,
  "insert_scope": null,
  "expected_new_symbol_kind": null,
  "parent_qualname": "editor.editor_window.EditorWindow",
  "import_changes": []
}
```

Для `replace_symbol` поле `insert_after` должно быть `null`.

Для `insert_after_symbol` используются `insert_after`, `insert_scope`, `expected_new_symbol_kind` и `parent_qualname`.

`codegenerator` возвращает текст изменяемого или добавляемого символа в `code`. Применение этого текста к файлу выполняет `codecollector`.

## Import changes

Новые imports должны передаваться через `import_changes`, а не добавляться вручную вокруг символа вне согласованного формата artifact.

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

Нормализация исправляет распространённые формы metadata:

- `add_import` с `names` преобразуется в `add_from_import`;
- `add_import` с alias класса преобразуется в `add_from_import`;
- `add_import` для модуля с локальным from-import в code преобразуется в `add_from_import`;
- дублирующиеся или несовместимые metadata формы приводятся к единому виду, если это возможно.

`codegenerator` не должен тихо переписывать тело `code` для улучшения результата. Текст производственного кода остаётся ответственностью модели, а диагностика и repair используются для исправления ошибок.

## Test artifact

`test_artifact` содержит:

```json
{
  "file_path": "tests/test_generated_example.py",
  "source_code": "..."
}
```

Generated test должен проверять наблюдаемое поведение production artifact через прямой вызов целевого символа. Для методов допускается вызов несвязанного метода на локальном объекте-заглушке `self`, если настоящий экземпляр класса не нужен.

Тестогенерация предназначена для минимальной проверки нового поведения. Она не заменяет полноценный набор проектных тестов.

## Планирование production artifact

Перед генерацией производственного кода выполняется planning step. Планировщик возвращает строгий JSON с:

- operation;
- target file;
- target qualname;
- intent;
- constraints;
- insert scope;
- parent qualname;
- explicit requirements;
- technical constraints;
- reuse hints;
- forbidden assumptions;
- literals to preserve.

Планировщик отделяет требования пользователя от технического способа реализации. Подсказки по переиспользованию являются мягким контекстом, если они не переданы как обязательные контракты.

## Repair

Repair использует:

- previous artifact;
- error context;
- critical diagnostics;
- allowed API surface;
- contract context;
- authoritative target coordinates;
- исходный пользовательский запрос.

Перед repair выполняется repair planner. Он возвращает строгий JSON с:

- `status`;
- `repair_objective`;
- `allowed_calls_to_use`;
- `forbidden_calls`;
- `required_changes`;
- `reason`.

Если repair требует неизвестный проектный метод, неподтверждённый импорт или новый контракт, repair planner возвращает отказ от repair.

## Контрактный контекст

Prompt содержит компактный contract block с видимыми вызовами зависимостей и проекта, моделями и целевым символом. Приоритет получают вызовы, явно упомянутые в planner result, diagnostics или previous artifact.

Отдельный type-sensitive contract block управляется флагом:

```yaml
generation:
  type_sensitive_contract_hints_enabled: false
```

По умолчанию этот блок выключен.

## Trace

Trace сохраняет:

- request;
- prompt;
- raw response;
- parsed response;
- normalized response;
- context metrics;
- trimming steps;
- artifact metadata;
- import changes count;
- usage;
- ошибки парсинга и нормализации.

Trace-файлы используются для анализа prompt, ответа модели, нормализации и расхода токенов.

## Конфигурация

Основной файл настроек — `config.yaml`.

В конфигурации задаются:

- точка доступа модели;
- имена моделей;
- timeout;
- параметры генерации;
- лимиты prompt;
- настройки trace;
- настройки parser;
- настройки normalization;
- пути prompt-шаблонов;
- флаги экспериментальных prompt-блоков.

## Структура проекта

```text
codegenerator/
  README.md
  config.yaml
  pyproject.toml
  codegenerator/
    api/
    context/
    generation/
    llm/
    models/
    orchestration/
    parsing/
    prompts/
    trace/
    validation/
  prompts/
  tests/
  examples/
  runs/
```

Основные элементы:

- `api/cli.py` — CLI-команды;
- `api/service.py` — сервисный слой режимов генерации;
- `orchestration/generation_service.py` — общая оркестрация режимов;
- `generation/planner.py` — планирование production change;
- `generation/coder.py` — генерация production artifact;
- `generation/repair.py` — repair production artifact;
- `generation/test_generator.py` — генерация теста;
- `prompts/prompt_builder.py` — сбор prompt для production и repair;
- `prompts/review_prompt_builder.py` — сбор prompt для advisory review;
- `parsing/` — извлечение и восстановление JSON;
- `trace/` — сохранение trace-файлов;
- `models/` — request, result и artifact модели.

## Проверки проекта

```bash
python -m compileall -q codegenerator
python -m pytest -q
```

## Ограничения и недоработки

- Основной поддерживаемый язык production-проекта — Python.
- `codegenerator` работает только с контекстом, переданным в request-файле.
- Семантическая проверка уровня проекта выполняется в `codecollector`.
- Применение artifact к файлам выполняется в `codecollector`.
- Generated tests являются вспомогательными и могут быть отклонены внешней проверкой.
- Качество результата зависит от полноты context pack и контрактов.
- Экспериментальные prompt-блоки должны включаться только через конфигурацию.
