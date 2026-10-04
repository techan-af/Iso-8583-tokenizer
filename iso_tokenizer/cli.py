"""Command-line interface for profile generation and message inspection."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .errors import ISO8583Error
from .mapping_importer import compile_mapping
from .message import CanonicalMessage
from .parser import ISO8583Parser
from .profile import ISOProfile
from .synthetic import synthetic_message
from .tokenizer import ISO8583Tokenizer
from .vocabulary import Vocabulary


def _redacted_message(message: CanonicalMessage, profile: ISOProfile) -> dict:
    result = message.to_dict()
    for field_id, value in result["fields"].items():
        spec = profile.fields.get(int(field_id))
        if spec and (spec.sensitive or spec.semantic_type in {
            "identifier", "card_identifier", "terminal_identifier", "merchant_identifier", "account_identifier"
        }):
            value["value"] = "[REDACTED]"
    return result


def _profile(path: str) -> ISOProfile:
    return ISOProfile.load(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iso-tokenizer")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-profiles", help="Compile mapping.txt to JSON profiles")
    build.add_argument("mapping", nargs="?", default="mapping.txt")
    build.add_argument("--out", default="profiles/iso8583")
    for name in ("parse", "tokenize", "roundtrip"):
        command = commands.add_parser(name)
        command.add_argument("message")
        command.add_argument("--profile", required=True)
    vocab = commands.add_parser("vocabulary", help="Write deterministic profile vocabulary")
    vocab.add_argument("--profile", required=True)
    vocab.add_argument("--out", required=True)
    generate = commands.add_parser("generate", help="Write a synthetic structural message fixture")
    generate.add_argument("--profile", required=True)
    generate.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-profiles":
            written = compile_mapping(args.mapping, args.out)
            print(json.dumps({"profiles": [str(path) for path in written]}, indent=2))
            return 0
        profile = _profile(args.profile)
        if args.command == "vocabulary":
            Vocabulary.for_profile(profile).save(args.out)
            print(f"Vocabulary saved: {args.out}")
            return 0
        if args.command == "generate":
            message = synthetic_message(profile)
            raw = ISO8583Parser(profile).pack(message)
            Path(args.out).write_bytes(raw)
            print(f"Synthetic structural fixture written: {args.out} ({len(raw)} bytes)")
            return 0
        raw = Path(args.message).read_bytes()
        iso_parser = ISO8583Parser(profile)
        message = iso_parser.parse(raw)
        if args.command == "parse":
            print(json.dumps(_redacted_message(message, profile), indent=2))
            return 0
        tokenizer = ISO8583Tokenizer(
            profile,
            pseudonymization_key=os.environ.get("ISO_TOKENIZER_HMAC_KEY", "").encode() or None,
        )
        result = tokenizer.tokenize(message)
        if args.command == "tokenize":
            print(json.dumps(result.public_dict(), indent=2))
            return 0
        reconstructed = tokenizer.detokenize(result)
        repacked = iso_parser.pack(reconstructed)
        print(json.dumps({
            "parse": "PASS",
            "tokenization": "PASS",
            "detokenization": "PASS",
            "semantic_equivalence": "PASS" if iso_parser.parse(repacked).to_dict() == message.to_dict() else "FAIL",
            "wire_bytes_equal": repacked == raw,
        }, indent=2))
        return 0 if repacked == raw else 1
    except (ISO8583Error, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
