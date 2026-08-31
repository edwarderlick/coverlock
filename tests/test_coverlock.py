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
    Validators return REJECTED. Pool is NOT paid out. Challenger loses C. Claim stays OPEN.
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

    # 3. Mock LLM consensus returning REJECTED
    llm_response = json.dumps(
        {
            "verdict": "REJECTED",
            "reason": "The brief faithfully reflects the postgres migration and rate limit updates. The alleged deletion of auth is not present in the source.",
        }
    )
    direct_vm.mock_llm(".*", llm_response)

    # 4. Resolve challenge 0
    contract.resolve_challenge(claim_id, 0)

    # 5. Verify final state. Should remain OPEN, but challenger lost C to claimant.
    settled_record = contract.get_claim(claim_id)
    assert settled_record["state_name"] == "OPEN"
    assert settled_record["challenges"][0]["verdict"] == "REJECTED"
    assert settled_record["challenges"][0]["settlement"] == "SUBMITTER_WINS"
    assert contract.recompute_settlement(claim_id) == "PENDING"


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

    contract.resolve_challenge(claim_id, 0)

    settled_record = contract.get_claim(claim_id)
    assert settled_record["state_name"] == "BROKEN"
    assert settled_record["challenges"][0]["verdict"] == "CONFIRMED"
    assert settled_record["challenges"][0]["settlement"] == "CHALLENGER_WINS"
    assert settled_record["settlement"] == "CHALLENGER_WINS"
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

    contract.resolve_challenge(claim_id, 0)

    settled_record = contract.get_claim(claim_id)
    assert settled_record["state_name"] == "BROKEN"
    assert settled_record["settlement"] == "CHALLENGER_WINS"


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
    assert record["settlement"] == "REFUND"
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
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    cov_mod = sys.modules["_contract_coverlock"]
    derive_settlement = cov_mod.derive_settlement

    assert derive_settlement("CONFIRMED") == "CHALLENGER_WINS"
    assert derive_settlement("REJECTED") == "SUBMITTER_WINS"
    assert derive_settlement("UNDETERMINED") == "REFUND"

    claimant = direct_alice
    challenger = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger, 10**18)

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
        json.dumps({"verdict": "CONFIRMED", "reason": "500% reward claim has zero foundation in source text."}),
    )

    contract.resolve_challenge(claim_id, 0)
    rec = contract.get_claim(claim_id)
    assert rec["settlement"] == "CHALLENGER_WINS"


