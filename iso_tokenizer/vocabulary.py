"""Stable vocabulary IDs; values never cause vocabulary growth."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


BASE_TOKENS = [
    "<PAD>", "<UNK>", "<BOS>", "<EOS>", "<BITMAP>", "<VALUE>",
    "<BOS_TRANSACTION_SEQUENCE>", "<EOS_TRANSACTION_SEQUENCE>",
]
VALUE_TOKENS = [
    "<AMOUNT>", "<AMOUNT_BUCKET>", "<CATEGORICAL_VALUE>", "<DATE>", "<IDENTIFIER>",
    "<NUMERIC_VALUE>", "<SENSITIVE_VALUE>", "<TEXT_VALUE>", "<TIME>", "<TIMESTAMP>",
]


class Vocabulary:
    def __init__(self, tokens: Iterable[str], version: str = "0.1.0"):
        unique = list(dict.fromkeys(tokens))
        self.version = version
        self.tokens = {token: index for index, token in enumerate(unique)}
        self.id_to_token = {index: token for token, index in self.tokens.items()}

    @classmethod
    def for_profile(cls, profile, include_bitmap_tokens: bool = True) -> "Vocabulary":
        return cls.for_profiles([profile], include_bitmap_tokens)

    @classmethod
    def for_profiles(cls, profiles, include_bitmap_tokens: bool = True) -> "Vocabulary":
        profiles = list(profiles)
        tokens = [*BASE_TOKENS, *VALUE_TOKENS]
        tokens.extend(f"<MTI_{mti}>" for mti in ("0100", "0110", "0200", "0210", "0400", "0410", "0800", "0810", "1200"))
        tokens.extend(f"<MSG_{mti}>" for mti in ("0100", "0110", "0200", "0210", "0400", "0410", "0800", "0810", "1200"))
        tokens.extend(f"<FIELD_{field_id}>" for field_id in range(1, 129))
        if include_bitmap_tokens:
            tokens.extend(f"<DE_PRESENT_{field_id}>" for field_id in range(1, 129))
        for profile in profiles:
            tokens.append(f"<MTI_{profile.mti}>")
            for values in profile.semantic_values.values():
                tokens.extend(values.values())
        return cls(tokens)

    def encode(self, tokens: Iterable[str]) -> list[int]:
        return [self.tokens.get(token, self.tokens["<UNK>"]) for token in tokens]

    def decode(self, ids: Iterable[int]) -> list[str]:
        return [self.id_to_token.get(index, "<UNK>") for index in ids]

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "tokens": self.tokens}

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
