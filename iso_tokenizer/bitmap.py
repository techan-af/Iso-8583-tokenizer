"""ISO primary/secondary bitmap helpers."""

from __future__ import annotations

from .errors import ParseError


def decode_bitmap(data: bytes, encoding: str = "binary") -> tuple[set[int], bytes]:
    if encoding == "binary":
        if len(data) < 8:
            raise ParseError("Truncated primary bitmap")
        primary_bytes = data[:8]
        primary_bits = int.from_bytes(primary_bytes, "big")
        present = {i + 1 for i in range(64) if primary_bits & (1 << (63 - i))}
        consumed = 8
        if 1 in present:
            if len(data) < 16:
                raise ParseError("Primary bitmap indicates a missing secondary bitmap")
            secondary_bytes = data[8:16]
            secondary_bits = int.from_bytes(secondary_bytes, "big")
            present.update(65 + i for i in range(64) if secondary_bits & (1 << (63 - i)))
            consumed = 16
        return present, primary_bytes + (data[8:16] if consumed == 16 else b"")
    if encoding == "hex_ascii":
        if len(data) < 16:
            raise ParseError("Truncated ASCII-hex primary bitmap")
        try:
            primary_bytes = bytes.fromhex(data[:16].decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ParseError("Invalid ASCII-hex primary bitmap") from exc
        primary_bits = int.from_bytes(primary_bytes, "big")
        present = {i + 1 for i in range(64) if primary_bits & (1 << (63 - i))}
        consumed = 16
        secondary_bytes = b""
        if 1 in present:
            if len(data) < 32:
                raise ParseError("Primary bitmap indicates a missing secondary bitmap")
            try:
                secondary_bytes = bytes.fromhex(data[16:32].decode("ascii"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ParseError("Invalid ASCII-hex secondary bitmap") from exc
            bits = int.from_bytes(secondary_bytes, "big")
            present.update(65 + i for i in range(64) if bits & (1 << (63 - i)))
            consumed = 32
        return present, primary_bytes + secondary_bytes
    raise ParseError(f"Unsupported bitmap encoding: {encoding}")


def encode_bitmap(fields: set[int], encoding: str = "binary") -> tuple[bytes, str, str | None]:
    has_secondary = any(field_id > 64 for field_id in fields)
    primary = 1 << 63 if has_secondary else 0
    secondary = 0
    for field_id in fields:
        if field_id == 1:
            continue
        if 2 <= field_id <= 64:
            primary |= 1 << (64 - field_id)
        elif 65 <= field_id <= 128:
            secondary |= 1 << (128 - field_id)
        else:
            raise ParseError(f"Field id outside bitmap range: {field_id}")
    primary_bytes = primary.to_bytes(8, "big")
    secondary_bytes = secondary.to_bytes(8, "big") if has_secondary else b""
    if encoding == "binary":
        wire = primary_bytes + secondary_bytes
    elif encoding == "hex_ascii":
        wire = primary_bytes.hex().upper().encode("ascii")
        if has_secondary:
            wire += secondary_bytes.hex().upper().encode("ascii")
    else:
        raise ParseError(f"Unsupported bitmap encoding: {encoding}")
    return wire, primary_bytes.hex().upper(), secondary_bytes.hex().upper() if has_secondary else None
