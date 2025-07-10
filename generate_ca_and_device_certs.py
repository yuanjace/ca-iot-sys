from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509 import DNSName, SubjectAlternativeName, IPAddress
import ipaddress
import datetime

# === 配置區（Configuration） ===
# 這裡定義需要產生憑證的裝置清單
devices = ["device001", "device002"]
# 憑證有效天數
validity_days = 365
ROOT_CA_VALIDITY_DAYS = 365 * 10  # Root CA 憑證的有效期
EXPIRY_THRESHOLD_DAYS = 30  # 憑證在過期前多少天開始算作“即將過期”


def generate_key(path, key_size=2048):
    """
    產生 RSA 私鑰（非對稱加密），並將其儲存為 PEM 格式
    :param path: 私鑰輸出檔案路徑
    :param key_size: 私鑰長度（最低預設 2048 bits），長期有效的root_ca NIST建議使用 3072 bits 或更高
    :return: 回傳生成的 private key 物件
    """
    # 使用 cryptography 建立 RSA 私鑰
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    # 將私鑰以 PEM 格式寫入檔案，並不加密
    with open(path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    return key


def is_certificate_expiring_soon(cert_path, threshold_days):
    """
    檢查憑證是否存在或是否即將過期
    :param cert_path: 憑證檔案路徑
    :param threshold_days: 憑證在過期前多少天視為“即將過期”
    :return: 如果憑證不存在或即將過期，返回 True；否則返回 False
    """
    if not os.path.exists(cert_path):
        print(f"  Certificate not found: {cert_path}. Will generate new.")
        return True

    try:
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())

        # 檢查憑證的有效期
        now = datetime.datetime.now(datetime.timezone.utc)
        time_remaining = cert.not_valid_after_utc - now
        print(f"  憑證的有效期{cert.not_valid_after_utc}")

        if time_remaining.days <= threshold_days:
            print(
                f"  Certificate {os.path.basename(cert_path)} expires in {time_remaining.days} days. Will generate new."
            )
            return True
        else:
            print(
                f"  Certificate {os.path.basename(cert_path)} valid for {time_remaining.days} more days. No need to update."
            )
            return False
    except Exception as e:
        print(
            f"  Error reading or parsing certificate {cert_path}: {e}. Will generate new."
        )
        return True  # 如果讀取或解析失敗，也視為需要重新生成


def generate_root_ca():
    """
    產生自簽 Root CA 憑證。如果憑證已存在且未即將過期，則載入現有的。
    :return: 回傳 root key 與 root certificate
    """
    os.makedirs("certs/root_ca", exist_ok=True)
    root_ca_dir = os.path.join("certs", "root_ca")

    key_path = os.path.join(root_ca_dir, "root_ca.key")
    cert_path = os.path.join(root_ca_dir, "root_ca.crt")

    # --- 檢查 Root CA 是否需要更新 ---
    print("Checking device certificate for Root CA...")
    if not is_certificate_expiring_soon(cert_path, EXPIRY_THRESHOLD_DAYS):
        # 如果憑證存在且未即將過期，則載入現有的金鑰和憑證
        try:
            with open(key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
            with open(cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
            print("  Loaded existing Root CA.")
            return key, cert
        except Exception as e:
            print(f"  Failed to load existing Root CA: {e}. Will generate new.")
            # 如果載入失敗，則繼續生成新的

    # 1. 生成 Root CA 的私鑰
    key = generate_key(key_path)

    # 2. 設定 CA 的證書主體與簽發者（因為是自簽，所以兩者相同）
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "TW"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "My Root CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "My Root CA"),
        ]
    )

    # 3. 取得當前 UTC 時間（時區感知）
    now = datetime.datetime.now(datetime.timezone.utc)

    # 4. 建立憑證
    cert_builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)  # 憑證開始生效時間
        .not_valid_after(
            now + datetime.timedelta(days=ROOT_CA_VALIDITY_DAYS)
        )  # 憑證過期時間
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )  # 基本約束：這是一個 CA 憑證
    )

    # 5. 使用私鑰簽署憑證
    cert = cert_builder.sign(key, hashes.SHA256())

    # 6. 將憑證以 PEM 格式寫入檔案
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return key, cert


