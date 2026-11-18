"""Urgency rules for Tesla fault message triage.

Rules:
    Safety_Urgent -> Tesla pickup. Applies to any message carrying a safety
                     fault code, and to any message whose subject or text
                     references a safety component (brakes, steering, ...).
                     A component reference counts on its own; no fault code
                     is needed.
    Soon          -> Service visit.
    Routine       -> Remote-fix or Customer visit.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class RequestType(StrEnum):
    SAFETY_URGENT = "Safety_Urgent"
    SOON = "Soon"
    ROUTINE = "Routine"


class FixPath(StrEnum):
    TESLA_PICKUP = "Tesla pickup"
    SERVICE_VISIT = "Service visit"
    REMOTE_FIX = "Remote-fix"
    CUSTOMER_VISIT = "Customer visit"


# Which fix paths each request type may use.
ALLOWED_FIX_PATHS: dict[RequestType, frozenset[FixPath]] = {
    RequestType.SAFETY_URGENT: frozenset({FixPath.TESLA_PICKUP}),
    RequestType.SOON: frozenset({FixPath.SERVICE_VISIT}),
    RequestType.ROUTINE: frozenset({FixPath.REMOTE_FIX, FixPath.CUSTOMER_VISIT}),
}


class SafetyFaultCode(StrEnum):
    """Fault codes that always make a message Safety_Urgent."""

    ABS_W002 = "ABS_w002"
    BRK_A001 = "BRK_a001"
    BRK_W003 = "BRK_w003"
    EPAS_A191 = "EPAS_a191"
    EPAS_W202 = "EPAS_w202"
    ESP_W003 = "ESP_w003"


_SAFETY_CODES_BY_KEY: dict[str, SafetyFaultCode] = {
    code.value.casefold(): code for code in SafetyFaultCode
}

# Gap inside one sentence, used by the symptom patterns below.
_SAME_SENTENCE = r"[^.!?\n]{0,60}?"
_PULL = r"\b(?:pull(?:s|ed|ing)?(?!\s+(?:over|up|in|into|out|away|off)\b)|tug(?:s|ged|ging)?|drift(?:s|ed|ing)?)\b"
_STOPPING = r"\b(?:stop(?:s|ped|ping)?|slow(?:s|ed|ing)?\s+down|slowing|halt|junctions?)\b"
_GRIND = r"\bgrind(?:s|ing)?\b"
_AT_A_STOP = r"\b(?:stop(?:s|ped|ping)?|lights|pedal|wheels?)\b"

# Safety components a customer may reference in the subject or text, either by
# name or by a symptom that only that component produces. Extend this to cover
# more; each entry is (component name, pattern).
SAFETY_COMPONENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("brakes", re.compile(r"\bbrak(?:e|es|ed|ing)\b", re.IGNORECASE)),
    # The only other pedal is the accelerator.
    ("brakes", re.compile(r"(?<!accelerator )(?<!gas )(?<!throttle )\bpedal\b", re.IGNORECASE)),
    # "tugs to the left when stopping", "when I slow down the car pulls left"
    ("brakes", re.compile(rf"{_PULL}{_SAME_SENTENCE}{_STOPPING}|{_STOPPING}{_SAME_SENTENCE}{_PULL}", re.IGNORECASE)),
    # "grinding noise from the front wheels when I'm stopped at the lights"
    ("brakes", re.compile(rf"{_GRIND}{_SAME_SENTENCE}{_AT_A_STOP}|{_AT_A_STOP}{_SAME_SENTENCE}{_GRIND}", re.IGNORECASE)),
    ("steering", re.compile(r"\bsteer(?:s|ed|ing)?\b", re.IGNORECASE)),
    # Upper-case only, so "abs" in ordinary prose does not match.
    ("ABS", re.compile(r"\bABS\b")),
    ("anti-lock brakes", re.compile(r"\banti-?lock\b", re.IGNORECASE)),
    ("stability control", re.compile(r"\bstability control\b", re.IGNORECASE)),
)

# A mention directly followed by one of these, within the same clause, is the
# customer saying the component is fine ("brakes and steering feel normal"),
# not reporting a problem with it.
_REASSURANCE = re.compile(
    r"\b(?:normal(?:ly)?|fine|ok(?:ay)?|perfect(?:ly)?|as (?:before|always|usual)"
    r"|(?:the )?same as (?:always|before|usual)|no different)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:not|never|no longer)\b|n't\b", re.IGNORECASE)
_CLAUSE_END = re.compile(
    r"[,.;:!?\n]|\b(?:but|until|then|when|while|except|although|though|however|yet)\b",
    re.IGNORECASE,
)
_REASSURANCE_WINDOW = 60


def _is_reassurance(text: str, mention_end: int) -> bool:
    """True if the words right after a mention say the component is fine."""
    window = text[mention_end : mention_end + _REASSURANCE_WINDOW]
    if boundary := _CLAUSE_END.search(window):
        window = window[: boundary.start()]
    return bool(_REASSURANCE.search(window)) and not _NEGATION.search(window)


class FaultMessage(BaseModel):
    """One row of the input CSV.

    Only the three triage columns are declared. Other columns (names, VIN,
    dates, ...) are kept as extra fields so nothing in the row is lost.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    vehicle_alert_code: str | None = None
    message_subject: str = ""
    message_text: str = ""

    @field_validator("vehicle_alert_code", mode="before")
    @classmethod
    def _blank_code_is_none(cls, value: object) -> object:
        # The export writes the literal "NONE" when a message has no code.
        if value is None or (isinstance(value, str) and value.strip().upper() in {"", "NONE"}):
            return None
        return value

    @field_validator("message_subject", "message_text", mode="before")
    @classmethod
    def _none_text_is_empty(cls, value: object) -> object:
        return "" if value is None else value

    @property
    def safety_fault_code(self) -> SafetyFaultCode | None:
        """The safety fault code on this message, matched case-insensitively."""
        if self.vehicle_alert_code is None:
            return None
        return _SAFETY_CODES_BY_KEY.get(self.vehicle_alert_code.casefold())

    @property
    def safety_components_mentioned(self) -> tuple[str, ...]:
        """Safety components referenced in the subject or text as a problem.

        Mentions that only say the component is fine are ignored.
        """
        haystack = f"{self.message_subject}\n{self.message_text}"
        found: dict[str, None] = {}
        for name, pattern in SAFETY_COMPONENT_PATTERNS:
            if name in found:
                continue
            if any(not _is_reassurance(haystack, m.end()) for m in pattern.finditer(haystack)):
                found[name] = None
        return tuple(found)

    @property
    def is_safety_issue(self) -> bool:
        return self.safety_fault_code is not None or bool(self.safety_components_mentioned)


