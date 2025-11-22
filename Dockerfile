FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY app.py .

# 设置默认环境变量 (可以在运行时覆盖)
ENV HTTP_PORT=8080

# 启动命令
CMD ["python", "app.py"]