#!/bin/bash

echo "🚀 開始設置 IoT 憑證管理與 Docker Compose 環境..."

# 1. 檢查並創建 Python 虛擬環境
echo "✨ 檢查並創建 Python 虛擬環境 (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "✅ 虛擬環境已創建。"
else
    echo "✅ 虛擬環境已存在。"
fi

# 進入虛擬環境
source .venv/bin/activate
echo "✅ 已進入虛擬環境。"

# 2. 安裝 Python 依賴
echo "📦 安裝 Python 依賴 (cryptography)..."
pip install -r requirements.txt
if [ $? -eq 0 ]; then
    echo "✅ 依賴安裝成功。"
else
    echo "❌ 依賴安裝失敗，請檢查 requirements.txt 或網路連線。"
    deactivate
    exit 1
fi

# 3. 執行憑證生成腳本
echo "🔒 生成/更新憑證..."
python3 generate_ca_and_device_certs.py
if [ $? -eq 0 ]; then
    echo "✅ 憑證生成/更新成功。"
else
    echo "❌ 憑證生成/更新失敗，請檢查 generate_ca_and_device_certs.py 腳本。"
    deactivate
    exit 1
fi

# 4. 執行 Docker Compose
echo "🐳 啟動 Docker Compose 服務..."
docker-compose up --build
if [ $? -eq 0 ]; then
    echo "🎉 Docker Compose 服務已啟動並運行！"
else
    echo "❌ Docker Compose 啟動失敗，請檢查 docker-compose.yml 或 Docker 狀態。"
    deactivate
    exit 1
fi

echo "設置完成。若要停止服務，請在另一個終端機中執行 'docker-compose down'。"
echo "若要退出虛擬環境，請執行 'deactivate'。"