def generate_device_cert(name, signer_key, signer_cert):
    """
    為單一裝置產生私鑰、CSR 及憑證，並簽署。同時將 Root CA 或 Intermediate CA 憑證複製到裝置目錄
    :param name: 裝置名稱，將用於憑證的 Common Name 及 SAN
    :param signer_key: 用於簽署的私鑰（Root CA 或 Intermediate CA）
    :param signer_cert: 用於簽署的憑證（Root CA 或 Intermediate CA）
    """
    os.makedirs(f"certs/{name}", exist_ok=True)
    device_dir = os.path.join("certs", name)

    key_path = os.path.join(device_dir, f"{name}.key")
    cert_path = os.path.join(device_dir, f"{name}.crt")
    csr_path = os.path.join(device_dir, f"{name}.csr")
    device_ca_path = os.path.join(device_dir, "root_ca.crt")

    # --- 檢查設備憑證是否需要更新 ---
    print(f"Checking device certificate for {name}...")
    if not is_certificate_expiring_soon(cert_path, EXPIRY_THRESHOLD_DAYS):
        # 如果憑證存在且未即將過期，則複製 Root CA 並返回
        # 複製 Root CA 即使憑證未過期也執行，確保 Root CA 始終存在於設備目錄
        with open(device_ca_path, "wb") as f:
            f.write(signer_cert.public_bytes(serialization.Encoding.PEM))
        print(
            f"  Device certificate for {name} is current. Root CA copied to {device_ca_path}"
        )
        return

    # 1. 生成裝置私鑰
    key = generate_key(key_path)

    # 2. 當前 UTC 時間
    now = datetime.datetime.now(datetime.timezone.utc)

    # 3. 產生 CSR（Certificate Signing Request）
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .add_extension(
            SubjectAlternativeName([DNSName(name)]), critical=False
        )  # 加入 SAN，讓裝置透過 DNSName 驗證
        .sign(key, hashes.SHA256())
    )

    # 4. 將 CSR 輸出
    with open(csr_path, "wb") as f:
        f.write(csr.public_bytes(serialization.Encoding.PEM))

    # 5. 使用 CA 簽署裝置憑證
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(signer_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=validity_days))  # 裝置憑證有效期
        .add_extension(
            SubjectAlternativeName([DNSName(name)]), critical=False
        )  # 同樣加入 SAN
        .sign(signer_key, hashes.SHA256())
    )

    # 6. 輸出裝置憑證
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    # 7. 自動分發 Root CA 或 Intermediate CA 憑證到每個設備資料夾
    with open(device_ca_path, "wb") as f:
        f.write(signer_cert.public_bytes(serialization.Encoding.PEM))


def generate_broker_cert(name, signer_key, signer_cert):
    """
    為 MQTT Broker 產生私鑰、CSR 及憑證，並簽署
    :param name: Broker 的主機名
    :param signer_key: 用於簽署的私鑰（Root CA 或 Intermediate CA）
    :param signer_cert: 用於簽署的憑證（Root CA 或 Intermediate CA）
    """
    os.makedirs(f"certs/{name}", exist_ok=True)
    broker_dir = os.path.join("certs", name)

    key_path = os.path.join(broker_dir, f"{name}.key")
    cert_path = os.path.join(broker_dir, f"{name}.crt")
    csr_path = os.path.join(broker_dir, f"{name}.csr")

    # --- 檢查 Broker 憑證是否需要更新 ---
    print(f"Checking broker certificate for {name}...")
    if not is_certificate_expiring_soon(cert_path, EXPIRY_THRESHOLD_DAYS):
        # 如果憑證存在且未即將過期，則返回
        print(f"  Broker certificate for {name} is current.")
        return

    # 1. 生成 Broker 私鑰
    key = generate_key(key_path)

    # 2. 當前 UTC 時間
    now = datetime.datetime.now(datetime.timezone.utc)

    # 3. 產生 CSR
    # SAN 應包含 localhost 和 127.0.0.1，以確保在本地測試環境下能被正確驗證
    # 現代瀏覽器主要依賴 SAN 欄位來進行比對
    san_entries = [
        DNSName("localhost"),
        IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        DNSName("mosquitto"),
    ]

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .add_extension(SubjectAlternativeName(san_entries), critical=False)
        .sign(key, hashes.SHA256())
    )

    # 4. 將 CSR 輸出
    with open(csr_path, "wb") as f:
        f.write(csr.public_bytes(serialization.Encoding.PEM))

    # 5. 使用 CA 簽署 Broker 憑證
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(signer_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=validity_days))
        .add_extension(
            SubjectAlternativeName(san_entries), critical=False
        )  # 同樣加入 SAN
        .add_extension(  # 新增：Extended Key Usage 確保憑證可用於伺服器驗證
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(signer_key, hashes.SHA256())
    )

    # 6. 輸出 Broker 憑證
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


if __name__ == "__main__":
    import os

    # 確保輸出目錄存在
    os.makedirs("certs", exist_ok=True)

    # 1. 生成 Root CA（金鑰 + 自簽憑證）
    root_key, root_cert = generate_root_ca()

    # 2. 為每個裝置生成憑證，簽署者使用 Root CA
    for dev in devices:
        generate_device_cert(dev, root_key, root_cert)

    # 3. 為 MQTT Broker 生成憑證，簽署者使用 Root CA
    generate_broker_cert("mosquitto", root_key, root_cert)

    print("CA and device certificates generated in 'certs' directory.")
