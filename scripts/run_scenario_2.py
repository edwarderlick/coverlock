import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from genlayer_py.client.genlayer_client import GenLayerClient
from genlayer_py.chains.studionet import studionet
from scripts.deploy_and_verify import load_account

client = GenLayerClient(studionet)
submitter = load_account("coverlock-submitter")
challenger = load_account("coverlock-challenger")
client.local_account = submitter

contract_address = "0x19d9512004570B24040Cc65B2B659DAf62395a85"
claim_id_2 = "claim_2"

print(f"Challenging {claim_id_2} (Faithful Brief + Bogus Omission)...")
bogus_excerpt = "Migrated postgres database schema to support UUIDv7 keys."
bogus_fact = "Challenger claims authentication was deleted (fact does not exist in source)."

tx_chal2 = client.write_contract(
    address=contract_address,
    function_name="challenge_claim",
    account=challenger,
    value=10**17,
    args=[claim_id_2, "OMISSION", bogus_fact, bogus_excerpt, ""],
)
print(f"Challenge Tx Hash: {tx_chal2}")
rc = client.wait_for_transaction_receipt(tx_chal2)
print(f"Challenge Status: {rc.get('status', 'ACCEPTED')}")

print(f"\nResolving {claim_id_2}...")
tx_res2 = client.write_contract(
    address=contract_address,
    function_name="resolve_claim",
    account=submitter,
    value=0,
    args=[claim_id_2],
)
print(f"Resolution Tx Hash: {tx_res2}")
rc2 = client.wait_for_transaction_receipt(tx_res2)
print(f"Resolution Status: {rc2.get('status', 'ACCEPTED')}")

claim2 = client.read_contract(address=contract_address, function_name="get_claim", args=[claim_id_2])
recomputed2 = client.read_contract(address=contract_address, function_name="recompute_settlement", args=[claim_id_2])

print("\n" + "=" * 50)
print(f"Final State:     {claim2['state_name']}")
print(f"Verdict:         {claim2['verdict']}")
print(f"Reason:          {claim2['reason']}")
print(f"Settlement:      {claim2['settlement']}")
print(f"Paid To:         {claim2['paid_to']}")
print(f"Recompute Match: {recomputed2 == claim2['settlement']}")
print("=" * 50)
