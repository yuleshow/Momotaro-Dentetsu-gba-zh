import hashlib
import json
import os
from pathlib import Path
import struct
import unittest

from PIL import Image
from opencc import OpenCC

from build_traditional import GlyphRenderer, build, convert_traditional, encode_tiles, make_ips, reading, replace_labels
from extract_text import TEXT_START, TEXT_END, load_mapping, render, split_records
from inspect_font import read_rom
from map_font import FONT_BASE, GLYPH_SIZE, SOURCE_SHA256


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / os.environ.get("TRANSLATION_CANDIDATE", "build/Momotarō Dentetsu.gba")


def apply_literal_ips(source, patch):
    if patch[:5] != b"PATCH":
        raise ValueError("Invalid IPS header")
    output = bytearray(source)
    cursor = 5
    while patch[cursor:cursor + 3] != b"EOF":
        offset = int.from_bytes(patch[cursor:cursor + 3], "big")
        size = int.from_bytes(patch[cursor + 3:cursor + 5], "big")
        cursor += 5
        if not size or cursor + size > len(patch) - 3 or offset + size > len(output):
            raise ValueError("Invalid literal IPS record")
        output[offset:offset + size] = patch[cursor:cursor + size]
        cursor += size
    if cursor + 3 != len(patch):
        raise ValueError("Unexpected trailing IPS bytes")
    return bytes(output)


class TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = next((ROOT / "assets").glob("*.gba")).read_bytes()
        cls.target = CANDIDATE.read_bytes()
        cls.report = json.loads(CANDIDATE.with_suffix(".json").read_text())
        cls.mapping = load_mapping(
            [ROOT / "analysis/font-map-consolidated.json", ROOT / "analysis/original-font/vision-map.json"],
            [ROOT / "analysis/original-font/review.json", ROOT / "analysis/font-audit-01.json"],
        )
        font = cls.report["font"]
        fallback_info = font.get("fallback")
        fallback = GlyphRenderer(Path(fallback_info["path"]), fallback_info["face"], fallback_info["size"]) if fallback_info else None
        cls.renderer = GlyphRenderer(Path(font["path"]), font["face"], font["size"], font.get("baseline_y"), fallback)

    def test_all_character_font_coverage(self):
        if not self.report.get("replace_all_mapped_glyphs"):
            self.skipTest("Candidate uses conversion-only font replacement")
        expected = {code for code, record in self.mapping.items() if reading(record, self.report["allow_unverified_ocr"]) is not None}
        changes = self.report["font_changes"]
        self.assertEqual({int(change["code"], 16) for change in changes}, expected)
        for change in changes:
            self.assertEqual(change["source"], reading(self.mapping[int(change["code"], 16)], self.report["allow_unverified_ocr"]))
            offset = change["offset"]
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(change["target"]))
        self.assertTrue(any(change["source"] == change["target"] == "A" for change in changes))
        self.assertTrue(any(change["source"] == change["target"] == "あ" for change in changes))
        self.assertTrue(any(change["source"] == change["target"] == "的" for change in changes))
        parenthesis = next(change for change in changes if change["code"] == "000D")
        self.assertEqual((parenthesis["source"], parenthesis["target"]), (")", ")"))

    def test_parenthesis_mapping(self):
        self.assertEqual(reading(self.mapping[0x000D], False), ")")
        self.assertEqual(reading(self.mapping[0x0014], True), "0")
        self.assertEqual(render([0x000C, 0x0099, 0x00AD, 0x009E, 0x000D, 0x0014], self.mapping, True), "(ゆざわ)0")

    def test_punctuation_mapping(self):
        punctuation = {0x0006: '"', 0x0008: "$", 0x000B: "'", 0x000E: "*", 0x000F: "+", 0x0012: "."}
        for code, character in punctuation.items():
            with self.subTest(code=f"{code:04X}"):
                self.assertEqual(reading(self.mapping[code], False), character)
        self.assertEqual(render(list(punctuation), self.mapping), "\"$'*+.")

    def test_traditional_conversion_policy(self):
        converter = OpenCC("s2t")
        for source, target in {"着": "著", "看着": "看著", "等着": "等著", "着陆": "著陸", "到着": "到著", "著作": "著作", "渋": "澀", "渋谷": "澀谷", "谷底": "谷底", "谷仓": "穀倉", "梅": "梅", "迎": "迎", "阎魔": "閻魔", "閻魔": "閻魔", "阎王": "閻王"}.items():
            with self.subTest(source=source):
                self.assertEqual(convert_traditional(source, converter), target)

    def test_user_confirmed_original_glyphs(self):
        for code, character in {0x001F: "閻", 0x0020: "魔", 0x0289: "渋", 0x028A: "谷", 0x04EE: "梅", 0x067C: "迎"}.items():
            with self.subTest(code=f"{code:04X}"):
                self.assertEqual(reading(self.mapping[code], False), character)
                self.assertTrue(self.mapping[code]["review"]["user_confirmed"])
        self.assertEqual(render([0x0289, 0x04EE, 0x067C], self.mapping), "渋梅迎")
        self.assertEqual(render([0x0289, 0x028A], self.mapping), "渋谷")
        self.assertEqual(render([0x001F, 0x0020], self.mapping), "閻魔")

    def test_resolved_used_glyphs_in_rom(self):
        self.assertEqual(self.report["unmapped_used_codes"], [])
        changes = {change["code"]: change for change in self.report["font_changes"]}
        for code, character in {"001F": "閻", "0020": "魔", "0289": "澀", "028A": "谷", "04EE": "梅", "067C": "迎"}.items():
            with self.subTest(code=code):
                change = changes[code]
                self.assertEqual(change["target"], character)
                self.assertTrue(change["source_verified"])
                offset = change["offset"]
                self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(character))
        grain_contexts = [change for change in self.report["context_changes"] if change["source"] == "谷" and change["target"] == "穀"]
        self.assertEqual(len(grain_contexts), 3)
        for change in grain_contexts:
            self.assertIn("谷仓", change["context_source"])
            self.assertIn("穀倉", change["context_target"])
            code = int(change["new_code"], 16)
            self.assertEqual(struct.unpack_from("<H", self.target, change["offset"])[0], code)
            offset = FONT_BASE + code * GLYPH_SIZE
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("穀"))

    def test_character_override_in_rom(self):
        self.assertEqual(self.report["character_overrides"], {"着": "著", "渋": "澀"})
        changes = [change for change in self.report["font_changes"] if change["source"] == "着"]
        self.assertTrue(changes)
        for change in changes:
            self.assertEqual(change["target"], "著")
            offset = change["offset"]
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("著"))
        for group, field in (("font_changes", "target"), ("context_changes", "context_target"), ("allocated_glyphs", "character")):
            self.assertTrue(all(character not in change[field] for change in self.report[group] for character in self.report["character_overrides"]))

    def test_silver_baseline_and_fallback(self):
        if Path(self.report["font"]["path"]).name != "Silver.ttf":
            self.skipTest("Candidate does not use Silver")
        self.assertEqual(self.renderer.size, 19)
        self.assertEqual(self.renderer.encode(" "), b"\x11" * GLYPH_SIZE)
        encoded = self.renderer.encode("。")
        rows = [index // 12 for index in range(192) if (encoded[index // 2] >> (4 * (index % 2))) & 15 == 3]
        self.assertGreaterEqual(min(rows), 10)
        self.assertIsNotNone(self.renderer.fallback)
        for record in self.report["font_fallbacks"]:
            self.assertEqual(self.renderer.encode(record["character"]), self.renderer.fallback.encode(record["character"]))

    def test_original_roms_unchanged(self):
        self.assertEqual(hashlib.sha256(self.source).hexdigest(), SOURCE_SHA256)
        japanese = read_rom(next((ROOT / "assets").glob("*.zip")))
        self.assertEqual(hashlib.sha256(japanese).hexdigest(), "f5853a1d314d9f534073fddf41bda7a4648ddf777860f3c309223bd45e563c86")

    def test_review_precedence_and_unknowns(self):
        for code, character in {0: " ", 0x60: "罗", 0x130: "的", 0x221: "赤", 0x388F: "钏", 0x3927: "憾", 0x3CDA: "宍", 0x3D58: "齊"}.items():
            self.assertEqual(reading(self.mapping[code], False), character)
        for code in (0x390C, 0x3D22, 0x3D23, 0x3D24, 0x3D27, 0x3D34, 0x3D35):
            self.assertIsNone(reading(self.mapping[code], True))
            self.assertEqual(render([code], self.mapping, True), f"[{code:04X}]")

    def test_control_words_and_offsets(self):
        data = struct.pack("<9H", 0xFFFF, 0x3CDA, 0x8000, 0x8100, 0x8300, 0xFFFF, 0xFFFF, 5, 0xFFFF)
        records = split_records(data, 100)
        self.assertEqual([record["offset"] for record in records], [102, 114])
        self.assertEqual(render(records[0]["words"], self.mapping), "宍\n{ARG:0}{STYLE_1}")
        self.assertTrue(all(record["terminated"] for record in records))
        self.assertFalse(split_records(b"\x05\x00", 0)[0]["terminated"])
        with self.assertRaises(ValueError):
            split_records(b"\x00", 0)

    def test_opponent_sprite_labels(self):
        manifest = json.loads((ROOT / "analysis/opponent-graphics-source/label-locations.json").read_text())
        replacements = {label["source"]: label["target"] for label in manifest["labels"]}
        for source, target in {"马": "馬", "饿": "餓", "风": "風", "罗": "羅", "阎魔": "閻魔"}.items():
            self.assertEqual(replacements[source], target)
        output = bytearray(self.source)
        allowed = bytearray(len(self.source))
        changes = replace_labels(self.source, output, allowed, self.renderer, [manifest])
        self.assertEqual(len(changes), 12)
        for change in changes:
            offset, size = change["offset"], change["size"]
            self.assertNotEqual(output[offset:offset + size], self.source[offset:offset + size])
            self.assertEqual(self.target[offset:offset + size], output[offset:offset + size])
            self.assertEqual(self.source.find(self.source[offset:offset + size]), offset)
            self.assertEqual(self.source.find(self.source[offset:offset + size], offset + 1), -1)
            indices = {nibble for value in output[offset:offset + size] for nibble in (value & 15, value >> 4)}
            self.assertEqual(indices, {0, 1, 2})
        self.assertTrue(all(before == after or allowed[offset] for offset, (before, after) in enumerate(zip(self.source, output))))

    def test_font_and_sprite_formats(self):
        for character in "繁體發髮幹乾齊鯱宍":
            encoded = self.renderer.encode(character)
            self.assertEqual(len(encoded), GLYPH_SIZE)
            values = {nibble for value in encoded for nibble in (value & 15, value >> 4)}
            self.assertLessEqual(values, {1, 2, 3})
            self.assertIn(3, values)
        image = Image.new("L", (32, 16))
        for pixel_y in range(16):
            for pixel_x in range(32):
                image.putpixel((pixel_x, pixel_y), (pixel_x + 3 * pixel_y) % 16)
        encoded = encode_tiles(image)
        for pixel_y in range(16):
            for pixel_x in range(32):
                position = ((pixel_y // 8) * 4 + pixel_x // 8) * 64 + (pixel_y % 8) * 8 + pixel_x % 8
                actual = (encoded[position // 2] >> (4 * (position % 2))) & 15
                self.assertEqual(actual, image.getpixel((pixel_x, pixel_y)))

    def test_wrong_rom_and_stale_mapping_rejected(self):
        with self.assertRaises(ValueError):
            build(b"wrong source", {}, self.renderer)
        stale = {0: {**self.mapping[0], "offset": "0x00000000"}}
        with self.assertRaises(ValueError):
            build(self.source, stale, self.renderer)

    def test_ips_record_limits_and_reserved_offset(self):
        source = bytes(0x454F48)
        target = bytearray(source)
        target[5:70005] = b"\xff" * 70000
        target[0x454F46] = 1
        self.assertEqual(apply_literal_ips(source, make_ips(source, target)), bytes(target))

    def test_final_patch_round_trip(self):
        patch = CANDIDATE.with_suffix(".ips").read_bytes()
        self.assertEqual(apply_literal_ips(self.source, patch), self.target)
        self.assertEqual(hashlib.sha256(self.target).hexdigest(), self.report["output_sha256"])

    def test_only_declared_ranges_change(self):
        self.assertEqual(len(self.source), len(self.target))
        self.assertEqual(self.source[:0xC0], self.target[:0xC0])
        self.assertEqual(self.source[0xFE0000:], self.target[0xFE0000:])
        allowed = bytearray(len(self.source))
        for group, size in (("font_changes", GLYPH_SIZE), ("context_changes", 2), ("allocated_glyphs", GLYPH_SIZE)):
            for change in self.report[group]:
                offset = change["offset"]
                allowed[offset:offset + size] = b"\x01" * size
        for change in self.report["graphics_changes"]:
            offset, size = change["offset"], change["size"]
            allowed[offset:offset + size] = b"\x01" * size
            self.assertEqual(hashlib.sha256(self.source[offset:offset + size]).hexdigest(), change["source_sha256"])
        self.assertTrue(all(before == after or allowed[offset] for offset, (before, after) in enumerate(zip(self.source, self.target))))
        for offset in range(TEXT_START, TEXT_END, 2):
            if int.from_bytes(self.source[offset:offset + 2], "little") >= 0x8000:
                self.assertEqual(self.source[offset:offset + 2], self.target[offset:offset + 2])
        for glyph in self.report["allocated_glyphs"]:
            offset = FONT_BASE + int(glyph["code"], 16) * GLYPH_SIZE
            self.assertEqual(offset, glyph["offset"])
            self.assertEqual(self.source[offset:offset + GLYPH_SIZE], b"\xff" * GLYPH_SIZE)


if __name__ == "__main__":
    unittest.main()