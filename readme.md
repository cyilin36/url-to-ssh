# url-to-ssh

这是一个轻量级的 Docker 工具，它充当 **HTTP 到 SSH 的网关**。 通过发送一个简单的 URL 请求，你可以远程控制局域网内的 Linux、Windows (开启SSH) 或 NAS 设备执行命令。非常适合配合 **iOS 快捷指令 (Siri)**、Home Assistant 或 Webhooks 使用。

## 1. 工作原理

该容器运行一个极简的 Python Flask Web 服务器。当它收到 HTTP 请求时：

1. **解析 URL**：从 URL 路径中获取要执行的 **命令**，从 URL 参数中获取目标设备的 **IP、用户名、密码** app.py。
2. **建立连接**：使用 Paramiko 库建立到目标设备的 SSH 连接（支持自定义 SSH 端口，默认 22）app.py。
3. **执行与返回**：在目标设备上执行命令，并将标准输出（stdout）和错误输出（stderr）合并，以 **纯文本 (text/plain)** 格式直接返回给浏览器或调用端 app.py。

_特点：无状态设计（不存储任何账号信息）、支持 Host 网络模式、返回结果直观易读。_

## 2. 部署方法

建议使用 **Host 网络模式** (`--net=host`) 部署，这样容器可以直接使用宿主机网络，避免 Docker 网桥导致的局域网连接问题。

### 方式 A: Docker CLI (直接运行)

```bash
# 默认运行在 8080 端口
docker run -d \
  --net=host \
  --name url-to-ssh \
  --restart unless-stopped \
  url-to-ssh

# 自定义运行在 9999 端口
docker run -d \
  --net=host \
  -e HTTP_PORT=9999 \
  --name url-to-ssh \
  --restart unless-stopped \
  url-to-ssh
  ```

### 方式 B: Docker Compose (推荐)

在项目根目录下创建 `docker-compose.yml`：

```yaml
version: '3'
services:
  url-to-ssh:
    image: ghcr.io/cyilin36/url-to-ssh:latest
    container_name: url-to-ssh
    network_mode: host      # 使用 Host 模式
    environment:
      - HTTP_PORT=8080      # 在此修改监听端口
    restart: unless-stopped
```

### 方式 C: 本地构建

```bash
docker build -t url-to-ssh .
```

## 3. URL 使用方法

### 基本格式

接口地址为 `/control/` 后接命令。参数通过 URL 查询字符串（Query String）传递。

```bash
http://<容器IP>:<端口>/control/<命令>?host=<目标IP>&user=<用户名>&pwd=<密码>&port=<SSH端口>
```

| 参数     | 说明           | 是否必填 | 默认值 |
| ------ | ------------ | ---- | --- |
| `host` | 目标设备的 IP 地址  | ✅ 是  | 无   |
| `user` | SSH 用户名      | ✅ 是  | 无   |
| `pwd`  | SSH 密码       | ✅ 是  | 无   |
| `port` | 目标设备的 SSH 端口 | ❌ 否  | 22  |

### 使用示例

#### 示例 1：查询 Linux 磁盘空间

```bash
http://192.168.1.10:8080/control/df -h?host=192.168.1.100&user=root&pwd=password123

```

#### 示例 2：Windows 远程关机 (配合 iOS 快捷指令)

```bash
http://192.168.1.10:8080/control/shutdown%20/s%20/t%200?host=192.168.1.5&user=myemail%40outlook.com&pwd=mypassword
```

>注意：URL 中的空格建议使用 `%20` 替换，特殊符号（如邮箱里的 `@`）建议使用 `%40` 替换。

---

## ⚠️ 安全警告

1. **仅限内网使用**：本工具通过 URL 明文传递密码，**绝对不要**将其端口暴露在公网（互联网）。
2. **敏感操作慎用**：请务必确认 URL 中的命令无误（如 `rm -rf` 等高危命令）。