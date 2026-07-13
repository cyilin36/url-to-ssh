from urllib.parse import parse_qs, urlencode, urlparse

import app as application


def test_signed_execution_link_and_rotation(
    authenticated_client, csrf_headers, stored_host, monkeypatch
):
    monkeypatch.setattr(
        application,
        "execute_stored_host",
        lambda _host, _command: {
            "stdout": "Linux lab 6.1\n",
            "stderr": "",
            "exit_code": 0,
            "error": None,
            "truncated": False,
        },
    )
    response = authenticated_client.post(
        f"/api/hosts/{stored_host['id']}/execute",
        json={"command": "uname -a"},
        headers=csrf_headers,
    )
    assert response.status_code == 200
    generated_url = response.get_json()["generated_url"]
    assert "very-secret-password" not in generated_url
    parsed = urlparse(generated_url)

    result = authenticated_client.get(parsed.path + "?" + parsed.query)
    assert result.status_code == 200
    assert "Linux lab 6.1" in result.text

    query = parse_qs(parsed.query)
    tampered = urlencode({"command": "reboot", "sig": query["sig"][0]})
    assert authenticated_client.get(parsed.path + "?" + tampered).status_code == 403

    rotation = authenticated_client.post(
        f"/api/hosts/{stored_host['id']}/rotate-link-key", headers=csrf_headers, json={}
    )
    assert rotation.status_code == 200
    assert authenticated_client.get(parsed.path + "?" + parsed.query).status_code == 403


class FakeChannel:
    def __init__(self, stdout=b"", stderr=b"", exit_code=0):
        self.stdout_chunks = [stdout] if stdout else []
        self.stderr_chunks = [stderr] if stderr else []
        self.exit_code = exit_code

    def recv_ready(self):
        return bool(self.stdout_chunks)

    def recv(self, _size):
        return self.stdout_chunks.pop(0)

    def recv_stderr_ready(self):
        return bool(self.stderr_chunks)

    def recv_stderr(self, _size):
        return self.stderr_chunks.pop(0)

    def exit_status_ready(self):
        return not self.stdout_chunks and not self.stderr_chunks

    def recv_exit_status(self):
        return self.exit_code

    def close(self):
        pass


class FakeSSHClient:
    def __init__(self, channel):
        self.channel = channel
        self.connected = None

    def set_missing_host_key_policy(self, _policy):
        pass

    def connect(self, **kwargs):
        self.connected = kwargs

    def exec_command(self, _command, timeout):
        stream = type("Stream", (), {"channel": self.channel})()
        return None, stream, stream

    def close(self):
        pass


def test_stored_ssh_execution_and_output_truncation(
    app, authenticated_client, csrf_headers, stored_host, monkeypatch
):
    channel = FakeChannel(stdout=b"x" * (application.MAX_OUTPUT_BYTES + 10), stderr=b"warning")
    fake_client = FakeSSHClient(channel)
    monkeypatch.setattr(application.paramiko, "SSHClient", lambda: fake_client)

    response = authenticated_client.post(
        f"/api/hosts/{stored_host['id']}/execute",
        json={"command": "large-output"},
        headers=csrf_headers,
    )
    data = response.get_json()
    assert response.status_code == 200
    assert data["truncated"] is True
    assert len(data["stdout"].encode()) == application.MAX_OUTPUT_BYTES
    assert fake_client.connected["password"] == "very-secret-password"


class FakeSocket:
    def __init__(self, *_args):
        self.options = []
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def setsockopt(self, *args):
        self.options.append(args)

    def sendto(self, packet, address):
        self.sent = (packet, address)


def test_wol_packet_and_signed_url(authenticated_client, csrf_headers, stored_host, monkeypatch):
    fake_socket = FakeSocket()
    monkeypatch.setattr(application.socket, "socket", lambda *_args: fake_socket)
    response = authenticated_client.post(
        f"/api/hosts/{stored_host['id']}/wake", headers=csrf_headers, json={}
    )
    assert response.status_code == 200
    packet, destination = fake_socket.sent
    assert destination == ("192.168.1.255", 9)
    assert packet == b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16

    parsed = urlparse(response.get_json()["generated_url"])
    public_response = authenticated_client.get(parsed.path + "?" + parsed.query)
    assert public_response.status_code == 200
    assert public_response.text == "[OK] Wake-on-LAN packet sent"
