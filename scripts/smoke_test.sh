#!/usr/bin/env bash
# Smoke test end-to-end untuk stack Docker Compose yang sedang berjalan.
# Menguji jalur lengkap: Nginx (HTTPS) -> FastAPI -> PostgreSQL, dan
# presigned URL -> Nginx -> Silo. Dipakai oleh GitHub Actions, dan bisa
# dijalankan manual di WSL setelah `docker compose up -d`.
set -euo pipefail

BASE="${BASE:-https://localhost}"
USERNAME="smoke-$(date +%s)"
PASSWORD="$(openssl rand -hex 16)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

step() { printf '\n==> %s\n' "$1"; }

step "Menunggu ${BASE}/health"
for attempt in $(seq 1 40); do
  if curl -fsk "${BASE}/health" > /dev/null; then
    echo "Sehat setelah percobaan ke-${attempt}"
    break
  fi
  if [ "$attempt" -eq 40 ]; then
    echo "Stack tidak sehat setelah 120 detik" >&2
    exit 1
  fi
  sleep 3
done

step "HTTP diarahkan ke HTTPS"
status=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost/health")
[ "$status" = "301" ] || { echo "Expected 301, dapat ${status}" >&2; exit 1; }

step "Security headers terpasang dan versi Nginx tersembunyi"
headers=$(curl -skI "${BASE}/health")
echo "$headers" | grep -qi '^x-content-type-options: nosniff' || { echo "nosniff hilang" >&2; exit 1; }
echo "$headers" | grep -qi '^referrer-policy: no-referrer' || { echo "referrer-policy hilang" >&2; exit 1; }
echo "$headers" | grep -qi '^server: nginx\s*$' || { echo "Header server bocor versi" >&2; exit 1; }

step "Endpoint terlindungi menolak request tanpa token"
status=$(curl -sk -o /dev/null -w '%{http_code}' "${BASE}/files")
[ "$status" = "401" ] || { echo "Expected 401, dapat ${status}" >&2; exit 1; }

step "Membuat user uji di dalam container api"
docker compose exec -T \
  -e SMOKE_USERNAME="$USERNAME" -e SMOKE_PASSWORD="$PASSWORD" \
  api python - <<'PY'
import os

from database import SessionLocal
from models import User
from security import hash_password

with SessionLocal() as db:
    db.add(User(username=os.environ["SMOKE_USERNAME"],
                password_hash=hash_password(os.environ["SMOKE_PASSWORD"])))
    db.commit()
PY

step "Login"
token=$(curl -sfk -X POST "${BASE}/auth/login" \
  --data-urlencode "username=${USERNAME}" \
  --data-urlencode "password=${PASSWORD}" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')
auth="Authorization: Bearer ${token}"

step "Upload file"
echo "Halo dari smoke test $(date -u +%FT%TZ)" > "${WORKDIR}/upload.txt"
file_id=$(curl -sfk -H "$auth" -F "file=@${WORKDIR}/upload.txt" "${BASE}/files" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')
echo "file id: ${file_id}"

step "Download lewat presigned URL (redirect ke Silo melalui Nginx)"
curl -sfkL -H "$auth" -o "${WORKDIR}/download.txt" "${BASE}/files/${file_id}"
cmp "${WORKDIR}/upload.txt" "${WORKDIR}/download.txt"
echo "Isi file identik"

step "Hapus file"
status=$(curl -sk -o /dev/null -w '%{http_code}' -X DELETE -H "$auth" "${BASE}/files/${file_id}")
[ "$status" = "204" ] || { echo "Expected 204, dapat ${status}" >&2; exit 1; }

printf '\nSmoke test lolos.\n'
