FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# 创建数据目录（挂载 volume 持久化告警日志）
RUN mkdir -p /data
VOLUME ["/data"]

# 使用 gunicorn 生产级 WSGI 服务器
EXPOSE 5001
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/healthz', timeout=2)"

CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "--access-logfile", "-", "app:app"]
