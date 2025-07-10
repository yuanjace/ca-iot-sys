import paho.mqtt.client as mqtt
import time
import ssl
import json
import random
import os

# MQTT Broker 配置
BROKER_ADDRESS = os.environ.get("BROKER_ADDRESS", "mosquitto")
BROKER_PORT = int(os.environ.get("BROKER_PORT", 8883))

# 憑證路徑 (從環境變數讀取，在 Docker 容器內的路徑)
# 這樣每個設備服務可以傳入自己的憑證路徑
CA_CERT_PATH = os.getenv("CA_CERT_PATH")
CLIENT_CERT_PATH = os.getenv("CLIENT_CERT_PATH")
CLIENT_KEY_PATH = os.getenv("CLIENT_KEY_PATH")

DEVICE_ID = os.getenv("DEVICE_ID")  # 從環境變數讀取設備ID
TOPIC = f"iot/thermometer/{DEVICE_ID}/temperature"


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"Connected to MQTT Broker with result code {rc}")
    else:
        print(f"Failed to connect, return code {rc}\n")


def on_publish(client, userdata, mid, reasonCode, properties):
    print(f"Message Published (mid={mid}, reasonCode={reasonCode})")


def main():
    if not all([CA_CERT_PATH, CLIENT_CERT_PATH, CLIENT_KEY_PATH, DEVICE_ID]):
        print(
            "Error: Missing environment variables for certificate paths or DEVICE_ID."
        )
        return

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID)
    client.on_connect = on_connect
    client.on_publish = on_publish

    # 配置 TLS/SSL
    try:
        client.tls_set(
            ca_certs=CA_CERT_PATH,  # 用於驗證 Broker 憑證的 CA 憑證
            certfile=CLIENT_CERT_PATH,  # 客戶端憑證
            keyfile=CLIENT_KEY_PATH,  # 客戶端私鑰
            tls_version=ssl.PROTOCOL_TLSv1_2,  # 推薦使用 TLSv1.2 或更高版本
        )
        print("TLS configured successfully.")
    except Exception as e:
        print(f"Error configuring TLS: {e}")
        return

    # === TLS 設定：載入憑證並啟用雙向驗證 ===
    try:
        # 握手中，Client 會：
        #    a. 驗證 Server Cert 是否由信任 CA 簽發
        #    b. 檢查 Server Cert 有效期與 CN/SAN
        # 將 Client Cert + 簽章傳送給 Server，用於 Server 驗證
        client.connect(BROKER_ADDRESS, BROKER_PORT, 60)
    except Exception as e:
        print(f"Error connecting to MQTT Broker: {e}")
        return

    client.loop_start()  # 在後台啟動網路迴圈

    while True:
        try:
            temperature = round(random.uniform(20.0, 30.0), 2)  # 模擬溫度數據
            payload = {
                "device_id": DEVICE_ID,
                "timestamp": int(time.time()),
                "temperature": temperature,
            }
            client.publish(TOPIC, json.dumps(payload), qos=1)
            print(f"Published: {payload}")
            time.sleep(5)  # 每 5 秒發布一次
        except KeyboardInterrupt:
            print("Exiting...")
            break
        except Exception as e:
            print(f"Error during publishing: {e}")
            break

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
