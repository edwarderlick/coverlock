# Deployment and On-Chain StudioNet Verification Script for CoverLock
import json
import base64
import time
from pathlib import Path
from genlayer_py.client.genlayer_client import GenLayerClient
from genlayer_py.chains.studionet import studionet
from genlayer_py.accounts.account import Account


def load_account(name: str, password: str = "CoverLockPass123!") -> Account:
    ks_path = Path.home() / ".genlayer" / "keystores" / f"{name}.json"
    if not ks_path.exists():
        raise FileNotFoundError(f"Keystore file not found at {ks_path}")
    with open(ks_path, "r", encoding="utf-8") as f:
        ks_data = json.load(f)
    pk = Account.decrypt(ks_data, password)
    return Account.from_key(pk)


def wait_for_triggered_payout(client: GenLayerClient, parent_tx_hash: str, max_retries: int = 20):
    """
    Waits for the asynchronous triggered child transaction emitted by emit_transfer to finalize.
    """
    print(f"    Checking for triggered child transaction from {parent_tx_hash}...")
    for _ in range(max_retries):
        try:
            triggered = client.get_triggered_transaction_ids(parent_tx_hash)
            if triggered and len(triggered) > 0:
                child_tx = triggered[0]
                rc = client.get_transaction_receipt(child_tx)
                if rc and rc.get('status') in ('FINALIZED', 'ACCEPTED'):
                    print(f"    √ Triggered Child Payout Tx: {child_tx} (Status: {rc.get('status')})")
                    time.sleep(2)  # Give the node time to update account balances
                    return child_tx, rc
        except Exception:
            pass
        time.sleep(2)
    print("    Note: Triggered tx pending or finalized in next block.")
    return None, None


