<!-- rtk-instructions v2 -->

# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:

```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)

```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (90-99% savings)

```bash
rtk cargo test          # Cargo test failures only (90%)
rtk vitest run          # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)

```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)

```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)

```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)

```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%)
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90%)

```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)

```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)

```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands

```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Codex sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to AGENTS.md
rtk init --global       # Add RTK to ~/.Codex/AGENTS.md
```

## Token Savings Overview

| Category         | Commands                       | Typical Savings |
| ---------------- | ------------------------------ | --------------- |
| Tests            | vitest, playwright, cargo test | 90-99%          |
| Build            | next, tsc, lint, prettier      | 70-87%          |
| Git              | status, log, diff, add, commit | 59-80%          |
| GitHub           | gh pr, gh run, gh issue        | 26-87%          |
| Package Managers | pnpm, npm, npx                 | 70-90%          |
| Files            | ls, read, grep, find           | 60-75%          |
| Infrastructure   | docker, kubectl                | 85%             |
| Network          | curl, wget                     | 65-70%          |

Overall average: **60-90% token reduction** on common development operations.

<!-- /rtk-instructions -->

# Monitor Cashback — инструкции для агента

## Язык

Отвечай всегда на русском языке.

## Контекст проекта

`monitor_cashback` — отдельный Python/FastAPI микросервис проекта Cashback Plugin / Савелло Клуб.

Основной WordPress/WooCommerce плагин находится здесь:

`F:\wamp64\www\kash-back\wp-content\plugins\cash-back`

Канонический Obsidian vault проекта находится здесь:

`F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian`

Важно: **не создавай локальную копию `obsidian/` в этом репозитории**. Если нужна новая заметка по сервису, создавай или обновляй её в общем vault:

`F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\knowledge\integrations\monitor-cashback.md`

## Общее описание системы

Cashback Plugin — это комплексная система кэшбэк-сервиса, состоящая из нескольких компонентов:

1. **WordPress/WooCommerce плагин** — пользовательский интерфейс, административная панель, управление пользователями, выплатами, партнёрской программой, транзакциями и внутренними REST API.
2. **Python/FastAPI микросервисы** — отдельные сервисы проекта: webhook receiver, workers, мониторинг цен/кэшбэка, интеграционные сервисы и фоновые обработчики.
3. **Инфраструктурный стек** — Docker, Redis, MariaDB, Traefik/Nginx, мониторинг, бэкапы и деплой.

Этот сервис разрабатывается как часть общей Cashback-системы, а не как изолированное приложение. Любые изменения API, БД, Redis-очередей, форматов сообщений, контрактов с WordPress-плагином или CPA-сетями должны быть отражены в Obsidian.

## Принципы разработки

- Безопасность прежде всего.
- Fail-closed вместо fail-open.
- Транзакционность критических операций.
- Идемпотентность публичных запросов, фоновых задач и повторных обработок.
- Аудит чувствительных действий.
- Валидация на всех уровнях: HTTP schema, service layer, DB constraints.
- Authenticated encryption (GCM) для секретов и чувствительных данных, если сервис хранит или обрабатывает такие данные.
- Rate limiting на всех публичных эндпоинтах.
- Structured logging без утечек PII, токенов, ключей, платёжных данных и cookies.
- Секреты только через env/config/secret storage. Не хардкодить ключи, токены и пароли.
- Внешние сбои обрабатывать явно: timeout, retry, backoff, DLQ или terminal status.
- Денежные, балансовые, CPA-transaction и payout-related операции должны иметь проверяемую идемпотентность.
- Любая интеграция с WordPress-плагином должна иметь понятный контракт, тесты и документацию.
- Если невозможно по какойто причине получить данные, не выдумывать или придумывать никаких данных, остановиться и спросить об этом и предложить пути решения или получения этих данных.
- Если видишь лучший вариант решения чем описан в промпте, обязательно остановиться и предлагать его.

## Python/FastAPI правила

- Используй типизацию и явные модели данных.
- Входящие payload валидируй через Pydantic или существующий проектный слой.
- Не доверяй query/body/header данным без нормализации.
- Разделяй слои:
  - FastAPI route/controller;
  - service/business logic;
  - repository/db layer;
  - integration clients;
  - background workers.
- Не пиши бизнес-логику прямо в route handler.
- Для внешних HTTP-запросов задавай timeout, retry-policy и обработку 4xx/5xx.
- Для фоновых воркеров обеспечивай idempotency key, dedup identity или иной проверяемый механизм exactly-once/at-least-once safety.
- Для Redis queues фиксируй формат сообщения и версионируй его при изменениях.
- Для БД используй parameterized queries или ORM expressions. Не собирай SQL строками.
- Миграции должны быть обратимыми или иметь явный forward-only rationale.
- Тесты должны покрывать happy path, duplicate/retry path, invalid input, external failure, idempotency и race-sensitive сценарии.
- Для локальной проверки предпочитай `rtk python -m pytest -q` или более узкие targeted-тесты.

