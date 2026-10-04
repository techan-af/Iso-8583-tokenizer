"""Deterministic profile-driven ISO 8583 parser and packer."""

from __future__ import annotations

from .bitmap import decode_bitmap, encode_bitmap
from .errors import ParseError
from .message import CanonicalMessage, FieldValue
from .profile import ISOProfile


class ISO8583Parser:
    def __init__(self, profile: ISOProfile):
        self.profile = profile

    def parse(self, raw_message: bytes, *, header_present: bool = False) -> CanonicalMessage:
        wire = self.profile.wire
        pos = 0
        header = None
        if header_present:
            length = int(wire.get("terminal_header_length", 3))
            header_bytes = raw_message[:length]
            if len(header_bytes) != length:
                raise ParseError("Truncated terminal application header")
            header = header_bytes.decode(wire.get("text_encoding", "ascii"))
            pos += length
        mti_size = int(wire.get("mti_length", 4))
        mti_bytes = raw_message[pos:pos + mti_size]
        pos += mti_size
        try:
            mti = mti_bytes.decode(wire.get("mti_encoding", "ascii"))
        except UnicodeDecodeError as exc:
            raise ParseError("MTI cannot be decoded") from exc
        if mti != self.profile.mti:
            raise ParseError(f"MTI {mti!r} does not match profile MTI {self.profile.mti}")
        present, bitmap_wire = decode_bitmap(raw_message[pos:], wire.get("bitmap_encoding", "binary"))
        bitmap_size = (16 if 1 in present else 8) * (2 if wire.get("bitmap_encoding", "binary") == "hex_ascii" else 1)
        primary = bitmap_wire[:8].hex().upper()
        secondary = bitmap_wire[8:16].hex().upper() if 1 in present else None
        pos += bitmap_size
        fields: dict[int, FieldValue] = {}
        ids = sorted(field_id for field_id in present if field_id != 1)
        unknown = [field_id for field_id in ids if field_id not in self.profile.fields]
        if unknown:
            raise ParseError(f"Bitmap contains fields absent from profile: {unknown}")
        for field_id in ids:
            spec = self.profile.fields[field_id]
            value, pos = self._read_field(raw_message, pos, field_id)
            fields[field_id] = FieldValue(spec.name, value, spec.semantic_type)
        if pos != len(raw_message):
            raise ParseError(f"Unexpected trailing bytes: {len(raw_message) - pos}")
        missing = self.profile.required_fields - set(fields)
        if missing:
            raise ParseError(f"Missing mandatory fields: {sorted(missing)}")
        return CanonicalMessage(self.profile.name, mti, fields, primary, secondary, header)

    def pack(self, message: CanonicalMessage) -> bytes:
        if message.mti != self.profile.mti:
            raise ParseError(f"Message MTI {message.mti!r} does not match profile {self.profile.mti}")
        ids = set(message.fields)
        unknown = ids - set(self.profile.fields)
        if unknown:
            raise ParseError(f"Fields absent from profile: {sorted(unknown)}")
        missing = self.profile.required_fields - ids
        if missing:
            raise ParseError(f"Missing mandatory fields: {sorted(missing)}")
        wire = self.profile.wire
        encoding = wire.get("bitmap_encoding", "binary")
        bitmap, _, _ = encode_bitmap(ids, encoding)
        header_bytes = b""
        if message.header is not None:
            header_bytes = message.header.encode(wire.get("text_encoding", "ascii"))
            expected = int(wire.get("terminal_header_length", 3))
            if len(header_bytes) != expected:
                raise ParseError(f"Header must be {expected} bytes")
        try:
            mti = message.mti.encode(wire.get("mti_encoding", "ascii"))
        except UnicodeEncodeError as exc:
            raise ParseError("MTI cannot be encoded") from exc
        chunks = [header_bytes, mti, bitmap]
        for field_id in sorted(ids):
            chunks.append(self._write_field(field_id, message.fields[field_id].value))
        return b"".join(chunks)

    def _read_field(self, raw: bytes, pos: int, field_id: int) -> tuple[str, int]:
        spec = self.profile.fields[field_id]
        encoding = self.profile.field_encoding(field_id)
        if spec.variable_length:
            prefix_size = int(spec.length_prefix_digits or 0)
            prefix_enc = self.profile.wire.get("length_prefix_encoding", "ascii")
            prefix = raw[pos:pos + prefix_size]
            if len(prefix) != prefix_size:
                raise ParseError(f"Truncated length prefix for field {field_id}")
            try:
                length = int(prefix.decode(prefix_enc))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ParseError(f"Invalid length prefix for field {field_id}") from exc
            pos += prefix_size
            if spec.max_length is not None and length > spec.max_length:
                raise ParseError(f"Field {field_id} length {length} exceeds {spec.max_length}")
            wire_length = self._wire_length(length, encoding, spec.character_type)
        else:
            length = spec.fixed_length
            if length is None:
                raise ParseError(f"Field {field_id} has no usable length in profile")
            wire_length = self._wire_length(length, encoding, spec.character_type)
        chunk = raw[pos:pos + wire_length]
        if len(chunk) != wire_length:
            raise ParseError(f"Truncated field {field_id}")
        if encoding == "binary":
            value = chunk.hex().upper()
        elif encoding == "bcd":
            value = self._decode_bcd(chunk, length)
        else:
            try:
                value = chunk.decode(encoding)
            except (UnicodeDecodeError, LookupError) as exc:
                raise ParseError(f"Invalid encoding in field {field_id}: {encoding}") from exc
        if spec.character_type == "numeric" and encoding != "bcd" and not value.isdigit():
            raise ParseError(f"Field {field_id} must contain numeric digits")
        return value, pos + wire_length

    def _write_field(self, field_id: int, value: str) -> bytes:
        spec = self.profile.fields[field_id]
        encoding = self.profile.field_encoding(field_id)
        if spec.character_type == "numeric" and encoding != "bcd" and not value.isdigit():
            raise ParseError(f"Field {field_id} must contain numeric digits")
        if encoding == "binary":
            try:
                payload = bytes.fromhex(value)
            except ValueError as exc:
                raise ParseError(f"Binary field {field_id} must be represented as hexadecimal") from exc
            length = len(payload)
        elif encoding == "bcd":
            payload = self._encode_bcd(value)
            length = len(value)
        else:
            try:
                payload = value.encode(encoding)
            except (UnicodeEncodeError, LookupError) as exc:
                raise ParseError(f"Cannot encode field {field_id} as {encoding}") from exc
            length = len(payload)
        expected = spec.max_length if spec.variable_length else spec.fixed_length
        if spec.variable_length:
            if spec.max_length is not None and length > spec.max_length:
                raise ParseError(f"Field {field_id} exceeds maximum length {spec.max_length}")
        elif expected is not None and length != expected:
            raise ParseError(f"Field {field_id} must have length {expected}, got {length}")
        if spec.variable_length:
            digits = int(spec.length_prefix_digits or 0)
            prefix_encoding = self.profile.wire.get("length_prefix_encoding", "ascii")
            try:
                prefix = f"{length:0{digits}d}".encode(prefix_encoding)
            except (UnicodeEncodeError, LookupError) as exc:
                raise ParseError(f"Cannot encode field {field_id} length prefix") from exc
            if len(prefix) != digits:
                raise ParseError(f"Length prefix overflow for field {field_id}")
            return prefix + payload
        return payload

    @staticmethod
    def _wire_length(length: int, encoding: str, character_type: str) -> int:
        if encoding == "binary":
            return length
        if encoding == "bcd":
            return (length + 1) // 2
        return length

    @staticmethod
    def _decode_bcd(data: bytes, digits: int) -> str:
        nibbles = "".join(f"{byte:02X}" for byte in data)
        if len(nibbles) > digits:
            nibbles = nibbles[-digits:]
        if any(nibble not in "0123456789" for nibble in nibbles):
            raise ParseError("Invalid packed BCD numeric data")
        return nibbles

    @staticmethod
    def _encode_bcd(value: str) -> bytes:
        if not value.isdigit():
            raise ParseError("Packed BCD values must be numeric digits")
        padded = ("0" if len(value) % 2 else "") + value
        return bytes.fromhex(padded)
