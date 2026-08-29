# Test Suite for CoverLock — Asymmetric Coverage Escrow Intelligent Contract
import json
import datetime
import sys
import pytest
from pathlib import Path
from genlayer.py.types import u256, Address

CONTRACT_PATH = Path(__file__).parent.parent / "contracts" / "coverlock.py"


def to_hex(addr) -> str:
    """Helper to get string hex address regardless of Address/bytes type."""
    if isinstance(addr, str):
        return addr
    if hasattr(addr, "as_hex"):
        return addr.as_hex
    return Address(addr).as_hex


# ---------------------------------------------------------------------------
# Task 4 — Happy & Unhappy Integration Tests (Direct Mode)
# ---------------------------------------------------------------------------


def test_faithful_brief_bogus_omission_rejected(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Happy Path: Faithful brief covers all source facts.
    Challenger files a bogus omission alleging an unmentioned third fact.
    Validators return REJECTED. Pool is paid to claimant (submitter wins).
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    challenger = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

    source = (
        "Release Notes v2.4: 1. Migrated postgres database schema to support UUIDv7 keys. "
        "2. Adjusted API rate limits to 500 requests per minute per IP address."
    )
    brief = (
        "Summary of Release v2.4: Upgraded the Postgres schema to use UUIDv7 keys for all tables, "
        "and configured API rate limits to 500 requests per minute per IP."
    )

    # 1. Claimant opens claim with 1 GEN stake
    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    claim_record = contract.get_claim(claim_id)
    assert claim_record["state_name"] == "OPEN"
    assert claim_record["stake"] == 10**18
    assert claim_record["claimant"] == to_hex(claimant)

    # 2. Challenger challenges alleging a bogus omission
    source_excerpt = "Migrated postgres database schema to support UUIDv7 keys."
    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "OMISSION",
            "Challenger claims authentication was deleted (not in source)",
            source_excerpt,
            "",
        )

    challenged_record = contract.get_claim(claim_id)
    assert challenged_record["state_name"] == "CHALLENGED"
    assert challenged_record["challenger"] == to_hex(challenger)
    assert challenged_record["counter_stake"] == 10**18

    # 3. Mock LLM consensus returning REJECTED
    llm_response = json.dumps(
        {
            "verdict": "REJECTED",
            "reason": "The brief faithfully reflects the postgres migration and rate limit updates. The alleged deletion of auth is not present in the source.",
        }
    )
    direct_vm.mock_llm(".*", llm_response)

    # 4. Resolve claim
    contract.resolve_claim(claim_id)

    # 5. Verify final state and single source of truth
    settled_record = contract.get_claim(claim_id)
    assert settled_record["state_name"] == "SETTLED"
    assert settled_record["verdict"] == "REJECTED"
    assert settled_record["settlement"] == "SUBMITTER_WINS"
    assert settled_record["paid_to"] == to_hex(claimant)
    assert settled_record["consensus_ran"] is True
    assert contract.recompute_settlement(claim_id) == "SUBMITTER_WINS"


def test_real_omission_confirmed(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Unhappy Path 1 (Real Omission): Source contains a breaking change that the brief quietly skips.
    Challenger files OMISSION with source citation.
    Validators return CONFIRMED. Pool is paid to challenger (challenger wins).
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    challenger = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

    source = (
        "Security Advisory & Patch Log: "
        "CRITICAL: Deprecated and permanently removed legacy /v1/auth endpoint, requiring all clients to migrate to OAuth2 tokens. "
        "Also performed minor internal caching optimizations."
    )
    brief = (
        "Release Overview: This release includes minor internal caching optimizations and routine stability enhancements."
    )

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    source_excerpt = "Deprecated and permanently removed legacy /v1/auth endpoint, requiring all clients to migrate to OAuth2 tokens."
    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "OMISSION",
            "Brief completely omitted the critical deprecation and removal of the /v1/auth endpoint.",
            source_excerpt,
            "",
        )

    llm_response = json.dumps(
        {
            "verdict": "CONFIRMED",
            "reason": "The source document explicitly specifies the breaking removal of /v1/auth endpoint which was entirely omitted from the brief.",
        }
    )
    direct_vm.mock_llm(".*", llm_response)

    contract.resolve_claim(claim_id)

    settled_record = contract.get_claim(claim_id)
    assert settled_record["state_name"] == "SETTLED"
    assert settled_record["verdict"] == "CONFIRMED"
    assert settled_record["settlement"] == "CHALLENGER_WINS"
    assert settled_record["paid_to"] == to_hex(challenger)
    assert settled_record["consensus_ran"] is True
    assert contract.recompute_settlement(claim_id) == "CHALLENGER_WINS"