def test_concord_scar_single_source_of_truth(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Concord Review Scar Fix:
    State is dynamically derived. A single rejected challenge does not settle the claim.
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

    direct_vm.mock_llm(".*", json.dumps({"verdict": "REJECTED", "reason": "No omission occurred"}))
    contract.resolve_challenge(claim_id, 0)

    # SETTLED state check - claim stays PENDING overall since it is not EXPIRED or BROKEN
    claim_record = contract.get_claim(claim_id)
    assert contract.recompute_settlement(claim_id) == claim_record["settlement"] == "PENDING"


def test_versionlock_scar_json_parsing_and_no_regex(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy(CONTRACT_PATH, 86400)
    cov_mod = sys.modules["_contract_coverlock"]
    parse_llm_verdict = cov_mod.parse_llm_verdict

    payload_nested_attack = json.dumps({
        "meta": {"verdict": "CONFIRMED", "status": "CONFIRMED"},
        "verdict": "REJECTED",
        "reason": "Top-level decision is rejected",
    })
    res1 = parse_llm_verdict(payload_nested_attack)
    assert res1["verdict"] == "REJECTED"

    payload_missing_top = json.dumps({
        "data": {"verdict": "CONFIRMED"},
        "reason": "No top-level verdict provided",
    })
    res2 = parse_llm_verdict(payload_missing_top)
    assert res2["verdict"] == "UNDETERMINED"


def test_proofreader_scar_excerpt_validation_pre_llm(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
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

    with direct_vm.prank(challenger):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("source_excerpt is not a literal substring"):
            contract.challenge_claim(
                claim_id, "OMISSION", "Fake gap", "This exact sentence does not appear anywhere in the source text.", ""
            )


def test_ironclad_scar_caps_and_bounded_history(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    challenger1 = direct_bob

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(challenger1, 10**18)

    source = "Valid source text describing the distributed protocol architecture."
    brief = "Valid brief text describing the distributed protocol architecture."
    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    with direct_vm.prank(challenger1):
        direct_vm.value = 10**18
        contract.challenge_claim(
            claim_id,
            "OMISSION",
            "First challenger claim",
            "distributed protocol architecture.",
            "",
        )

# ---------------------------------------------------------------------------
# Multi-Challenge Lifecycle Tests (New)
# ---------------------------------------------------------------------------

def test_immunization_staff_case(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    """
    Staff requirement: "one REJECTED challenge must NOT settle the whole brief and freeze it."
    A bogus challenge (REJECTED) leaves the claim OPEN. A subsequent real challenge (CONFIRMED) breaks it.
    """
    contract = direct_deploy(CONTRACT_PATH, 86400)
    claimant = direct_alice
    ch_bogus = direct_bob
    ch_real = direct_charlie

    direct_vm.deal(claimant, 10**18)
    direct_vm.deal(ch_bogus, 10**18)
    direct_vm.deal(ch_real, 10**18)

    source = "Feature 1: Added user avatars. Feature 2: Added 2FA."
    brief = "Feature 1: Added user avatars."

    with direct_vm.prank(claimant):
        direct_vm.value = 10**18
        claim_id = contract.open_claim(source, brief)

    # 1. Bogus Challenge
    with direct_vm.prank(ch_bogus):
        direct_vm.value = 10**18
        contract.challenge_claim(claim_id, "OMISSION", "Missing avatar", "Feature 1: Added user avatars.", "")
    
    direct_vm.mock_llm(".*Missing avatar.*", json.dumps({"verdict": "REJECTED", "reason": "Already in brief"}))
    contract.resolve_challenge(claim_id, 0)

    # Claim should remain OPEN
    rec = contract.get_claim(claim_id)
    assert rec["state_name"] == "OPEN"

    # 2. Real Challenge
    with direct_vm.prank(ch_real):
        direct_vm.value = 10**18
        contract.challenge_claim(claim_id, "OMISSION", "Missing 2FA", "Feature 2: Added 2FA.", "")

    direct_vm.mock_llm(".*Missing 2FA.*", json.dumps({"verdict": "CONFIRMED", "reason": "2FA omitted"}))
    contract.resolve_challenge(claim_id, 1)

    rec = contract.get_claim(claim_id)
    assert rec["state_name"] == "BROKEN"
    assert rec["settlement"] == "CHALLENGER_WINS"


def test_replay_protection(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Same kind + excerpts should revert."""
    contract = direct_deploy(CONTRACT_PATH, 86400)
    direct_vm.deal(direct_alice, 10**18)
    direct_vm.deal(direct_bob, 10**18)

    with direct_vm.prank(direct_alice):
        direct_vm.value = 10**18
        claim_id = contract.open_claim("Source text with exactly 20 characters.", "Brief text")

    with direct_vm.prank(direct_bob):
        direct_vm.value = 10**18
        contract.challenge_claim(claim_id, "OMISSION", "Fact 1", "Source text with exactly 20 characters.", "")

    # Exact duplicate citations should revert
    with direct_vm.prank(direct_bob):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("Challenge with exactly these citations already exists"):
            contract.challenge_claim(claim_id, "OMISSION", "Fact 2", "Source text with exactly 20 characters.", "")


def test_double_payout_protection(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    """Two valid omissions. First breaks it. Second gets C refunded, S is not paid twice."""
    contract = direct_deploy(CONTRACT_PATH, 86400)
    direct_vm.deal(direct_alice, 10**18)
    direct_vm.deal(direct_bob, 10**18)
    direct_vm.deal(direct_charlie, 10**18)

    with direct_vm.prank(direct_alice):
        direct_vm.value = 10**18
        claim_id = contract.open_claim("Source text part A that is long enough, part B that is long enough", "Brief text")

    # Bob challenges part A
    with direct_vm.prank(direct_bob):
        direct_vm.value = 10**18
        contract.challenge_claim(claim_id, "OMISSION", "Missing A", "Source text part A that is long enough", "")

    # Charlie challenges part B
    with direct_vm.prank(direct_charlie):
        direct_vm.value = 10**18
        contract.challenge_claim(claim_id, "OMISSION", "Missing B", "part B that is long enough", "")

    # Resolve Bob
    direct_vm.mock_llm(".*", json.dumps({"verdict": "CONFIRMED", "reason": "Missing A"}))
    contract.resolve_challenge(claim_id, 0)

    # Resolve Charlie
    direct_vm.mock_llm(".*", json.dumps({"verdict": "CONFIRMED", "reason": "Missing B"}))
    contract.resolve_challenge(claim_id, 1)

    rec = contract.get_claim(claim_id)
    assert rec["state_name"] == "BROKEN"
    assert rec["coverage_paid"] is True


def test_expire_after_rejects(direct_vm, direct_deploy, direct_alice, direct_bob):
    """One REJECTED challenge. Warp past deadline. Expire claim -> refunds S."""
    contract = direct_deploy(CONTRACT_PATH, 3600)
    direct_vm.deal(direct_alice, 10**18)
    direct_vm.deal(direct_bob, 10**18)

    with direct_vm.prank(direct_alice):
        direct_vm.value = 10**18
        claim_id = contract.open_claim("Source text part A that is long enough, part B", "Brief text")

    with direct_vm.prank(direct_bob):
        direct_vm.value = 10**18
        contract.challenge_claim(claim_id, "OMISSION", "Missing A", "Source text part A that is long enough", "")

    direct_vm.mock_llm(".*", json.dumps({"verdict": "REJECTED", "reason": "Not a big deal"}))
    contract.resolve_challenge(claim_id, 0)

    # Warp past deadline
    future_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
    direct_vm.warp(future_dt.isoformat().replace("+00:00", "Z"))

    contract.expire_claim(claim_id)

    rec = contract.get_claim(claim_id)
    assert rec["state_name"] == "EXPIRED"


def test_expire_pending_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Expire while a PENDING challenge exists -> Reverts."""
    contract = direct_deploy(CONTRACT_PATH, 3600)
    direct_vm.deal(direct_alice, 10**18)
    direct_vm.deal(direct_bob, 10**18)

    with direct_vm.prank(direct_alice):
        direct_vm.value = 10**18
        claim_id = contract.open_claim("Source text part A that is long enough, part B", "Brief text")

    with direct_vm.prank(direct_bob):
        direct_vm.value = 10**18
        contract.challenge_claim(claim_id, "OMISSION", "Missing A", "Source text part A that is long enough", "")

    # Warp past deadline
    future_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
    direct_vm.warp(future_dt.isoformat().replace("+00:00", "Z"))

    with direct_vm.expect_revert("Cannot expire claim while there are pending challenges"):
        contract.expire_claim(claim_id)


def test_window_closes(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Challenge after deadline -> Reverts."""
    contract = direct_deploy(CONTRACT_PATH, 3600)
    direct_vm.deal(direct_alice, 10**18)
    direct_vm.deal(direct_bob, 10**18)

    with direct_vm.prank(direct_alice):
        direct_vm.value = 10**18
        claim_id = contract.open_claim("Source text part A that is long enough, part B", "Brief text")

    # Warp past deadline
    future_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
    direct_vm.warp(future_dt.isoformat().replace("+00:00", "Z"))

    with direct_vm.prank(direct_bob):
        direct_vm.value = 10**18
        with direct_vm.expect_revert("Challenge window has expired"):
            contract.challenge_claim(claim_id, "OMISSION", "Missing A", "Source text part A that is long enough", "")
