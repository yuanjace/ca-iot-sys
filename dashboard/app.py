import paho.mqtt.client as mqtt
import ssl
import json
import os
import datetime
from flask import Flask, render_template, jsonify
from threading import Thread, Lock
from cryptography import x509
from cryptography.hazmat.primitives import serialization

# --- 配置 (從環境變數讀取) ---
BROKER_ADDRESS = os.environ.get("BROKER_ADDRESS", "mosquitto")
BROKER_PORT = int(os.environ.get("BROKER_PORT", 8883))
DASHBOARD_ID = os.environ.get("DASHBOARD_ID", "dashboard_monitor")

# 憑證路徑 (從環境變數讀取)
CA_CERT_PATH = os.environ.get("CA_CERT_PATH")
CLIENT_CERT_PATH = os.environ.get("CLIENT_CERT_PATH")
CLIENT_KEY_PATH = os.environ.get("CLIENT_KEY_PATH")

# 設備列表，用於讀取憑證信息
DEVICES = os.environ.get("DEVICE_IDS", "device001,device002").split(",")
# 所有設備的憑證都在 /app/certs/<device_id>/ 路徑下
DEVICE_CERTS_BASE_PATH = "/app/certs/"

app = Flask(__name__)

# 全域變數用於存儲數據和日誌
device_data = {}  # 儲存最新的溫度數據
device_logs = []  # 儲存最近的日誌
log_lock = Lock()  # 鎖定日誌列表以確保線程安全


# --- MQTT 客戶端回調函式 ---
def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print("MQTT Connected successfully.")
        # 訂閱所有設備的溫度主題
        client.subscribe("iot/thermometer/+/temperature", qos=1)
        print("Subscribed to iot/thermometer/+/temperature")
    else:
        print(f"MQTT Connect failed with code {rc}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        log_entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "topic": msg.topic,
            "payload": payload,
        }
        with log_lock:
            device_logs.append(log_entry)
            # 保持日誌列表在一定大小，例如最新的 50 條
            if len(device_logs) > 50:
                device_logs.pop(0)

        # 更新最新設備數據
        device_id = payload.get("device_id")
        if device_id:
            device_data[device_id] = payload

    except json.JSONDecodeError:
        print(f"Received non-JSON message: {msg.payload.decode('utf-8')}")
    except Exception as e:
        print(f"Error processing MQTT message: {e}")


# --- 憑證讀取函式 ---
def get_certificate_info(device_id):
    cert_path = os.path.join(DEVICE_CERTS_BASE_PATH, device_id, f"{device_id}.crt")

    if not os.path.exists(cert_path):
        return {"error": "Certificate not found", "path": cert_path}

    try:
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())

        # 格式化日期
        not_valid_before = cert.not_valid_before_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        not_valid_after = cert.not_valid_after_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

        # 計算剩餘天數
        now = datetime.datetime.now(datetime.timezone.utc)
        time_remaining = cert.not_valid_after_utc - now
        days_remaining = time_remaining.days if time_remaining.days >= 0 else 0

        return {
            "device_id": device_id,
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
            "serial_number": cert.serial_number,
            "not_valid_before": not_valid_before,
            "not_valid_after": not_valid_after,
            "days_remaining": days_remaining,
            "status": "有效" if days_remaining > 0 else "已過期",
            "path": cert_path,
        }
    except Exception as e:
        return {"error": f"Error parsing certificate: {e}", "path": cert_path}


# --- Flask 路由 ---
@app.route("/")
def index():
    # 獲取所有設備的憑證信息
    certs_info = [get_certificate_info(dev) for dev in DEVICES]
    return render_template("index.html", certs_info=certs_info, devices=DEVICES)


@app.route("/api/data")
def get_data():
    certs_info = [get_certificate_info(dev) for dev in DEVICES]

    with log_lock:
        current_logs = list(device_logs)  # 獲取日誌的副本

    return jsonify(
        {"certs_info": certs_info, "device_data": device_data, "logs": current_logs}
    )


# --- MQTT 客戶端運行線程 ---
def run_mqtt_client():
    client = mqtt.Client(client_id=DASHBOARD_ID, protocol=mqtt.MQTTv5)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        # 配置 TLS/SSL
        client.tls_set(
            ca_certs=CA_CERT_PATH,
            certfile=CLIENT_CERT_PATH,
            keyfile=CLIENT_KEY_PATH,
            tls_version=ssl.PROTOCOL_TLSv1_2,
        )
        print("Dashboard MQTT TLS configured successfully.")
    except Exception as e:
        print(f"Error configuring Dashboard MQTT TLS: {e}")
        return

    try:
        client.connect(BROKER_ADDRESS, BROKER_PORT, 60)
        client.loop_forever()  # 保持 MQTT 客戶端運行
    except Exception as e:
        print(f"Error connecting Dashboard MQTT client: {e}")


# 在 Flask 應用啟動前啟動 MQTT 客戶端線程
if __name__ == "__main__":
    # 檢查憑證檔案是否存在
    if (
        not os.path.exists(CA_CERT_PATH)
        or not os.path.exists(CLIENT_CERT_PATH)
        or not os.path.exists(CLIENT_KEY_PATH)
    ):
        print(
            "Dashboard client certificates are missing! Please run generate_ca_and_device_certs.py first."
        )
        exit(1)

    mqtt_thread = Thread(target=run_mqtt_client)
    mqtt_thread.daemon = True  # 設置為守護線程，當主程序退出時自動終止
    mqtt_thread.start()

    print("Starting Flask web server...")
    app.run(host="0.0.0.0", port=5000, debug=False)  # 關閉 debug 模式以避免多線程問題