def test_real_contradiction_confirmed(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Unhappy Path 2 (Real Contradiction): Brief contradicts source directly.
    Challenger files CONTRADICTION citing both excerpts.
    Validators return CONFIRMED. Challenger wins pool.
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    challenger = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

    source = (
        "API Spec v3: All synchronous payment webhooks have been deprecated and removed. "
        "Developers must register asynchronous WebSocket listeners."
    )
    brief = (
        "Changelog: Synchronous payment webhooks remain fully supported and active for all existing accounts."
    )

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    source_excerpt = "All synchronous payment webhooks have been deprecated and removed."
    brief_excerpt = "Synchronous payment webhooks remain fully supported and active for all existing accounts."

    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "CONTRADICTION",
            "Brief asserts synchronous webhooks are supported, whereas source explicitly states they are deprecated and removed.",
            source_excerpt,
            brief_excerpt,
        )

    llm_response = json.dumps(
        {
            "verdict": "CONFIRMED",
            "reason": "Direct contradiction regarding payment webhook support.",
        }
    )
    direct_vm.mock_llm(".*", llm_response)

    contract.resolve_claim(claim_id)

    settled_record = contract.get_claim(claim_id)
    assert settled_record["state_name"] == "SETTLED"
    assert settled_record["verdict"] == "CONFIRMED"
    assert settled_record["settlement"] == "CHALLENGER_WINS"
    assert settled_record["paid_to"] == to_hex(challenger)
    assert contract.recompute_settlement(claim_id) == "CHALLENGER_WINS"


def test_unchallenged_expiry_refund(
    direct_vm, direct_deploy, direct_alice
):
    """
    Expiry Path: Unchallenged claim passes deadline.
    expire_claim() refunds claimant without invoking consensus.
    """
    challenge_window = 3600  # 1 hour
    contract = direct_deploy(CONTRACT_PATH, challenge_window)
    claimant = direct_alice

    direct_vm.deal(claimant, 10**18)

    source = "Valid source text describing system architecture and service level agreements."
    brief = "Faithful brief describing system architecture and service level agreements."

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    # Warp time past deadline (3 days in future)
    future_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
    direct_vm.warp(future_dt.isoformat().replace("+00:00", "Z"))

    # Expire claim
    contract.expire_claim(claim_id)

    record = contract.get_claim(claim_id)
    assert record["state_name"] == "EXPIRED"
    assert record["verdict"] == ""
    assert record["settlement"] == "REFUND"
    assert record["paid_to"] == "REFUNDED_TO_CLAIMANT"
    assert record["consensus_ran"] is False
    assert contract.recompute_settlement(claim_id) == "REFUND"


# ---------------------------------------------------------------------------
# Task 4 — The 5 Review-Scar Hardening Tests
# ---------------------------------------------------------------------------


def test_fairsplit_scar_payout_invariance(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    FairSplit Review Scar Fix:
    Payout is invariant across allegation kinds and reasoning differences.
    OMISSION, CONTRADICTION, and FABRICATION all pay the exact same 100% pool to the challenger
    if verdict == CONFIRMED.
    derive_settlement is a pure function of verdict only (no numeric tolerance / weight drift).
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    cov_mod = sys.modules["_contract_coverlock"]
    derive_settlement = cov_mod.derive_settlement

    # 1. Pure function assertions
    assert derive_settlement("CONFIRMED") == "CHALLENGER_WINS"
    assert derive_settlement("REJECTED") == "SUBMITTER_WINS"
    assert derive_settlement("UNDETERMINED") == "REFUND"
    assert derive_settlement("UNKNOWN") == "REFUND"

    # 2. Verify on contract instance across different kinds
    claimant = direct_alice
    challenger = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

    # Test FABRICATION
    source = "Project documentation detailing core protocol rules and parameters."
    brief = "Project documentation detailing core protocol rules and claiming a 500% staking reward."
    brief_excerpt = "claiming a 500% staking reward."

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "FABRICATION",
            "The brief fabricated a 500% staking reward not mentioned in source.",
            "",
            brief_excerpt,
        )

    direct_vm.mock_llm(
        ".*",
        json.dumps(
            {
                "verdict": "CONFIRMED",
                "reason": "500% reward claim has zero foundation in source text.",
            }
        ),
    )

    contract.resolve_claim(claim_id)
    rec = contract.get_claim(claim_id)
    assert rec["settlement"] == "CHALLENGER_WINS"
    assert rec["paid_to"] == to_hex(challenger)


