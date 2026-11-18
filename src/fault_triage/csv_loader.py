"""Read fault messages from a CSV file."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import FaultMessage

REQUIRED_COLUMNS = ("vehicle_alert_code", "message_subject", "message_text")


def load_messages(path: str | Path) -> list[FaultMessage]:
    """Parse every row of the CSV into a FaultMessage.

    Raises ValueError if any of the three triage columns is missing.
    """
    # utf-8-sig drops the byte-order mark Excel adds to exported CSVs.
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = [name.strip() for name in reader.fieldnames or []]
        missing = [col for col in REQUIRED_COLUMNS if col not in header]
        if missing:
            raise ValueError(f"{path}: missing column(s): {', '.join(missing)}")
        reader.fieldnames = header
        return [FaultMessage.model_validate(row) for row in reader]
