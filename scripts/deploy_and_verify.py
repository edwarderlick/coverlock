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

    # Target deployed contract
    contract_address = "0x19d9512004570B24040Cc65B2B659DAf62395a85"
    print(f"\n[2] Target Contract Address on StudioNet: {contract_address}")

    # Verify on-chain source code against submitted local source
    print("\n[3] Verifying Submitted Source vs Deployed On-Chain Source:")
    raw_res = client.provider.make_request("gen_getContractCode", [contract_address])
    on_chain_code = base64.b64decode(raw_res["result"]).decode("utf-8")
    source_matches = (on_chain_code.strip() == local_source.strip())
    print(f"    On-Chain Source Exact Match: {source_matches}")
    assert source_matches, "Deployed source code does not match submitted source code!"
    assert "parse_llm_verdict" in on_chain_code, "Missing parse_llm_verdict in on-chain code"
    assert "json.loads" in on_chain_code, "Missing json.loads in on-chain code"
    assert "re.search" not in on_chain_code, "Regex search found in on-chain source code!"
    print("    Verified: On-chain code contains strict schema-aware json.loads and zero regex JSON parsers.")

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

    print("Step 1.1: Submitter opens claim with 10^17 wei (0.1 GEN) stake...")
    tx_open = client.write_contract(
        address=contract_address,
        function_name="open_claim",
        account=submitter,
        value=10**17,
        args=[omission_source, omission_brief],
    )
    print(f"    Transaction Hash: {tx_open}")
    client.wait_for_transaction_receipt(tx_open)

    # Find the newly created open claim
    claim_id_1 = None
    for i in range(100):
        try:
            c = client.read_contract(address=contract_address, function_name="get_claim", args=[f"claim_{i}"])
            if c["state_name"] == "OPEN" and omission_excerpt in c["source"]:
                claim_id_1 = f"claim_{i}"
                break
        except Exception:
            break

    assert claim_id_1 is not None, "Failed to find newly opened claim for Scenario 1"
    print(f"    Target Claim ID: {claim_id_1}")

    print(f"\nStep 1.2: Challenger ({challenger.address}) challenges {claim_id_1} with 0.1 GEN counter-stake...")
    tx_chal = client.write_contract(
        address=contract_address,
        function_name="challenge_claim",
        account=challenger,
        value=10**17,
        args=[claim_id_1, "OMISSION", omission_fact, omission_excerpt, ""],
    )
    print(f"    Challenge Tx Hash: {tx_chal}")
    receipt_chal = client.wait_for_transaction_receipt(tx_chal)
    print(f"    Challenge Status:  {receipt_chal.get('status', 'ACCEPTED')}")

    claim1_chal = client.read_contract(
        address=contract_address,
        function_name="get_claim",
        args=[claim_id_1],
    )
    print(f"    State after challenge: {claim1_chal['state_name']}, Challenger: {claim1_chal['challenger']}")

    print(f"\nStep 1.3: Triggering GenVM consensus resolution on {claim_id_1}...")
    tx_res = client.write_contract(
        address=contract_address,
        function_name="resolve_claim",
        account=challenger,
        value=0,
        args=[claim_id_1],
    )
    print(f"    Resolution Tx Hash: {tx_res}")
    receipt_res = client.wait_for_transaction_receipt(tx_res)
    print(f"    Resolution Status:  {receipt_res.get('status', 'ACCEPTED')}")

    claim1_settled = client.read_contract(
        address=contract_address,
        function_name="get_claim",
        args=[claim_id_1],
    )
    recomputed_1 = client.read_contract(
        address=contract_address,
        function_name="recompute_settlement",
        args=[claim_id_1],
    )

    print("\n[Result Scenario 1]:")
    print(f"    Final State:      {claim1_settled['state_name']}")
    print(f"    Verdict:          {claim1_settled['verdict']}")
    print(f"    Reason:           {claim1_settled['reason']}")
    print(f"    Settlement:       {claim1_settled['settlement']}")
    print(f"    Paid To:          {claim1_settled['paid_to']}")
    print(f"    Recompute Match:  {recomputed_1 == claim1_settled['settlement']}")
    assert claim1_settled["verdict"] == "CONFIRMED", f"Expected CONFIRMED, got {claim1_settled['verdict']}"
    assert claim1_settled["settlement"] == "CHALLENGER_WINS", f"Expected CHALLENGER_WINS, got {claim1_settled['settlement']}"
    assert recomputed_1 == claim1_settled["settlement"], "recompute_settlement did not match get_claim settlement!"

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
    bogus_fact = "Challenger claims authentication was deleted (fact does not exist in source)."

    print("Step 2.1: Submitter opens claim with 0.1 GEN stake...")
    tx_open2 = client.write_contract(
        address=contract_address,
        function_name="open_claim",
        account=submitter,
        value=10**17,
        args=[faithful_source, faithful_brief],
    )
    print(f"    Open Claim Tx Hash: {tx_open2}")
    client.wait_for_transaction_receipt(tx_open2)

    claim_id_2 = None
    for i in range(100):
        try:
            c = client.read_contract(address=contract_address, function_name="get_claim", args=[f"claim_{i}"])
            if c["state_name"] == "OPEN" and bogus_excerpt in c["source"]:
                claim_id_2 = f"claim_{i}"
                break
        except Exception:
            break

    assert claim_id_2 is not None, "Failed to find newly opened claim for Scenario 2"
    print(f"    Target Claim ID: {claim_id_2}")

    print(f"\nStep 2.2: Challenger files bogus challenge on {claim_id_2}...")
    tx_chal2 = client.write_contract(
        address=contract_address,
        function_name="challenge_claim",
        account=challenger,
        value=10**17,
        args=[claim_id_2, "OMISSION", bogus_fact, bogus_excerpt, ""],
    )
    print(f"    Challenge Tx Hash:  {tx_chal2}")
    client.wait_for_transaction_receipt(tx_chal2)

    print(f"\nStep 2.3: Triggering GenVM consensus resolution on {claim_id_2}...")
    tx_res2 = client.write_contract(
        address=contract_address,
        function_name="resolve_claim",
        account=submitter,
        value=0,
        args=[claim_id_2],
    )
    print(f"    Resolution Tx Hash: {tx_res2}")
    client.wait_for_transaction_receipt(tx_res2)

    claim2_settled = client.read_contract(
        address=contract_address,
        function_name="get_claim",
        args=[claim_id_2],
    )
    recomputed_2 = client.read_contract(
        address=contract_address,
        function_name="recompute_settlement",
        args=[claim_id_2],
    )

    print("\n[Result Scenario 2]:")
    print(f"    Final State:      {claim2_settled['state_name']}")
    print(f"    Verdict:          {claim2_settled['verdict']}")
    print(f"    Reason:           {claim2_settled['reason']}")
    print(f"    Settlement:       {claim2_settled['settlement']}")
    print(f"    Paid To:          {claim2_settled['paid_to']}")
    print(f"    Recompute Match:  {recomputed_2 == claim2_settled['settlement']}")
    assert claim2_settled["verdict"] == "REJECTED", f"Expected REJECTED, got {claim2_settled['verdict']}"
    assert claim2_settled["settlement"] == "SUBMITTER_WINS", f"Expected SUBMITTER_WINS, got {claim2_settled['settlement']}"
    assert recomputed_2 == claim2_settled["settlement"], "recompute_settlement did not match get_claim settlement!"

    print("\n" + "=" * 80)
    print(" ALL ON-CHAIN STUDIONET VERIFICATIONS COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
