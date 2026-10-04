"""Transaction-sequence representation composed from message tokenizers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .errors import ISO8583Error
from .message import CanonicalMessage
from .tokenizer import ISO8583Tokenizer
from .vocabulary import Vocabulary


@dataclass
class TransactionSequenceResult:
    tokens: list[str]
    token_ids: list[int]
    _snapshots: list[dict]  # In-memory only; may hold sensitive payment data.


def tokenize_sequence(
    messages: Iterable[tuple[ISO8583Tokenizer, CanonicalMessage]],
) -> TransactionSequenceResult:
    items = list(messages)
    if not items:
        raise ISO8583Error("A transaction sequence must contain at least one message")
    vocab = Vocabulary.for_profiles(
        [tokenizer.profile for tokenizer, _ in items],
        items[0][0].include_bitmap_tokens,
    )
    tokens = ["<BOS_TRANSACTION_SEQUENCE>"]
    snapshots = []
    for tokenizer, message in items:
        result = tokenizer.tokenize(message)
        tokens.append(f"<MSG_{message.mti}>")
        tokens.extend(result.tokens[1:-1])
        snapshots.append(message.to_dict())
    tokens.append("<EOS_TRANSACTION_SEQUENCE>")
    return TransactionSequenceResult(tokens, vocab.encode(tokens), snapshots)


def detokenize_sequence(result: TransactionSequenceResult) -> list[CanonicalMessage]:
    return [CanonicalMessage.from_dict(snapshot) for snapshot in result._snapshots]
