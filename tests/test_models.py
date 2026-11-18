import pytest
from pydantic import ValidationError

from fault_triage import (
    FaultMessage,
    FixPath,
    RequestType,
    SafetyFaultCode,
    TriageDecision,
    TriagedMessage,
    load_messages,
    safety_triage,
)


# --- fixed allowed values -------------------------------------------------


def test_request_types_are_exactly_the_three_allowed():
    assert {t.value for t in RequestType} == {"Safety_Urgent", "Soon", "Routine"}


def test_fix_paths_are_exactly_the_four_allowed():
    assert {p.value for p in FixPath} == {
        "Tesla pickup",
        "Service visit",
        "Remote-fix",
        "Customer visit",
    }


@pytest.mark.parametrize("bad", ["Urgent", "safety_urgent", "Later", ""])
def test_unknown_request_type_is_rejected(bad):
    with pytest.raises(ValidationError):
        TriageDecision(request_type=bad, fix_path="Tesla pickup")


@pytest.mark.parametrize("bad", ["Tow", "tesla pickup", "Remote fix", ""])
def test_unknown_fix_path_is_rejected(bad):
    with pytest.raises(ValidationError):
        TriageDecision(request_type="Routine", fix_path=bad)


# --- request type -> fix path ----------------------------------------------


@pytest.mark.parametrize(
    "request_type, fix_path",
    [
        ("Safety_Urgent", "Tesla pickup"),
        ("Soon", "Service visit"),
        ("Routine", "Remote-fix"),
        ("Routine", "Customer visit"),
    ],
)
def test_allowed_pairs(request_type, fix_path):
    decision = TriageDecision(request_type=request_type, fix_path=fix_path)
    assert decision.request_type == request_type
    assert decision.fix_path == fix_path


@pytest.mark.parametrize(
    "request_type, fix_path",
    [
        ("Safety_Urgent", "Service visit"),
        ("Safety_Urgent", "Remote-fix"),
        ("Soon", "Tesla pickup"),
        ("Soon", "Customer visit"),
        ("Routine", "Tesla pickup"),
        ("Routine", "Service visit"),
    ],
)
def test_disallowed_pairs(request_type, fix_path):
    with pytest.raises(ValidationError):
        TriageDecision(request_type=request_type, fix_path=fix_path)


# --- safety detection ------------------------------------------------------


@pytest.mark.parametrize("code", [c.value for c in SafetyFaultCode])
def test_every_listed_fault_code_is_a_safety_issue(code):
    message = FaultMessage(vehicle_alert_code=code, message_text="Light came on")
    assert message.safety_fault_code == code
    assert message.is_safety_issue


def test_fault_code_match_ignores_case_and_whitespace():
    message = FaultMessage(vehicle_alert_code="  brk_A001 ")
    assert message.safety_fault_code is SafetyFaultCode.BRK_A001


@pytest.mark.parametrize("blank", ["", "  ", "NONE", "none", None])
def test_blank_or_none_code_means_no_code(blank):
    assert FaultMessage(vehicle_alert_code=blank).vehicle_alert_code is None


def test_unknown_fault_code_is_not_a_safety_issue_on_its_own():
    message = FaultMessage(vehicle_alert_code="UI_w001", message_text="Screen froze")
    assert message.safety_fault_code is None
    assert not message.is_safety_issue


@pytest.mark.parametrize(
    "subject, text, component",
    [
        ("Brakes feel soft", "", "brakes"),
        ("", "Grinding noise when braking downhill", "brakes"),
        ("Question", "The steering wheel pulls left", "steering"),
        ("ABS light", "", "ABS"),
        ("", "Anti-lock warning showed up", "anti-lock brakes"),
        ("", "Stability control disabled message", "stability control"),
    ],
)
def test_safety_component_mention_without_code(subject, text, component):
    message = FaultMessage(vehicle_alert_code="", message_subject=subject, message_text=text)
    assert message.vehicle_alert_code is None
    assert component in message.safety_components_mentioned
    assert message.is_safety_issue


@pytest.mark.parametrize(
    "text",
    [
        "The pedal feels a bit softer than it used to, sinking further before it bites.",
        "Pedal feels spongy after the long descent.",
        "Since the update the car pulls to the left when I slow down to a stop.",
        "Owner reports car tugs left when stopping at junctions.",
        "When I slow down for the lights the car tugs gently to the left.",
        "There's a grinding noise from the front wheels when I'm stopped at the lights.",
        "Feels like there's a grinding through the pedal at traffic lights.",
    ],
)
def test_brake_symptoms_count_as_brake_references(text):
    message = FaultMessage(message_subject="question", message_text=text)
    assert message.safety_components_mentioned == ("brakes",)
    assert message.is_safety_issue


