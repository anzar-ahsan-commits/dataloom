"""Small HL7 v2.5 ER7 builders with explicit required-field placement."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from dataloom.domains import Context


def escape(value: str) -> str:
    """Escape ER7 delimiters and control characters in a scalar field."""
    codes = {"|": "F", "^": "S", "~": "R", "\\": "E", "&": "T"}
    return "".join(
        f"\\{codes[c]}\\" if c in codes else f"\\X{ord(c):02X}\\" if ord(c) < 32 else c
        for c in value
    )


def _segment(name: str, fields: dict[int, str]) -> str:
    return name + "|" + "|".join(fields.get(i, "") for i in range(1, max(fields) + 1))


def build_message(
    context: Context,
    kind: Literal["ADT^A01", "ORU^R01"],
    patient_id: str,
    first_name: str,
    last_name: str,
) -> str:
    """Build a fictional v2.5 admission or final hemoglobin observation.

    ADT includes EVN, required by the selected v2.5 event structure.
    This is a minimal test profile, not jurisdiction-specific conformance.
    """
    if kind not in ("ADT^A01", "ORU^R01"):
        raise ValueError("Supported messages: ADT^A01, ORU^R01")
    timestamp = context.reference_date.strftime("%Y%m%d") + "120000"
    control = f"DL{context.rng.getrandbits(64):016x}"
    structure = "ADT_A01" if kind == "ADT^A01" else "ORU_R01"
    segments = [
        f"MSH|^~\\&|DATALOOM|FICTIONAL|TEST|TEST|{timestamp}||{kind}^{structure}|{control}|T|2.5"
    ]
    if kind == "ADT^A01":
        segments.append(_segment("EVN", {1: "A01", 2: timestamp}))
    segments.append(
        _segment(
            "PID",
            {
                1: "1",
                3: escape(patient_id) + "^^^DATALOOM^MR",
                5: escape(last_name) + "^" + escape(first_name),
            },
        )
    )
    if kind == "ADT^A01":
        segments.append(_segment("PV1", {1: "1", 2: "I"}))
    else:
        segments.append(
            _segment(
                "OBR",
                {
                    1: "1",
                    3: control + "^DATALOOM",
                    4: "718-7^Hemoglobin^LN",
                    7: timestamp,
                    25: "F",
                },
            )
        )
        segments.append(
            _segment(
                "OBX",
                {
                    1: "1",
                    2: "NM",
                    3: "718-7^Hemoglobin^LN",
                    5: "14.0",
                    6: "g/dL^grams per deciliter^UCUM",
                    7: "12-16",
                    8: "N",
                    11: "F",
                    14: timestamp,
                },
            )
        )
    return "\r".join(segments) + "\r"