## Workflow и разрешения на сервере

**Ключевое правило:** на сервере никаких изменений не делать. Все правки кода/конфигов выполняются только локально на компьютере, затем синхронизируются через git.

### Репозитории

- **Плагин:** локально `F:\wamp64\www\kash-back\wp-content\plugins\cash-back` → репо `Igor-creato/cash-back` (https://github.com/Igor-creato/cash-back)
- **Стэк (инфраструктура):** локально `F:\cash-back\deploy` → репо `Igor-creato/deploy-cashback` (https://github.com/Igor-creato/deploy-cashback)
- **Monitor Cashback:** локально `F:\cash-back\monitor_cashback` → репозиторий этого Python/FastAPI микросервиса.

### Последовательность правок

| Что меняется                          | Шаги                                                                                                                                                            |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Monitor Cashback**                  | 1) локальный компьютер → 2) тесты → 3) коммит → 4) пуш.                                                                                                         |
| **Плагин**                            | 1) локальный компьютер → 2) коммит → 3) пуш. Дальше GitHub Actions сами выкатывают на сервер.                                                                   |
| **Стэк**                              | 1) локальный компьютер → 2) коммит → 3) пуш → 4) `git pull` на сервере. Без шага 4 правка на сервер не приедет.                                                 |
| **Серверная правка по явной команде** | 1) правка на сервере → 2) `git commit` + `git push` с сервера → 3) `git pull` на локальном компьютере. Это нужно, чтобы локальный клон и сервер не расходились. |

### Обязательные шаги после написания кода

Для любой задачи, где агент изменял код, конфиги, миграции, тесты или проектную документацию, перед завершением работы обязательно выполнить весь цикл:

