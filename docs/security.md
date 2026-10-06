# Security

The service will hold a family's private photos and documents, so security was designed in from Phase 1 rather than added at the end. This page lists what is protected against, the controls in place, and the gaps that are known and scheduled.

## Threat model

| Asset | Threat | Main controls |
|---|---|---|
| File contents | Another family member, or an outsider, reading or deleting them | Per-user isolation, `404` for private resources, uploader-only modification, short-lived signed URLs |
| Passwords | Database leak, online guessing | Argon2id hashing; rate limiting planned (Phase 11) |
| Sessions | Token theft or forgery | HS256 signature, 60-minute expiry, active-flag check per request, TLS |
| Secrets | Leaking through Git, images, logs or screenshots | `.env` excluded from Git and image; template in `.env.example`; CI uses throwaway secrets |
| Server | Exploits against exposed services | One entry point (Nginx); database and S3 API not published; non-root API; version banners hidden |
| Availability | Huge uploads filling disk or tying up the API | Nginx body limit, API size check, per-user quota |

## Controls by layer

### Edge (Nginx)

- TLS 1.2 and 1.3 only; HTTP is redirected to HTTPS with `301`.
- `server_tokens off`, and storage responses go through Nginx too, so no `uvicorn`, `Silo` or version string leaks.
- Headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. The last one matters here: a presigned URL in the address bar must not be sent to another site in the `Referer` header.
- `client_max_body_size 1024m` rejects oversized uploads before the body is read. There is no `100 Continue`; the connection is closed.
- On the storage route the `Authorization` header is cleared, so the user's JWT never reaches Silo, and the duplicate or unwanted headers Silo adds (HSTS, legacy `X-Xss-Protection`, a second `nosniff`) are removed.
- HSTS is intentionally **off** on `localhost` (it would force HTTPS for every local project). Enable it on the production domain.

### Application (FastAPI)

- **Passwords:** Argon2id via `pwdlib` (`m=65536` KiB, `t=3`, `p=4`, random salt per hash). Never stored or returned in plain text; `UserInfo` has no hash field.
- **Login:** identical error message for unknown user and wrong password, plus a dummy Argon2 verification for unknown users, so neither the message nor the timing reveals which usernames exist.
- **JWT:** `algorithms=["HS256"]` is pinned when decoding, which blocks the `alg: none` attack. Payload holds only the user id and expiry. Any decode problem becomes `401`.
- **Revocation workaround:** JWTs cannot be revoked, so `get_current_user` reloads the user on every request and refuses inactive accounts. Deactivating an account locks it out immediately.
- **Authorization:** all rules live in `permissions.py`. Visibility is checked before permission, so `403` is only ever returned for things the caller is allowed to know exist. Admin rights cover accounts and quotas, not other people's files.
- **Input handling:** upload names are reduced to their final path component (`Path(name).name`), so `../../x` cannot escape; names with `/` or `\` are rejected on rename; search escapes SQL `LIKE` wildcards; every body, query and path parameter is validated by Pydantic (`422`).
- **No public sign-up:** accounts are created by the admin.
- **Admin self-lockout** is prevented (`400`).

### Storage

- Objects use random UUID keys, so knowing a file name does not reveal its key.
- Presigned URLs sign bucket, key, expiry and `Host`. Any modification gives `403 SignatureDoesNotMatch`, and expiry gives `403 AccessDenied`. Download redirects live 5 minutes; share links 60 seconds to 7 days.
- Silo verifies per-block bitrot hashes on read, and the stored ETag (MD5) allows integrity checks against the original file.

### Containers and secrets

- The API image runs as `appuser` (UID 1000), not root.
- PostgreSQL has no published port; the S3 API port is not published; the Silo console and Nginx bind to `127.0.0.1` only.
- `.env` and `nginx/certs/` (private key) are in `.gitignore`; `.env`, `.git`, tests, scripts and `nginx/` are in `.dockerignore`, so secrets cannot end up in an image layer.
- In the native (non-Docker) setup the application connects as `cloud_app`, a login role that owns only its database. In Docker, see the gap below.
- The storage image is pinned to an exact release; PostgreSQL is pinned to major version 18.

### CI/CD

- The workflow token defaults to `contents: read`; only the publish job gets `packages: write`, and only on pushes to `main`. Pull requests can never publish images.
- The smoke test generates random credentials and a one-day certificate per run, and destroys them with the runner. No real secret is stored in GitHub.

## Known gaps (scheduled for Phase 11 unless noted)

| Gap | Risk | Planned fix |
|---|---|---|
| The API uses the Silo **root** credential, and its access key appears in every presigned URL (`X-Amz-Credential`) | A leaked app credential would give full storage control | Dedicated Silo user and policy limited to one bucket |
| In Docker, the app connects as `POSTGRES_USER`, which the official image creates as a **superuser** | SQL injection or a code bug would have full database rights | Init script creating a separate non-superuser application role; superuser kept for migrations only |
| No rate limiting on `/auth/login` | Online password guessing | Nginx `limit_req` and/or an app-level limiter keyed on the real client IP (already forwarded via `X-Forwarded-For`) |
| No password-change endpoint for users | Users depend on the admin CLI | `PATCH /users/me/password` requiring the old password |
| No Content-Security-Policy | Less defense if HTML is ever served | CSP that still allows Swagger UI's assets |
| Quota check is not atomic | Two simultaneous uploads can both pass and exceed the quota slightly | Row lock on the user, or a usage counter updated in the same transaction |
| Orphaned objects after partial failures are not swept | Wasted space only (never visible to users) | Periodic job comparing bucket keys with `files.object_key` |
| Self-signed certificate locally | Browser warning | Real certificate from Cloudflare at deployment (Phase 12) |
| HSTS disabled | Downgrade on first visit | Enable on the production domain |
| Backups | Data loss on disk failure | Phase 10: scheduled PostgreSQL dumps + object replication, tested restore |

Before the service is shared with the family, rotate every credential used during development (admin password, `SILO_ROOT_PASSWORD`, `POSTGRES_PASSWORD`, `JWT_SECRET`), use long random values, and remove or deactivate test accounts.

## Reporting

This is a personal project. If you notice a security problem, please open a GitHub issue without exploit details, or contact the author directly.