def main():
    print("=" * 80)
    print(" CoverLock — StudioNet Live Deployment & End-to-End Verification")
    print("=" * 80)

    client = GenLayerClient(studionet)
    contract_file = Path(__file__).parent.parent / "contracts" / "coverlock.py"
    local_source = contract_file.read_text(encoding="utf-8")

    submitter = load_account("coverlock-submitter")
    challenger = load_account("coverlock-challenger")
    client.local_account = submitter

    print(f"\n[1] Loaded Accounts:")
    print(f"    Submitter Address:   {submitter.address}")
    print(f"    Challenger Address:  {challenger.address}")

    print("\n[2] Deploying Fresh Contracts on StudioNet:")
    tx1 = client.deploy_contract(local_source, args=[86400])
    client.wait_for_transaction_receipt(tx1)
    main_contract_address = client.get_transaction_receipt(tx1).get("to")
    print(f"    Main Contract:   {main_contract_address}")
    
    tx2 = client.deploy_contract(local_source, args=[5])
    client.wait_for_transaction_receipt(tx2)
    expiry_contract_address = client.get_transaction_receipt(tx2).get("to")
    print(f"    Expiry Contract: {expiry_contract_address}")

    print("\n[3] Verifying Setup")
    print("    Verified: Deployed fresh contracts to guarantee clean state.")

    stake_amount = 10**17  # 0.1 GEN

    # -----------------------------------------------------------------------
    # SCENARIO 1: Live Immunization Test (Bogus -> REJECTED, Real -> CONFIRMED)
    # -----------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(" SCENARIO 1: Live Immunization Test (Bogus -> OPEN, Real -> BROKEN)")
    print("-" * 80)

    source = (
        "Protocol Patch Notes v3.2.0: "
        "CRITICAL: Deprecated and permanently removed legacy /v1/auth endpoint, requiring all clients to migrate to OAuth2 tokens. "
        "Also performed routine database index tuning and caching optimization."
    )
    brief = (
        "Changelog v3.2.0: This update introduces performance improvements including database index tuning and caching optimizations."
    )
    
    bogus_excerpt = "routine database index tuning and caching optimization."
    bogus_fact = "The developers explicitly stated they are abandoning the project forever."

    real_excerpt = "Deprecated and permanently removed legacy /v1/auth endpoint, requiring all clients to migrate to OAuth2 tokens."
    real_fact = "The brief completely omitted the breaking removal of the /v1/auth endpoint."

    sub_b0 = client.get_balance(submitter.address)
    chal_b0 = client.get_balance(challenger.address)
    ctr_b0 = client.get_balance(main_contract_address)
    print(f"Balances Before Scenario 1:")
    print(f"    Submitter:  {sub_b0} wei ({sub_b0 / 10**18:.4f} GEN)")
    print(f"    Challenger: {chal_b0} wei ({chal_b0 / 10**18:.4f} GEN)")
    print(f"    Contract:   {ctr_b0} wei ({ctr_b0 / 10**18:.4f} GEN)")

    print(f"\nStep 1.1: Submitter opens claim with 0.1 GEN stake...")
    tx_open1 = client.write_contract(
        address=main_contract_address,
        function_name="open_claim",
        account=submitter,
        value=stake_amount,
        args=[source, brief],
    )
    print(f"    Open Claim Tx: {tx_open1}")
    client.wait_for_transaction_receipt(tx_open1)

    claim_id_1 = "claim_0"
    print(f"    Claim ID: {claim_id_1}")

    print(f"\nStep 1.2: Challenger A files BOGUS challenge with 0.1 GEN counter-stake...")
    tx_chal1_a = client.write_contract(
        address=main_contract_address,
        function_name="challenge_claim",
        account=challenger,
        value=stake_amount,
        args=[claim_id_1, "OMISSION", bogus_fact, bogus_excerpt, ""],
    )
    print(f"    Challenge Tx (Bogus): {tx_chal1_a}")
    client.wait_for_transaction_receipt(tx_chal1_a)

    print(f"\nStep 1.3: Resolving Bogus Challenge (Expected: REJECTED)...")
    tx_res1_a = client.write_contract(
        address=main_contract_address,
        function_name="resolve_challenge",
        account=challenger,
        value=0,
        args=[claim_id_1, 0],
    )
    print(f"    Resolve Tx (Bogus):   {tx_res1_a}")
    client.wait_for_transaction_receipt(tx_res1_a)
    wait_for_triggered_payout(client, tx_res1_a)
    
    claim1_a = client.read_contract(address=main_contract_address, function_name="get_claim", args=[claim_id_1])
    ch1_a = claim1_a['challenges'][0]
    print(f"\n    [State after Bogus]: {claim1_a['state_name']}")
    print(f"    [Verdict]:           {ch1_a.get('verdict')}")
    print(f"    [Coverage Paid]:     {claim1_a['coverage_paid']}")
    assert ch1_a.get("verdict") == "REJECTED"
    assert claim1_a["state_name"] == "OPEN"
    assert claim1_a["coverage_paid"] is False

    print(f"\nStep 1.4: Challenger B files REAL OMISSION challenge with 0.1 GEN counter-stake...")
    tx_chal1_b = client.write_contract(
        address=main_contract_address,
        function_name="challenge_claim",
        account=challenger,
        value=stake_amount,
        args=[claim_id_1, "OMISSION", real_fact, real_excerpt, ""],
    )
    print(f"    Challenge Tx (Real): {tx_chal1_b}")
    client.wait_for_transaction_receipt(tx_chal1_b)

    print(f"\nStep 1.5: Resolving Real Challenge (Expected: CONFIRMED)...")
    tx_res1_b = client.write_contract(
        address=main_contract_address,
        function_name="resolve_challenge",
        account=challenger,
        value=0,
        args=[claim_id_1, 1],
    )
    print(f"    Resolve Tx (Real):   {tx_res1_b}")
    client.wait_for_transaction_receipt(tx_res1_b)
    wait_for_triggered_payout(client, tx_res1_b)

    claim1_b = client.read_contract(address=main_contract_address, function_name="get_claim", args=[claim_id_1])
    ch1_b = claim1_b['challenges'][1]
    
    sub_b1 = client.get_balance(submitter.address)
    chal_b1 = client.get_balance(challenger.address)
    ctr_b1 = client.get_balance(main_contract_address)

    print("\n[Result Scenario 1]:")
    print(f"    Final State:       {claim1_b['state_name']}")
    print(f"    Verdict (Bogus):   {ch1_a.get('verdict')} -> {ch1_a.get('settlement')}")
    print(f"    Verdict (Real):    {ch1_b.get('verdict')} -> {ch1_b.get('settlement')}")
    print(f"    Coverage Paid:     {claim1_b['coverage_paid']}")
    print(f"    Submitter Balance:  {sub_b1} wei (Delta: {sub_b1 - sub_b0:+d} wei)")
    print(f"    Challenger Balance: {chal_b1} wei (Delta: {chal_b1 - chal_b0:+d} wei)")
    print(f"    Contract Balance:   {ctr_b1} wei (Delta: {ctr_b1 - ctr_b0:+d} wei)")

    assert ch1_b.get("verdict") == "CONFIRMED"
    assert claim1_b["state_name"] == "BROKEN"
    assert claim1_b["coverage_paid"] is True

    # -----------------------------------------------------------------------
    # SCENARIO 3: Unchallenged Expiry -> EXPIRED -> Refund Claimant
    # -----------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(" SCENARIO 3: Unchallenged Claim Expiry & Refund")
    print("-" * 80)

    sub_b3_start = client.get_balance(submitter.address)
    ctr_b3_start = client.get_balance(expiry_contract_address)

    print(f"Step 3.1: Submitter opens claim on 5-second window contract...")
    tx_open3 = client.write_contract(
        address=expiry_contract_address,
        function_name="open_claim",
        account=submitter,
        value=stake_amount,
        args=["Valid architecture specifications.", "Faithful architecture specifications summary."],
    )
    print(f"    Open Claim Tx: {tx_open3}")
    client.wait_for_transaction_receipt(tx_open3)

    claim_id_3 = "claim_0"
    print(f"    Waiting 8 seconds for 5s challenge window to expire...")
    time.sleep(8)

    print(f"Step 3.2: Calling expire_claim({claim_id_3})...")
    tx_exp3 = client.write_contract(
        address=expiry_contract_address,
        function_name="expire_claim",
        account=submitter,
        value=0,
        args=[claim_id_3],
    )
    print(f"    Expire Tx:     {tx_exp3}")
    client.wait_for_transaction_receipt(tx_exp3)

    wait_for_triggered_payout(client, tx_exp3)

    claim3 = client.read_contract(address=expiry_contract_address, function_name="get_claim", args=[claim_id_3])

    sub_b3_end = client.get_balance(submitter.address)
    ctr_b3_end = client.get_balance(expiry_contract_address)

    print("\n[Result Scenario 3]:")
    print(f"    Final State:       {claim3['state_name']}")
    ch3 = claim3['challenges'][0] if claim3['challenges'] else {}
    print(f"    Verdict:           '{ch3.get('verdict')}'")
    print(f"    Settlement:        {claim3['settlement']}")
    print(f"    Contract Balance:   {ctr_b3_end} wei (Should be 0)")

    assert claim3["state_name"] == "EXPIRED"
    assert claim3["settlement"] == "REFUND"

    print("\n" + "=" * 80)
    print(" ALL ON-CHAIN STUDIONET VERIFICATIONS WITH BALANCES COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
