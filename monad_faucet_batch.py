import requests
import json
import logging
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# ==========================
# Konstanta Faucet
# ==========================
DOMAIN = "faucet-miniapp.monad.xyz"
BASE_URL = f"https://{DOMAIN}"
CHAIN_ID = 10  # Optimism (ubah sesuai chain Monad testnet jika beda)
GET_NONCE_ENDPOINT = f"{BASE_URL}/api/auth"
POST_AUTH_ENDPOINT = f"{BASE_URL}/api/auth/verify"
CLAIM_ENDPOINT = f"{BASE_URL}/api/claim"

# ==========================
# Wallet Utama & RPC
# ==========================
MAIN_WALLET = "0x17014818ceb3cdd8ef179b1c8a33765de8611deb"  # GANTI WALLET UTAMA
RPC_URL = "https://testnet-rpc.monad.xyz"  # Ganti RPC sesuai jaringan testnet
GAS_LIMIT = 21000
w3 = Web3(Web3.HTTPProvider(RPC_URL))

if not w3.is_connected():
    raise Exception("❌ RPC tidak bisa connect, cek URL RPC!")

# ==========================
# Logging
# ==========================
logging.basicConfig(
    filename="bot_batch.log",
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ==========================
# Load Akun
# ==========================
def load_accounts():
    with open("data.json") as f:
        data = json.load(f)
    accounts = []
    if isinstance(data, list):
        accounts = data
    elif isinstance(data, dict):
        for wallet, pk in data.items():
            accounts.append({
                "wallet_address": wallet,
                "fid": 0,
                "private_key": pk
            })
    return accounts

# ==========================
# Request Helper
# ==========================
def make_request(url, method="GET", headers=None, data=None):
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        else:
            r = requests.post(url, headers=headers, json=data, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"Request error {url} | {str(e)}")
        return None

# ==========================
# Faucet Auth
# ==========================
def get_nonce(wallet):
    url = f"{GET_NONCE_ENDPOINT}?address={wallet}"
    res = make_request(url, "GET")
    if res and "nonce" in res:
        return res["nonce"]
    return None

def authenticate(wallet, fid, private_key):
    nonce = get_nonce(wallet)
    if not nonce:
        return None
    message = encode_defunct(text=nonce)
    signed = Account.sign_message(message, private_key)
    payload = {
        "fid": fid,
        "address": wallet,
        "signature": signed.signature.hex()
    }
    res = make_request(POST_AUTH_ENDPOINT, "POST", data=payload)
    if res and "token" in res:
        return res["token"]
    return None

def claim_faucet(wallet, fid, private_key):
    token = authenticate(wallet, fid, private_key)
    if not token:
        return "auth_failed"
    headers = {"Authorization": f"Bearer {token}"}
    res = make_request(CLAIM_ENDPOINT, "POST", headers=headers)
    if res and res.get("success"):
        return "claimed"
    return "claim_failed"

# ==========================
# Transfer ke Wallet Utama
# ==========================
def send_to_main(wallet, private_key):
    try:
        balance = w3.eth.get_balance(wallet)
        if balance == 0:
            return f"{wallet[:6]}... balance kosong"

        nonce = w3.eth.get_transaction_count(wallet)
        gas_price = w3.eth.gas_price
        value = balance - gas_price * GAS_LIMIT
        if value <= 0:
            return f"{wallet[:6]}... tidak cukup balance untuk transfer"

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
        return f"{wallet[:6]}... gagal transfer: {str(e)}"

# ==========================
# Jalankan Batch
# ==========================
def main():
    accounts = load_accounts()

    print("🚰 Mulai klaim faucet semua wallet...")
    sukses = []
    for acc in accounts:
        wallet = acc["wallet_address"]
        fid = acc.get("fid", 0)
        private_key = acc["private_key"]

        status = claim_faucet(wallet, fid, private_key)
        if status == "claimed":
            print(f"✅ {wallet[:6]}... berhasil klaim")
            sukses.append(acc)
            logging.info(f"{wallet} claimed")
        else:
            print(f"❌ {wallet[:6]}... gagal klaim ({status})")
            logging.warning(f"{wallet} failed with status {status}")

    print("\n💸 Mulai transfer semua wallet yang sukses klaim ke wallet utama...")
    for acc in sukses:
        wallet = acc["wallet_address"]
        private_key = acc["private_key"]
        transfer_result = send_to_main(wallet, private_key)
        print(f"   🔄 {transfer_result}")
        logging.info(f"{wallet} -> {MAIN_WALLET} | {transfer_result}")

if __name__ == "__main__":
    main()
