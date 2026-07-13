from unittest.mock import Mock

import app as application


def test_legacy_help_is_plain_text(client):
    response = client.get("/", headers={"Host": "gateway.local:9091"})
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "API[GET]: http://gateway.local:9091/control/<Command>" in response.text
    assert "/ui/" not in response.text


def test_legacy_missing_parameters(client):
    response = client.get("/control/ls?host=192.168.1.2")
    assert response.status_code == 400
    assert response.text == "[Error] Missing parameters. Please check: host, user, pwd"


def test_legacy_execution_response_is_unchanged(client, monkeypatch):
    ssh = Mock()
    stdout = Mock()
    stdout.read.return_value = b"file.txt\n"
    stderr = Mock()
    stderr.read.return_value = b""
    ssh.exec_command.return_value = (Mock(), stdout, stderr)
    monkeypatch.setattr(application.paramiko, "SSHClient", lambda: ssh)

    response = client.get("/control/ls?host=10.0.0.2&user=root&pwd=secret")

    assert response.status_code == 200
    assert response.text == "[root@10.0.0.2] exec: ls\n========================================\nfile.txt\n"
    ssh.connect.assert_called_once_with(
        hostname="10.0.0.2", port=22, username="root", password="secret", timeout=10
    )