1. Проверить изменения на ошибки: targeted-команды, линтеры, статический анализ, сборка или другие релевантные проверки для затронутой области.
2. Прогнать релевантные тесты: сначала targeted-тесты по изменённому модулю, затем полный или максимально уместный suite проекта.
3. Если любая проверка или тест упали — исправить ошибку в минимальном scope.
4. После исправлений повторно прогнать упавшие проверки и финальный набор релевантных тестов.
5. Делать `git commit` только когда все релевантные проверки и тесты зелёные.
6. После успешного commit выполнить `git push` в соответствующий remote/branch, если пользователь явно не запретил push или не выбран PR-only workflow.
7. Сохранить сессию в Obsidian: создать заметку в `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\sessions\`, обновить `00-home\текущие приоритеты.md`, а при изменении архитектуры/API/БД/Redis/очередей/деплоя — обновить соответствующую заметку `atlas/` или `knowledge/`.

Запрещено завершать coding-task словами «готово», «исправлено», «проверено», «закоммичено» или «запушено», если соответствующая команда не была запущена в этой же сессии и её результат не подтверждён. Если проверки остаются красными, не делать commit/push; вместо этого остановиться и сообщить пользователю, что именно падает.

### SSH-доступ к серверу

**Единственный ключ:** `F:\cash-back\.test_ssh\admin_vps_claude`

**Команда:** `ssh -i F:/cash-back/.test_ssh/admin_vps_claude -p 56789 igor@5.35.124.64`

Если ключ не пускает (`Permission denied (publickey)`) — **сразу остановиться и сообщить пользователю**. Не пробовать другие ключи, не искать альтернативы (`~/.ssh/`, `ssh-agent`, другие пути в `F:\`), не запускать `ssh -vv` для диагностики чужих ключей. Просто сообщение: «SSH-доступ закрыт, нужен разбан / перевыпуск ключа» и ждать пока пользователь даст доступ.

Возможные причины закрытия: CrowdSec на стэке банит IP после быстрых retry'ев или подозрительной активности; fail2ban; ключ ротирован.

### Что можно на сервере без явной команды

- Читать логи (`docker logs`, файлы логов).
- Проверять данные read-only запросами (`SELECT`, read-only CLI/API commands).
- Смотреть `git status` / `git log`.
- Выполнять non-modifying диагностику.
- Создавать временные файлы для тестов — но удалять их после теста, если они не понадобятся для будущих тестов.

### Что можно на сервере ТОЛЬКО при явной команде пользователя

- Любая правка файлов (включая конфиги стэка, файлы сервиса, env-файлы).
- Любые DDL/UPDATE/DELETE/INSERT в БД.
- Команды с побочными эффектами: migrations, queue replay, worker restart, cache flush, `docker compose up/down/restart`, `docker compose exec` с правкой.
- Любой `git commit`/`push` от имени серверного пользователя.

Если в ходе работы выяснилось, что без серверной правки не обойтись — остановиться, описать что и зачем, и дождаться явного разрешения.

## При сжатии всегда сохраняй

- Текущую задачу и принятые решения.
- Список изменённых файлов.
- Какие тесты запускались.
- Какие заметки Obsidian были прочитаны или обновлены.
- Открытые вопросы.

## Obsidian Knowledge Vault

**Канонический путь:** `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian`

> Это основной источник контекста. Читай отсюда — не из локальной копии и не из `context/`, если в Obsidian есть нужная информация.

### Карта vault'а — что где искать

| Тема                                                                 | Файл в Obsidian                                                        |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Архитектура, поток данных                                            | `atlas/архитектура системы.md`                                         |
| Стек технологий                                                      | `atlas/технологический стек.md`                                        |
| База данных, таблицы, триггеры                                       | `atlas/база данных.md`                                                 |
| Деплой, Docker, мониторинг                                           | `atlas/деплой и инфраструктура.md`                                     |
| Ядро плагина, UUID v7, endpoints                                     | `atlas/ядро плагина.md`                                                |
| Webhook Receiver (Python)                                            | `knowledge/integrations/webhook-receiver.md`                           |
| Monitor Cashback (Python/FastAPI)                                    | `knowledge/integrations/monitor-cashback.md`                           |
| Internal REST API для микросервисов                                  | `knowledge/integrations/internal-rest-api-price-monitor.md`            |
| Admitad / EPN / Advcake интеграции                                   | `knowledge/integrations/admitad.md`, `epn.md`, `advcake.md`            |
| API-клиент reconciliation                                            | `knowledge/integrations/api-клиент reconciliation.md`                  |
| REST API браузерного расширения                                      | `knowledge/integrations/rest-api детали.md`                            |
| Браузерное расширение                                                | `knowledge/integrations/браузерное расширение.md`                      |
| Вся admin-панель                                                     | `knowledge/admin/панель обзор.md`                                      |
| Выплаты (admin)                                                      | `knowledge/admin/управление выплатами.md`                              |
| Транзакции (admin)                                                   | `knowledge/admin/управление транзакциями.md`                           |
| Сверка баланса и ручная корректировка (admin)                        | `knowledge/admin/сверка баланса и корректировка.md`                    |
| Пользователи, бан (admin)                                            | `knowledge/admin/управление пользователями.md`                         |
| Статистика KPI                                                       | `knowledge/admin/статистика и kpi.md`                                  |
| API синхронизация                                                    | `knowledge/admin/api валидация и синхронизация.md`                     |
| Health check БД                                                      | `knowledge/admin/health-check целостность бд.md`                       |
| Партнёрская программа (admin)                                        | `knowledge/admin/партнёрская программа.md`                             |
| Уведомления (admin)                                                  | `knowledge/admin/уведомления.md`                                       |
| Заявки кэшбэка (admin)                                               | `knowledge/admin/заявки кэшбэка.md`                                    |
| Партнёры CPA-сети (admin)                                            | `knowledge/admin/управление партнёрами cpa.md`                         |
| Shop Importer v12 (автоимпорт магазинов)                             | `knowledge/integrations/shop-importer.md`                              |
| Поддержка (admin)                                                    | `knowledge/admin/поддержка.md`                                         |
| Защита / Антифрод + капча (admin)                                    | `knowledge/admin/защита антифрод.md`                                   |
| Личный кабинет (все вкладки, шорткод баланса)                        | `knowledge/frontend/личный кабинет пользователя.md`                    |
| Раздельные /login/ и /register/ (sc-auth-pages)                      | `knowledge/frontend/раздельные login-register sc-auth-pages.md`        |
| Вывод кэшбэка (фронтенд)                                             | `knowledge/patterns/вывод кэшбэка.md`                                  |
| История покупок/выплат                                               | `knowledge/patterns/история покупок и выплат.md`                       |
| Антифрод: логика                                                     | `knowledge/patterns/антифрод система.md`                               |
| Антифрод: числовые пороги                                            | `knowledge/patterns/антифрод настройки и пороги.md`                    |
| Антифрод: тумблеры подсистем                                         | `knowledge/patterns/антифрод тумблеры подсистем.md`                    |
| Claims: процесс                                                      | `knowledge/patterns/claims модуль.md`                                  |
| Claims: скоринг с числами                                            | `knowledge/patterns/claims скоринг детали.md`                          |
| Реферальная программа                                                | `knowledge/patterns/реферальная программа.md`                          |
| Idempotency pattern                                                  | `knowledge/patterns/idempotency pattern.md`                            |
| Общая пагинация плагина                                              | `knowledge/patterns/общая пагинация.md`                                |
| FOR UPDATE блокировки                                                | `knowledge/patterns/for-update блокировки.md`                          |
| Ledger-first баланс (источник правды)                                | `knowledge/patterns/ledger-first баланс.md`                            |
| Grey scoring: числа                                                  | `knowledge/patterns/grey scoring числа и пороги.md`                    |
| Шифрование AES-256                                                   | `knowledge/patterns/шифрование детали.md`                              |
| Trigger fallbacks (бан/баланс)                                       | `knowledge/patterns/trigger-fallbacks детали.md`                       |
| User profile defaults (rate/min_payout)                              | `knowledge/patterns/user-profile-defaults.md`                          |
| Удаление плагина                                                     | `knowledge/patterns/удаление плагина.md`                               |
| Шорткоды                                                             | `knowledge/patterns/шорткоды плагина.md`                               |
| Партнёрские URL WooCommerce                                          | `knowledge/patterns/партнёрские url woocommerce.md`                    |
| Продукт, бизнес                                                      | `knowledge/business/продукт кэшбэк сервис.md`                          |
| CPA-монетизация                                                      | `knowledge/business/cpa-сети и монетизация.md`                         |
| Типичные баги                                                        | `knowledge/debugging/типичные баги и решения.md`                       |
| Диагностика                                                          | `knowledge/debugging/диагностика производительности.md`                |
| Архитектурные решения (ADR)                                          | `knowledge/decisions/`                                                 |
| Legal compliance ADR (152/38/161/149-ФЗ, ГК 437)                     | `knowledge/decisions/legal-compliance-152fz.md`                        |
| Legal: append-only журнал согласий                                   | `knowledge/patterns/legal-consent-log.md`                              |
| Legal: defensive аудит сторонних форм                                | `knowledge/patterns/legal-third-party-audit.md`                        |
| Legal: admin-раздел «Юр. документы»                                  | `knowledge/admin/юр документы.md`                                      |
| User anonymization (152-ФЗ + soft-delete)                            | `knowledge/patterns/user-anonymization.md`                             |
| Bug: AJAX payload собран вручную (теряются поля)                     | `knowledge/debugging/ajax-payload-manual-сборка.md`                    |
| Bug: nginx upstream keepalive vs FPM max_children                    | `knowledge/debugging/nginx-fpm-keepalive-pool-starvation.md`           |
| Bug: Wordfence WAF блокирует FPM на 25 сек                           | `knowledge/debugging/wordfence-waf-blocking-curl-russia.md`            |
| Bug: msmtp logfile leak через webroot                                | `knowledge/debugging/msmtp-syslog-leak-webroot.md`                     |
| Bug: WoodMart Loop Builder fatal на пустом каталоге                  | `knowledge/debugging/woodmart-loop-builder-empty-catalog-fatal.md`     |
| Methodology: Explore-агенты обрезают длинные файлы → false positives | `knowledge/debugging/explore-agent-truncated-files-false-positives.md` |

### При старте каждой сессии

1. Прочитай `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\00-home\index.md`.
2. Прочитай `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\00-home\текущие приоритеты.md`.
3. Если задача касается `monitor_cashback`, прочитай или создай в общем vault заметку `knowledge/integrations/monitor-cashback.md`.
4. Если задача касается FastAPI/Python микросервисов, прочитай `knowledge/integrations/webhook-receiver.md` как ближайший существующий пример архитектуры.
5. Если задача касается конкретного модуля — найди нужную заметку по карте выше и прочитай её.
6. Не читай `context/` без необходимости — обращайся туда только если в Obsidian заметке не хватает деталей.
7. Не создавай локальную папку `obsidian/` в `F:\cash-back\monitor_cashback`.
8. Отвечай всегда на русском языке.

### При завершении сессии (пользователь: "сохрани сессию")

1. Создай заметку в `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\sessions\` с датой.
2. Обнови `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\00-home\текущие приоритеты.md`.
3. Если принято архитектурное решение → создай ADR в `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\knowledge\decisions\`.
4. Если найден и исправлен баг → создай заметку в `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\knowledge\debugging\`.
5. Если изменилась архитектура, API, БД, Redis-контракт, очередь или деплой → обнови нужную заметку в `atlas/` или `knowledge/` общего vault.

# Ruflo Integration

When working on multi-file tasks or complex features, use ToolSearch to find and invoke ruflo MCP tools.
Key tools: memory_store, memory_search, hooks_route, swarm_init, agent_spawn.
Check system-reminder tags for [INTELLIGENCE] pattern suggestions before starting work.

<!-- SPECKIT START -->

For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan

<!-- SPECKIT END -->
