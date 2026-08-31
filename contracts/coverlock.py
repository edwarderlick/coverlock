# { "Seq": [{ "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }, { "Depends": "py-lib-genlayer-std:11rhn002yfajawsz7fai6mykznbxkxs6l91iskj5cm82c92qhy3v" }] }
import genlayer.gl as gl
from genlayer.py.types import u256, Address
from genlayer.py.storage import allow_storage, TreeMap, inmem_allocate
from genlayer.gl.vm import UserError
import json
import datetime
import hashlib

# State Constants
STATE_OPEN: int = 0
STATE_BROKEN: int = 1
STATE_EXPIRED: int = 2

STATE_NAMES: list[str] = ["OPEN", "BROKEN", "EXPIRED"]

# String Limits
MAX_SOURCE_LEN: int = 8000
MAX_BRIEF_LEN: int = 4000
MAX_FACT_LEN: int = 500
MIN_EXCERPT_LEN: int = 20
MAX_EXCERPT_LEN: int = 280

VALID_KINDS: set[str] = {"OMISSION", "CONTRADICTION", "FABRICATION"}


def derive_settlement(verdict: str) -> str:
    """
    Pure function mapping consensus verdict to settlement outcome.
    Zero tolerance, discrete closed enum, invariant across allegation kinds.
    UNDETERMINED or unparseable outputs strictly refund both parties (never default to a winner).
    """
    if verdict == "CONFIRMED":
        return "CHALLENGER_WINS"
    elif verdict == "REJECTED":
        return "SUBMITTER_WINS"
    else:
        return "REFUND"


def validate_excerpts_and_caps(
    source: str,
    brief: str,
    kind: str,
    fact: str,
    source_excerpt: str,
    brief_excerpt: str,
) -> None:
    """
    Deterministic pre-LLM Python validation of allegation kind, fact, and excerpts.
    Reverts immediately without invoking consensus if citations are missing or non-matching.
    """
    if kind not in VALID_KINDS:
        raise UserError(f"Invalid allegation kind: {kind}. Must be one of {VALID_KINDS}")

    if len(fact) < 1 or len(fact) > MAX_FACT_LEN:
        raise UserError(f"Fact length must be between 1 and {MAX_FACT_LEN} characters (got {len(fact)})")

    # Validate source_excerpt if present
    if source_excerpt:
        if len(source_excerpt) < MIN_EXCERPT_LEN or len(source_excerpt) > MAX_EXCERPT_LEN:
            raise UserError(
                f"source_excerpt length must be between {MIN_EXCERPT_LEN} and {MAX_EXCERPT_LEN} chars (got {len(source_excerpt)})"
            )
        if source_excerpt not in source:
            raise UserError("source_excerpt is not a literal substring of the committed source text")

    # Validate brief_excerpt if present
    if brief_excerpt:
        if len(brief_excerpt) < MIN_EXCERPT_LEN or len(brief_excerpt) > MAX_EXCERPT_LEN:
            raise UserError(
                f"brief_excerpt length must be between {MIN_EXCERPT_LEN} and {MAX_EXCERPT_LEN} chars (got {len(brief_excerpt)})"
            )
        if brief_excerpt not in brief:
            raise UserError("brief_excerpt is not a literal substring of the committed brief text")

    # Enforce kind-specific mandatory citation requirements
    if kind == "OMISSION":
        if not source_excerpt:
            raise UserError("OMISSION requires a non-empty source_excerpt citing the missing material fact")
    elif kind == "CONTRADICTION":
        if not source_excerpt:
            raise UserError("CONTRADICTION requires a non-empty source_excerpt citing the source position")
        if not brief_excerpt:
            raise UserError("CONTRADICTION requires a non-empty brief_excerpt citing the conflicting statement")
    elif kind == "FABRICATION":
        if not brief_excerpt:
            raise UserError("FABRICATION requires a non-empty brief_excerpt citing the fabricated claim")


def parse_llm_verdict(raw: str | dict) -> dict:
    """
    Strict schema-aware parser for LLM consensus response.
    Extracts top-level 'verdict' only via exact json.loads.
    Invalid, malformed, or nested-only outputs return UNDETERMINED (never a paying default).
    """
    if isinstance(raw, dict):
        data = raw
    else:
        text = str(raw).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except Exception:
            return {"verdict": "UNDETERMINED", "reason": "Failed to parse JSON response"}

    if not isinstance(data, dict):
        return {"verdict": "UNDETERMINED", "reason": "JSON root is not an object"}

    verdict_raw = data.get("verdict")
    if not isinstance(verdict_raw, str):
        return {"verdict": "UNDETERMINED", "reason": "Missing or non-string top-level verdict"}

    verdict = verdict_raw.strip().upper()
    if verdict not in ("CONFIRMED", "REJECTED"):
        return {"verdict": "UNDETERMINED", "reason": f"Invalid verdict value: {verdict}"}

    reason = str(data.get("reason", ""))
    return {"verdict": verdict, "reason": reason}


