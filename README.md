# post-draft-bot

TG-бот, который из голосовых и тезисов автора собирает черновик поста в его авторском голосе — не «ИИшный».

Архитектура: **3 LLM-агента в линии** + **самообучение**.

```
brief (текст + расшифровка голосовых)
   │
   ▼
┌───────────┐   жанр, крюк, структура, key_points,
│  Planner  │   must_keep_phrases, тон, тип концовки
└─────┬─────┘
      ▼
┌───────────┐  получает план + few-shot из 2 эталонов + анти-эталон
│  Writer   │  ──► draft
└─────┬─────┘
      ▼
┌───────────┐  rubric -10..+10 + must_fix + ai_markers_found
│  Critic   │  ──► если score < 5 — назад в Writer (до 2 раз)
└─────┬─────┘
      ▼
   финальный draft (max score)
      │
      ▼  юзер ставит rating ≥ 7
┌───────────┐
│  Stylist  │  извлекает хорошие фразы → в базу
└───────────┘  следующие генерации видят их как часть голоса
```

## Что внутри

```
post_bot/
├── config.py              # pydantic-settings из .env
├── __main__.py            # запуск: init_db + seed + polling
├── cli.py                 # smoke-test без TG: python -m post_bot.cli "тезисы"
├── db/
│   ├── models.py          # Brief, Draft, Post, StyleExample, GoodPhrase, BadPhrase
│   ├── engine.py          # async SQLAlchemy
│   └── repository.py      # CRUD-обёртки
├── llm/
│   ├── client.py          # AsyncOpenAI + retry, авто-адаптация под reasoning-модели
│   ├── stt.py             # Whisper API
│   ├── prompts.py         # все system-промпты + анти-эталон
│   ├── planner.py         # Planner agent — структурный план поста
│   ├── writer.py          # Writer agent — пишет по плану + few-shot
│   ├── critic.py          # Critic agent — оценивает по rubric'у
│   └── stylist.py         # извлекает good_phrases из одобренных постов
├── pipeline/
│   ├── orchestrator.py    # Writer↔Critic loop + сохранение в БД
│   └── style_retrieval.py # подбор few-shot примеров по жанру
└── bot/
    ├── handlers.py        # /new, /done, /cancel, /history + сбор голосовых
    ├── states.py          # FSM
    ├── keyboards.py       # inline-кнопки оценки -10..+10
    ├── messages.py        # тексты бота
    └── middleware.py      # whitelist по user_id

data/
├── seed_posts.py          # 2 эталонных поста + 1 анти-эталон ChatGPT
├── anti_patterns.py       # ИИ-маркеры + banned_words
└── seed.py                # сидинг БД при первом запуске
```

## Установка

```bash
cd post-draft-bot
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -e .[dev]
```

## Конфиг

```bash
cp .env.example .env
```

