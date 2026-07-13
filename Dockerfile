FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用与 WebUI 资源
COPY app.py .
COPY templates ./templates
COPY static ./static

# SQLite、加密密钥和其他持久化数据
RUN mkdir -p /data
VOLUME ["/data"]

# 设置默认环境变量 (可以在运行时覆盖)
ENV HTTP_PORT=8080
ENV DATA_DIR=/data

# 启动命令
CMD ["python", "app.py"]
