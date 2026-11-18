# tesla-fault-triage

Sorts Tesla vehicle fault messages from a CSV file by urgency. Each message gets a request
type and a fix path, and safety issues can never be triaged below `Safety_Urgent`.

The rules are Pydantic models, so a request type or fix path outside the allowed values is
rejected, as is a fix path that doesn't belong to its request type.

## Urgency rules

| Request type    | Fix path                       | When                                                                    |
| --------------- | ------------------------------ | ----------------------------------------------------------------------- |
| `Safety_Urgent` | `Tesla pickup`                 | Any safety fault code, or the subject/text references a safety component |
| `Soon`          | `Service visit`                | Needs a service visit                                                   |
| `Routine`       | `Remote-fix`, `Customer visit` | Can be fixed remotely or at a customer visit                            |

These are the only request types and fix paths. Anything else, including a different
capitalization such as `safety_urgent`, fails validation.

### Safety fault codes

`ABS_w002`, `BRK_a001`, `BRK_w003`, `EPAS_a191`, `EPAS_w202`, `ESP_w003`

Any message with one of these codes is `Safety_Urgent`. Matching ignores case and
surrounding spaces. An empty code, or the literal `NONE`, means the message has no code.

### Safety components in the message text

A message is also `Safety_Urgent` if its subject or text references a safety component,
even with no fault code:

- **Brakes**, by name ("brake", "braking"), or by a symptom only the brakes produce:
  - any mention of the pedal (except the accelerator)
  - the car pulling, tugging or drifting when stopping or slowing down
  - grinding at a stop, at the lights, through the pedal or from the wheels
- **Steering**
- **ABS** (upper case only) and **anti-lock brakes**
- **Stability control**

A mention is ignored when the words right after it say the component is fine, such as
"Brakes and steering feel normal" or "the brakes feel just the same as always". A real
problem still counts:

- a negated reassurance: "the brakes don't feel normal"
- a problem after "but", "until" or "then": "brakes feel fine but the pedal sinks"

The patterns are `SAFETY_COMPONENT_PATTERNS` in `src/fault_triage/models.py`. Add entries
there to cover more components (airbags, seatbelts and tyres aren't included yet).

## CSV format

The CSV needs these three columns:

| Column               | Example                                  |
| -------------------- | ---------------------------------------- |
| `vehicle_alert_code` | `BRK_w003`, `HVAC_w003`, `NONE` or empty |
| `message_subject`    | `brake warning on dash`                  |
| `message_text`       | `Pedal feels lower than usual.`          |

Every other column (customer name, VIN, service center, and so on) is kept on the parsed
row as an extra field. A missing triage column raises a `ValueError`. Files exported from
Excel with a byte-order mark load fine.

```csv
message_id,customer_name,vehicle_alert_code,message_subject,message_text
MSG-1,Sample Owner,BRK_w003,brake warning on dash,Pedal feels lower than usual.
MSG-2,Sample Owner,NONE,cabin heat weak,Takes ten minutes to warm up.
```

## Usage

```python
from fault_triage import TriageDecision, TriagedMessage, load_messages, safety_triage

for message in load_messages("faults.csv"):
    decision = safety_triage(message)  # Safety_Urgent / Tesla pickup, or None
    if decision is None:
        # Not a safety issue: the caller chooses Soon or Routine.
        decision = TriageDecision(request_type="Routine", fix_path="Remote-fix")
    triaged = TriagedMessage(message=message, decision=decision)
    print(message.message_id, triaged.decision.request_type, triaged.decision.fix_path)
```

`FaultMessage` also exposes why a message is a safety issue:

```python
message.safety_fault_code            # e.g. SafetyFaultCode.BRK_W003, or None
message.safety_components_mentioned  # e.g. ("brakes", "steering")
message.is_safety_issue              # True if either of the above is set
```

## What isn't decided yet

The rules only say what makes a message `Safety_Urgent`. For everything else,
`safety_triage` returns `None` and the choice between `Soon` and `Routine` (and between
`Remote-fix` and `Customer visit`) is up to the caller. `TriagedMessage` accepts any valid
decision for a message that isn't a safety issue, and also lets you escalate one to
`Safety_Urgent` by hand.

## Project layout

```
src/fault_triage/
  models.py      request types, fix paths, fault codes, safety detection, validation
  csv_loader.py  load_messages() and the required-column check
tests/
  test_models.py
```

## Development

Requires Python 3.11 or later.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```
