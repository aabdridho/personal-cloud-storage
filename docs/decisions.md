# Architecture decision records

Short records of the decisions that shaped the project: the context, what was chosen, and what it costs.

---

## ADR-001: Grow the system in phases, starting from local files

**Context.** The goal is to learn cloud engineering, not only to finish an app.
**Decision.** Phase 1 stored uploads in a local folder. Each later phase replaces or adds exactly one layer (object storage, database, auth, containers, proxy, CI, …) to solve a problem the previous phase made visible.
**Consequence.** Each technology was introduced when its need was felt, which makes the reasoning easy to explain. Some code was rewritten between phases on purpose.

## ADR-002: S3 API with Silo instead of MinIO Community Edition

**Context.** MinIO Inc. stopped publishing community binaries and images in October 2025, put the project into maintenance mode in December 2025, and archived the repository in 2026, so the last official community build gets no security fixes.
**Decision.** Use [Silo](https://github.com/pgsty/silo), an actively maintained AGPLv3 community fork with Windows binaries, a restored console, and the same `MINIO_*` configuration. Write all storage code against the generic S3 API through `boto3`.
**Consequence.** The backend can be swapped (Garage, SeaweedFS, AWS S3, Cloudflare R2) by changing endpoint and credentials. Silo is maintained by a small community, a risk this portability reduces.

## ADR-003: PostgreSQL as source of truth, UUID object keys

**Context.** Phase 2 read metadata straight from S3. Timestamps differed between `HeadObject` and `ListObjects`, there was no owner, and listing many objects is slow.
**Decision.** Store metadata in a relational database and name objects with random UUIDs. Write to storage first, then commit the row, deleting the object if the commit fails; delete the row first, then the object.
**Consequence.** Rename and move are single-row updates; names are free-form and per-user; failures leave at most invisible orphaned objects. Two systems must be kept consistent without a shared transaction, and a cleanup job for orphans is still to be written.

## ADR-004: SQLite first, then PostgreSQL with Alembic

**Context.** Learn the ORM without running a database server, but production needs concurrent writes, roles and real timestamps.
**Decision.** Start on SQLite through SQLAlchemy, then switch to PostgreSQL by changing only `DATABASE_URL`, and manage schema changes with Alembic from that point on.
**Consequence.** The switch needed no endpoint changes. SQLite drops time zones, so the API normalizes all timestamps to UTC itself. Every migration must be reversible (named constraints), and CI enforces that.

## ADR-005: Redirect downloads to presigned URLs

**Context.** Streaming downloads through FastAPI lost `Accept-Ranges` and `ETag`, and made the API relay every byte of every file.
**Decision.** Authorize in the API, then answer `307` with a 5-minute presigned URL; share links use the same mechanism with a chosen expiry (60 s to 7 days).
**Consequence.** Storage serves the bytes with range requests (resume, video seeking) and caching headers. Links are bearer tokens that cannot be revoked individually, so lifetimes are kept short.

## ADR-006: Admin-created accounts, JWT, Argon2id

**Context.** The users are one family; strangers must not be able to sign up.
**Decision.** No public registration: the first admin is created via CLI and creates the others. Passwords use Argon2id. Sessions use 60-minute HS256 JWTs, and the account's `is_active` flag is checked on every request.
**Consequence.** Stateless authentication with immediate lockout. There is no refresh token yet, so users log in again after an hour.

## ADR-007: 404 for invisible resources, 403 for visible-but-forbidden

**Context.** Answering `403` for another user's private file confirms that it exists.
**Decision.** Check visibility first and answer `404` when the caller may not know the resource; only then check permission and answer `403`. All rules live in `permissions.py`.
**Consequence.** No information leaks through status codes, and shared-folder behavior stays understandable (a file you can see but not delete gives `403`).

## ADR-008: Admin role does not grant access to files

**Context.** The admin is a family member too.
**Decision.** Admin endpoints manage accounts and quotas only; file access follows the same rules for everyone.
**Consequence.** Better privacy within the family. An admin who needs to recover someone's file has to do it at the infrastructure level, deliberately.

## ADR-009: One-level folders, shared folders, quota charged to uploader

**Context.** Families need common albums, but nested folders add cycle prevention and recursive queries.
**Decision.** Folders are flat; a folder is private or shared; uploads into a shared folder count against the uploader's quota; only the uploader may change a file, and only the creator may change a folder; a shared folder cannot be made private while it contains other members' files.
**Consequence.** Simple, predictable rules. File names are unique per uploader across the whole drive, not per folder; nested folders are a future improvement.

## ADR-010: Docker Compose with an init container

**Context.** Running PostgreSQL, Silo and the API by hand, in the right order, with the right environment, was error-prone.
**Decision.** One Compose file. Health checks gate start-up; a one-shot `init` service runs migrations and creates the bucket before the API starts; the database is not published; the API runs as non-root; secrets come from `.env` at runtime, never from the image.
**Consequence.** `docker compose up -d` reproduces the stack anywhere. Docker Engine inside WSL 2 is used on Windows instead of Docker Desktop.

## ADR-011: Nginx as the only entry point

**Context.** Directly exposed services meant several ports, no TLS, version banners, and uploads that were fully received before being rejected.
**Decision.** Nginx terminates TLS, routes `/cloud-storage/*` to Silo and everything else to the API on one origin, enforces the body size limit, sets security headers, and strips the JWT before proxying to storage. Uvicorn trusts forwarded headers only because nothing else can reach it.
**Consequence.** One certificate, one origin (no CORS for downloads), edge-level limits. Nginx resolves upstream names at start, so it must be restarted after the API container is recreated.

## ADR-012: Three-stage pipeline, images on GHCR tagged by SHA

**Context.** Manual testing with curl did not scale and could not stop regressions.
**Decision.** GitHub Actions runs lint and API tests (SQLite and PostgreSQL), then a smoke test on the real Compose stack including a migration roundtrip, then publishes the image to GHCR as `latest` and `sha-<commit>` from `main` only, with least-privilege tokens and throwaway secrets.
**Consequence.** Every change is verified end-to-end before an image exists, and deployments can pin and roll back exact builds. CI time is a few minutes per push.

## ADR-014: Prometheus pull model, metrics computed from the database at scrape time

**Context.** Logs alone could not answer "is it up, is it slow, who is close to their quota, is the disk filling up". The monitoring stack had to run on the same small home server.
**Decision.** Prometheus scrapes the API, postgres-exporter and Silo's built-in endpoint; Grafana shows one provisioned dashboard. Event counters (uploads, logins, downloads) live in process memory, while totals (files, bytes, per-user usage) are computed by a custom collector that queries PostgreSQL on each scrape instead of being kept in memory. `/metrics` is reachable only inside the Docker network; Prometheus and Grafana bind to `127.0.0.1`. Dashboards, data sources and alert rules are files in Git, with `promtool` unit tests. No Alertmanager yet: alerts are visible in Prometheus and Grafana.
**Consequence.** Totals stay correct across restarts and need no bookkeeping in the request path; a scrape costs four small queries every 15 s. Counters reset on restart, which `rate()`/`increase()` handle. Monitoring is reproducible from the repository. Usernames appear as label values, which is acceptable for a handful of family accounts but would not scale to thousands of users.

## ADR-013: Home server with Cloudflare Tunnel, not a cloud VM (planned)

**Context.** Vercel's serverless model has no persistent disk and a 4.5 MB request limit. A free cloud VM has 1 GB RAM and paid egress, which family photo and video traffic would exceed.
**Decision.** Develop on the laptop; deploy in Phase 12 to a home server exposed through Cloudflare Tunnel.
**Consequence.** No egress fees, LAN-speed access at home, and no open ports on the router. Availability depends on home power and internet, which the backup work in Phase 10 partly mitigates.