@pytest.mark.parametrize(
    "text",
    [
        "Touchscreen reboots on its own. Brakes and steering feel normal to the owner.",
        "Clunk over bumps. The car tracks straight and brakes and steers exactly as before.",
        "Clunk from the front end. The car still drives normally and steers fine.",
        "Rides a bit bouncy. Brakes feel completely normal when I stop.",
        "Tyre pressure light on. Pedal and steering feel completely normal.",
        "Dull knock at the rear and the brakes feel just the same as always.",
        "Clunk on tight turns. Brakes feel normal and the steering is fine, just wanted it checked.",
    ],
)
def test_saying_a_component_is_fine_is_not_a_reference(text):
    message = FaultMessage(message_subject="noise", message_text=text)
    assert message.safety_components_mentioned == ()
    assert not message.is_safety_issue


@pytest.mark.parametrize(
    "text, component",
    [
        ("The brakes do not feel normal anymore.", "brakes"),
        ("Steering isn't fine at low speed.", "steering"),
        ("The brakes feel fine but the pedal sinks at the lights.", "brakes"),
        ("The car drives normally until I brake and then it pulls left.", "brakes"),
        ("Steering feels fine, brakes are grabby.", "brakes"),
    ],
)
def test_reassurance_does_not_hide_a_real_problem(text, component):
    message = FaultMessage(message_text=text)
    assert component in message.safety_components_mentioned


@pytest.mark.parametrize(
    "text",
    [
        "The wiper arm makes a horrible grinding noise every time it parks.",
        "I pulled over at the next exit and drove home slowly.",
        "The accelerator pedal squeaks.",
        "The rear door handle needs two pulls to open.",
        "The cable is hard to pull out of the charge port.",
    ],
)
def test_lookalike_phrases_are_not_brake_references(text):
    assert not FaultMessage(message_text=text).is_safety_issue


def test_ordinary_message_is_not_a_safety_issue():
    message = FaultMessage(
        message_subject="Charging slow",
        message_text="Working on my abs at the gym while it charged; took 3 hours.",
    )
    assert not message.is_safety_issue


# --- safety rule enforcement ------------------------------------------------


def test_safety_triage_returns_pickup_for_safety_issue():
    decision = safety_triage(FaultMessage(vehicle_alert_code="EPAS_w202"))
    assert decision.request_type is RequestType.SAFETY_URGENT
    assert decision.fix_path is FixPath.TESLA_PICKUP


def test_safety_triage_leaves_non_safety_to_caller():
    assert safety_triage(FaultMessage(message_text="Wiper streaks")) is None


def test_safety_issue_cannot_be_downgraded():
    message = FaultMessage(message_subject="Steering shudder")
    with pytest.raises(ValidationError, match="steering"):
        TriagedMessage(
            message=message,
            decision=TriageDecision(request_type="Soon", fix_path="Service visit"),
        )


def test_safety_code_cannot_be_downgraded():
    message = FaultMessage(vehicle_alert_code="ABS_w002")
    with pytest.raises(ValidationError, match="ABS_w002"):
        TriagedMessage(
            message=message,
            decision=TriageDecision(request_type="Routine", fix_path="Remote-fix"),
        )


def test_non_safety_message_accepts_any_valid_decision():
    message = FaultMessage(message_text="Bluetooth keeps dropping")
    triaged = TriagedMessage(
        message=message,
        decision=TriageDecision(request_type="Routine", fix_path="Remote-fix"),
    )
    assert triaged.decision.fix_path is FixPath.REMOTE_FIX


# --- CSV loading -------------------------------------------------------------


def test_load_messages_keeps_extra_columns(tmp_path):
    csv_file = tmp_path / "faults.csv"
    csv_file.write_text(
        "﻿customer_name,vehicle_alert_code,message_subject,message_text\n"
        "Pat,BRK_w003,Brake warning,Pedal feels low\n"
        "Sam,,Charging,Charge port door stuck\n",
        encoding="utf-8",
    )
    first, second = load_messages(csv_file)
    assert first.customer_name == "Pat"
    assert first.is_safety_issue
    assert second.vehicle_alert_code is None
    assert not second.is_safety_issue


def test_load_messages_requires_triage_columns(tmp_path):
    csv_file = tmp_path / "faults.csv"
    csv_file.write_text("customer_name,message_text\nPat,hello\n", encoding="utf-8")
    with pytest.raises(ValueError, match="vehicle_alert_code, message_subject"):
        load_messages(csv_file)
