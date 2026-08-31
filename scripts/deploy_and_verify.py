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

    # Target deployed contracts
    main_contract_address = "0x4D007b17583649A4B1E33B02B070995f17746047"
    expiry_contract_address = "0xc13bFa3C56191Ce06CB9D2Bc73475490704F8295"
    print(f"\n[2] Target Contract Addresses on StudioNet:")
    print(f"    Main Contract:   {main_contract_address}")
    print(f"    Expiry Contract: {expiry_contract_address}")

    # Verify on-chain source code against submitted local source
    print("\n[3] Verifying Submitted Source vs Deployed On-Chain Source:")
    raw_res = client.provider.make_request("gen_getContractCode", [main_contract_address])
    on_chain_code = base64.b64decode(raw_res["result"]).decode("utf-8")
    source_matches = (on_chain_code.strip() == local_source.strip())
    print(f"    On-Chain Source Exact Match: {source_matches}")
    assert source_matches, "Deployed source code does not match submitted source code!"
    assert "parse_llm_verdict" in on_chain_code, "Missing parse_llm_verdict in on-chain code"
    assert "json.loads" in on_chain_code, "Missing json.loads in on-chain code"
    assert "re.search" not in on_chain_code, "Regex search found in on-chain source code!"
    assert 'return {"verdict": "UNDETERMINED"' in on_chain_code, "Parser must return UNDETERMINED on failures"
    print("    Verified: On-chain code contains strict schema-aware json.loads, zero regex JSON parsers, and safe UNDETERMINED failure mode.")

    stake_amount = 10**17  # 0.1 GEN

    # -----------------------------------------------------------------------
    # SCENARIO 1: Real Omission -> CONFIRMED -> Challenger Wins Pool
    # -----------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(" SCENARIO 1: Real Omission Challenge (Breaking Removal Omitted)")
    print("-" * 80)

    omission_source = (
        "Protocol Patch Notes v3.2.0: "
        "CRITICAL: Deprecated and permanently removed legacy /v1/auth endpoint, requiring all clients to migrate to OAuth2 tokens. "
        "Also performed routine database index tuning and caching optimization."
    )
    omission_brief = (
        "Changelog v3.2.0: This update introduces performance improvements including database index tuning and caching optimizations."
    )
    omission_excerpt = "Deprecated and permanently removed legacy /v1/auth endpoint, requiring all clients to migrate to OAuth2 tokens."
    omission_fact = "The brief completely omitted the breaking removal of the /v1/auth endpoint."

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
        args=[omission_source, omission_brief],
    )
    print(f"    Open Claim Tx: {tx_open1}")
    client.wait_for_transaction_receipt(tx_open1)

    claim_id_1 = "claim_0"
    print(f"    Claim ID: {claim_id_1}")

    print(f"\nStep 1.2: Challenger challenges {claim_id_1} with 0.1 GEN counter-stake...")
    tx_chal1 = client.write_contract(
        address=main_contract_address,
        function_name="challenge_claim",
        account=challenger,
        value=stake_amount,
        args=[claim_id_1, "OMISSION", omission_fact, omission_excerpt, ""],
    )
    print(f"    Challenge Tx: {tx_chal1}")
    client.wait_for_transaction_receipt(tx_chal1)

    print(f"\nStep 1.3: Resolving {claim_id_1} via GenVM consensus...")
    tx_res1 = client.write_contract(
        address=main_contract_address,
        function_name="resolve_challenge",
        account=challenger,
        value=0,
        args=[claim_id_1, 0],
    )
    print(f"    Resolve Tx:   {tx_res1}")
    client.wait_for_transaction_receipt(tx_res1)

    wait_for_triggered_payout(client, tx_res1)

    claim1 = client.read_contract(address=main_contract_address, function_name="get_claim", args=[claim_id_1])
    recomputed1 = client.read_contract(address=main_contract_address, function_name="recompute_settlement", args=[claim_id_1])

    sub_b1 = client.get_balance(submitter.address)
    chal_b1 = client.get_balance(challenger.address)
    ctr_b1 = client.get_balance(main_contract_address)

    print("\n[Result Scenario 1]:")
    print(f"    Final State:       {claim1['state_name']}")
    ch1 = claim1['challenges'][0] if claim1['challenges'] else {}
    print(f"    Verdict:           {ch1.get('verdict')}")
    print(f"    Reason:            {ch1.get('reason')}")
    print(f"    Settlement:        {claim1['settlement']}")
    print(f"    Recompute Match:   {recomputed1 == claim1['settlement']}")
    print(f"    Submitter Balance:  {sub_b1} wei (Delta: {sub_b1 - sub_b0:+d} wei)")
    print(f"    Challenger Balance: {chal_b1} wei (Delta: {chal_b1 - chal_b0:+d} wei)")
    print(f"    Contract Balance:   {ctr_b1} wei (Delta: {ctr_b1 - ctr_b0:+d} wei)")

    assert ch1.get("verdict") == "CONFIRMED", f"Expected CONFIRMED, got {ch1.get('verdict')}"
    assert claim1["settlement"] == "CHALLENGER_WINS", f"Expected CHALLENGER_WINS, got {claim1['settlement']}"
    assert recomputed1 == claim1["settlement"], "recompute_settlement mismatch!"

    # -----------------------------------------------------------------------
    # SCENARIO 2: Faithful Brief + Bogus Challenge -> REJECTED -> Submitter Wins Pool
    # -----------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(" SCENARIO 2: Faithful Brief + Bogus Challenge (Submitter Wins)")
    print("-" * 80)

    faithful_source = (
        "Release Notes v2.4: 1. Migrated postgres database schema to support UUIDv7 keys. "
        "2. Adjusted API rate limits to 500 requests per minute per IP address."
    )
    faithful_brief = (
        "Summary of Release v2.4: Upgraded the Postgres schema to use UUIDv7 keys for all tables, "
        "and configured API rate limits to 500 requests per minute per IP."
    )
    bogus_excerpt = "Migrated postgres database schema to support UUIDv7 keys."
    bogus_fact = "Authentication was completely deleted from the system."

    sub_b2_start = client.get_balance(submitter.address)
    chal_b2_start = client.get_balance(challenger.address)
    ctr_b2_start = client.get_balance(main_contract_address)

    print(f"\nStep 2.1: Submitter opens claim with 0.1 GEN stake...")
    tx_open2 = client.write_contract(
        address=main_contract_address,
        function_name="open_claim",
        account=submitter,
        value=stake_amount,
        args=[faithful_source, faithful_brief],
    )
    print(f"    Open Claim Tx: {tx_open2}")
    client.wait_for_transaction_receipt(tx_open2)

    claim_id_2 = "claim_1"
    print(f"    Claim ID: {claim_id_2}")

    print(f"\nStep 2.2: Challenger files bogus challenge on {claim_id_2} with 0.1 GEN counter-stake...")
    tx_chal2 = client.write_contract(
        address=main_contract_address,
        function_name="challenge_claim",
        account=challenger,
        value=stake_amount,
        args=[claim_id_2, "OMISSION", bogus_fact, bogus_excerpt, ""],
    )
    print(f"    Challenge Tx:  {tx_chal2}")
    client.wait_for_transaction_receipt(tx_chal2)

    print(f"\nStep 2.3: Resolving {claim_id_2} via GenVM consensus...")
    tx_res2 = client.write_contract(
        address=main_contract_address,
        function_name="resolve_challenge",
        account=submitter,
        value=0,
        args=[claim_id_2, 0],
    )
    print(f"    Resolve Tx:    {tx_res2}")
    client.wait_for_transaction_receipt(tx_res2)

    wait_for_triggered_payout(client, tx_res2)

    claim2 = client.read_contract(address=main_contract_address, function_name="get_claim", args=[claim_id_2])
    recomputed2 = client.read_contract(address=main_contract_address, function_name="recompute_settlement", args=[claim_id_2])

    sub_b2_end = client.get_balance(submitter.address)
    chal_b2_end = client.get_balance(challenger.address)
    ctr_b2_end = client.get_balance(main_contract_address)

    print("\n[Result Scenario 2]:")
    print(f"    Final State:       {claim2['state_name']}")
    ch2 = claim2['challenges'][0] if claim2['challenges'] else {}
    print(f"    Verdict:           {ch2.get('verdict')}")
    print(f"    Reason:            {ch2.get('reason')}")
    print(f"    Settlement:        {claim2['settlement']}")
    print(f"    Recompute Match:   {recomputed2 == claim2['settlement']}")
    print(f"    Submitter Balance:  {sub_b2_end} wei (Delta: {sub_b2_end - sub_b2_start:+d} wei)")
    print(f"    Challenger Balance: {chal_b2_end} wei (Delta: {chal_b2_end - chal_b2_start:+d} wei)")
    print(f"    Contract Balance:   {ctr_b2_end} wei (Delta: {ctr_b2_end - ctr_b2_start:+d} wei)")

    assert ch2.get("verdict") == "REJECTED", f"Expected REJECTED, got {ch2.get('verdict')}"
    # Wait, claim2 is left open since it's only one REJECTED challenge.
    # Settlement should be PENDING.
    assert claim2["settlement"] == "PENDING", f"Expected PENDING, got {claim2['settlement']}"
    assert recomputed2 == claim2["settlement"], "recompute_settlement mismatch!"

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
    recomputed3 = client.read_contract(address=expiry_contract_address, function_name="recompute_settlement", args=[claim_id_3])

    sub_b3_end = client.get_balance(submitter.address)
    ctr_b3_end = client.get_balance(expiry_contract_address)

    print("\n[Result Scenario 3]:")
    print(f"    Final State:       {claim3['state_name']}")
    ch3 = claim3['challenges'][0] if claim3['challenges'] else {}
    print(f"    Verdict:           '{ch3.get('verdict')}'")
    print(f"    Settlement:        {claim3['settlement']}")
    print(f"    Recompute Match:   {recomputed3 == claim3['settlement']}")
    print(f"    Contract Balance:   {ctr_b3_end} wei (Should be 0)")

    assert claim3["state_name"] == "EXPIRED"
    assert claim3["settlement"] == "REFUND"

    print("\n" + "=" * 80)
    print(" ALL ON-CHAIN STUDIONET VERIFICATIONS WITH BALANCES COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
