"""Deterministic synthetic fixture builder (never uses production data)."""

from __future__ import annotations

from .message import CanonicalMessage, FieldValue
from .profile import ISOProfile


def synthetic_message(profile: ISOProfile, seed: int = 1) -> CanonicalMessage:
    """Make a structural test fixture satisfying top-level mandatory fields.

    Variable-length and composite fields are synthetic placeholders. This is
    useful for parser/tokenizer tests, not a claim of processor-valid traffic.
    """
    fields: dict[int, FieldValue] = {}
    for field_id in sorted(profile.required_fields):
        spec = profile.fields[field_id]
        length = spec.fixed_length or min(8, spec.max_length or 8)
        semantic = spec.semantic_type or ""
        if spec.character_type == "binary":
            value = ("00" * length)
        elif semantic == "amount" or spec.character_type == "numeric":
            value = str(seed % 10).zfill(length)
        else:
            value = ("SYNTH" + str(seed)).ljust(length, "X")[:length]
        if spec.variable_length:
            value = value[:min(4, spec.max_length or 4)]
        fields[field_id] = FieldValue(spec.name, value, spec.semantic_type)
    return CanonicalMessage(profile.name, profile.mti, fields)
