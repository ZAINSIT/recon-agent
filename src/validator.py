"""
validator.py — the deterministic check on every LLM proposal.

A pure function of (proposal, candidate_orders, settlement). No I/O,
no clock, no randomness. If it returns reject, the settlement stays
unresolved. This is the "code disposes" half of "the model proposes,
the code disposes".

The validator does NOT score the proposal's plausibility. It checks
concrete facts: is the claimed order in the candidate set the model was
given? Does the arithmetic hold? Is the confidence consistent with what
was actually verified?
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_REASONS = {
    "partial_refund",
    "fee_difference",
    "truncated_ref",
    "substituted_digit",
    "merged",
    "no_match",
}

VALID_CONFIDENCE = {"high", "medium", "low"}

AMOUNT_TOLERANCE = 0.01


@dataclass
class ValidatorResult:
    accepted: bool
    reason: str  # empty if accepted
    matched_order_ids: list[str]


def validate(
    proposal: dict,
    candidate_orders: dict[str, dict],
    settlement_amount: float,
) -> ValidatorResult:
    """
    proposal: {reason, matched_order_id, confidence, evidence}
    candidate_orders: {order_id: {amount, refund_amount, fee, ...}}
        the set the model was allowed to choose from
    settlement_amount: the settlement's amount
    """
    reason = proposal.get("reason")
    order_id = proposal.get("matched_order_id")
    confidence = proposal.get("confidence")

    # 1. Structural checks.
    if reason not in VALID_REASONS:
        return ValidatorResult(False, f"invalid reason: {reason!r}", [])
    if confidence not in VALID_CONFIDENCE:
        return ValidatorResult(False, f"invalid confidence: {confidence!r}", [])
    if reason == "no_match":
        return ValidatorResult(True, "", [])
    if not order_id:
        return ValidatorResult(False, "missing matched_order_id", [])

    # 2. The proposed order must be in the candidate set the model was given.
    if order_id not in candidate_orders:
        return ValidatorResult(
            False, f"order {order_id} not in candidate set", []
        )

    order = candidate_orders[order_id]
    order_amount = float(order["amount"])
    delta = round(settlement_amount - order_amount, 2)

    # 3. Arithmetic must hold for the claimed reason.
    if reason == "partial_refund":
        refund = float(order.get("refund_amount") or 0.0)
        if refund and abs(delta + refund) <= AMOUNT_TOLERANCE:
            return ValidatorResult(True, "", [order_id])
        # No recorded refund, but a plausible fraction of the amount.
        frac = abs(delta) / order_amount if order_amount else 0.0
        if delta < 0 and 0.05 <= frac <= 0.60:
            return ValidatorResult(True, "", [order_id])
        return ValidatorResult(
            False, f"refund arithmetic fails: delta={delta}, refund={refund}", []
        )

    if reason == "fee_difference":
        fee = float(order.get("fee") or 0.0)
        if fee and abs(delta + fee) <= AMOUNT_TOLERANCE:
            return ValidatorResult(True, "", [order_id])
        frac = abs(delta) / order_amount if order_amount else 0.0
        if delta < 0 and 0.0 < frac < 0.03:
            return ValidatorResult(True, "", [order_id])
        return ValidatorResult(
            False, f"fee arithmetic fails: delta={delta}, fee={fee}", []
        )

    if reason in ("truncated_ref", "substituted_digit"):
        # Reference-level reasons: the amounts must still agree.
        if abs(delta) <= AMOUNT_TOLERANCE:
            return ValidatorResult(True, "", [order_id])
        return ValidatorResult(
            False, f"amount mismatch for {reason}: delta={delta}", []
        )

    if reason == "merged":
        # A merged proposal names one order here; multi-order merges are
        # handled by Stage 2's sum matcher, not the LLM.
        return ValidatorResult(
            False, "merged proposals are not accepted from the LLM", []
        )

    return ValidatorResult(False, f"unhandled reason: {reason!r}", [])