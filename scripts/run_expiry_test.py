import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from genlayer_py.client.genlayer_client import GenLayerClient
from genlayer_py.chains.studionet import studionet
from scripts.deploy_and_verify import load_account

client = GenLayerClient(studionet)
submitter = load_account("coverlock-submitter")
client.local_account = submitter

# Deploy contract with a 5-second challenge window
contract_file = Path(__file__).parent.parent / "contracts" / "coverlock.py"
print("Deploying CoverLock with 5s challenge window for Expiry testing...")
contract_code = contract_file.read_text(encoding="utf-8")
deploy_tx = client.deploy_contract(
    code=contract_code,
    account=submitter,
    args=[5],
)
print(f"Deploy Tx Hash: {deploy_tx}")
rc_deploy = client.wait_for_transaction_receipt(deploy_tx)
short_contract_addr = rc_deploy.get("contract_address") or rc_deploy.get("recipient")
print(f"Short Window Contract Address: {short_contract_addr}")

# Open claim
print("\nOpening claim with 0.1 GEN stake...")
open_tx = client.write_contract(
    address=short_contract_addr,
    function_name="open_claim",
    account=submitter,
    value=10**17,
    args=["Valid source text describing system specifications.", "Faithful brief describing system specifications."],
)
print(f"Open Tx Hash: {open_tx}")
client.wait_for_transaction_receipt(open_tx)

# Wait 10 seconds for window to expire
print("\nWaiting 10s for challenge window to expire...")
time.sleep(10)

# Call expire_claim
print("Calling expire_claim('claim_0')...")
expire_tx = client.write_contract(
    address=short_contract_addr,
    function_name="expire_claim",
    account=submitter,
    value=0,
    args=["claim_0"],
)
print(f"Expire Tx Hash: {expire_tx}")
rc_expire = client.wait_for_transaction_receipt(expire_tx)
print(f"Expire Tx Status: {rc_expire.get('status', 'ACCEPTED')}")

claim_exp = client.read_contract(address=short_contract_addr, function_name="get_claim", args=["claim_0"])
recomputed_exp = client.read_contract(address=short_contract_addr, function_name="recompute_settlement", args=["claim_0"])

print("\n" + "=" * 50)
print(f"Final State:     {claim_exp['state_name']}")
print(f"Verdict:         '{claim_exp['verdict']}'")
print(f"Consensus Ran:   {claim_exp['consensus_ran']}")
print(f"Settlement:      {claim_exp['settlement']}")
print(f"Paid To:         {claim_exp['paid_to']}")
print(f"Recompute Match: {recomputed_exp == claim_exp['settlement']}")
print("=" * 50)
