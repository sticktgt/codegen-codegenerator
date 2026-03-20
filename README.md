# codegenerator

Узкий генератор кода и тестов для вызова из `codecollector`.

## Что делает
- принимает готовый `generation request` или `repair request`
- строит prompt для planner/coder/test generator/repair из файловых шаблонов
- вызывает локальную Ollama
- возвращает `code_artifact` и опционально `test_artifact`
- сохраняет trace, raw prompt/raw response и timing в `runs/`

## Конфигурация
Основной конфиг хранится в `config.yaml`. В нем задаются:
- Ollama endpoint и runtime options
- модели для planner/coder/test generator/repair
- пути к prompt templates
- default constraints
- параметры trace

## CLI
```bash
python -m codegenerator generate --request-file examples/generation_request.json
python -m codegenerator repair --request-file examples/repair_request.json
```

## Что не делает
- не ищет target в проекте
- не строит индекс проекта
- не управляет workspace изменяемого проекта
- не принимает решение о repair-loop по результатам тестов проекта


## ADR

### ADR-001. `codegenerator` отвечает только за генерацию
Проект не ищет target в кодовой базе и не управляет workspace изменяемого проекта.

### ADR-002. Решение о repair-loop принимает `codecollector`
`codegenerator` умеет выполнять одиночный `repair` по готовому request packet, но не владеет project-level циклом повторных попыток.

### ADR-003. Каноническая операция артефакта — symbol-level
Во внешнем контракте используются `replace_symbol`, `add_symbol`, `insert_after_symbol`. Ответы моделей с вариантами вроде `replace_function` нормализуются внутри `codegenerator`.
