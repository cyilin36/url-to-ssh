# url-to-ssh

一个轻量的 HTTP 到 SSH 网关，并带有主机、预设指令和 Wake-on-LAN 管理界面。适合在可信局域网内配合浏览器、iOS 快捷指令、Home Assistant 或 Webhook 使用。

当前 Compose 使用镜像：`ghcr.io/cyilin36/url-to-ssh:v1.1-beta1`。

## 功能

- 在 `/ui/` 初始化单管理员密码并登录管理后台
- 管理主机的 IP/主机名、MAC、SSH 账号和连接端口
- 加密保存 SSH 密码，使用 SQLite 持久化数据
- 在主机页面执行临时指令并查看 stdout、stderr、退出码和错误信息
- 保存全局指令或指定主机的专属指令，点击后可以直接执行
- 根据保存的主机和输入的指令生成原 `/control` 接口 URL
- 从 WebUI 发送 Wake-on-LAN 魔术包
- 完整保留原有 `/control/<command>` 接口

## Docker Compose 部署

仓库中的 `docker-compose.yml` 默认面向 Linux 主机，使用 Host 网络模式，以便容器直接访问局域网主机并发送广播包。

```yaml
services:
  url-to-ssh:
    image: ghcr.io/cyilin36/url-to-ssh:v1.1-beta1
    container_name: url-to-ssh
    restart: always
    network_mode: host
    environment:
      - HTTP_PORT=9091
      - DATA_DIR=/data
      # 可选：首次启动时自动设置管理员密码
      # - ADMIN_PASSWORD=change-me-now
      # 可选：固定主密钥；设置后不可随意更改
      # - APP_SECRET=replace-with-a-long-random-secret
    volumes:
      - ./data:/data
```

启动：

```bash
docker compose pull
docker compose up -d
```

启动后访问：

- WebUI：`http://<服务器IP>:9091/ui/`
- 原有接口帮助：`http://<服务器IP>:9091/`

如果没有配置 `ADMIN_PASSWORD`，第一次打开 WebUI 时会要求创建管理员密码。如果没有配置 `APP_SECRET`，应用会在 `/data/app.secret` 自动生成主密钥。数据库和该文件必须一起备份；丢失或更改密钥后，已保存的密码将无法解密。

持久化数据保存在项目目录的 `./data/` 中，主要包含：

```text
data/
├── app.secret
└── url-to-ssh.db
```

### Linux 网络配置

Linux 用户直接使用仓库中的 `docker-compose.yml` 即可。`network_mode: host` 会让服务直接监听 Linux 主机的 `9091` 端口，不需要再添加 `ports:`。

### macOS 与 `docker-compose.override.yml`

macOS 用户需要在项目根目录创建 `docker-compose.override.yml`：

```yaml
services:
  url-to-ssh:
    network_mode: bridge
    ports:
      - "9091:9091"
```

然后仍然使用普通命令启动：

```bash
docker compose pull
docker compose up -d
```

然后访问 `http://localhost:9091/ui/`。macOS 下 Wake-on-LAN 广播可能受 Docker 虚拟机网络限制，需要稳定使用 WOL 时建议部署到 Linux 主机。

也可以在项目目录本地构建：

```bash
docker build -t url-to-ssh .
```

## WebUI 使用流程

1. 打开 `/ui/` 并设置或输入管理员密码。
2. 添加主机，填写名称、IP/主机名、SSH 用户名和密码。MAC 地址只在需要 Wake-on-LAN 时填写。
3. 打开主机控制台，输入命令并点击“发送并生成 URL”。
4. 页面会显示执行结果和原 `/control` 接口 URL，可复制给快捷指令或其他自动化工具使用。
5. 在“指令库”中保存常用命令；全局指令会出现在所有主机页面，主机专属指令只出现在对应主机页面。

## 原有接口（保持兼容）

原有调用格式和响应保持不变：

```text
GET /control/<命令>?host=<目标IP>&user=<用户名>&pwd=<密码>&port=<SSH端口>
```

例如：

```text
http://192.168.1.10:9091/control/df%20-h?host=192.168.1.100&user=root&pwd=password123
```

| 参数 | 说明 | 必填 | 默认值 |
| --- | --- | --- | --- |
| `host` | 目标设备 IP 或主机名 | 是 | — |
| `user` | SSH 用户名 | 是 | — |
| `pwd` | SSH 密码 | 是 | — |
| `port` | SSH 端口 | 否 | `22` |

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HTTP_PORT` | `8080` | HTTP 监听端口 |
| `DATA_DIR` | `/data` | SQLite 和自动生成密钥的保存目录 |
| `ADMIN_PASSWORD` | 空 | 仅在尚未初始化管理员时设置初始密码 |
| `APP_SECRET` | 自动生成 | SSH 凭据加密和管理员会话使用的主密钥 |
| `SSH_CONNECT_TIMEOUT` | `10` | SSH 连接超时，单位秒 |
| `SSH_COMMAND_TIMEOUT` | `60` | SSH 指令执行超时，单位秒 |
| `COOKIE_SECURE` | `false` | 通过 HTTPS 使用时设为 `true` |

单条指令最大 4096 个字符，单次 stdout 与 stderr 合计最多保存 1 MiB，超出后会在结果中标记截断。

## 开发与测试

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
DATA_DIR=/tmp/url-to-ssh-dev ADMIN_PASSWORD=development-password python app.py
```

运行测试：

```bash
pytest
```

## 安全提示

- 本项目默认面向可信内网。需要公网访问时，请使用 HTTPS、网络访问控制和反向代理。
- `/control` URL 会包含 SSH 用户名和密码，请只在可信内网中使用并避免公开分享。
- 对关机、删除文件等高风险命令，应在保存和分享前仔细确认。
