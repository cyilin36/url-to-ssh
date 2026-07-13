import base64
import hashlib
import hmac
import os
import re
import secrets
import socket
import sqlite3
import time
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

import paramiko
from cryptography.fernet import Fernet, InvalidToken
from flask import (
    Flask,
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


LISTEN_PORT = int(os.getenv("HTTP_PORT", 8080))
MAX_COMMAND_LENGTH = 4096
MAX_OUTPUT_BYTES = 1024 * 1024
MAC_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hosts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    mac TEXT,
    ssh_port INTEGER NOT NULL DEFAULT 22 CHECK (ssh_port BETWEEN 1 AND 65535),
    username TEXT NOT NULL,
    password_encrypted BLOB NOT NULL,
    wol_broadcast TEXT NOT NULL DEFAULT '255.255.255.255',
    wol_port INTEGER NOT NULL DEFAULT 9 CHECK (wol_port BETWEEN 1 AND 65535),
    link_secret_encrypted BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    command TEXT NOT NULL,
    host_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_commands_host_id ON commands(host_id);
INSERT OR IGNORE INTO settings(key, value) VALUES ('schema_version', '1');
"""


def _load_master_secret(data_dir):
    configured = os.getenv("APP_SECRET")
    if configured:
        return configured.encode("utf-8")

    secret_path = Path(data_dir) / "app.secret"
    if secret_path.exists():
        return secret_path.read_bytes().strip()

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48).encode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(secret_path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as secret_file:
            secret_file.write(secret)
    except FileExistsError:
        return secret_path.read_bytes().strip()
    return secret


def _derive_key(master_secret, purpose):
    return hmac.new(master_secret, purpose.encode("ascii"), hashlib.sha256).digest()


def create_app(test_config=None):
    data_dir = os.getenv("DATA_DIR", "/data")
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.path.join(data_dir, "url-to-ssh.db"),
        DATA_DIR=data_dir,
        SSH_CONNECT_TIMEOUT=int(os.getenv("SSH_CONNECT_TIMEOUT", "10")),
        SSH_COMMAND_TIMEOUT=int(os.getenv("SSH_COMMAND_TIMEOUT", "60")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    master_secret = app.config.get("MASTER_SECRET") or _load_master_secret(app.config["DATA_DIR"])
    app.secret_key = _derive_key(master_secret, "flask-session")
    encryption_key = base64.urlsafe_b64encode(_derive_key(master_secret, "stored-secrets"))
    app.extensions["secret_cipher"] = Fernet(encryption_key)

    app.teardown_appcontext(close_db)
    register_routes(app)

    with app.app_context():
        get_db().executescript(SCHEMA)
        get_db().commit()
        bootstrap_password = os.getenv("ADMIN_PASSWORD")
        if bootstrap_password and not get_setting("admin_password_hash"):
            set_setting("admin_password_hash", generate_password_hash(bootstrap_password))

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            g.get("database_path", None) or request_app_config("DATABASE"),
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def request_app_config(key):
    from flask import current_app

    return current_app.config[key]


def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def get_setting(key):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key, value):
    get_db().execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    get_db().commit()


def encrypt_value(value):
    from flask import current_app

    return current_app.extensions["secret_cipher"].encrypt(value.encode("utf-8"))


def decrypt_value(value):
    from flask import current_app

    try:
        return current_app.extensions["secret_cipher"].decrypt(value).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("无法解密已保存的凭据，请检查 APP_SECRET 是否发生变化") from exc


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csrf_protect():
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    expected = session.get("csrf_token")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        if request.path.startswith("/api/"):
            return jsonify(error="安全令牌无效，请刷新页面后重试"), 400
        return Response("Bad CSRF token", status=400, mimetype="text/plain")
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify(error="请先登录"), 401
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def api_login_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        csrf_error = csrf_protect()
        if csrf_error:
            return csrf_error
        return view(*args, **kwargs)

    return wrapped


def normalize_mac(value):
    value = (value or "").strip().upper().replace("-", ":")
    if value and not MAC_PATTERN.match(value):
        raise ValueError("MAC 地址格式应为 AA:BB:CC:DD:EE:FF")
    return value or None


def bounded_port(value, field_name):
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是数字") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"{field_name}必须在 1 到 65535 之间")
    return port


def validate_host_payload(payload, existing=None):
    name = str(payload.get("name", "")).strip()
    address = str(payload.get("address", "")).strip()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not name or not address or not username:
        raise ValueError("名称、IP/主机名和 SSH 用户名不能为空")
    if not password and existing is None:
        raise ValueError("新增主机时 SSH 密码不能为空")
    return {
        "name": name[:120],
        "address": address[:255],
        "mac": normalize_mac(payload.get("mac")),
        "ssh_port": bounded_port(payload.get("ssh_port", 22), "SSH 端口"),
        "username": username[:255],
        "password": password,
        "wol_broadcast": str(payload.get("wol_broadcast") or "255.255.255.255").strip()[:255],
        "wol_port": bounded_port(payload.get("wol_port", 9), "WOL 端口"),
    }


def validate_command_payload(payload):
    name = str(payload.get("name", "")).strip()
    command = str(payload.get("command", ""))
    host_id = payload.get("host_id") or None
    if not name or not command.strip():
        raise ValueError("指令名称和指令内容不能为空")
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValueError(f"指令不能超过 {MAX_COMMAND_LENGTH} 个字符")
    if host_id and not get_host(host_id):
        raise ValueError("指定的主机不存在")
    return {"name": name[:120], "command": command, "host_id": host_id}


def get_host(host_id):
    return get_db().execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()


def public_host(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"],
        "mac": row["mac"] or "",
        "ssh_port": row["ssh_port"],
        "username": row["username"],
        "wol_broadcast": row["wol_broadcast"],
        "wol_port": row["wol_port"],
    }


def host_link_secret(host):
    return decrypt_value(host["link_secret_encrypted"]).encode("ascii")


def link_signature(host, action, command=""):
    message = f"{action}\n{host['id']}\n{command}".encode("utf-8")
    return hmac.new(host_link_secret(host), message, hashlib.sha256).hexdigest()


def signature_valid(host, action, command, signature):
    return bool(signature) and hmac.compare_digest(link_signature(host, action, command), signature)


def execution_url(host, command):
    query = urlencode({"command": command, "sig": link_signature(host, "run", command)})
    return request.url_root.rstrip("/") + url_for("signed_run", host_id=host["id"]) + "?" + query


def wake_url(host):
    query = urlencode({"sig": link_signature(host, "wake")})
    return request.url_root.rstrip("/") + url_for("signed_wake", host_id=host["id"]) + "?" + query


def execute_stored_host(host, command):
    if not command or len(command) > MAX_COMMAND_LENGTH:
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "error": f"指令不能为空且不能超过 {MAX_COMMAND_LENGTH} 个字符",
            "truncated": False,
        }

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    stdout_data = bytearray()
    stderr_data = bytearray()
    truncated = False
    try:
        client.connect(
            hostname=host["address"],
            port=host["ssh_port"],
            username=host["username"],
            password=decrypt_value(host["password_encrypted"]),
            timeout=request_app_config("SSH_CONNECT_TIMEOUT"),
        )
        _stdin, stdout, _stderr = client.exec_command(
            command, timeout=request_app_config("SSH_COMMAND_TIMEOUT")
        )
        channel = stdout.channel
        deadline = time.monotonic() + request_app_config("SSH_COMMAND_TIMEOUT")
        while True:
            received = False
            if channel.recv_ready():
                chunk = channel.recv(65536)
                received = True
                if len(stdout_data) < MAX_OUTPUT_BYTES:
                    stdout_data.extend(chunk[: MAX_OUTPUT_BYTES - len(stdout_data)])
                if len(stdout_data) >= MAX_OUTPUT_BYTES and chunk:
                    truncated = True
            if channel.recv_stderr_ready():
                chunk = channel.recv_stderr(65536)
                received = True
                remaining = MAX_OUTPUT_BYTES - len(stdout_data) - len(stderr_data)
                if remaining > 0:
                    stderr_data.extend(chunk[:remaining])
                if remaining <= 0 or len(chunk) > remaining:
                    truncated = True
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            if time.monotonic() >= deadline:
                channel.close()
                raise TimeoutError(f"指令执行超过 {request_app_config('SSH_COMMAND_TIMEOUT')} 秒")
            if not received:
                time.sleep(0.02)
        exit_code = channel.recv_exit_status()
        return {
            "stdout": stdout_data.decode("utf-8", errors="replace"),
            "stderr": stderr_data.decode("utf-8", errors="replace"),
            "exit_code": exit_code,
            "error": None,
            "truncated": truncated,
        }
    except Exception as exc:
        return {
            "stdout": stdout_data.decode("utf-8", errors="replace"),
            "stderr": stderr_data.decode("utf-8", errors="replace"),
            "exit_code": None,
            "error": str(exc),
            "truncated": truncated,
        }
    finally:
        client.close()


def send_magic_packet(host):
    if not host["mac"]:
        raise ValueError("该主机尚未填写 MAC 地址")
    mac_bytes = bytes.fromhex(host["mac"].replace(":", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.sendto(packet, (host["wol_broadcast"], host["wol_port"]))


def register_routes(app):
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.route("/")
    def index():
        base_url = request.host
        help_text = f"""SSH远程控制网关 (url-to-ssh)
API[GET]: http://{base_url}/control/<Command>
Params:
  host    : 目标设备的IP地址 (必须),
  user    : SSH登录用户名 (必须),
  pwd     : SSH登录密码 (必须),
  port    : 目标设备的SSH端口 (默认: 22),
Example: http://{base_url}/control/ls -la?host=192.168.1.100&user=root&pwd=password
"""
        return Response(help_text, mimetype="text/plain")

    @app.route("/control/<path:command>", methods=["GET"])
    def execute_ssh_command(command):
        target_host = request.args.get("host")
        username = request.args.get("user")
        password = request.args.get("pwd")
        ssh_port = request.args.get("port", 22)
        if not all([target_host, username, password]):
            return Response(
                "[Error] Missing parameters. Please check: host, user, pwd",
                mimetype="text/plain",
                status=400,
            )

        ssh_client = paramiko.SSHClient()
        output_text = ""
        try:
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(
                hostname=target_host,
                port=int(ssh_port),
                username=username,
                password=password,
                timeout=10,
            )
            _stdin, stdout, stderr = ssh_client.exec_command(command)
            out_str = stdout.read().decode("utf-8", errors="ignore")
            err_str = stderr.read().decode("utf-8", errors="ignore")
            output_text += f"[{username}@{target_host}] exec: {command}\n"
            output_text += "=" * 40 + "\n"
            if out_str:
                output_text += out_str
            if err_str:
                output_text += "\n[STDERR]:\n" + err_str
        except Exception as exc:
            output_text += f"[Connection Failed]: {str(exc)}"
        finally:
            ssh_client.close()
        return Response(output_text, mimetype="text/plain")

    @app.route("/ui/setup", methods=["GET", "POST"])
    def setup():
        if get_setting("admin_password_hash"):
            return redirect(url_for("login"))
        if request.method == "POST":
            csrf_error = csrf_protect()
            if csrf_error:
                return csrf_error
            password = request.form.get("password", "")
            confirmation = request.form.get("confirmation", "")
            if len(password) < 8:
                flash("管理员密码至少需要 8 个字符", "error")
            elif password != confirmation:
                flash("两次输入的密码不一致", "error")
            else:
                set_setting("admin_password_hash", generate_password_hash(password))
                session.clear()
                session["authenticated"] = True
                csrf_token()
                return redirect(url_for("dashboard"))
        return render_template("auth.html", mode="setup")

    @app.route("/ui/login", methods=["GET", "POST"])
    def login():
        if not get_setting("admin_password_hash"):
            return redirect(url_for("setup"))
        if request.method == "POST":
            csrf_error = csrf_protect()
            if csrf_error:
                return csrf_error
            if check_password_hash(get_setting("admin_password_hash"), request.form.get("password", "")):
                session.clear()
                session["authenticated"] = True
                csrf_token()
                destination = request.args.get("next", "")
                if not destination.startswith("/ui/"):
                    destination = url_for("dashboard")
                return redirect(destination)
            flash("密码不正确", "error")
        return render_template("auth.html", mode="login")

    @app.post("/ui/logout")
    @login_required
    def logout():
        csrf_error = csrf_protect()
        if csrf_error:
            return csrf_error
        session.clear()
        return redirect(url_for("login"))

    @app.get("/ui/")
    @login_required
    def dashboard():
        hosts = get_db().execute("SELECT * FROM hosts ORDER BY name COLLATE NOCASE").fetchall()
        return render_template("dashboard.html", hosts=hosts)

    @app.get("/ui/hosts/<host_id>")
    @login_required
    def host_detail(host_id):
        host = get_host(host_id)
        if not host:
            return Response("Host not found", status=404)
        commands = get_db().execute(
            "SELECT * FROM commands WHERE host_id IS NULL OR host_id = ? "
            "ORDER BY host_id IS NOT NULL, name COLLATE NOCASE",
            (host_id,),
        ).fetchall()
        return render_template(
            "host_detail.html", host=host, commands=commands, generated_wake_url=wake_url(host)
        )

    @app.get("/ui/commands")
    @login_required
    def command_library():
        commands = get_db().execute(
            "SELECT commands.*, hosts.name AS host_name FROM commands "
            "LEFT JOIN hosts ON hosts.id = commands.host_id "
            "ORDER BY commands.host_id IS NOT NULL, commands.name COLLATE NOCASE"
        ).fetchall()
        hosts = get_db().execute("SELECT id, name FROM hosts ORDER BY name COLLATE NOCASE").fetchall()
        return render_template("commands.html", commands=commands, hosts=hosts)

    @app.post("/api/hosts")
    @api_login_required
    def create_host():
        try:
            values = validate_host_payload(request.get_json(silent=True) or {})
            host_id = str(uuid.uuid4())
            get_db().execute(
                "INSERT INTO hosts(id, name, address, mac, ssh_port, username, password_encrypted, "
                "wol_broadcast, wol_port, link_secret_encrypted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    host_id,
                    values["name"],
                    values["address"],
                    values["mac"],
                    values["ssh_port"],
                    values["username"],
                    encrypt_value(values["password"]),
                    values["wol_broadcast"],
                    values["wol_port"],
                    encrypt_value(secrets.token_urlsafe(32)),
                ),
            )
            get_db().commit()
            return jsonify(host=public_host(get_host(host_id))), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.put("/api/hosts/<host_id>")
    @api_login_required
    def update_host(host_id):
        existing = get_host(host_id)
        if not existing:
            return jsonify(error="主机不存在"), 404
        try:
            values = validate_host_payload(request.get_json(silent=True) or {}, existing)
            password_encrypted = (
                encrypt_value(values["password"])
                if values["password"]
                else existing["password_encrypted"]
            )
            get_db().execute(
                "UPDATE hosts SET name=?, address=?, mac=?, ssh_port=?, username=?, password_encrypted=?, "
                "wol_broadcast=?, wol_port=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    values["name"],
                    values["address"],
                    values["mac"],
                    values["ssh_port"],
                    values["username"],
                    password_encrypted,
                    values["wol_broadcast"],
                    values["wol_port"],
                    host_id,
                ),
            )
            get_db().commit()
            return jsonify(host=public_host(get_host(host_id)))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.delete("/api/hosts/<host_id>")
    @api_login_required
    def delete_host(host_id):
        cursor = get_db().execute("DELETE FROM hosts WHERE id = ?", (host_id,))
        get_db().commit()
        if not cursor.rowcount:
            return jsonify(error="主机不存在"), 404
        return jsonify(ok=True)

    @app.post("/api/hosts/<host_id>/execute")
    @api_login_required
    def api_execute(host_id):
        host = get_host(host_id)
        if not host:
            return jsonify(error="主机不存在"), 404
        command = str((request.get_json(silent=True) or {}).get("command", ""))
        if not command.strip() or len(command) > MAX_COMMAND_LENGTH:
            return jsonify(error=f"指令不能为空且不能超过 {MAX_COMMAND_LENGTH} 个字符"), 400
        result = execute_stored_host(host, command)
        result["generated_url"] = execution_url(host, command)
        return jsonify(result)

    @app.post("/api/hosts/<host_id>/wake")
    @api_login_required
    def api_wake(host_id):
        host = get_host(host_id)
        if not host:
            return jsonify(error="主机不存在"), 404
        try:
            send_magic_packet(host)
            return jsonify(message="唤醒数据包已发送", generated_url=wake_url(host))
        except (ValueError, OSError) as exc:
            return jsonify(error=str(exc)), 400

    @app.post("/api/hosts/<host_id>/rotate-link-key")
    @api_login_required
    def rotate_link_key(host_id):
        if not get_host(host_id):
            return jsonify(error="主机不存在"), 404
        get_db().execute(
            "UPDATE hosts SET link_secret_encrypted=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (encrypt_value(secrets.token_urlsafe(32)), host_id),
        )
        get_db().commit()
        return jsonify(message="链接密钥已轮换，旧链接现已失效", wake_url=wake_url(get_host(host_id)))

    @app.post("/api/commands")
    @api_login_required
    def create_command():
        try:
            values = validate_command_payload(request.get_json(silent=True) or {})
            command_id = str(uuid.uuid4())
            get_db().execute(
                "INSERT INTO commands(id, name, command, host_id) VALUES (?, ?, ?, ?)",
                (command_id, values["name"], values["command"], values["host_id"]),
            )
            get_db().commit()
            return jsonify(id=command_id), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.put("/api/commands/<command_id>")
    @api_login_required
    def update_command(command_id):
        if not get_db().execute("SELECT 1 FROM commands WHERE id=?", (command_id,)).fetchone():
            return jsonify(error="预设指令不存在"), 404
        try:
            values = validate_command_payload(request.get_json(silent=True) or {})
            get_db().execute(
                "UPDATE commands SET name=?, command=?, host_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (values["name"], values["command"], values["host_id"], command_id),
            )
            get_db().commit()
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.delete("/api/commands/<command_id>")
    @api_login_required
    def delete_command(command_id):
        cursor = get_db().execute("DELETE FROM commands WHERE id=?", (command_id,))
        get_db().commit()
        if not cursor.rowcount:
            return jsonify(error="预设指令不存在"), 404
        return jsonify(ok=True)

    @app.get("/run/<host_id>")
    def signed_run(host_id):
        host = get_host(host_id)
        command = request.args.get("command", "")
        if not host:
            return Response("[Error] Host not found", status=404, mimetype="text/plain")
        if not signature_valid(host, "run", command, request.args.get("sig")):
            return Response("[Error] Invalid signature", status=403, mimetype="text/plain")
        result = execute_stored_host(host, command)
        lines = [f"[{host['username']}@{host['address']}] exec: {command}", "=" * 40]
        if result["stdout"]:
            lines.append(result["stdout"])
        if result["stderr"]:
            lines.extend(["[STDERR]:", result["stderr"]])
        if result["error"]:
            lines.append(f"[Connection Failed]: {result['error']}")
        if result["truncated"]:
            lines.append("[Output truncated at 1 MiB]")
        return Response("\n".join(lines), mimetype="text/plain")

    @app.get("/wake/<host_id>")
    def signed_wake(host_id):
        host = get_host(host_id)
        if not host:
            return Response("[Error] Host not found", status=404, mimetype="text/plain")
        if not signature_valid(host, "wake", "", request.args.get("sig")):
            return Response("[Error] Invalid signature", status=403, mimetype="text/plain")
        try:
            send_magic_packet(host)
            return Response("[OK] Wake-on-LAN packet sent", mimetype="text/plain")
        except (ValueError, OSError) as exc:
            return Response(f"[Error] {str(exc)}", status=400, mimetype="text/plain")


app = create_app()


if __name__ == "__main__":
    print(f"Server starting on port {LISTEN_PORT}...")
    app.run(host="0.0.0.0", port=LISTEN_PORT)
