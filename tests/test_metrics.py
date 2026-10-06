from prometheus_client import REGISTRY


def upload(client, headers, content: bytes):
    return client.post("/files", headers=headers, files={"file": ("m.txt", content, "text/plain")})


def sample(name: str, labels: dict | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def test_metrics_endpoint_is_public_inside_the_network(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "pcs_metrics_db_up 1.0" in response.text
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_http_requests_are_instrumented(client):
    client.get("/files")  # 401
    text = client.get("/metrics").text
    assert 'handler="/files"' in text
    assert 'handler="/health"' not in text


def test_upload_and_login_counters(client, admin):
    before_ok = sample("pcs_file_uploads_total", {"result": "success"})
    before_conflict = sample("pcs_file_uploads_total", {"result": "conflict"})
    before_bytes = sample("pcs_file_upload_bytes_total")
    before_fail = sample("pcs_login_attempts_total", {"result": "failure"})

    assert upload(client, admin, content=b"12345").status_code == 201
    assert upload(client, admin, content=b"12345").status_code == 409
    client.post("/auth/login", data={"username": "admin", "password": "salah-banget"})

    assert sample("pcs_file_uploads_total", {"result": "success"}) == before_ok + 1
    assert sample("pcs_file_uploads_total", {"result": "conflict"}) == before_conflict + 1
    assert sample("pcs_file_upload_bytes_total") == before_bytes + 5
    assert sample("pcs_login_attempts_total", {"result": "failure"}) == before_fail + 1


def test_storage_collector_reads_database(client, admin, member):
    upload(client, admin, content=b"abc")
    assert sample("pcs_files") == 1
    assert sample("pcs_stored_bytes") == 3
    assert sample("pcs_users", {"status": "active"}) == 2
    assert sample("pcs_user_used_bytes", {"username": "admin"}) == 3
    assert sample("pcs_user_used_bytes", {"username": "member"}) == 0
    assert sample("pcs_user_quota_bytes", {"username": "admin"}) > 0
