"""Field-aware semantic tokenizer over the canonical message representation."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import ISO8583Error
from .message import CanonicalMessage
from .profile import ISOProfile
from .vocabulary import Vocabulary


@dataclass
class TokenizationResult:
    tokens: list[str]
    token_ids: list[int]
    numeric_features: dict[str, float] = field(default_factory=dict)
    identifier_digests: dict[str, str] = field(default_factory=dict)
    # Ephemeral sidecar enables exact reconstruction; never log or persist it.
    _canonical_snapshot: dict[str, Any] | None = field(default=None, repr=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "token_ids": self.token_ids,
            "numeric_features": self.numeric_features,
            "identifier_digests": self.identifier_digests,
        }


class ISO8583Tokenizer:
    def __init__(
        self,
        profile: ISOProfile,
        *,
        include_bitmap_tokens: bool = True,
        pseudonymization_key: bytes | None = None,
        vocabulary: Vocabulary | None = None,
    ):
        self.profile = profile
        self.include_bitmap_tokens = include_bitmap_tokens
        self.pseudonymization_key = pseudonymization_key
        self.vocabulary = vocabulary or Vocabulary.for_profile(profile, include_bitmap_tokens)

    def tokenize(self, message: CanonicalMessage) -> TokenizationResult:
        if message.mti != self.profile.mti:
            raise ISO8583Error(f"Message MTI {message.mti} does not match tokenizer profile {self.profile.mti}")
        output = ["<BOS>", f"<MTI_{message.mti}>"]
        if self.include_bitmap_tokens:
            output.append("<BITMAP>")
            if message.secondary_bitmap is not None:
                output.append("<DE_PRESENT_1>")
            output.extend(f"<DE_PRESENT_{field_id}>" for field_id in sorted(message.fields))
        numeric_features: dict[str, float] = {}
        digests: dict[str, str] = {}
        for field_id, field_value in sorted(message.fields.items()):
            spec = self.profile.fields.get(field_id)
            if spec is None:
                raise ISO8583Error(f"Field {field_id} is absent from tokenizer profile")
            output.append(f"<FIELD_{field_id}>")
            semantic_tokens = self.profile.semantic_values.get(str(field_id), {})
            if field_value.value in semantic_tokens:
                output.append(semantic_tokens[field_value.value])
                continue
            semantic = spec.semantic_type or ""
            if spec.sensitive:
                output.append("<SENSITIVE_VALUE>")
                if self.pseudonymization_key:
                    digest = hmac.new(self.pseudonymization_key, field_value.value.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
                    digests[str(field_id)] = digest
                continue
            if semantic in {"card_identifier", "identifier", "terminal_identifier", "merchant_identifier", "account_identifier"}:
                output.append("<IDENTIFIER>")
                if self.pseudonymization_key:
                    digest = hmac.new(self.pseudonymization_key, field_value.value.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
                    digests[str(field_id)] = digest
            elif semantic == "amount":
                output.append("<AMOUNT>")
                self._numeric_feature(field_id, field_value.value, numeric_features)
            elif semantic in {"timestamp", "date", "time", "expiry_date"}:
                output.append({"timestamp": "<TIMESTAMP>", "date": "<DATE>", "time": "<TIME>", "expiry_date": "<DATE>"}[semantic])
            elif spec.character_type == "numeric":
                output.append("<NUMERIC_VALUE>")
                self._numeric_feature(field_id, field_value.value, numeric_features)
            elif semantic in {"processing_code", "merchant_type", "pos_entry_mode", "currency_code"}:
                output.append("<CATEGORICAL_VALUE>")
            else:
                output.append("<TEXT_VALUE>")
        output.append("<EOS>")
        snapshot = message.to_dict()
        return TokenizationResult(output, self.vocabulary.encode(output), numeric_features, digests, snapshot)

    @staticmethod
    def _numeric_feature(field_id: int, value: str, features: dict[str, float]) -> None:
        try:
            numeric = Decimal(value)
        except InvalidOperation:
            return
        if numeric.is_finite():
            # Preserve source units; no currency exponent/decimal placement is inferred.
            features[str(field_id)] = float(numeric)

    def detokenize(self, result: TokenizationResult) -> CanonicalMessage:
        if result._canonical_snapshot is None:
            raise ISO8583Error("Detokenization requires the in-memory canonical sidecar")
        return CanonicalMessage.from_dict(result._canonical_snapshot)

    def encode(self, message: CanonicalMessage) -> list[int]:
        return self.tokenize(message).token_ids

    def decode(self, token_ids: list[int], *, sidecar: TokenizationResult | None = None) -> CanonicalMessage:
        if sidecar is None or sidecar.token_ids != token_ids:
            raise ISO8583Error("Token IDs alone are lossy; pass the matching in-memory sidecar")
        return self.detokenize(sidecar)
