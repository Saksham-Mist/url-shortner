# URL Shortener API

A production-style URL shortener built with FastAPI, async SQLAlchemy, and PostgreSQL (Neon). Given a long URL, it returns a short code that 302-redirects to the original and logs every click for analytics — total clicks, clicks per day, and top referrers.

Built as a learning project to go deep on things that are easy to hand-wave in a tutorial: collision-free ID generation, why redirects use 302 instead of 301, async session handling with background tasks, and schema migrations with Alembic.

## Features

- **Shorten a URL** — `POST /api/v1/shorten` turns any `http(s)` URL into a 7-character short code.
- **Redirect + click tracking** — `GET /{shortCode}` 302-redirects to the original URL and logs the click (referrer, user agent, IP, timestamp) without adding latency to the redirect itself.
- **Analytics** — `GET /api/v1/stats/{shortCode}` returns total clicks, a day-by-day breakdown, and the top referring sources for a given code.
- **Health check** — `GET /health` for uptime monitors / load balancers.
- **Collision-free codes** — short codes are derived from the database's own row sequence, not randomly generated, so there's no retry-on-collision logic anywhere (see [What I Learned](#what-i-learned)).
- **Schema-versioned** — every table change goes through an Alembic migration, not an app-level `create_all()`.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | FastAPI | Async-native, Pydantic-validated request/response models, automatic OpenAPI docs |
| Language | Python 3.14, fully type-hinted | Editor/mypy support, self-documenting function signatures |
| ORM | SQLAlchemy 2.0 (async) | Modern `Mapped[...]`/`mapped_column` typed models, async session support |
| DB driver | asyncpg | Fastest Postgres driver available to SQLAlchemy's async engine |
| Database | PostgreSQL via [Neon](https://neon.tech) (serverless Postgres) | Managed, branchable, free tier suitable for a portfolio project |
| Validation | Pydantic v2 | `HttpUrl` type does scheme/format validation for free; separates API contract (`schemas.py`) from DB models (`models/url.py`) |
| Config | pydantic-settings | Typed settings loaded from `.env` / real env vars, single source of truth |
| Migrations | Alembic (async template) | Versioned, reviewable schema changes instead of `Base.metadata.create_all()` |
| Testing | pytest + pytest-asyncio + httpx.AsyncClient | Async test functions hitting the app in-process over ASGI, no real server needed |
| Deployment | Railway | `Procfile`-driven deploy; migrations run automatically before the app starts |

## Architecture

```
main.py                        FastAPI app instance, route registration
app/
├── config.py                  Settings (env vars / .env), incl. Neon SSL + asyncpg URL handling
├── database.py                Async engine, session factory, get_db dependency
├── models/url.py              SQLAlchemy ORM models: Url, Click
├── schemas.py                 Pydantic request/response models (API contract)
├── services/shortener_service.py   Business logic: code generation, click recording, stats
└── routes/shorten.py          HTTP layer: all 4 endpoints
migrations/                    Alembic migration environment + versions/
tests/                         pytest suite (conftest.py + test_*.py)
```

**Layering, and why it's split this way:**

- **`schemas.py` vs `models/url.py`** — the ORM model describes what's *stored* (includes internal fields like `is_active`, `expires_at`); the Pydantic schema describes what's *exposed over HTTP* (camelCase, no internal fields). Collapsing them into one class would mean every DB migration risks becoming a breaking API change, and vice versa.
- **`routes/` → `services/` → DB**, not routes talking to the DB directly — routes stay a thin HTTP translation layer (status codes, request/response shapes) with no logic to unit test; `services/` holds business logic that's testable without spinning up FastAPI at all.
- **`config.py` as the single source of truth for `DATABASE_URL`** — both the app (`database.py`) and the migration tooling (`migrations/env.py`) import `get_settings()` rather than each parsing the connection string independently. One place handles the Neon-specific quirks (see [Database Setup](#database-setup-neon-postgresql)).

## Setup Instructions

```bash
# 1. Clone the repo
git clone https://github.com/Saksham-Mist/url-shortner.git
cd url-shortner

# 2. Create and activate a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
# for running tests too:
pip install -r requirements-dev.txt

# 4. Configure environment variables
```

Create a `.env` file in the project root (never commit this — it's gitignored):

```bash
DATABASE_URL=postgresql://<user>:<password>@<neon-host>/<dbname>?sslmode=require
```

Get this from your [Neon](https://neon.tech) project dashboard → **Connection Details**. See [Database Setup](#database-setup-neon-postgresql) below for why the URL needs a bit of rewriting before it reaches `asyncpg`.

## Running Locally

Apply migrations, then start the dev server:

```bash
alembic upgrade head
uvicorn main:app --reload
```

The API is now live at `http://localhost:8000`. Interactive docs (auto-generated by FastAPI from the Pydantic schemas) are at `http://localhost:8000/docs`.

## Running Tests

```bash
pytest
# or, more explicitly:
python -m pytest tests/ -v
```

**Important caveat**: the test suite currently runs against the same live database as `DATABASE_URL` in `.env` — there's no separate test database yet. `tests/conftest.py` truncates `urls` and `clicks` before *and* after every test, so it's safe for solo development but **do not point this at a database whose data you want to keep**, and don't wire it into shared CI until a dedicated `TEST_DATABASE_URL` is set up (tracked in [Next Steps](#next-steps)).

## API Endpoints

### `POST /api/v1/shorten`

Creates a short code for a long URL. Returns `201 Created`.

```bash
curl -X POST http://localhost:8000/api/v1/shorten \
  -H "Content-Type: application/json" \
  -d '{"longUrl": "https://example.com/articles/some-very-long-slug?utm_source=newsletter"}'
```

```json
{
  "shortCode": "08gvE03",
  "shortUrl": "http://localhost:8000/08gvE03"
}
```

Invalid or non-`http(s)` URLs (including `javascript:` / `ftp:` schemes) are rejected with `422 Unprocessable Entity`:

```bash
curl -X POST http://localhost:8000/api/v1/shorten \
  -H "Content-Type: application/json" \
  -d '{"longUrl": "not-a-url"}'
```

```json
{
  "detail": [
    {
      "type": "url_parsing",
      "loc": ["body", "longUrl"],
      "msg": "Input should be a valid URL, relative URL without a base",
      "input": "not-a-url"
    }
  ]
}
```

### `GET /{shortCode}`

Redirects to the original URL with `302 Found` and logs the click in the background. Use `-D -` to see the response headers instead of following the redirect:

```bash
curl -D - -o /dev/null "http://localhost:8000/08gvE03"
```

```
HTTP/1.1 302 Found
location: https://example.com/articles/some-very-long-slug?utm_source=newsletter
```

Unknown codes return `404 Not Found`.

### `GET /api/v1/stats/{shortCode}`

```bash
curl http://localhost:8000/api/v1/stats/08gvE03
```

```json
{
  "shortCode": "08gvE03",
  "totalClicks": 3,
  "clicksByDay": [
    { "day": "2026-08-01", "clicks": 3 }
  ],
  "topReferrers": [
    { "referrer": "https://google.com", "clicks": 2 },
    { "referrer": "https://twitter.com", "clicks": 1 }
  ]
}
```

### `GET /health`

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok" }
```

## Database Setup (Neon PostgreSQL)

The project uses [Neon](https://neon.tech) — serverless Postgres with a generous free tier, good for a portfolio project since it doesn't need to run 24/7. Two Postgres-specific things the schema relies on (worth knowing, since a from-scratch SQLite swap wouldn't work here):

- **`INET`** column type for `clicks.ip_address` (native IP address type, not just a string).
- **`nextval('urls_id_seq')`** called directly in `shortener_service.create_short_url()` to get a row's id *before* inserting, so the derived short code can be written in the same `INSERT` as the row itself (see [What I Learned](#what-i-learned)).

**One connection-string wrinkle worth understanding**: Neon's connection string uses `sslmode=require`, a `libpq`/`psycopg2` convention. `asyncpg` (the async driver this project uses) doesn't understand `sslmode` as a query parameter at all — leaving it in the URL raises a connect error. `app/config.py` strips it and rewrites the URL:

```python
# app/config.py
@property
def database_url(self) -> str:
    url = self.raw_database_url
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return re.sub(r"[?&]sslmode=[^&]*", "", url)
```

SSL itself is turned back on separately, via `connect_args={"ssl": True}` when the engine is created in `app/database.py` (and again in `migrations/env.py` for Alembic) — so TLS is still enforced, just configured the way `asyncpg` expects it rather than the way `libpq` expects it.

## Alembic Migrations

Schema changes are versioned migrations, not an app-level `create_all()`. `migrations/env.py` imports `Base.metadata` (via `app/models/url.py`) and the same `DATABASE_URL`-derived settings the app itself uses, so `--autogenerate` diffs your actual models against the live database.

```bash
# After changing a model in app/models/url.py, generate a migration:
alembic revision --autogenerate -m "describe the change"

# ALWAYS read the generated file in migrations/versions/ before applying --
# autogenerate is a diffing heuristic, not infallible (it won't always catch
# column-type-precision changes, for example).

# Apply pending migrations:
alembic upgrade head

# View migration history:
alembic history
# <base> -> 615ed06d7cdc (head), initial schema

# Check whether models and DB have drifted (no pending changes = clean):
alembic check
```

On a fresh database (new teammate, CI, or a new deploy), `alembic upgrade head` alone builds the entire schema — tables, indexes, foreign keys — from nothing.

## What I Learned

### Concepts

- **Async all the way down, or not at all.** Using `async def` routes with a blocking DB driver would've silently defeated the whole point of async — one blocking call stalls FastAPI's *entire* event loop, not just that request.
- **A `BackgroundTasks` function can't safely reuse the request's DB session.** By the time a background task runs (after the response is already sent), the request-scoped session from `Depends(get_db)` may already be closed. `record_click()` opens its own session via `async_session_factory()` instead — I hit this as a real bug, not a hypothetical.
- **Collision-free short codes don't require a retry loop.** Two designs exist for generating short codes: (a) random string + retry on a `UNIQUE` violation, or (b) derive the code from a value that's already guaranteed unique. I went with (b): each code is a Base62 encoding of a *permutation* of the row's own database-sequence id (`urls_id_seq`). The permutation multiplier is coprime with the code space (`62**7`), which makes `id -> code` a bijection — so two different ids can never produce the same code, which is a stronger guarantee than "collisions are improbable." A raw sequential id would leak signup volume/order, which is why it's permuted before encoding rather than encoded directly.
- **Why redirects use 302, not 301.** A `301 Moved Permanently` gets cached by browsers indefinitely — the browser stops hitting the server on repeat visits. That breaks click analytics (every returning visitor goes uncounted) and the ability to deactivate or repoint a link later (a cached 301 can't be revoked). `302 Found` tells the browser "check with me every time," which is the only choice compatible with tracking every click.
- **Autogenerate is a diff tool, not a from-scratch generator.** The first time I ran `alembic revision --autogenerate`, it produced a near-empty migration — because it diffs against the *actual live database*, and my tables already existed from an earlier `create_all()` call. Getting a genuine "creates everything" initial migration required generating it against an actually-empty database.

### Debugging Process

- **Route registration order silently broke `/health`.** `GET /{shortCode}` is a catch-all for any single path segment. When it was registered *before* `GET /health` in `main.py`, a request to `/health` matched the catch-all instead — FastAPI/Starlette match routes in registration order, not by specificity, so `"health"` was treated as a short code and returned 404. Fixed by declaring `/health` first. This one only surfaced because I actually curl'd the running app instead of trusting the code by inspection.
- **Schema drift between "what `create_all()` built" and "what the models declare."** The live database's `urls` table enforced uniqueness on `short_code` via a table constraint named `uq_urls_short_code` (from early raw SQL), while the SQLAlchemy model declared a separately-named index (`ix_urls_short_code`, SQLAlchemy's default naming). Functionally identical, but Alembic's `--autogenerate` flagged it as drift. Also caused a `NotNullViolationError`: an early service design tried a two-phase insert (insert row, then set `short_code` after learning the new row's id), which needs a `NULL` in between — but the live table already had `short_code NOT NULL`. Redesigned to pull `nextval('urls_id_seq')` *before* inserting, so `id` and `short_code` are written together in a single `INSERT` — one round trip instead of two, and no schema relaxation needed.
- **`pytest-asyncio`'s default event loop breaks a module-level async engine.** `pytest-asyncio` creates a *new* event loop per test function by default. But `app/database.py`'s `engine` is a single object created once at import time — its pooled connections bind to whichever event loop touches them first, then raise `RuntimeError: Event loop is closed` on the next test's fresh loop. Fixed with `asyncio_default_fixture_loop_scope = session` in `pytest.ini`, so the whole test run shares one loop — matching how a real running app only ever has one.
- **`.gitignore` has to be plain text.** Mine had been silently UTF-16-encoded (likely from a Windows editor save) since the start of the project — `git check-ignore` proved it was matching *nothing*, meaning `.env` was never actually protected. This is almost certainly what caused the credential-rotation incident early in this repo's history (see commit `ee7fa53`). Fixed by re-writing the file as plain UTF-8 and verifying with `git check-ignore -v .env`.
- **Environment variables aren't a race condition on container platforms.** When Railway couldn't find `DATABASE_URL`, my first instinct was "the app started before the env var loaded." That's not how containers work — the platform injects env vars *before* your process starts. The real cause was that Railway only auto-populates `DATABASE_URL` for its own managed Postgres plugin; an external database like Neon has to be added as a variable manually.

## Deployment (Railway)

Deployed via Railway, driven by a `Procfile`:

```
web: alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT
```

Migrations run automatically before the server starts on every deploy — schema changes ship with the code that needs them, instead of requiring a manual migration step.

**Required environment variable**: `DATABASE_URL`, set manually in Railway's dashboard (**Service → Variables**) with the same Neon connection string used locally. Railway only auto-populates `DATABASE_URL` for its own managed Postgres plugin — since this project uses Neon, that variable does not appear automatically and has to be added by hand.

**Deploy debugging notes**, kept here because I hit both:
- The `Procfile`'s `$PORT` must be a literal `$PORT` for Railway's shell to expand at runtime — a stray backslash-escaped `\$PORT` gets passed through literally and uvicorn fails to bind.
- Running `pytest` (or importing `app/`) from outside the project root fails with `ModuleNotFoundError: No module named 'app'` unless the project root is on `sys.path` — `tests/conftest.py` inserts it explicitly at the top of the file for exactly this reason.

## File Structure

```
url-shortner/
├── main.py
├── alembic.ini
├── pytest.ini
├── Procfile
├── requirements.txt
├── requirements-dev.txt
├── .env                          # gitignored, never committed
├── .gitignore
├── app/
│   ├── config.py
│   ├── database.py
│   ├── schemas.py
│   ├── models/
│   │   └── url.py
│   ├── routes/
│   │   └── shorten.py
│   └── services/
│       └── shortener_service.py
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 615ed06d7cdc_initial_schema.py
└── tests/
    ├── conftest.py
    ├── test_health.py
    └── test_shorten.py
```

## Next Steps

- **Dedicated test database.** The suite currently truncates the live dev database between tests (documented and intentional for now, see [Running Tests](#running-tests)). Wire up a `TEST_DATABASE_URL` and CI workflow before adding collaborators.
- **Authentication + ownership.** The stats endpoint currently has no owner check — anyone who knows a short code can see its analytics. Add auth and scope stats to the creating user.
- **Rate limiting** on `POST /api/v1/shorten` to prevent abuse of the short-code space.
- **Link expiry enforcement UI/cron** — `expires_at` exists on the model but nothing currently purges or surfaces expired links beyond excluding them from redirects.
- **Structured logging + request tracing**, especially around the background click-logging path, to make production debugging less dependent on manually curling the API.
- **CI pipeline** (GitHub Actions) running `pytest` and `alembic check` on every PR, once the dedicated test database above exists.
