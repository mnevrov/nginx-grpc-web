# Agent Prompt — Start Here

Ты работаешь над `ngx_http_grpc_web_module`.

## Контекст

Production сегодня использует:

```text
React grpc-web -> NGINX -> Envoy grpc_web filter -> native gRPC services
```

Цель:

```text
React grpc-web -> NGINX + ngx_http_grpc_web_module -> native gRPC services
```

React-клиент должен остаться без изменений.

## Перед началом

Обязательно прочитай:

- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/PROTOCOL_CONTRACT.md`
- `docs/TEST_STRATEGY.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/DEFINITION_OF_DONE.md`

Затем:

1. определи текущий milestone;
2. запусти доступные тесты;
3. посмотри git status/diff;
4. изучи актуальные официальные исходники NGINX для затрагиваемых hooks;
5. изучи соответствующий behavior в Envoy grpc_web filter;
6. сформулируй минимальный change;
7. сначала добавь/уточни тест;
8. только потом реализуй код.

## Главный запрет

Не решай несовместимость изменением React. Любая frontend-specific правка для NGINX означает архитектурную ошибку.

## Формат завершения

В конце сообщи:

- milestone/scope;
- изменённые файлы;
- какие тесты добавлены;
- какие команды реально запускались;
- результат sanitizer/build tests;
- известные ограничения;
- следующий минимальный шаг.

Не утверждай, что behavior production-ready, если browser+differential tests ещё не зелёные.
