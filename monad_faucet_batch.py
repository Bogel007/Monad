import requests
import time
import random
import threading
import json
import logging
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3
import os
import sys

# ==========================
# Konfigurasi Faucet & Wallet
# ==========================
DOMAIN = "faucet-miniapp.monad.xyz"
BASE_URL = f"https://{DOMAIN}"
GET_NONCE_ENDPOINT = f"{BASE_URL}/api/auth"
POST_AUTH_ENDPOINT = f"{BASE_URL}/api/auth/verify"
POST_CLAIM_ENDPOINT = f"{BASE_URL}/api/claim"

RPC_URL = "https://testnet-rpc.monad.xyz"
MAIN_WALLET = "0x17014818ceb3cdd8ef179b1c8a33765de8611deb"
CHAIN_ID = 10
GAS_LIMIT = 21000

w3 = Web3(Web3.HTTPProvider(RPC_URL))

MAX_ATTEMPTS = 3
THREADS_PER_BATCH = 5
RETRY_BACKOFF = [1,2,4]  # detik

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
# Dashboard
# ==========================
dashboard_status = {}
dashboard_lock = threading.Lock()
stop_render_thread = threading.Event()

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def render_dashboard():
    with dashboard_lock:
        clear_console()
        print("="*50)
        print("🚀 BOT FAUCET MONAD - DASHBOARD 🚀")
        print(f"📁 Working Dir: {os.getcwd()}")
        print("="*50)
        for wallet, status in dashboard_status.items():
            print(f"{wallet}: {status}")
        print("="*50)
        sys.stdout.flush()

def dashboard_loop():
    while not stop_render_thread.is_set():
        render_dashboard()
        time.sleep(1)

# ==========================
# Load Accounts & Proxy
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
                "fid": item.get("fid",0)
            })
        return accounts
    except:
        return []

def load_proxies():
    try:
        with open("proxy.txt") as f:
            proxies = [line.strip() for line in f if line.strip()]
        return proxies if proxies else [None]
    except:
        return [None]

# ==========================
# Web3 Transfer
# ==========================
def send_to_main(wallet, private_key):
    try:
        balance = w3.eth.get_balance(wallet)
        if balance <=0:
            return f"{wallet[:6]}... saldo kosong"
        nonce = w3.eth.get_transaction_count(wallet)
        gas_price = w3.eth.gas_price
        value = balance - gas_price * GAS_LIMIT
        if value <=0:
            return f"{wallet[:6]}... saldo tidak cukup"
        tx = {
            "to": MAIN_WALLET,
            "value": value,
            "gas": GAS_LIMIT,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID
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
    s.headers.update({"User-Agent": f"PythonBot-{random.randint(100,999)}","Accept":"application/json"})
    if proxy:
        if not proxy.startswith("http"):
            proxy = "http://" + proxy
        s.proxies.update({"http": proxy, "https": proxy})
    return s

def get_nonce(session, wallet):
    try:
        res = session.get(f"{GET_NONCE_ENDPOINT}?address={wallet}",timeout=15)
        if res.status_code==200 and "nonce" in res.json():
            return res.json()["nonce"]
    except Exception as e:
        logging.error(f"{wallet} | Nonce error: {e}")
    return None

def authenticate(session, wallet, private_key, fid=0):
    nonce = get_nonce(session, wallet)
    if not nonce:
        with dashboard_lock:
            dashboard_status[wallet]="❌ Gagal auth: nonce tidak diterima"
        return None
    message = encode_defunct(text=nonce)
    signed = Account.sign_message(message, private_key)
    payload = {"fid": fid,"address": wallet,"signature":signed.signature.hex()}
    try:
        res = session.post(POST_AUTH_ENDPOINT,json=payload,timeout=15)
        if res.status_code==200 and "token" in res.json():
            with dashboard_lock:
                dashboard_status[wallet]="✅ Auth berhasil"
            return res.json()["token"]
        else:
            err_msg=res.json().get("error","Unknown")
            with dashboard_lock:
                dashboard_status[wallet]=f"❌ Gagal auth: {err_msg}"
    except Exception as e:
        with dashboard_lock:
            dashboard_status[wallet]=f"⚠️ Error saat auth: {e}"
        logging.error(f"{wallet} | Auth error: {e}")
    return None

def claim_faucet(session, token, wallet):
    headers={"Authorization":f"Bearer {token}"}
    try:
        res=session.post(POST_CLAIM_ENDPOINT,headers=headers,json={"address":wallet},timeout=15)
        if res.status_code==200:
            data=res.json()
            if data.get("success"):
                with dashboard_lock:
                    dashboard_status[wallet]="✅ Claimed"
                return True
    except Exception as e:
        with dashboard_lock:
            dashboard_status[wallet]=f"⚠️ Claim error: {e}"
        logging.error(f"{wallet} | Claim error: {e}")
    return False

# ==========================
# Worker
# ==========================
def worker(acc, proxies):
    wallet=acc["wallet_address"]
    private_key=acc["private_key"]
    fid=acc.get("fid",0)
    proxy=random.choice(proxies)
    session=make_session(proxy)

    for attempt in range(MAX_ATTEMPTS):
        token=authenticate(session,wallet,private_key,fid)
        if not token:
            time.sleep(RETRY_BACKOFF[attempt%len(RETRY_BACKOFF)])
            continue
        success=claim_faucet(session,token,wallet)
        if success:
            transfer_res=send_to_main(wallet,private_key)
            with dashboard_lock:
                dashboard_status[wallet]+=f" | {transfer_res}"
            return
        else:
            time.sleep(RETRY_BACKOFF[attempt%len(RETRY_BACKOFF)])
    with dashboard_lock:
        dashboard_status[wallet]+=" | ❌ Gagal total"

# ==========================
# Main Loop
# ==========================
def main():
    accounts=load_accounts()
    proxies=load_proxies()

    if not accounts:
        print("❌ Tidak ada akun di data.json")
        return
    if not proxies:
        print("❌ Tidak ada proxy, lanjut tanpa proxy")
        proxies=[None]

    render_thread=threading.Thread(target=dashboard_loop)
    render_thread.daemon=True
    render_thread.start()

    threads=[]
    for acc in accounts:
        t=threading.Thread(target=worker,args=(acc,proxies))
        t.start()
        threads.append(t)
        while threading.active_count()>THREADS_PER_BATCH:
            time.sleep(0.5)

    for t in threads:
        t.join()

    stop_render_thread.set()
    render_thread.join()

if __name__=="__main__":
    main()
