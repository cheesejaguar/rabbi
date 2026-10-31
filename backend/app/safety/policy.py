"""Policy router: combine the lexicon floor and the classifier into one plan.

The router is a pure function so every safety decision is unit-testable
without a model. Its output tells the pipeline which overlay to append,
which effort to use, whether to show a resource card first, whether to
retrieve sources, and whether the turn is charged.
"""

from dataclasses import dataclass, field
from typing import Optional

from .classifier import ClassifierResult
from .lexicon import LexiconResult

CARE_MODES = ("counseling", "crisis")


@dataclass
class TurnPolicy:
    mode: str = "teaching"
    question_type: str = "other"
    card_level: Optional[str] = None      # crisis | abuse | support
    youth: bool = False
    overlays: list[str] = field(default_factory=list)
    effort: str = "low"
    retrieve: bool = True
    charge: bool = True
    alert_admin: bool = False
    flags: list[str] = field(default_factory=list)
    requires_human_referral: bool = False
    vulnerability_detected: bool = False

    @property
    def is_crisis(self) -> bool:
        return self.card_level in ("crisis", "abuse")


def decide(lex: LexiconResult, cls: ClassifierResult, *, prior_crisis: bool = False,
           effort_default: str = "low", effort_care: str = "medium") -> TurnPolicy:
    r = cls.risk
    p = TurnPolicy(mode=cls.mode, question_type=cls.question_type, retrieve=cls.needs_sources)

    # --- Self-harm (lexicon floor first: deterministic) ------------------
    if lex.forces_crisis or r["self_harm"] >= 2 or cls.mode == "crisis":
        p.card_level = "crisis"
        p.mode = "crisis"
        p.flags.append("self_harm" if (lex.forces_crisis or r["self_harm"] >= 2) else "crisis_mode")
        p.overlays.append("crisis")
        p.alert_admin = lex.forces_crisis or r["self_harm"] >= 2
    elif prior_crisis and r["self_harm"] >= 1:
        # Stay with the person: keep crisis care until clearly de-escalated.
        p.card_level = "crisis"
        p.mode = "crisis"
        p.overlays.append("crisis")
        p.flags.append("crisis_followup")

    # --- Abuse ------------------------------------------------------------
    if lex.forces_abuse_protocol or r["abuse_disclosure"] >= 2:
        if p.card_level != "crisis":
            p.card_level = "abuse"
        p.mode = "crisis" if p.card_level == "crisis" else "counseling"
        p.overlays.append("abuse")
        p.flags.append("abuse_disclosure")
        p.alert_admin = True

    # --- Harm to others ---------------------------------------------------
    if lex.harm_to_others or r["harm_to_others"] >= 2:
        p.overlays.append("harm_to_others")
        p.flags.append("harm_to_others")
        p.alert_admin = True
        p.retrieve = False

    if r["medical_or_eating_disorder"] >= 2:
        p.overlays.append("medical")
        p.flags.append("medical")
    if r["minor_signals"] >= 2:
        p.youth = True
        p.overlays.append("youth")
        p.flags.append("minor")
    if r["hate_or_extremism"] >= 2:
        p.overlays.append("hate")
        p.flags.append("hate_or_extremism")
        p.retrieve = False
    if r["manipulation_attempt"] >= 2:
        p.overlays.append("manipulation")
        p.flags.append("manipulation_attempt")
    if r["off_platform_misuse"] >= 2:
        p.overlays.append("scope")
        p.flags.append("off_platform")
        p.retrieve = False

    # --- Classifier unavailable: fail safe, not closed --------------------
    if not cls.available:
        p.flags.append("classifier_unavailable")
        if p.mode not in CARE_MODES:
            p.mode = "counseling"
        p.overlays.append("elevated_unknown")
        if lex.self_harm == "topic" and not p.card_level:
            p.card_level = "support"

    if p.mode in CARE_MODES and "pastoral" not in p.overlays:
        p.overlays.insert(0, "pastoral")

    if p.card_level in ("crisis", "abuse"):
        p.retrieve = False  # warmth first; no source analysis in a crisis turn
        p.charge = False    # crisis turns are always free
        p.requires_human_referral = True
    p.vulnerability_detected = p.mode in CARE_MODES or cls.emotional_state in (
        "grieving", "ashamed", "distressed", "lonely", "anxious")
    if p.mode == "counseling":
        p.requires_human_referral = p.requires_human_referral or r["self_harm"] >= 1
    p.effort = effort_care if p.mode in CARE_MODES else effort_default
    # Deduplicate overlays, preserving order.
    seen = set()
    p.overlays = [o for o in p.overlays if not (o in seen or seen.add(o))]
    return p
