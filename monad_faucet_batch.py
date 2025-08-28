import requests
import time
import random
import threading
import json
import logging
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# ==========================
# Konfigurasi
# ==========================
DOMAIN = "faucet-miniapp.monad.xyz"
BASE_URL = f"https://{DOMAIN}"
CHAIN_ID = 10  # Optimism testnet
GET_NONCE_ENDPOINT = f"{BASE_URL}/api/auth"
POST_AUTH_ENDPOINT = f"{BASE_URL}/api/auth/verify"
POST_CLAIM_ENDPOINT = f"{BASE_URL}/api/claim"

RPC_URL = "https://testnet-rpc.monad.xyz"
MAIN_WALLET = "0x17014818ceb3cdd8ef179b1c8a33765de8611deb"
GAS_LIMIT = 21000

w3 = Web3(Web3.HTTPProvider(RPC_URL))

MAX_ATTEMPTS = 3
RETRY_BACKOFF = [1, 2, 4]  # detik
THREADS_PER_BATCH = 5

# ==========================
# Logging
# ==========================
logging.basicConfig(
    filename="bot.log",
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ==========================
# Load Data
# ==========================
def load_accounts():
    try:
        with open("data.json") as f:
            data = json.load(f)
        accounts = []
        for item in data:
            accounts.append({
                "wallet_address": item["wallet_address"],
                "private_key": item["private_key"],
                "fid": item.get("fid", 0)
            })
        return accounts
    except Exception as e:
        print(f"❌ Gagal load akun: {e}")
        return []

def load_proxies():
    try:
        with open("proxy.txt") as f:
            proxies = [line.strip() for line in f if line.strip()]
        return proxies if proxies else [None]
    except:
        return [None]

# ==========================
# Helper Web3
# ==========================
def send_to_main(wallet, private_key):
    try:
        balance = w3.eth.get_balance(wallet)
        if balance <= 0:
            return f"{wallet[:6]}... saldo kosong"
        nonce = w3.eth.get_transaction_count(wallet)
        gas_price = w3.eth.gas_price
        value = balance - gas_price * GAS_LIMIT
        if value <= 0:
            return f"{wallet[:6]}... saldo tidak cukup untuk transfer"
        tx = {
            "to": MAIN_WALLET,
            "value": value,
            "gas": GAS_LIMIT,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        }
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        return f"{wallet[:6]}... transfer sukses tx: {tx_hash.hex()}"
    except Exception as e:
        return f"{wallet[:6]}... gagal transfer: {e}"

# ==========================
# Session & Faucet
# ==========================
def make_session(proxy=None):
    s = requests.Session()
    s.headers.update({
        "User-Agent": f"Mozilla/5.0 (Python Bot) {random.randint(100,999)}",
        "Accept": "application/json",
        "Connection": "keep-alive"
    })
    if proxy:
        if not proxy.startswith("http"):
            proxy = "http://" + proxy
        s.proxies.update({"http": proxy, "https": proxy})
    return s

def get_nonce(session, wallet, fid):
    try:
        res = session.get(f"{GET_NONCE_ENDPOINT}?address={wallet}", timeout=15)
        if res.status_code == 200 and "nonce" in res.json():
            return res.json()["nonce"]
    except Exception as e:
        logging.error(f"{wallet} | Nonce error: {e}")
    return None

def authenticate(session, wallet, fid, private_key):
    nonce = get_nonce(session, wallet, fid)
    if not nonce:
        return None
    message = encode_defunct(text=nonce)
    signed = Account.sign_message(message, private_key)
    payload = {"fid": fid, "address": wallet, "signature": signed.signature.hex()}
    try:
        res = session.post(POST_AUTH_ENDPOINT, json=payload, timeout=15)
        if res.status_code == 200 and "token" in res.json():
            return res.json()["token"]
    except Exception as e:
        logging.error(f"{wallet} | Auth error: {e}")
    return None

def claim_faucet(session, token, wallet):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = session.post(POST_CLAIM_ENDPOINT, headers=headers, json={"address": wallet}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if data.get("success"):
                return True
    except Exception as e:
        logging.error(f"{wallet} | Claim error: {e}")
    return False

# ==========================
# Worker
# ==========================
def worker(acc, proxies):
    wallet = acc["wallet_address"]
    private_key = acc["private_key"]
    fid = acc["fid"]
    proxy = random.choice(proxies)
    session = make_session(proxy)

    for attempt in range(MAX_ATTEMPTS):
        token = authenticate(session, wallet, fid, private_key)
        if not token:
            print(f"❌ {wallet[:6]} | Auth gagal, retry {attempt+1}/{MAX_ATTEMPTS}")
            time.sleep(RETRY_BACKOFF[attempt % len(RETRY_BACKOFF)])
            continue
        success = claim_faucet(session, token, wallet)
        if success:
            print(f"✅ {wallet[:6]} | Claim berhasil")
            transfer_res = send_to_main(wallet, private_key)
            print(f"🔄 {transfer_res}")
            logging.info(f"{wallet} | Claimed & transferred")
            return
        else:
            print(f"❌ {wallet[:6]} | Claim gagal, retry {attempt+1}/{MAX_ATTEMPTS}")
            time.sleep(RETRY_BACKOFF[attempt % len(RETRY_BACKOFF)])
    print(f"❌ {wallet[:6]} | Gagal total setelah {MAX_ATTEMPTS} percobaan")

# ==========================
# Main
# ==========================
def main():
    accounts = load_accounts()
    proxies = load_proxies()
    threads = []

    for acc in accounts:
        t = threading.Thread(target=worker, args=(acc, proxies))
        t.start()
        threads.append(t)
        while threading.active_count() > THREADS_PER_BATCH:
            time.sleep(0.5)

    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
