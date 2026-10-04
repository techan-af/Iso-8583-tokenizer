"""Loadable profile model; wire details stay outside the parser core."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ProfileError


@dataclass(frozen=True)
class FieldSpec:
    id: int
    name: str
    raw_type: str
    character_type: str
    required: bool = False
    requirement: str = ""
    notes: str = ""
    fixed_length: int | None = None
    min_length: int | None = None
    max_length: int | None = None
    variable_length: bool = False
    length_prefix_digits: int | None = None
    encoding: str | None = None
    semantic_type: str | None = None
    sensitive: bool = False
    subfields: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FieldSpec":
        return cls(
            id=int(data["id"]),
            name=str(data["name"]),
            raw_type=str(data.get("raw_type", "")),
            character_type=str(data.get("character_type", "alphanumeric")),
            required=bool(data.get("required", False)),
            requirement=str(data.get("requirement", "")),
            notes=str(data.get("notes", "")),
            fixed_length=data.get("length"),
            min_length=data.get("min_length"),
            max_length=data.get("max_length"),
            variable_length=bool(data.get("variable_length", False)),
            length_prefix_digits=data.get("length_prefix_digits"),
            encoding=data.get("encoding"),
            semantic_type=data.get("semantic_type"),
            sensitive=bool(data.get("sensitive", False)),
            subfields=tuple(data.get("subfields", ())),
        )


@dataclass(frozen=True)
class ISOProfile:
    name: str
    version: str
    mti: str
    source: str
    wire: dict[str, Any]
    fields: dict[int, FieldSpec] = field(default_factory=dict)
    semantic_values: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "ISOProfile":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            fields = {int(k): FieldSpec.from_dict(v) for k, v in data["fields"].items()}
            mti = str(data["mti"])
            if len(mti) != 4 or not mti.isdigit():
                raise ProfileError("Profile MTI must be exactly four digits")
            return cls(
                name=str(data["name"]),
                version=str(data.get("version", "0.1.0")),
                mti=mti,
                source=str(data.get("source", "")),
                wire=dict(data.get("wire", {})),
                fields=fields,
                semantic_values=dict(data.get("semantic_values", {})),
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProfileError(f"Unable to load profile {path}: {exc}") from exc

    @property
    def required_fields(self) -> set[int]:
        return {number for number, spec in self.fields.items() if spec.required}

    def field_encoding(self, field_id: int) -> str:
        spec = self.fields[field_id]
        overrides = self.wire.get("field_encodings", {})
        if str(field_id) in overrides:
            return str(overrides[str(field_id)])
        if spec.encoding:
            return spec.encoding
        if spec.character_type == "binary":
            return "binary"
        return str(self.wire.get("text_encoding", "ascii"))
