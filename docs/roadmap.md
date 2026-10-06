# Roadmap

| Phase | Topic | Status | What it added |
|---|---|---|---|
| 1 | FastAPI + local folder | ✅ | Upload, list, download, delete; path traversal defense; `201/204/404/409/422` semantics |
| 2 | Object storage (Silo, S3 API) | ✅ | boto3 client, bucket, presigned URLs, `307` downloads, range requests (`206`) |
| 3 | Database | ✅ | SQLite → PostgreSQL, SQLAlchemy, Alembic migrations, UUID object keys, UTC timestamps |
| 4 | Authentication | ✅ | Argon2id, JWT, admin-created accounts, per-user isolation, timing-safe login |
| 5 | Storage features | ✅ | Quotas (`507`), size limit (`413`), rename/move, search, pagination, admin user management, private and shared family folders, routers refactor |
| 6 | Docker Compose | ✅ | API, PostgreSQL and Silo containers, health checks, init container, volumes, non-root image |
| 7 | Nginx | ✅ | HTTPS, HTTP→HTTPS redirect, security headers, edge upload limit, single origin for API and storage |
| 8 | CI/CD | ✅ | ruff, pytest (SQLite + PostgreSQL), full-stack smoke test with migration roundtrip, image publishing to GHCR |
| 9 | Monitoring | ✅ | Prometheus (API, PostgreSQL, Silo), app metrics, provisioned Grafana dashboard, 8 alert rules with `promtool` tests, monitoring check in CI |
| 10 | Backup & restore | ⏳ | Scheduled PostgreSQL dumps, object replication, tested restore procedure |
| 11 | Security hardening | ⏳ | Least-privilege storage credentials, non-superuser DB role, login rate limiting, password change, CSP, credential rotation |
| 12 | Deployment | ⏳ | Home server + Cloudflare Tunnel, real certificate and domain, HSTS, deployment from GHCR by commit SHA |

## Commit history by phase

| Commit | Change |
|---|---|
| `496c6fc` | Project setup with health check |
| `a79a701` | Fix `requirements.txt` encoding (UTF-16 → UTF-8) |
| `f329347` | Upload and list endpoints |
| `ee06481` | Ignore Office lock files |
| `b25cf30` | Download and delete endpoints |
| `1cde217` | Migrate storage to S3-compatible Silo |
| `e5d0fbd` | Presigned share links and redirect downloads |
| `2063aa3` | Metadata in SQLite with UUID object keys |
| `f0e1743` | PostgreSQL and Alembic |
| `ce91ba0` | JWT auth, admin-managed users, file ownership |
| `85a2baf` | Quota, rename, search, pagination, user management |
| `398d291` | Private and shared family folders |
| `dab151c` | Docker Compose |
| `ed814a2` | Nginx reverse proxy with HTTPS |
| `5975a08` | CI/CD pipeline, tests, docs (Phase 8) |
| *(Phase 9)* | Prometheus + Grafana monitoring |

## Future improvements (beyond Phase 12)

- Web or mobile frontend (currently API + Swagger UI only).
- Nested folders, file versioning, trash with restore.
- Thumbnails and previews for photos and videos.
- Refresh tokens instead of a fixed 60-minute session.
- Duplicate detection using stored ETags.
- `naming_convention` on the SQLAlchemy metadata so every constraint is named automatically.
- Alertmanager to deliver alerts (e.g. to Telegram) instead of only showing them in Prometheus and Grafana.
- Log aggregation (Loki) next to metrics.
- Trim `requirements.txt` to direct dependencies plus a lock file.