def build_judge_prompt(
    source: str,
    brief: str,
    kind: str,
    fact: str,
    source_excerpt: str,
    brief_excerpt: str,
) -> str:
    """
    Constructs the impartial LLM consensus prompt.
    """
    return f"""You are an impartial GenVM consensus validator evaluating an asymmetric coverage escrow claim.

A claimant staked funds asserting that their published BRIEF is a complete and faithful account of a privileged SOURCE OF TRUTH.
A challenger has staked counter-funds alleging the following specific gap:

ALLEGATION KIND: {kind}
ALLEGED GAP / FACT: {fact}
VERIFIED SOURCE EXCERPT: {source_excerpt or "(none)"}
VERIFIED BRIEF EXCERPT: {brief_excerpt or "(none)"}

PRIVILEGED SOURCE TEXT:
\"\"\"
{source}
\"\"\"

PUBLISHED BRIEF TEXT:
\"\"\"
{brief}
\"\"\"

JUDGING RULES:
1. OMISSION: CONFIRMED if the alleged fact is actually present in the source (supported by the source excerpt), is material/substantive to a reader of the brief, and is absent from or unmentioned in the brief. REJECTED if the fact is already adequately covered, not material, or not in the source.
2. CONTRADICTION: CONFIRMED if the brief and source assert mutually incompatible statements regarding the fact in a way that changes meaning. REJECTED if they agree, differ only harmlessly, or are compatible.
3. FABRICATION: CONFIRMED if the brief asserts a claim (supported by the brief excerpt) that has no factual basis in or is contradicted by the source. REJECTED if the claim is supported by the source.

OUTPUT FORMAT:
Return ONLY a valid JSON object with exactly two top-level keys:
{{
  "verdict": "CONFIRMED" or "REJECTED",
  "reason": "1-2 sentence concise explanation"
}}
"""


@allow_storage
class ChallengeRecord:
    challenger: Address
    counter_stake: u256
    kind: str
    fact: str
    source_excerpt: str
    brief_excerpt: str
    challenged_at: u256
    verdict: str
    reason: str
    resolved_at: u256


@allow_storage
class ClaimRecord:
    claimant: Address
    source: str
    brief: str
    stake: u256
    created_at: u256
    deadline: u256
    state: u256
    
    coverage_paid: bool
    challenge_count: u256
    challenges: TreeMap[u256, ChallengeRecord]
    fingerprints: TreeMap[str, bool]


