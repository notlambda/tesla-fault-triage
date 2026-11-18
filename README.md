# fault-triage

Sorts Tesla vehicle fault messages from a CSV file by urgency.

## Urgency rules

| Request type    | Fix path                      | When                                                                         |
| --------------- | ----------------------------- | ---------------------------------------------------------------------------- |
| `Safety_Urgent` | `Tesla pickup`                | Any safety fault code, or the subject/text mentions a safety component      |
| `Soon`          | `Service visit`               | Needs a service visit                                                        |
| `Routine`       | `Remote-fix`, `Customer visit` | Can be fixed remotely or at a customer visit                                 |

Safety fault codes: `ABS_w002`, `BRK_a001`, `BRK_w003`, `EPAS_a191`, `EPAS_w202`, `ESP_w003`.

A message that references brakes, steering, ABS, anti-lock brakes or stability control is
`Safety_Urgent` even without a fault code. Brake symptoms count as a brake reference: any
mention of the pedal, pulling or tugging when stopping, and grinding at a stop. A mention
directly followed by "normal", "fine", "same as always" and similar ("brakes and steering
feel normal") is ignored unless it is negated ("brakes don't feel normal"). The patterns are
`SAFETY_COMPONENT_PATTERNS` in `src/fault_triage/models.py`.

## CSV columns

Required: `vehicle_alert_code`, `message_subject`, `message_text`. Every other column is kept
on the parsed `FaultMessage` as an extra field.

## Usage

```python
from fault_triage import load_messages, safety_triage

for message in load_messages("faults.csv"):
    decision = safety_triage(message)  # Safety_Urgent / Tesla pickup, or None
```

`safety_triage` returns `None` for messages that are not safety issues; deciding between
`Soon` and `Routine` is up to the caller. `TriagedMessage` rejects any decision that puts a
safety issue below `Safety_Urgent`.

## Development

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```
