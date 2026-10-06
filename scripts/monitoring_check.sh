#!/usr/bin/env bash
# Checks the monitoring stack (Phase 9) after `docker compose up -d`.
# Run it after smoke_test.sh so the API counters have something to show.
# Needs GRAFANA_ADMIN_PASSWORD in .env.
set -euo pipefail

BASE="${BASE:-https://localhost}"
PROM="${PROM:-http://localhost:9090}"
GRAFANA="${GRAFANA:-http://localhost:3000}"
GRAFANA_PASSWORD="$(grep '^GRAFANA_ADMIN_PASSWORD=' .env | cut -d= -f2-)"

step() { printf '\n==> %s\n' "$1"; }

# Prints the result of a PromQL instant query as "<value>" (empty if no data).
promql() {
  curl -sf -G "${PROM}/api/v1/query" --data-urlencode "query=$1" \
    | python3 -c 'import json, sys; r = json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")'
}

wait_for() {
  local description="$1" query="$2" expected="$3"
  for attempt in $(seq 1 30); do
    if [ "$(promql "$query")" = "$expected" ]; then
      echo "${description}: OK (percobaan ke-${attempt})"
      return 0
    fi
    sleep 3
  done
  echo "${description}: gagal setelah 90 detik" >&2
  curl -s "${PROM}/api/v1/targets" | python3 -m json.tool >&2 || true
  return 1
}

step "/metrics tidak bisa diakses dari luar (Nginx)"
status=$(curl -sk -o /dev/null -w '%{http_code}' "${BASE}/metrics")
[ "$status" = "404" ] || { echo "Expected 404, dapat ${status}" >&2; exit 1; }

step "Prometheus siap dan konfigurasinya valid"
for attempt in $(seq 1 30); do
  curl -sf "${PROM}/-/ready" > /dev/null && break
  [ "$attempt" -eq 30 ] && { echo "Prometheus tidak siap" >&2; exit 1; }
  sleep 2
done
rules=$(curl -sf "${PROM}/api/v1/rules" | python3 -c 'import json, sys; print(sum(len(g["rules"]) for g in json.load(sys.stdin)["data"]["groups"]))')
[ "$rules" -gt 0 ] || { echo "Alert rules tidak termuat" >&2; exit 1; }
echo "${rules} alert rules termuat"

step "Semua target scrape UP"
wait_for "4 target up" 'count(up == 1)' "4"
wait_for "PostgreSQL terjangkau oleh exporter" 'pg_up' "1"
wait_for "Collector API bisa membaca database" 'pcs_metrics_db_up' "1"

step "Metrik aplikasi tercatat (upload dari smoke test)"
wait_for "Upload sukses tercatat" 'sum(pcs_file_uploads_total{result="success"}) > bool 0' "1"
wait_for "Metrik kapasitas Silo tersedia" 'count(minio_cluster_capacity_usable_total_bytes) > bool 0' "1"

step "Grafana sehat, datasource dan dashboard ter-provision"
for attempt in $(seq 1 30); do
  curl -sf "${GRAFANA}/api/health" > /dev/null && break
  [ "$attempt" -eq 30 ] && { echo "Grafana tidak sehat" >&2; exit 1; }
  sleep 2
done
# /api/health answers before the bundled plugins finish loading, so a health
# check right after start can get 404 "plugin not registered". Retry.
for attempt in $(seq 1 30); do
  body=$(curl -s -u "admin:${GRAFANA_PASSWORD}" "${GRAFANA}/api/datasources/uid/prometheus/health" || true)
  if echo "$body" | python3 -c 'import json, sys; sys.exit(json.load(sys.stdin).get("status") != "OK")' 2>/dev/null; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "Datasource Prometheus gagal: ${body}" >&2
    exit 1
  fi
  sleep 2
done
curl -sf -u "admin:${GRAFANA_PASSWORD}" "${GRAFANA}/api/dashboards/uid/pcs-overview" > /dev/null \
  || { echo "Dashboard tidak ter-provision" >&2; exit 1; }
echo "Datasource OK, dashboard 'Personal Cloud Storage' ada"

step "Grafana menolak akses tanpa login"
status=$(curl -s -o /dev/null -w '%{http_code}' "${GRAFANA}/api/dashboards/uid/pcs-overview")
[ "$status" = "401" ] || { echo "Expected 401, dapat ${status}" >&2; exit 1; }

printf '\nMonitoring check lolos.\n'