class CoverLock(gl.Contract):
    challenge_window: u256
    claim_counter: u256
    claims: TreeMap[str, ClaimRecord]

    def __init__(self, challenge_window_seconds: int):
        if challenge_window_seconds <= 0:
            raise UserError("challenge_window_seconds must be positive")
        self.challenge_window = u256(challenge_window_seconds)
        self.claim_counter = u256(0)

    def _get_current_timestamp(self) -> int:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    @gl.public.write.payable
    def open_claim(self, source: str, brief: str) -> str:
        """
        Posts source and brief, escrowing claimant stake.
        """
        stake = gl.message.value
        if stake <= u256(0):
            raise UserError("Claim stake must be greater than 0")

        if len(source) < 1 or len(source) > MAX_SOURCE_LEN:
            raise UserError(f"Source length must be between 1 and {MAX_SOURCE_LEN} chars (got {len(source)})")

        if len(brief) < 1 or len(brief) > MAX_BRIEF_LEN:
            raise UserError(f"Brief length must be between 1 and {MAX_BRIEF_LEN} chars (got {len(brief)})")

        now_ts = self._get_current_timestamp()
        deadline_ts = now_ts + int(self.challenge_window)

        claim_id = f"claim_{int(self.claim_counter)}"
        self.claim_counter = u256(int(self.claim_counter) + 1)

        rec = inmem_allocate(ClaimRecord)
        rec.claimant = gl.message.sender_address
        rec.source = source
        rec.brief = brief
        rec.stake = stake
        rec.created_at = u256(now_ts)
        rec.deadline = u256(deadline_ts)
        rec.state = u256(STATE_OPEN)
        
        rec.coverage_paid = False
        rec.challenge_count = u256(0)

        self.claims[claim_id] = rec
        return claim_id

    @gl.public.write.payable
    def challenge_claim(
        self,
        claim_id: str,
        kind: str,
        fact: str,
        source_excerpt: str,
        brief_excerpt: str,
    ) -> None:
        """
        Challenges an open claim by staking matching counter-funds and citing a specific gap with verified excerpts.
        Supports up to 8 independent challenges per claim while the window is open.
        """
        if claim_id not in self.claims:
            raise UserError(f"Claim '{claim_id}' not found")

        c = self.claims[claim_id]
        if int(c.state) != STATE_OPEN:
            raise UserError(f"Claim is not OPEN (current state: {STATE_NAMES[int(c.state)]})")

        now_ts = self._get_current_timestamp()
        if now_ts > int(c.deadline):
            raise UserError("Challenge window has expired")

        if int(c.challenge_count) >= 8:
            raise UserError("Maximum 8 challenges per claim reached")

        counter_stake = gl.message.value
        if counter_stake < c.stake:
            raise UserError(f"Counter-stake ({int(counter_stake)} wei) must be at least equal to claimant stake ({int(c.stake)} wei)")

        if gl.message.sender_address == c.claimant:
            raise UserError("Claimant cannot challenge their own claim")

        # Replay protection: fingerprint = sha256(kind + \0 + source_excerpt + \0 + brief_excerpt)
        fingerprint_input = f"{kind}\0{source_excerpt}\0{brief_excerpt}".encode('utf-8')
        fingerprint = hashlib.sha256(fingerprint_input).hexdigest()
        if fingerprint in c.fingerprints:
            raise UserError("Challenge with exactly these citations already exists")

        # Deterministic excerpt substring and bounds validation (reverts in Python pre-LLM)
        validate_excerpts_and_caps(
            c.source,
            c.brief,
            kind,
            fact,
            source_excerpt,
            brief_excerpt,
        )

        c.fingerprints[fingerprint] = True

        ch = inmem_allocate(ChallengeRecord)
        ch.challenger = gl.message.sender_address
        ch.counter_stake = counter_stake
        ch.kind = kind
        ch.fact = fact
        ch.source_excerpt = source_excerpt
        ch.brief_excerpt = brief_excerpt
        ch.challenged_at = u256(now_ts)
        ch.verdict = ""
        ch.reason = ""
        ch.resolved_at = u256(0)

        c.challenges[c.challenge_count] = ch
        c.challenge_count = u256(int(c.challenge_count) + 1)

    @gl.public.write
    def expire_claim(self, claim_id: str) -> None:
        """
        Expires a claim after the deadline if there are no pending challenges, refunding the submitter's pool.
        """
        if claim_id not in self.claims:
            raise UserError(f"Claim '{claim_id}' not found")

        c = self.claims[claim_id]
        if int(c.state) != STATE_OPEN:
            raise UserError(f"Claim is not in OPEN state (current state: {STATE_NAMES[int(c.state)]})")

        now_ts = self._get_current_timestamp()
        if now_ts <= int(c.deadline):
            raise UserError(f"Challenge window has not expired yet (deadline: {int(c.deadline)}, now: {now_ts})")

        if c.coverage_paid:
            raise UserError("Coverage pool already paid out")

        for i in range(int(c.challenge_count)):
            if not c.challenges[u256(i)].verdict:
                raise UserError("Cannot expire claim while there are pending challenges")

        c.state = u256(STATE_EXPIRED)

        # Refund claimant stake
        gl.get_contract_at(c.claimant).emit_transfer(value=c.stake)

    @gl.public.write
    def resolve_challenge(self, claim_id: str, challenge_id: int) -> None:
        """
        Resolves a single pending challenge via GenVM comparative consensus on verdict.
        If REJECTED, forfeits C.
        If CONFIRMED and first to hit, transfers S+C to challenger and breaks claim.
        If CONFIRMED but claim already broken, refunds C to challenger.
        """
        if claim_id not in self.claims:
            raise UserError(f"Claim '{claim_id}' not found")

        c = self.claims[claim_id]
        ch_id = u256(challenge_id)
        
        if ch_id not in c.challenges:
            raise UserError(f"Challenge {challenge_id} not found")
            
        ch = c.challenges[ch_id]
        if ch.verdict:
            raise UserError("Challenge is already resolved")

        # Defensive excerpt check
        validate_excerpts_and_caps(
            c.source,
            c.brief,
            ch.kind,
            ch.fact,
            ch.source_excerpt,
            ch.brief_excerpt,
        )

        # GenVM Comparative Consensus
        def run_judge() -> dict:
            prompt = build_judge_prompt(
                c.source,
                c.brief,
                ch.kind,
                ch.fact,
                ch.source_excerpt,
                ch.brief_excerpt,
            )
            raw = gl.nondet.exec_prompt(prompt, response_format="text")
            return parse_llm_verdict(raw)

        def validator_comparator(leader_res: gl.vm.Result) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False
            leader_data = leader_res.calldata
            if not isinstance(leader_data, dict):
                return False
            leader_verdict = leader_data.get("verdict")
            if leader_verdict not in ("CONFIRMED", "REJECTED", "UNDETERMINED"):
                return False

            # Validator independently re-runs the judge
            my_data = run_judge()
            my_verdict = my_data.get("verdict")

            # Comparative equivalence compares ONLY valid legal verdicts
            return leader_verdict == my_verdict

        consensus_output = gl.vm.run_nondet(run_judge, validator_comparator)

        if isinstance(consensus_output, dict):
            raw_verdict = consensus_output.get("verdict")
            if raw_verdict in ("CONFIRMED", "REJECTED"):
                verdict = raw_verdict
                reason = str(consensus_output.get("reason", ""))
            else:
                verdict = "UNDETERMINED"
                reason = str(consensus_output.get("reason", "Undetermined verdict"))
        else:
            verdict = "UNDETERMINED"
            reason = "Consensus undetermined"

        now_ts = self._get_current_timestamp()
        ch.verdict = verdict
        ch.reason = reason
        ch.resolved_at = u256(now_ts)

        # Multi-Challenge Accounting
        if verdict == "CONFIRMED":
            if not c.coverage_paid:
                c.coverage_paid = True
                c.state = u256(STATE_BROKEN)
                total_pool = u256(int(c.stake) + int(ch.counter_stake))
                gl.get_contract_at(ch.challenger).emit_transfer(value=total_pool)
            else:
                # Double-payout protection: refund their C, claim is already broken
                gl.get_contract_at(ch.challenger).emit_transfer(value=ch.counter_stake)
        elif verdict == "REJECTED":
            # Forfeit C to claimant. Claim stays OPEN.
            gl.get_contract_at(c.claimant).emit_transfer(value=ch.counter_stake)
        else:
            # UNDETERMINED: refund C. Claim stays OPEN.
            gl.get_contract_at(ch.challenger).emit_transfer(value=ch.counter_stake)

    @gl.public.view
    def get_claim(self, claim_id: str) -> dict:
        """
        Returns the complete structured public record for a claim.
        The state is dynamically derived to prevent drift (single source of truth).
        """
        if claim_id not in self.claims:
            raise UserError(f"Claim '{claim_id}' not found")

        c = self.claims[claim_id]
        
        # Concord fix: derive claim state dynamically
        if c.coverage_paid:
            derived_state = STATE_BROKEN
            settlement = "CHALLENGER_WINS"
        elif int(c.state) == STATE_EXPIRED:
            derived_state = STATE_EXPIRED
            settlement = "REFUND"
        else:
            derived_state = STATE_OPEN
            settlement = "PENDING"
            
        challenges_list = []
        for i in range(int(c.challenge_count)):
            ch = c.challenges[u256(i)]
            ch_settlement = "PENDING"
            if ch.verdict:
                ch_settlement = derive_settlement(ch.verdict)
            
            challenges_list.append({
                "challenge_id": i,
                "challenger": ch.challenger.as_hex,
                "counter_stake": int(ch.counter_stake),
                "kind": ch.kind,
                "fact": ch.fact,
                "source_excerpt": ch.source_excerpt,
                "brief_excerpt": ch.brief_excerpt,
                "challenged_at": int(ch.challenged_at),
                "verdict": ch.verdict,
                "reason": ch.reason,
                "resolved_at": int(ch.resolved_at),
                "settlement": ch_settlement
            })

        return {
            "claim_id": claim_id,
            "claimant": c.claimant.as_hex,
            "stake": int(c.stake),
            "source": c.source,
            "brief": c.brief,
            "created_at": int(c.created_at),
            "deadline": int(c.deadline),
            "state": derived_state,
            "state_name": STATE_NAMES[derived_state],
            "coverage_paid": c.coverage_paid,
            "challenge_count": int(c.challenge_count),
            "challenges": challenges_list,
            "settlement": settlement
        }

    @gl.public.view
    def recompute_settlement(self, claim_id: str) -> str:
        """
        Pure function to compute settlement state.
        """
        if claim_id not in self.claims:
            raise UserError(f"Claim '{claim_id}' not found")

        c = self.claims[claim_id]
        if c.coverage_paid:
            return "CHALLENGER_WINS"
        elif int(c.state) == STATE_EXPIRED:
            return "REFUND"
        else:
            return "PENDING"
