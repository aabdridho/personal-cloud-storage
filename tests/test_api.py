def upload(client, headers, name="tes.txt", content=b"Halo dari test", folder_id=None):
    data = {"folder_id": str(folder_id)} if folder_id is not None else {}
    return client.post(
        "/files",
        headers=headers,
        files={"file": (name, content, "text/plain")},
        data=data,
    )


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_with_wrong_password_is_rejected(client, admin):
    response = client.post("/auth/login", data={"username": "admin", "password": "salah-banget"})
    assert response.status_code == 401


def test_login_unknown_user_gets_same_error(client, admin):
    unknown = client.post("/auth/login", data={"username": "hantu", "password": "salah-banget"})
    wrong = client.post("/auth/login", data={"username": "admin", "password": "salah-banget"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_files_require_token(client):
    assert client.get("/files").status_code == 401


def test_tampered_token_is_rejected(client, admin):
    tampered = {"Authorization": admin["Authorization"][:-2] + "xx"}
    assert client.get("/files", headers=tampered).status_code == 401


def test_upload_list_download_delete(client, admin):
    response = upload(client, admin)
    assert response.status_code == 201
    file_id = response.json()["id"]

    files = client.get("/files", headers=admin).json()
    assert [f["filename"] for f in files] == ["tes.txt"]

    download = client.get(f"/files/{file_id}", headers=admin, follow_redirects=False)
    assert download.status_code == 307
    assert "X-Amz-Signature" in download.headers["location"]

    assert client.delete(f"/files/{file_id}", headers=admin).status_code == 204
    assert client.get("/files", headers=admin).json() == []


def test_duplicate_filename_conflicts(client, admin):
    assert upload(client, admin).status_code == 201
    assert upload(client, admin).status_code == 409


def test_rename_rules(client, admin):
    first = upload(client, admin, name="a.txt").json()["id"]
    upload(client, admin, name="b.txt")

    assert client.patch(f"/files/{first}", headers=admin, json={"filename": "c.txt"}).status_code == 200
    assert client.patch(f"/files/{first}", headers=admin, json={"filename": "b.txt"}).status_code == 409
    assert client.patch(f"/files/{first}", headers=admin, json={"filename": "x/y.txt"}).status_code == 422


def test_other_user_cannot_access_file(client, admin, member):
    file_id = upload(client, admin).json()["id"]

    assert client.get(f"/files/{file_id}", headers=member, follow_redirects=False).status_code == 404
    assert client.delete(f"/files/{file_id}", headers=member).status_code == 404


def test_member_cannot_create_user(client, member):
    response = client.post(
        "/users",
        headers=member,
        json={"username": "baru", "password": "password123"},
    )
    assert response.status_code == 403


def test_deactivated_user_token_is_rejected(client, admin, member):
    users = client.get("/users", headers=admin).json()
    member_id = next(u["id"] for u in users if u["username"] == "member")

    response = client.patch(f"/users/{member_id}", headers=admin, json={"is_active": False})
    assert response.status_code == 200
    assert client.get("/files", headers=member).status_code == 401


def test_quota_exceeded(client, admin, login):
    response = client.post(
        "/users",
        headers=admin,
        json={"username": "hemat", "password": "password123", "quota_bytes": 10},
    )
    assert response.status_code == 201

    hemat = login("hemat", "password123")
    assert upload(client, hemat, content=b"x" * 20).status_code == 507


def test_shared_folder_rules(client, admin, member):
    folder = client.post(
        "/folders",
        headers=admin,
        json={"name": "Keluarga", "is_shared": True},
    ).json()

    response = upload(client, member, name="foto.txt", folder_id=folder["id"])
    assert response.status_code == 201
    file_id = response.json()["id"]

    listed = client.get("/files", headers=admin, params={"folder_id": folder["id"]}).json()
    assert [f["filename"] for f in listed] == ["foto.txt"]

    assert client.get(f"/files/{file_id}", headers=admin, follow_redirects=False).status_code == 307
    assert client.delete(f"/files/{file_id}", headers=admin).status_code == 403
    assert client.delete(f"/folders/{folder['id']}", headers=admin).status_code == 409


def test_private_folder_is_hidden(client, admin, member):
    folder = client.post("/folders", headers=admin, json={"name": "Pribadi"}).json()
    assert upload(client, member, folder_id=folder["id"]).status_code == 404
    assert client.get("/files", headers=member, params={"folder_id": folder["id"]}).status_code == 404


def test_search_escapes_wildcards(client, admin):
    upload(client, admin, name="catatan.txt")

    assert client.get("/files", headers=admin, params={"q": "%"}).json() == []
    assert len(client.get("/files", headers=admin, params={"q": "CAT"}).json()) == 1
