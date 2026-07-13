import os
import tempfile

import pytest
from werkzeug.security import generate_password_hash


os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="url-to-ssh-import-")
os.environ.pop("ADMIN_PASSWORD", None)

import app as application  # noqa: E402


@pytest.fixture
def app(tmp_path):
    flask_app = application.create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.db"),
            "DATA_DIR": str(tmp_path),
            "MASTER_SECRET": b"test-master-secret-that-is-long-enough",
            "SSH_CONNECT_TIMEOUT": 1,
            "SSH_COMMAND_TIMEOUT": 1,
        }
    )
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authenticated_client(app, client):
    with app.app_context():
        application.set_setting("admin_password_hash", generate_password_hash("test-password"))
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["csrf_token"] = "test-csrf"
    return client


@pytest.fixture
def csrf_headers():
    return {"X-CSRF-Token": "test-csrf"}


@pytest.fixture
def host_payload():
    return {
        "name": "Lab NAS",
        "address": "192.168.1.20",
        "mac": "aa-bb-cc-dd-ee-ff",
        "ssh_port": 22,
        "username": "root",
        "password": "very-secret-password",
        "wol_broadcast": "192.168.1.255",
        "wol_port": 9,
    }


@pytest.fixture
def stored_host(authenticated_client, csrf_headers, host_payload):
    response = authenticated_client.post("/api/hosts", json=host_payload, headers=csrf_headers)
    assert response.status_code == 201
    return response.get_json()["host"]
