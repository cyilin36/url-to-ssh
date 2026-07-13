import app as application


def csrf_from_session(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_first_run_setup_and_login(app, client):
    response = client.get("/ui/")
    assert response.status_code == 302
    assert "/ui/login" in response.location

    response = client.get("/ui/login")
    assert response.status_code == 302
    assert "/ui/setup" in response.location

    client.get("/ui/setup")
    token = csrf_from_session(client)
    response = client.post(
        "/ui/setup",
        data={"password": "new-password", "confirmation": "new-password", "csrf_token": token},
    )
    assert response.status_code == 302
    assert response.location.endswith("/ui/")

    with app.app_context():
        assert "new-password" not in application.get_setting("admin_password_hash")


def test_login_rejects_bad_password(app, client):
    with app.app_context():
        application.set_setting(
            "admin_password_hash", application.generate_password_hash("right-password")
        )
    client.get("/ui/login")
    response = client.post(
        "/ui/login",
        data={"password": "wrong-password", "csrf_token": csrf_from_session(client)},
    )
    assert response.status_code == 200
    assert "密码不正确" in response.text


def test_api_requires_login_and_csrf(client, authenticated_client):
    unauthenticated = client.application.test_client()
    assert unauthenticated.post("/api/hosts", json={}).status_code == 401
    assert authenticated_client.post("/api/hosts", json={}).status_code == 400
    assert "安全令牌" in authenticated_client.post("/api/hosts", json={}).get_json()["error"]


def test_host_and_command_crud_encrypts_and_cascades(
    app, authenticated_client, csrf_headers, host_payload
):
    response = authenticated_client.post("/api/hosts", json=host_payload, headers=csrf_headers)
    assert response.status_code == 201
    host = response.get_json()["host"]
    assert host["mac"] == "AA:BB:CC:DD:EE:FF"
    assert "password" not in host

    with app.app_context():
        raw = application.get_host(host["id"])
        assert b"very-secret-password" not in raw["password_encrypted"]
        assert application.decrypt_value(raw["password_encrypted"]) == "very-secret-password"

    global_command = authenticated_client.post(
        "/api/commands",
        json={"name": "Disk", "command": "df -h", "host_id": ""},
        headers=csrf_headers,
    )
    host_command = authenticated_client.post(
        "/api/commands",
        json={"name": "Restart", "command": "reboot", "host_id": host["id"]},
        headers=csrf_headers,
    )
    assert global_command.status_code == 201
    assert host_command.status_code == 201

    response = authenticated_client.delete(f"/api/hosts/{host['id']}", headers=csrf_headers)
    assert response.status_code == 200
    with app.app_context():
        remaining = application.get_db().execute("SELECT name FROM commands").fetchall()
        assert [row["name"] for row in remaining] == ["Disk"]


def test_host_update_blank_password_preserves_secret(
    app, authenticated_client, csrf_headers, stored_host, host_payload
):
    with app.app_context():
        old_ciphertext = application.get_host(stored_host["id"])["password_encrypted"]
    host_payload.update({"name": "Renamed NAS", "password": ""})
    response = authenticated_client.put(
        f"/api/hosts/{stored_host['id']}", json=host_payload, headers=csrf_headers
    )
    assert response.status_code == 200
    with app.app_context():
        assert application.get_host(stored_host["id"])["password_encrypted"] == old_ciphertext
