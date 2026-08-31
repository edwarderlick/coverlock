import time
from pathlib import Path
from genlayer_py.client.genlayer_client import GenLayerClient
from genlayer_py.chains.studionet import studionet
import json
from genlayer_py.accounts.account import Account

def load_account(name: str, password: str = "CoverLockPass123!") -> Account:
    ks_path = Path.home() / ".genlayer" / "keystores" / f"{name}.json"
    with open(ks_path, "r", encoding="utf-8") as f:
        ks_data = json.load(f)
    pk = Account.decrypt(ks_data, password)
    return Account.from_key(pk)

def main():
    client = GenLayerClient(studionet)
    contract_file = Path(__file__).parent.parent / "contracts" / "coverlock.py"
    local_source = contract_file.read_text(encoding="utf-8")
    
    submitter = load_account("coverlock-submitter")
    client.local_account = submitter
    
    print("Deploying main contract...")
    tx1 = client.deploy_contract(local_source, args=[86400])
    client.wait_for_transaction_receipt(tx1)
    addr1 = client.get_transaction_receipt(tx1).get("contractAddress")
    print(f"Main Contract deployed at: {addr1}")
    
    print("Deploying expiry contract...")
    tx2 = client.deploy_contract(local_source, args=[5])
    client.wait_for_transaction_receipt(tx2)
    addr2 = client.get_transaction_receipt(tx2).get("contractAddress")
    print(f"Expiry Contract deployed at: {addr2}")

if __name__ == "__main__":
    main()
