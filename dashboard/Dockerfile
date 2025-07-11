# 使用一個輕量級的 Python 基礎映像
FROM python:3.9-slim-buster

# 設定工作目錄
WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式程式碼和模板
COPY app.py .
COPY templates ./templates

# 暴露 Flask 應用程式的埠
EXPOSE 5000

# 定義容器啟動時執行的命令
# CMD ["python", "app.py"]
# 為了確保在生產環境中正確啟動，可以考慮使用 Gunicorn 或其他 WSGI 伺服器
# 這裡我們為了簡潔，直接使用 Flask 的內建伺服器
ENTRYPOINT ["python", "app.py"]