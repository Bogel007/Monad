import requests
from datetime import datetime, timezone
from eth_account import Account
from eth_account.messages import encode_defunct
import os
import json
import random
import time
import threading

Account.enable_unaudited_hdwallet_features()

# === Konstanta dan Endpoint ===
DOMAIN = "faucet-miniapp.monad.xyz"
BASE_URL = f"https://{DOMAIN}"
CHAIN_ID = 10

GET_NONCE_ENDPOINT = f"{BASE_URL}/api/auth"
POST_AUTH_ENDPOINT = f"{BASE_URL}/api/auth"
POST_CLAIM_ENDPOINT = f"{BASE_URL}/api/claim"
PROXY_CHECK_URL = "http://httpbin.org/ip"

# === Konfigurasi ===
MAX_ATTEMPTS = 2
ACCOUNTS_PER_BATCH = 5
lock = threading.Lock()

# === Loader Akun & Proxy ===
def load_accounts_from_json(json_file="data.json"):
    if not os.path.exists(json_file):
        print(f"❌ File `{json_file}` tidak ditemukan.")
        return []
    with open(json_file, "r") as f:
        data = json.load(f)
        return [
            {
                "wallet_address": acc["wallet_address"].strip(),
                "private_key": acc["private_key"].strip(),
                "fid": int(acc["fid"])
            }
            for acc in data
            if all(k in acc for k in ["wallet_address", "private_key", "fid"]) and acc["fid"]
        ]

def load_proxies(proxy_file="proxy.txt"):
    if not os.path.exists(proxy_file):
        print(f"❌ File `{proxy_file}` tidak ditemukan.")
        return []
    with open(proxy_file, "r") as f:
        return [{'http': line.strip(), 'https': line.strip()} for line in f if line.strip()]

def get_external_ip(proxy):
    try:
        res = requests.get(PROXY_CHECK_URL, proxies=proxy, timeout=10)
        return res.json().get("origin")
    except:
        return None

# === Autentikasi & Klaim ===
def fetch_nonce(fid, proxy):
    try:
        res = requests.get(f"{GET_NONCE_ENDPOINT}?fid={fid}", proxies=proxy, timeout=15)
        return res.json().get("nonce")
    except:
        return None

def build_siwe_message(wallet, fid, nonce, issued_at):
    return (
        f"{DOMAIN} wants you to sign in with your Ethereum account:\n"
        f"{wallet}\n\n"
        f"Farcaster Auth\n\n"
        f"URI: https://{DOMAIN}/\n"
        f"Version: 1\n"
        f"Chain ID: {CHAIN_ID}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
        f"Resources:\n"
        f"- farcaster://fid/{fid}"
    )

def sign_message(message, pk):
    encoded = encode_defunct(text=message)
    signed = Account.sign_message(encoded, pk)
    return "0x" + signed.signature.hex()

def authenticate(wallet_address, fid, private_key, proxy):
    nonce = fetch_nonce(fid, proxy)
    if not nonce:
        return None
    issued_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    message = build_siwe_message(wallet_address, fid, nonce, issued_at)
    signature = sign_message(message, private_key)
    payload = {
        "message": message,
        "signature": signature,
        "nonce": nonce,
        "fid": fid
    }
    headers = {"Content-Type": "application/json"}
    try:
        res = requests.post(POST_AUTH_ENDPOINT, headers=headers, json=payload, proxies=proxy, timeout=30)
        return res.json().get("token")
    except:
        return None

def claim_faucet(token, wallet_address, proxy):
    payload = {"address": wallet_address}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    try:
        res = requests.post(POST_CLAIM_ENDPOINT, headers=headers, json=payload, proxies=proxy, timeout=30)
        result = res.json()
        if "txHash" in result:
            return "already_claimed"
        return "claimed"
    except:
        return "failed"

# === Proses Satu Akun (Dipanggil oleh Thread) ===
def run_account(acc, proxies):
    wallet = acc["wallet_address"]
    fid = acc["fid"]
    pk = acc["private_key"]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        proxy = random.choice(proxies)
        ip = get_external_ip(proxy)
        if not ip:
            continue

        try:
            signer = Account.from_key(pk)
            if signer.address.lower() != wallet.lower():
                with lock:
                    print(f"❌ {wallet} - Private key tidak cocok.")
                return
        except:
            with lock:
                print(f"❌ {wallet} - Private key tidak valid.")
            return

        token = authenticate(wallet, fid, pk, proxy)
        if not token:
            continue

        result = claim_faucet(token, wallet, proxy)
        with lock:
            if result == "claimed":
                print(f"🎉 {wallet} - Klaim sukses.")
                return
            elif result == "already_claimed":
                print(f"✅ {wallet} - Sudah diklaim sebelumnya.")
                return
            else:
                print(f"⚠️ {wallet} - Gagal klaim (percobaan {attempt}).")
        time.sleep(2)

    with lock:
        print(f"❌ {wallet} - Gagal setelah {MAX_ATTEMPTS} percobaan.")

# === Main Loop ===
def main_loop():
    try:
        while True:
            all_accounts = load_accounts_from_json()
            proxies = load_proxies()
            if not all_accounts or not proxies:
                print("❌ Tidak ada akun atau proxy.")
                break

            batch_num = 1
            total = len(all_accounts)
            print(f"🚀 Menjalankan total {total} akun dalam batch 5-thread...\n")

            for i in range(0, total, ACCOUNTS_PER_BATCH):
                batch = all_accounts[i:i + ACCOUNTS_PER_BATCH]
                print(f"\n📦 Batch {batch_num}: {len(batch)} akun")
                threads = []

                for acc in batch:
                    t = threading.Thread(target=run_account, args=(acc, proxies))
                    t.start()
                    threads.append(t)
                    time.sleep(0.5)  # opsional jeda antar thread

                for t in threads:
                    t.join()
                batch_num += 1

            print("\n✅ Semua akun selesai diproses.")
            print("⏳ Menunggu 6 jam sebelum siklus berikutnya...\n")
            time.sleep(6 * 60 * 60)

    except KeyboardInterrupt:
        print("\n🛑 Program dihentikan oleh pengguna (Ctrl+C).\n")

if __name__ == "__main__":
    main_loop()