def test_concord_scar_single_source_of_truth(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Concord Review Scar Fix:
    There is exactly one source of truth. Payout and status are derived at read/settle time
    strictly from the stored verdict.
    recompute_settlement(claim_id) is pure and always matches get_claim(claim_id)['settlement'].
    No separately-trusted duplicate status field exists that can desync.
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    challenger = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

    source = "Source text containing verified audit reports and code coverage metrics."
    brief = "Brief text summarizing verified audit reports and code coverage metrics."

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    # OPEN state check
    assert contract.recompute_settlement(claim_id) == contract.get_claim(claim_id)["settlement"] == "PENDING"

    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "OMISSION",
            "Alleged omission gap",
            "verified audit reports and code coverage metrics.",
            "",
        )

    # CHALLENGED state check
    assert contract.recompute_settlement(claim_id) == contract.get_claim(claim_id)["settlement"] == "PENDING"

    direct_vm.mock_llm(
        ".*",
        json.dumps({"verdict": "REJECTED", "reason": "No omission occurred"}),
    )

    contract.resolve_claim(claim_id)

    # SETTLED state check
    claim_record = contract.get_claim(claim_id)
    assert contract.recompute_settlement(claim_id) == claim_record["settlement"] == "SUBMITTER_WINS"


def test_versionlock_scar_json_parsing_and_no_regex(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    VersionLock Review Scar Fix:
    LLM output is parsed with schema-aware json.loads only.
    Top-level verdict key is accepted only if strictly CONFIRMED or REJECTED.
    Nested homonyms, garbage, and unparseable outputs return UNDETERMINED.
    UNDETERMINED never pays the submitter; it strictly refunds both stakes.
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    cov_mod = sys.modules["_contract_coverlock"]
    parse_llm_verdict = cov_mod.parse_llm_verdict
    derive_settlement = cov_mod.derive_settlement

    # 1. Nested homonym attack: nested CONFIRMED with top-level REJECTED
    # Parser extracts top-level REJECTED
    payload_nested_attack = json.dumps(
        {
            "meta": {"verdict": "CONFIRMED", "status": "CONFIRMED"},
            "verdict": "REJECTED",
            "reason": "Top-level decision is rejected",
        }
    )
    res1 = parse_llm_verdict(payload_nested_attack)
    assert res1["verdict"] == "REJECTED", "Top-level verdict must be respected"

    # 2. Missing top-level verdict (nested only) -> UNDETERMINED (NOT REJECTED!)
    payload_missing_top = json.dumps(
        {
            "data": {"verdict": "CONFIRMED"},
            "reason": "No top-level verdict provided",
        }
    )
    res2 = parse_llm_verdict(payload_missing_top)
    assert res2["verdict"] == "UNDETERMINED", "Nested-only verdict must return UNDETERMINED"
    assert derive_settlement(res2["verdict"]) == "REFUND", "UNDETERMINED must map to REFUND"

    # 3. Valid top-level CONFIRMED with markdown codeblock wrapper
    payload_markdown = (
        "```json\n"
        '{\n  "verdict": "CONFIRMED",\n  "reason": "Valid omission cited."\n}\n'
        "```"
    )
    res3 = parse_llm_verdict(payload_markdown)
    assert res3["verdict"] == "CONFIRMED"
    assert derive_settlement(res3["verdict"]) == "CHALLENGER_WINS"

    # 4. Total garbage string / malformed JSON -> UNDETERMINED (NOT REJECTED!)
    res4 = parse_llm_verdict("Invalid unstructured non-json response text")
    assert res4["verdict"] == "UNDETERMINED", "Malformed JSON must return UNDETERMINED"
    assert derive_settlement(res4["verdict"]) == "REFUND", "Malformed JSON parser default must NOT pay submitter"

    # 5. Contract execution on UNDETERMINED returns REFUND
    claimant = direct_alice
    challenger = direct_bob
    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

    source = "Source text containing verified audit reports and code coverage metrics."
    brief = "Brief text summarizing verified audit reports and code coverage metrics."

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "OMISSION",
            "Alleged gap",
            "verified audit reports and code coverage metrics.",
            "",
        )

    # Mock unparseable LLM output
    direct_vm.mock_llm(".*", "Non-JSON unparseable garbage output")
    contract.resolve_claim(claim_id)

    rec = contract.get_claim(claim_id)
    assert rec["verdict"] == "UNDETERMINED"
    assert rec["settlement"] == "REFUND"
    assert rec["paid_to"] == "REFUNDED"
    assert contract.recompute_settlement(claim_id) == "REFUND"


