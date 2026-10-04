"""Compile the supplied Worldpay markdown tables into machine-readable profiles.

The importer retains each specification's raw type and notes. It deliberately
does not claim that the mapping defines byte-level encodings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TABLE_RE = re.compile(r"^---\s*TABLE\s+[^:]+:\s*(\d{4})\s+(.+?)\s*---$", re.I)
ROW_RE = re.compile(r"^\s*([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|(.*)$")
SENSITIVE_IDS = {2, 35, 45, 52, 55, 62, 100}


def _type_details(raw_type: str) -> dict[str, Any]:
    compact = raw_type.strip()
    variable = re.match(r"^(LLL|LLLL|LL)\b", compact)
    prefix_digits = {"LL": 2, "LLL": 3, "LLLL": 4}.get(variable.group(1)) if variable else None
    numeric = bool(re.search(r"(?:^|\s)nP?\d", compact, re.I))
    binary = bool(re.search(r"(?:^|\s)b\d", compact, re.I))
    char_type = "binary" if binary else "numeric" if numeric else "alphanumeric"
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", compact)]
    maximum = numbers[-1] if numbers else None
    if binary and maximum is not None:
        maximum = (maximum + 7) // 8
    is_variable = prefix_digits is not None
    return {
        "character_type": char_type,
        "length": None if is_variable else maximum,
        "min_length": 0 if is_variable else maximum,
        "max_length": maximum,
        "variable_length": is_variable,
        "length_prefix_digits": prefix_digits,
        "encoding": None,
    }


def _semantic_type(field_id: int, name: str) -> str | None:
    by_id = {
        2: "card_identifier", 3: "processing_code", 4: "amount", 5: "amount",
        6: "amount", 7: "timestamp", 11: "identifier", 12: "time",
        13: "date", 14: "expiry_date", 18: "merchant_type", 22: "pos_entry_mode",
        35: "track_data", 37: "identifier", 41: "terminal_identifier",
        42: "merchant_identifier", 45: "track_data", 49: "currency_code",
        51: "currency_code", 52: "pin_block", 55: "emv_data", 62: "composite_data",
        99: "identifier", 100: "encrypted_payment_data", 102: "account_identifier",
        103: "account_identifier", 123: "merchant_name",
    }
    return by_id.get(field_id)


def compile_mapping(source: str | Path, output_dir: str | Path) -> list[Path]:
    source_path = Path(source)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    profiles: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in source_path.read_text(encoding="utf-8").splitlines():
        heading = TABLE_RE.match(line.strip())
        if heading:
            if current:
                profiles.append(current)
            mti, title = heading.groups()
            key = "authorization" if mti == "0100" else "financial_request" if mti == "0200" else f"mti_{mti}"
            current = {
                "name": f"worldpay_{key}",
                "version": "0.1.0",
                "mti": mti,
                "message_name": title.strip(),
                "source": source_path.name,
                "wire": {
                    "mti_encoding": "ascii",
                    "bitmap_encoding": "binary",
                    "text_encoding": "ascii",
                    "length_prefix_encoding": "ascii",
                    "wire_assumptions": "Illustrative defaults only; confirm with the Worldpay transport/interface guide.",
                },
                "fields": {},
                "semantic_values": {},
            }
            continue
        if current is None:
            continue
        row = ROW_RE.match(line)
        if not row:
            continue
        bit, name, raw_type, requirement, notes = [v.strip() for v in row.groups()]
        if not re.fullmatch(r"\d{3}(?:\.\d+)?", bit):
            continue
        components = bit.split(".")
        field_id = int(components[0])
        if len(components) > 1:
            parent = current["fields"].get(str(field_id))
            if parent is not None:
                detail = _type_details(raw_type)
                parent.setdefault("subfields", []).append({
                    "id": int(components[1]), "name": name, "raw_type": raw_type,
                    "requirement": requirement, "required": requirement == "M",
                    "notes": notes, **detail,
                })
            continue
        # The table's 001 is the ISO secondary bitmap, not a normal data element.
        if field_id == 1:
            continue
        details = _type_details(raw_type)
        current["fields"][str(field_id)] = {
            "id": field_id,
            "name": name,
            "raw_type": raw_type,
            "requirement": requirement,
            "required": requirement == "M",
            "conditional": notes if requirement == "C" else None,
            "notes": notes,
            "semantic_type": _semantic_type(field_id, name),
            "sensitive": field_id in SENSITIVE_IDS,
            **details,
        }

    if current:
        profiles.append(current)

    paths: list[Path] = []
    for profile in profiles:
        file_name = "authorization.json" if profile["mti"] == "0100" else "financial_request.json" if profile["mti"] == "0200" else f"{profile['mti']}.json"
        target = out_dir / file_name
        target.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(target)
    return paths
