"""Traceable evidence ledger, claim links, and conflict expression (S16)."""
from evidence_agent.evidence.claims import ClaimRecord, link_claim_evidence, register_claim
from evidence_agent.evidence.conflict import ConflictAssessment, assess_scopes
from evidence_agent.evidence.ledger import EvidenceRecord, register_from_read, reject_non_body
from evidence_agent.evidence.verify import VerificationResult, verify_evidence

__all__ = [
    "EvidenceRecord",
    "register_from_read",
    "reject_non_body",
    "VerificationResult",
    "verify_evidence",
    "ClaimRecord",
    "register_claim",
    "link_claim_evidence",
    "ConflictAssessment",
    "assess_scopes",
]
