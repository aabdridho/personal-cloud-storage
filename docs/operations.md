# Operations guide

How to run, administer and troubleshoot the stack. Commands assume the repository root.

On Windows the reference setup is **Docker Engine inside WSL 2 (Ubuntu)**: run `docker` commands in the WSL terminal (`cd "/mnt/e/<path>/Personal-Cloud-Storage"`), and `curl.exe` or browser tests from Windows. Ports published by containers in WSL are reachable from Windows on `127.0.0.1`.

## 1. First-time setup

```bash
cp .env.example .env                       # then replace every "ganti-saya"
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # for JWT_SECRET
openssl rand -hex 24                       # for POSTGRES_PASSWORD, SILO_ROOT_PASSWORD

mkdir -p nginx/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout nginx/certs/localhost.key -out nginx/certs/localhost.crt \
  -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

docker compose up -d --build
docker compose ps -a                       # db, silo, api healthy; init "Exited (0)"
docker compose exec api python create_user.py <admin-username> --admin
```

Rules for `.env`:

- Use letters and digits only for database passwords, because they are embedded in a URL.
- Save it with **LF** line endings. Compose on Linux reads a CRLF file's `\r` as part of each value.
- `POSTGRES_PASSWORD` is used only when the `pgdata` volume is first initialized. Changing it later does **not** change the database password. Use `ALTER ROLE` instead (see below).
- Never commit it. `.gitignore` and `.dockerignore` both exclude it.

## 2. Everyday commands

| Task | Command |
|---|---|
| Start / update after code changes | `docker compose up -d --build` |
| Status | `docker compose ps -a` |
| Logs (follow) | `docker compose logs -f api` (or `nginx`, `silo`, `db`, `init`) |
| Stop and remove containers, **keep data** | `docker compose down` |
| Stop and **delete all data** | `docker compose down -v` ⚠️ |
| Shell inside the API container | `docker compose exec api sh` |
| Validate Nginx config | `docker compose exec nginx nginx -t` |
| Reload Nginx without downtime | `docker compose exec nginx nginx -s reload` |
| Restart Nginx after rebuilding `api` | `docker compose restart nginx` |

Nginx resolves `api:8000` once at start-up. After `api` is recreated it may have a new IP, and Nginx answers `502` until it is restarted.

## 3. Account administration

```bash
# create a member account
docker compose exec api python create_user.py ibu

# reset a forgotten password
docker compose exec api python reset_password.py ibu
```

Through the API (admin token required): `GET /users`, `POST /users`, and `PATCH /users/{id}` with `{"is_active": false}` to lock an account immediately, or `{"quota_bytes": 10737418240}` for a 10 GiB quota.

## 4. Database

```bash
docker compose exec db psql -U cloud_app -d cloud_storage        # SQL shell
docker compose exec api alembic current                          # schema version
docker compose exec api alembic history                          # migration chain
```

Changing the schema:

1. Edit `models.py`.
2. Run `alembic revision --autogenerate -m "describe change"` (locally, against a database at the current head).
3. **Read the generated file.** Give every constraint an explicit name, because an unnamed `drop_constraint(None, ...)` makes `downgrade` fail. When adding a `NOT NULL` column to a table that already has rows, add a `server_default`.
4. Run `alembic upgrade head`, then `alembic downgrade -1`, then `alembic upgrade head` again.
5. Commit the migration with the model change. CI repeats the roundtrip and runs `alembic check`.

Changing the database password after initialization:

```bash
docker compose exec db psql -U cloud_app -d cloud_storage -c "ALTER ROLE cloud_app PASSWORD 'new-password';"
# then update POSTGRES_PASSWORD in .env and recreate the app containers
docker compose up -d --force-recreate init api
```

## 5. Object storage

- Console: http://127.0.0.1:9001 (log in with `SILO_ROOT_USER` / `SILO_ROOT_PASSWORD`). The S3 API port is not published to the host; it is reached through Nginx.
- Objects appear under random hex keys. The database maps them to file names.
- **Never edit `/data` (or the `silodata` volume) by hand.** Silo stores each object as metadata (`xl.meta`) plus data parts with per-block bitrot hashes.

## 6. Running the API without Docker (development)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
# .env with S3_* pointing at a local Silo and DATABASE_URL at a local PostgreSQL
alembic upgrade head
python init_storage.py
uvicorn main:app --reload
```

Local Silo on Windows (binary from the [Silo releases](https://github.com/pgsty/silo/releases), checksum verified):

```powershell
$env:MINIO_ROOT_USER = "..."; $env:MINIO_ROOT_PASSWORD = "..."
& "<path>\silo.exe" server "<path>\silo-data" --address "127.0.0.1:9000" --console-address "127.0.0.1:9001"
```

Stop the local Uvicorn and Silo before `docker compose up`, because they use the same ports.

## 7. Tests

```bash
pip install -r requirements-dev.txt
ruff check .
pytest -v
TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/testdb pytest -v
bash scripts/smoke_test.sh            # needs the Docker stack running
```

Do not regenerate `requirements.txt` with `pip freeze` from a venv that has the dev tools installed, or pytest, moto and ruff end up in the production image. Add runtime dependencies to `requirements.txt` by hand.

## 8. Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| `bind ... 127.0.0.1:80: address already in use` | Another web server (e.g. Nginx or Apache installed in WSL) | `sudo ss -ltnp \| grep -E ':(80\|443)\s'`, then `sudo systemctl disable --now nginx` |
| `nginx` keeps `Restarting`, log says `host not found in upstream "api:8000"` | Container left half-created by an earlier failed start | `docker compose up -d --force-recreate nginx` |
| `502 Bad Gateway` | `api` down, or recreated with a new IP | `docker compose ps`, `docker compose logs api`, `docker compose restart nginx` |
| `init` exited with code 1 | Migration or bucket creation failed | `docker compose logs init`; often a typo or symbol in `.env` passwords |
| `api` never starts | Waits for `init` to succeed (by design) | Fix `init` first |
| Login works with `psql` but the API says `password authentication failed` | `.env` still contains a placeholder like `<password>`, or CRLF line endings | Check the value length and characters without printing it; convert to LF |
| `403 SignatureDoesNotMatch` on a download link | `S3_PUBLIC_ENDPOINT` differs from the address used, or Nginx not forwarding `Host` | Must be exactly `https://localhost` locally |
| `400 ... multiple authentication types` from storage | JWT forwarded to Silo | Nginx must keep `proxy_set_header Authorization "";` on `/cloud-storage/` |
| `413` HTML page | Request larger than `client_max_body_size` | Expected; adjust in `nginx/default.conf` and `MAX_UPLOAD_MB` together |
| `KeyError: 'JWT_SECRET'` (or another variable) at start-up | Variable missing or misspelled in `.env` | List names only: `grep -oE '^[A-Z0-9_]+=' .env` |
| `docker` not found in PowerShell | Docker Engine is installed inside WSL | Run it from the Ubuntu terminal, or `wsl docker ...` |
