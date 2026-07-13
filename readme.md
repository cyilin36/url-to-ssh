# url-to-ssh

一个轻量的 HTTP 到 SSH 网关，并带有主机、预设指令和 Wake-on-LAN 管理界面。适合在可信局域网内配合浏览器、iOS 快捷指令、Home Assistant 或 Webhook 使用。

## 功能

- 在 `/ui/` 管理主机的 IP、MAC、SSH 账号和连接端口
- 加密保存 SSH 密码，使用 SQLite 持久化数据
- 在主机页面执行临时指令并查看 stdout、stderr 和退出码
- 保存全局指令或指定主机的专属指令
- 为固定的“主机 + 指令”生成不含 SSH 密码的永久签名 URL
- 发送 Wake-on-LAN 魔术包并生成签名唤醒 URL
- 完整保留原有 `/control/<command>` 接口

## Docker Compose 部署

建议使用 Host 网络模式，以便容器直接访问局域网主机并发送广播包。

```yaml
services:
  url-to-ssh:
    image: ghcr.io/cyilin36/url-to-ssh:latest
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
      - url-to-ssh-data:/data

volumes:
  url-to-ssh-data:
```

启动后访问：

- WebUI：`http://<服务器IP>:9091/ui/`
- 原有接口帮助：`http://<服务器IP>:9091/`

如果没有配置 `ADMIN_PASSWORD`，第一次打开 WebUI 时会要求创建管理员密码。如果没有配置 `APP_SECRET`，应用会在 `/data/app.secret` 自动生成主密钥。数据库和该文件必须一起备份；丢失或更改密钥后，已保存的密码将无法解密。

也可以在项目目录本地构建：

```bash
docker build -t url-to-ssh .
```

## WebUI 使用流程

1. 打开 `/ui/` 并设置或输入管理员密码。
2. 添加主机，填写名称、IP/主机名、SSH 用户名和密码。MAC 地址只在需要 Wake-on-LAN 时填写。
3. 打开主机控制台，输入命令并点击“发送并生成 URL”。
4. 页面会显示执行结果和永久签名链接。该链接无需登录即可重复执行同一条命令。
5. 在“指令库”中保存常用命令；全局指令会出现在所有主机页面，主机专属指令只出现在对应主机页面。

每台主机都有独立的链接密钥。在主机页面轮换密钥后，该主机过去生成的全部执行链接和唤醒链接都会失效。

## 新接口

### 永久签名执行链接

WebUI 自动生成以下格式的链接：

```text
GET /run/<host_uuid>?command=<url_encoded_command>&sig=<hmac_signature>
```

签名同时绑定动作、主机 UUID 和完整指令。修改其中任意内容都会导致验证失败。链接不会包含 SSH 用户名或密码。

### 永久签名唤醒链接

```text
GET /wake/<host_uuid>?sig=<hmac_signature>
```

默认向 `255.255.255.255:9` 发送魔术包，可以在每台主机的资料中覆盖广播地址和 UDP 端口。成功响应只代表数据包已经发送，不能保证目标设备已经开机。

### WebUI 管理接口

`/api/hosts`、`/api/commands` 及执行、唤醒、密钥轮换接口仅供登录后的 WebUI 使用，并要求有效的 CSRF 令牌。

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
| `APP_SECRET` | 自动生成 | 凭据加密、会话签名和链接密钥加密的主密钥 |
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
- 永久签名链接本身就是访问凭证；拿到链接的人可以执行其中固定的指令。
- 原有 `/control` 接口会在 URL 中携带明文密码，只为兼容旧调用而保留。新的自动化应优先使用签名链接。
- 对关机、删除文件等高风险命令，应在保存和分享前仔细确认。
