# Testing and CI/CD

## Strategy

Three layers, each catching what the cheaper one cannot:

| Layer | What runs | Speed | Catches |
|---|---|---|---|
| **Lint** | `ruff check .` (pyflakes, pycodestyle, isort, bugbear, pyupgrade; config in `ruff.toml`) | < 1 s | Unused or undefined names, unsorted imports, outdated syntax, swallowed exception context |
| **Unit/API tests** | `pytest` with FastAPI `TestClient`, S3 mocked by `moto`; run twice in CI, on SQLite and on PostgreSQL | ~6 s each | Regressions in business rules: auth, isolation, quotas, folders, search |
| **Alert rule tests** | `promtool check config` and `promtool test rules` on synthetic time series | < 1 s | Broken PromQL, alerts that never fire or fire too early |
| **Smoke test** | The real Docker Compose stack (Nginx, API, PostgreSQL, Silo, monitoring), then `scripts/smoke_test.sh` and `scripts/monitoring_check.sh` | 2–3 min | Wiring problems mocks cannot see: TLS, proxy headers, presigned URL signing through Nginx, migrations on a fresh database, container health |

## Unit tests (`tests/`)

`tests/conftest.py` sets the environment **before** the application is imported (because `config.py` reads it at import time):

- `DATABASE_URL` points at a throwaway SQLite file, or at `TEST_DATABASE_URL` when set.
- `moto`'s `mock_aws()` is started before `storage.py` builds its boto3 clients, and `MOTO_S3_CUSTOM_ENDPOINTS` makes it intercept the custom endpoint.
- Each test gets fresh tables (`autouse` fixture), so tests are independent and can run in any order.
- Fixtures `admin` and `member` return ready-to-use `Authorization` headers.

What the 19 tests cover (`test_api.py` and `test_metrics.py`):

| Test | Rule protected |
|---|---|
| `test_health` | Health endpoint |
| `test_login_with_wrong_password_is_rejected` | Wrong password → `401` |
| `test_login_unknown_user_gets_same_error` | No username enumeration through error responses |
| `test_files_require_token` | No token → `401` |
| `test_tampered_token_is_rejected` | Modified JWT signature → `401` |
| `test_upload_list_download_delete` | Full file lifecycle; download is a signed `307` |
| `test_duplicate_filename_conflicts` | Same name twice → `409` |
| `test_rename_rules` | Rename OK, conflict `409`, slash in name `422` |
| `test_other_user_cannot_access_file` | Another user's file → `404` for read and delete |
| `test_member_cannot_create_user` | Non-admin → `403` on `/users` |
| `test_deactivated_user_token_is_rejected` | A still-valid token stops working once the account is deactivated |
| `test_quota_exceeded` | Over quota → `507` |
| `test_shared_folder_rules` | Members upload into shared folders, others may read (`307`) but not delete (`403`), non-empty folder cannot be deleted (`409`) |
| `test_private_folder_is_hidden` | Private folder is `404` for others, for both upload and listing |
| `test_search_escapes_wildcards` | `%` is literal; search is case-insensitive |
| `test_metrics_endpoint_is_public_inside_the_network` | `/metrics` works and is hidden from the OpenAPI schema |
| `test_http_requests_are_instrumented` | Requests are counted per route template; `/health` is excluded |
| `test_upload_and_login_counters` | Upload results, uploaded bytes and failed logins are counted |
| `test_storage_collector_reads_database` | File count, stored bytes, users and per-user usage come from the database |

Run locally:

```bash
pip install -r requirements-dev.txt
ruff check .
pytest -v
TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/testdb pytest -v
```

The PostgreSQL run exists because SQLite and PostgreSQL differ in ways that matter here: timezone storage, `ILIKE`, constraint enforcement. Passing on SQLite alone would not prove the production database behaves the same.

## Smoke test (`scripts/smoke_test.sh`)

Runs against a live stack (`docker compose up -d` first) and fails on the first problem (`set -euo pipefail`):