class TriageDecision(BaseModel):
    """A request type and the fix path it resolves to."""

    model_config = ConfigDict(frozen=True)

    request_type: RequestType
    fix_path: FixPath

    @model_validator(mode="after")
    def _fix_path_matches_request_type(self) -> TriageDecision:
        allowed = ALLOWED_FIX_PATHS[self.request_type]
        if self.fix_path not in allowed:
            names = ", ".join(sorted(p.value for p in allowed))
            raise ValueError(
                f"{self.request_type.value} requests must use: {names} "
                f"(got {self.fix_path.value})"
            )
        return self


SAFETY_URGENT_DECISION = TriageDecision(
    request_type=RequestType.SAFETY_URGENT, fix_path=FixPath.TESLA_PICKUP
)


class TriagedMessage(BaseModel):
    """A message paired with its decision.

    A safety issue can never be triaged below Safety_Urgent. A message that is
    not a safety issue may still be escalated to Safety_Urgent by hand.
    """

    message: FaultMessage
    decision: TriageDecision

    @model_validator(mode="after")
    def _safety_issues_are_urgent(self) -> TriagedMessage:
        if (
            self.message.is_safety_issue
            and self.decision.request_type is not RequestType.SAFETY_URGENT
        ):
            reasons = []
            if code := self.message.safety_fault_code:
                reasons.append(f"fault code {code.value}")
            if parts := self.message.safety_components_mentioned:
                reasons.append(f"mentions {', '.join(parts)}")
            raise ValueError(
                f"Safety issue ({'; '.join(reasons)}) must be "
                f"{RequestType.SAFETY_URGENT.value}, "
                f"not {self.decision.request_type.value}"
            )
        return self


def safety_triage(message: FaultMessage) -> TriageDecision | None:
    """Return the Safety_Urgent decision for safety issues, otherwise None.

    None means the rules leave the choice between Soon and Routine (and
    between Remote-fix and Customer visit) to the caller.
    """
    return SAFETY_URGENT_DECISION if message.is_safety_issue else None
