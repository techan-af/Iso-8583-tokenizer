import json
import tempfile
import unittest
from pathlib import Path

from iso_tokenizer.errors import ISO8583Error, ParseError
from iso_tokenizer.mapping_importer import compile_mapping
from iso_tokenizer.message import CanonicalMessage, FieldValue
from iso_tokenizer.parser import ISO8583Parser
from iso_tokenizer.profile import ISOProfile
from iso_tokenizer.sequence import detokenize_sequence, tokenize_sequence
from iso_tokenizer.tokenizer import ISO8583Tokenizer
from iso_tokenizer.vocabulary import Vocabulary


def profile_for_test(bitmap_encoding="binary", field_encodings=None):
    data = {
        "name": "test", "version": "0.1.0", "mti": "0100", "source": "test",
        "wire": {
            "mti_encoding": "ascii", "bitmap_encoding": bitmap_encoding,
            "text_encoding": "ascii", "length_prefix_encoding": "ascii",
            "field_encodings": field_encodings or {},
        },
        "fields": {
            "3": {"id": 3, "name": "processing_code", "raw_type": "nP6", "character_type": "numeric", "required": True, "length": 6, "max_length": 6, "semantic_type": "processing_code"},
            "4": {"id": 4, "name": "transaction_amount", "raw_type": "nP12", "character_type": "numeric", "required": True, "length": 12, "max_length": 12, "semantic_type": "amount"},
            "35": {"id": 35, "name": "track_ii", "raw_type": "LLd nP37", "character_type": "numeric", "required": False, "max_length": 37, "variable_length": True, "length_prefix_digits": 2, "semantic_type": "track_data", "sensitive": True},
            "70": {"id": 70, "name": "network_code", "raw_type": "an3", "character_type": "alphanumeric", "required": False, "length": 3, "max_length": 3},
        },
        "semantic_values": {},
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "profile.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return ISOProfile.load(path)


class ParserTests(unittest.TestCase):
    def make_message(self, extra=None):
        fields = {
            3: FieldValue("processing_code", "000000", "processing_code"),
            4: FieldValue("transaction_amount", "000000005000", "amount"),
        }
        fields.update(extra or {})
        return CanonicalMessage("test", "0100", fields)

    def test_binary_bitmap_roundtrip_with_secondary_and_llvar(self):
        profile = profile_for_test()
        parser = ISO8583Parser(profile)
        message = self.make_message({
            35: FieldValue("track_ii", "12345", "track_data"),
            70: FieldValue("network_code", "ABC"),
        })
        wire = parser.pack(message)
        parsed = parser.parse(wire)
        self.assertEqual(parsed.fields[35].value, "12345")
        self.assertEqual(parsed.fields[70].value, "ABC")
        self.assertEqual(parser.pack(parsed), wire)
        self.assertIsNotNone(parsed.secondary_bitmap)

    def test_ascii_hex_bitmap_roundtrip(self):
        profile = profile_for_test(bitmap_encoding="hex_ascii")
        parser = ISO8583Parser(profile)
        message = self.make_message()
        raw = parser.pack(message)
        self.assertEqual(parser.pack(parser.parse(raw)), raw)

    def test_bcd_numeric_field_override(self):
        profile = profile_for_test(field_encodings={"3": "bcd", "4": "bcd"})
        parser = ISO8583Parser(profile)
        message = self.make_message()
        self.assertEqual(parser.parse(parser.pack(message)).fields[4].value, "000000005000")

    def test_rejects_missing_required_field(self):
        parser = ISO8583Parser(profile_for_test())
        with self.assertRaises(ParseError):
            parser.pack(CanonicalMessage("test", "0100", {}))

    def test_rejects_mti_mismatch(self):
        parser = ISO8583Parser(profile_for_test())
        with self.assertRaises(ParseError):
            parser.parse(b"0200" + b"\x00" * 8)


class TokenizerTests(unittest.TestCase):
    def test_deterministic_tokens_and_lossless_ephemeral_detokenization(self):
        profile = profile_for_test()
        message = CanonicalMessage("test", "0100", {
            3: FieldValue("processing_code", "000000", "processing_code"),
            4: FieldValue("transaction_amount", "000000005000", "amount"),
            35: FieldValue("track_ii", "123456789", "track_data"),
        })
        tokenizer = ISO8583Tokenizer(profile, pseudonymization_key=b"test-only-key")
        first = tokenizer.tokenize(message)
        second = tokenizer.tokenize(message)
        self.assertEqual(first.tokens, second.tokens)
        self.assertNotIn("123456789", first.tokens)
        self.assertEqual(tokenizer.detokenize(first).to_dict(), message.to_dict())
        self.assertEqual(first.numeric_features["4"], 5000.0)
        self.assertIn("35", first.identifier_digests)

    def test_token_ids_are_stable(self):
        first = Vocabulary.for_profile(profile_for_test())
        second = Vocabulary.for_profile(profile_for_test())
        self.assertEqual(first.tokens, second.tokens)
        self.assertEqual(first.encode(["<BOS>", "<FIELD_4>"]), second.encode(["<BOS>", "<FIELD_4>"]))

    def test_ids_without_sidecar_are_not_reversible(self):
        tokenizer = ISO8583Tokenizer(profile_for_test())
        with self.assertRaises(ISO8583Error):
            tokenizer.decode([1])

    def test_transaction_sequence_has_boundaries_and_roundtrips_sidecar(self):
        profile = profile_for_test()
        parser = ISO8583Parser(profile)
        message = CanonicalMessage("test", "0100", {
            3: FieldValue("processing_code", "000000", "processing_code"),
            4: FieldValue("transaction_amount", "000000005000", "amount"),
        })
        tokenizer = ISO8583Tokenizer(profile)
        sequence = tokenize_sequence([(tokenizer, message), (tokenizer, message)])
        self.assertEqual(sequence.tokens[0], "<BOS_TRANSACTION_SEQUENCE>")
        self.assertEqual(sequence.tokens[-1], "<EOS_TRANSACTION_SEQUENCE>")
        self.assertEqual(len(detokenize_sequence(sequence)), 2)


class MappingImportTests(unittest.TestCase):
    def test_supplied_mapping_compiles_only_mapped_message_types(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            paths = compile_mapping(root / "mapping.txt", temp)
            loaded = {profile.mti: profile for profile in map(ISOProfile.load, paths)}
        self.assertIn("0100", loaded)
        self.assertIn("0200", loaded)
        self.assertNotIn("1200", loaded)
        self.assertIn(62, loaded["0200"].fields)
        self.assertTrue(loaded["0100"].fields[2].sensitive)


if __name__ == "__main__":
    unittest.main()