1. Wait for `https://localhost/health` through Nginx.
2. `http://localhost` answers `301`.
3. Security headers are present and the `Server` header is a bare `nginx`.
4. `/files` without a token answers `401`.
5. Create a random test user inside the `api` container.
6. Log in, upload a file, follow the download redirect through Nginx to Silo, and compare the downloaded bytes with the original (`cmp`).
7. Delete the file (`204`).

## Monitoring check (`scripts/monitoring_check.sh`)

Runs after the smoke test: `/metrics` answers `404` through Nginx; Prometheus is ready and has loaded the alert rules; all four scrape targets (`prometheus`, `api`, `postgres`, `silo`) are up; the smoke test's upload shows up in `pcs_file_uploads_total`; Silo capacity metrics exist; Grafana is healthy, its Prometheus data source answers, the dashboard is provisioned, and anonymous requests get `401`.

## Alert rule tests (`monitoring/prometheus/alerts.test.yml`)

`promtool test rules` feeds synthetic series into the rules and asserts which alerts fire and when: 30 failed logins in 15 minutes fire `LoginFailureSpike`; a user at 95% of quota fires `UserQuotaAlmostFull` while one at 10% does not; `TargetDown` stays silent until the target has been down for the full 2 minutes.

In CI, before the smoke test, the pipeline also runs `alembic downgrade base`, `alembic upgrade head` and `alembic check` inside the container. That proves every migration is reversible and that `models.py` and the migrations describe the same schema.

## Pipeline (`.github/workflows/ci.yml`)

```mermaid
flowchart TD
    trigger["push to main · pull request · manual run"] --> test
    subgraph test [job: test]
        t1[ruff check] --> t2[pytest on SQLite] --> t3[pytest on PostgreSQL service container] --> t4[promtool check + rule tests]
    end
    test --> smoke
    subgraph smoke [job: smoke]
        s1[throwaway .env + 1-day certificate] --> s2[docker compose up --build]
        s2 --> s3[migration roundtrip + alembic check] --> s4[scripts/smoke_test.sh] --> s6[scripts/monitoring_check.sh]
        s6 --> s5[logs on failure · docker compose down -v always]
    end
    smoke -->|push to main only| publish
    subgraph publish [job: publish]
        p1[login to ghcr.io with GITHUB_TOKEN] --> p2[build with GHA layer cache] --> p3["push :latest and :sha-&lt;commit&gt;"]
    end
```

Design choices:

- **Fail fast:** `needs:` chains the jobs, so the slow smoke test does not run if lint or unit tests fail, and nothing is published unless the full stack works.
- **Least privilege:** the workflow token is `contents: read`. Only `publish` gets `packages: write`, and it runs only for pushes to `main`, never for pull requests.
- **No stored secrets:** smoke-test credentials are generated per run with `openssl rand`; publishing uses the automatic, short-lived `GITHUB_TOKEN`.
- **Reproducible artifacts:** every image is tagged with the commit SHA as well as `latest`, so a deployment can pin an exact build and roll back to a previous one.
- **Concurrency:** a newer push to the same branch cancels the older run.
- **Caching:** pip downloads are cached by `requirements*.txt`; Docker layers by the GitHub Actions cache.

- **Current action versions:** all actions run on the Node 24 runtime (`checkout@v7`, `setup-python@v7`, Docker actions v4–v7), which removed the Node 20 deprecation warnings of the first runs.

The workflow file itself is validated with `actionlint`, and the scripts with `shellcheck`.

## Adding a feature safely

1. Write or extend a test in `tests/test_api.py` that describes the new rule.
2. Implement it; run `ruff check .` and `pytest -v`.
3. If the schema changes, add an Alembic migration and test the roundtrip (see [operations.md](operations.md#4-database)).
4. Open a pull request. CI runs lint, both test suites and the smoke test, but does not publish.
5. Merge to `main`. CI runs again and publishes the image.