Заполнить:
- `BOT_TOKEN` — у [@BotFather](https://t.me/BotFather): `/newbot` → токен.
- `ALLOWED_USER_IDS` — CSV из TG user_id (у [@userinfobot](https://t.me/userinfobot)). Сначала Артём + Андрей + ты.
- `OPENAI_API_KEY` — твой ключ.
- (опц.) поменять `MODEL_WRITER` / `MODEL_CRITIC` если хочется gpt-4o-mini для дешевизны или o1 для качества.

## Запуск

**Бот:**
```bash
python -m post_bot
```

**CLI smoke-test (без TG, печатает в консоль):**
```bash
python -m post_bot.cli "Тема: почему первые 30 дней на YouTube — это сжигание денег. Тезисы: 1) не нужен дорогой монтаж 2) сценарий важнее обложки 3) копируют тренды трёхмесячной давности"
```

**Тесты:**
```bash
pytest                          # юнит-тесты (без LLM-вызовов)
pytest -k llm                   # регрессия Critic + smoke pipeline (нужен OPENAI_API_KEY)
```

## UX бота

Управление — кнопками. Команды есть как алиасы, но не главный путь.

**`/start`** показывает главное меню:
- 📝 **Новый пост** — открывает бриф.
- 📚 **Добавить пример** — учишь бот своему стилю: кидаешь хороший пост → жанр → оценка. Если оценка ≥ 7, Stylist извлекает из него хорошие фразы для будущих генераций.
- 📋 **Мои правила** — все активные директивы, выученные из твоих комментариев.
- 📜 **История** — последние 5 постов с оценками.

**Поток «Новый пост»:**
1. Выбор длины (`~200` / `~400` / `~600` / `Авто`) — кнопками.
2. Кидаешь тезисы текстом и/или голосовые. Каждое голосовое расшифровывается Whisper'ом, бот показывает превью.
3. «✅ Готово, генерируй».
4. Через 20-40 сек — черновик с заголовком (жанр, score критика, число итераций).
5. Кнопки оценки **-10..+10** + «💬 Комментарий» + «💾 В образцы» + «🆕 Новый пост» / «🏠 Меню».

**💬 Комментарий** — пишешь свободным текстом что не так. LLM извлекает 1-3 директивы (`do`/`don't`), сохраняет в `UserDirective` → подкладывается в Planner+Writer на всех будущих генерациях.

**Команды как алиасы:** `/new` `/done` `/cancel` `/history` `/directives` — работают, но в обычном flow не нужны.

## Как «не звучит как ИИ»

1. **Planner перед Writer'ом** — структурное решение (жанр, крюк, концовка) отделено от стилистического. Writer фокусируется на голосе, не на композиции.
2. **Few-shot из 2 реальных постов Артёма + 1 анти-эталон** — Writer видит и «как надо», и «как ChatGPT обычно пишет». Анти-эталон взят из переписки, где Артём прямо забраковал такой текст.
3. **Жёсткий промпт** с списком запрещённых конструкций (заголовки «Кто Мы? 🏆», тройки прилагательных, «Подписывайтесь!», канцелярит).
4. **Жёсткий лимит эмодзи** — макс. 4-6 на пост, никогда внутри предложения, никогда на каждой строке списка. Critic снижает `anti_ai` если перебор.
5. **Критик** ловит то, что Writer пропустил — отдельная модель с rubric'ом на 4 оси (liveliness / authenticity / originality / anti_ai). При score < 5 отправляет обратно на rewrite с конкретным feedback.
6. **Самообучение через два канала:**
   - **Style examples + good_phrases** — при оценке ≥ 7 пост идёт в базу примеров, Stylist выдёргивает хорошие обороты.
   - **User directives** — из текстовых комментариев автора LLM извлекает правила («больше цифр», «не использовать слово ниша»). Они подкладываются в Planner+Writer на каждой генерации.

## Регрессионная защита промптов

`tests/test_critic_on_seed_posts.py` — Critic ставит обоим эталонам Артёма ≥ 7. Если упал — Critic-промпт сломан.

`tests/test_critic_rejects_bad_post.py` — Critic ставит анти-эталону («Кто Мы? 👨‍💻») ≤ -3 и находит ИИ-маркеры. Если упал — rubric слишком мягкий.

`tests/test_pipeline_smoke.py` — full pipeline на типичных тезисах не выдаёт очевидные ИИ-маркеры.

## Деплой на Railway

Бот работает в polling-режиме, HTTP-портов не открывает, дополнительных сервисов не требует.

**Шаги:**

1. Создать новый проект на Railway → **Deploy from GitHub repo** → выбрать этот репозиторий.
2. Сразу после первого билда добавить **Volume**:
   - Settings → Volumes → New Volume.
   - Mount path: `/data`.
   - Size: 1GB (для начала достаточно — SQLite + voice cache).
3. Переменные окружения (Variables):
   ```
   # обязательные
   BOT_TOKEN=<токен от BotFather>
   OPENAI_API_KEY=<sk-...>
   ALLOWED_USER_IDS=<csv user_id: твой, Артёма, Андрея>
   DB_PATH=/data/post_bot.sqlite

   # опционально — прокси для OpenAI (если прямой API недоступен из РФ)
   # пример: OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1
   OPENAI_BASE_URL=

   # опционально — модели
   MODEL_WRITER=gpt-4o
   MODEL_CRITIC=gpt-4o-mini
   MODEL_STYLIST=gpt-4o-mini
   MODEL_STT=whisper-1

   # опционально — pipeline
   MAX_REWRITE_ITERATIONS=2
   MIN_ACCEPTABLE_SCORE=5
   AUTO_SAVE_AS_EXAMPLE_THRESHOLD=7
   LOG_LEVEL=INFO
   ```
   **Важно:** после добавления/изменения переменных — **Deploy → Redeploy**, иначе Railway не подхватит новые значения.
4. Redeploy. В логах должно появиться `Bot @username ready. Polling…`.

**Что в репозитории под Railway:**
- [Procfile](Procfile) — `worker: python -m post_bot`.
- [nixpacks.toml](nixpacks.toml) — Python 3.11 + venv + pip install requirements.txt.
- [railway.toml](railway.toml) — `restartPolicyType = ALWAYS`, healthcheck отключён (нет HTTP).
- [requirements.txt](requirements.txt) — runtime-зависимости.
- [runtime.txt](runtime.txt) — `python-3.11`.

**Альтернатива (VPS):**
```bash
git clone https://github.com/kbeautyg/botwriter.git
cd botwriter
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить
python -m post_bot
```
Для автозапуска — systemd unit или `pm2 start "python -m post_bot" --name post-bot`.

**Webhook вместо polling** — потом, когда понадобится >50 RPS (актуально вряд ли).

## Идея на v2 (если зайдёт)

- Эмбеддинги для style_retrieval (сейчас по жанру → потом по семантике темы).
- Diff edited_text vs original → извлечь чем пользователь заменил — пополнить BadPhrase автоматически.
- A/B: две модели Writer одновременно, Артём выбирает → собирается preference dataset.
- Веб-админка для просмотра истории/оценок (можно повторно использовать стек finish-bot-2: FastAPI + jinja).
