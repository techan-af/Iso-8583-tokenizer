"""Canonical intermediate representation shared by parser and tokenizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldValue:
    name: str
    value: str
    semantic_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "semantic_type": self.semantic_type}


@dataclass
class CanonicalMessage:
    profile: str
    mti: str
    fields: dict[int, FieldValue]
    primary_bitmap: str = ""
    secondary_bitmap: str | None = None
    header: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "mti": self.mti,
            "bitmap": {"primary": self.primary_bitmap, "secondary": self.secondary_bitmap},
            "header": self.header,
            "fields": {str(k): v.to_dict() for k, v in sorted(self.fields.items())},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalMessage":
        bitmaps = data.get("bitmap", {})
        return cls(
            profile=str(data["profile"]),
            mti=str(data["mti"]),
            fields={
                int(k): FieldValue(
                    name=str(v["name"]),
                    value=str(v["value"]),
                    semantic_type=v.get("semantic_type"),
                )
                for k, v in data.get("fields", {}).items()
            },
            primary_bitmap=str(bitmaps.get("primary", "")),
            secondary_bitmap=bitmaps.get("secondary"),
            header=data.get("header"),
            metadata=dict(data.get("metadata", {})),
        )