def test_proofreader_scar_excerpt_validation_pre_llm(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    ProofReader Review Scar Fix:
    Citations are verified as literal substrings in Python BEFORE any consensus / LLM call.
    Bogus citations revert immediately, preventing invalid challenges from reaching consensus.
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    challenger = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

    source = "Official release log: Implemented zero-knowledge proofs for batch transactions."
    brief = "Release log: Implemented zero-knowledge proofs for batch transactions."

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    # 1. Non-existent source excerpt reverts
    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("source_excerpt is not a literal substring of the committed source text"):
            contract.challenge_claim(
                claim_id,
                "OMISSION",
                "Alleging a fake gap",
                "This exact sentence does not appear anywhere in the source text.",
                "",
            )

    # 2. Empty source excerpt on OMISSION reverts
    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("OMISSION requires a non-empty source_excerpt"):
            contract.challenge_claim(
                claim_id,
                "OMISSION",
                "Missing source citation",
                "",
                "",
            )

    # 3. Excerpt shorter than 20 chars reverts
    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("source_excerpt length must be between 20 and 280 chars"):
            contract.challenge_claim(
                claim_id,
                "OMISSION",
                "Too short citation",
                "short text",
                "",
            )

    # Verify claim remains in OPEN state because all bogus challenges reverted
    assert contract.get_claim(claim_id)["state_name"] == "OPEN"


def test_ironclad_scar_caps_and_bounded_history(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """
    Ironclad Review Scar Fix:
    Explicit size caps on write inputs (source <= 8000, brief <= 4000, fact <= 500).
    Max 1 challenge per claim (reverts on 2nd challenge).
    Under-staking counter-stake reverts.
    Bounded storage history.
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    challenger1 = direct_bob
    challenger2 = direct_charlie

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger1, 10**18)
    direct_vm.deal(challenger2, 10**18)

    # 1. Oversized source (> 8000 chars) reverts
    oversized_source = "A" * 8001
    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("Source length must be between 1 and 8000 chars"):
            contract.open_claim(oversized_source, "Valid brief text")

    # 2. Oversized brief (> 4000 chars) reverts
    oversized_brief = "B" * 4001
    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("Brief length must be between 1 and 4000 chars"):
            contract.open_claim("Valid source text", oversized_brief)

    # 3. Valid open_claim
    source = "Valid source text describing the distributed protocol architecture."
    brief = "Valid brief text describing the distributed protocol architecture."
    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    # 4. Under-stake challenge reverts
    with direct_vm.prank(challenger1):
        direct_vm.value = 10**17  # Less than 10**18
        with direct_vm.expect_revert("Counter-stake (100000000000000000 wei) must be at least equal to claimant stake"):
            contract.challenge_claim(
                claim_id,
                "OMISSION",
                "Under-staked challenge",
                "distributed protocol architecture.",
                "",
            )

    # 5. First full-stake challenge succeeds
    with direct_vm.prank(challenger1):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "OMISSION",
            "First challenger claim",
            "distributed protocol architecture.",
            "",
        )

    # 6. Second challenge on already-challenged claim reverts
    with direct_vm.prank(challenger2):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("Claim is not OPEN"):
            contract.challenge_claim(
                claim_id,
                "OMISSION",
                "Second challenger attempt",
                "distributed protocol architecture.",
                "",
            )
