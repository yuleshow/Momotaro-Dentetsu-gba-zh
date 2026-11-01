import hashlib
import json
import os
from pathlib import Path
import struct
import unittest

from PIL import Image
from opencc import OpenCC

from build_traditional import CURRENCY_FONT_SLOTS, RED_CURRENCY_FONT_SLOTS, CURRENCY_PIXEL_GLYPHS, DEFAULT_DECK_NAME, DECK_NAME_HOOK_OFFSET, DECK_NAME_ROUTINE_OFFSET, DECK_NAME_ROUTINE, PHRASE_OVERRIDES, SILVER_19_PIXEL_GLYPHS, SPEED_LABEL_FIXES, GlyphRenderer, build, convert_traditional, encode_mask, encode_tiles, make_ips, reading, replace_default_deck_name, replace_labels
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

    def test_extreme_glyph_mapping_and_rom(self):
        self.assertEqual(reading(self.mapping[0x3866], False), "极")
        words = [0x01F8, 0x37E9, 0x37A1, 0x0000, 0x3866, 0x01F9, 0x0130, 0x3786, 0x0005, 0x01FB, 0x8000]
        source_text = render(words, self.mapping, True)
        self.assertEqual(source_text, "「这是 极好的卡！」\n")
        self.assertEqual(convert_traditional(source_text, OpenCC("s2t")), "「這是 極好的卡！」\n")
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        self.assertEqual(sum(record["words"].count(0x3866) for record in records), 44)
        change = next(change for change in self.report["font_changes"] if change["code"] == "3866")
        self.assertEqual((change["source"], change["target"]), ("极", "極"))
        self.assertTrue(change["source_verified"])
        offset = change["offset"]
        self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("極"))
        self.assertNotEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("板"))

    def test_soup_glyph_mapping_and_rom(self):
        self.assertEqual(reading(self.mapping[0x3855], False), "汤")
        words = [0x0126, 0x0181, 0x05BC, 0x3855, 0x0333, 0x0005]
        source_text = render(words, self.mapping, True)
        self.assertEqual(source_text, "全都泡汤了！")
        self.assertEqual(convert_traditional(source_text, OpenCC("s2t")), "全都泡湯了！")
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        self.assertEqual(sum(record["words"].count(0x3855) for record in records), 35)
        for record in records:
            if record["offset"] in (0xDD02F2, 0xDD7EEC):
                self.assertIn("全都泡汤了！", render(record["words"], self.mapping, True))
        change = next(change for change in self.report["font_changes"] if change["code"] == "3855")
        self.assertEqual((change["source"], change["target"]), ("汤", "湯"))
        self.assertTrue(change["source_verified"])
        offset = change["offset"]
        self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("湯"))
        self.assertNotEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("涵"))

    def test_traditional_conversion_policy(self):
        converter = OpenCC("s2t")
        for source, target in {"着": "著", "看着": "看著", "等着": "等著", "着陆": "著陸", "到着": "到著", "著作": "著作", "渋": "澀", "渋谷": "澀谷", "谷底": "谷底", "谷仓": "穀倉", "梅": "梅", "迎": "迎", "阎魔": "閻魔", "閻魔": "閻魔", "阎王": "閻王"}.items():
            with self.subTest(source=source):
                self.assertEqual(convert_traditional(source, converter), target)
        self.assertEqual(self.report["phrase_overrides"], PHRASE_OVERRIDES)
        for source, target in {
            "一夜干鱿鱼店": "一夜乾魷魚店",
            "手工素面店": "手工素麵店",
            "鲷素面店": "鯛素麵店",
            "流水素面列车": "流水素麵列車",
            "干这种事": "幹這種事",
            "路面电车": "路面電車",
            "表面": "表面",
            "面片火锅店": "麵片火鍋店",
            "拉麺 麪包 麵條": "拉麵 麵包 麵條",
            "面与汤 卷曲面 加面(替玉) 强棒面 冬粉面": "麵與湯 捲曲麵 加麵(替玉) 強棒麵 冬粉麵",
            "面與湯 捲曲面 強棒面": "麵與湯 捲曲麵 強棒麵",
            "画面 路面 见面 面子 面孔 局面 仮面 貧面魚": "畫面 路面 見面 面子 面孔 局面 仮面 貧面魚",
            "萝ト": "蘿蔔",
            "萝卜": "蘿蔔",
            "蘿卜": "蘿蔔",
            "蘿蔔": "蘿蔔",
            "菠萝园": "菠蘿園",
            "卜卦": "卜卦",
            "ト": "ト",
        }.items():
            with self.subTest(source=source):
                self.assertEqual(convert_traditional(source, converter), target)

    def test_radish_contexts_and_rom(self):
        converter = OpenCC("s2t")
        effective = {code: convert_traditional(reading(record, True), converter)
                     for code, record in self.mapping.items() if reading(record, True)}
        effective.update({int(glyph["code"], 16): glyph["character"] for glyph in self.report["allocated_glyphs"]})
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        expected_records = {
            0xDB5EF4: "三浦白蘿蔔田\n",
            0xDB651A: "越前蘿蔔泥蕎麵店\n",
            0xDB656E: "伊勢醃蘿蔔店\n",
            0xDCADC8: "{STYLE_0}「配著醃蘿蔔\n 喫的味道令人不厭！」\n",
            0xDD30C8: "{STYLE_1}「配著醃蘿蔔\n 喫的味道令人不厭！」\n",
        }
        radish_records = [record for record in records if "萝ト" in render(record["words"], self.mapping, True)]
        self.assertEqual({record["offset"] for record in radish_records}, set(expected_records))
        target_mapping = {code: {"verified": True, "character": character} for code, character in effective.items()}
        for record in radish_records:
            with self.subTest(offset=hex(record["offset"])):
                expected = expected_records[record["offset"]]
                self.assertEqual(convert_traditional(render(record["words"], self.mapping, True), converter), expected)
                words = struct.unpack_from(f"<{len(record['words'])}H", self.target, record["offset"])
                self.assertEqual(render(words, target_mapping, True), expected)
        glyph = next(glyph for glyph in self.report["allocated_glyphs"] if glyph["character"] == "蔔")
        offset = glyph["offset"]
        self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("蔔"))

    def test_all_face_and_noodle_contexts(self):
        food_face_records = {
            0xDB4752, 0xDB50DC, 0xDB53AA, 0xDB54D0, 0xDB56C4, 0xDB56D2, 0xDB56DE,
            0xDB56EE, 0xDB5782, 0xDB57F2, 0xDB5936, 0xDB5E80, 0xDB5F3C, 0xDB60D8,
            0xDB613A, 0xDB651A, 0xDB66FE, 0xDB68CC, 0xDB6924, 0xDB6AB4, 0xDB6EFE,
            0xDB6FCC, 0xDB71A8, 0xDB72D4, 0xDB731E, 0xDC26C2, 0xDC2708, 0xDC31DE,
            0xDC36B6, 0xDCA986, 0xDCA9DC, 0xDCA9FA, 0xDCAA44, 0xDCAA54, 0xDCAAAC,
            0xDCAABC, 0xDCAB12, 0xDCAB62, 0xDCABA0, 0xDCABB0, 0xDCAC16, 0xDCAC28,
            0xDCAC80, 0xDCACEC, 0xDCAD30, 0xDCADB6, 0xDCAE4A, 0xDCCA94, 0xDCE6AA,
            0xDCF5C8, 0xDCFF02, 0xDD2C94, 0xDD2CEA, 0xDD2D08, 0xDD2D52, 0xDD2D62,
            0xDD2DBA, 0xDD2DCA, 0xDD2E20, 0xDD2E70, 0xDD2EA0, 0xDD2EB0, 0xDD2F16,
            0xDD2F28, 0xDD2F80, 0xDD2FEC, 0xDD3030, 0xDD30B6, 0xDD998E, 0xDD9FB4,
            0xDDE4FE,
        }
        effective = {int(change["code"], 16): {"verified": True, "character": change["target"]}
                     for change in self.report["font_changes"]}
        effective.update({int(glyph["code"], 16): {"verified": True, "character": glyph["character"]}
                          for glyph in self.report["allocated_glyphs"]})
        self.assertEqual(reading(self.mapping[0x03BD], True), "面")
        self.assertEqual(reading(self.mapping[0x04CB], True), "麺")
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        counts = {"面": 0, "麵": 0}
        source_counts = {0x03BD: 0, 0x04CB: 0}
        audited = {}
        observed_food_face_records = set()
        glyphs = {character: self.renderer.encode(character) for character in counts}
        for record in records:
            if not any(code in source_counts for code in record["words"]):
                continue
            words = struct.unpack_from(f"<{len(record['words'])}H", self.target, record["offset"])
            audited[record["offset"]] = render(words, effective)
            for index, code in enumerate(record["words"]):
                if code not in source_counts:
                    continue
                expected = "麵" if code == 0x04CB or record["offset"] in food_face_records else "面"
                with self.subTest(offset=hex(record["offset"] + index * 2)):
                    self.assertEqual(render([words[index]], effective), expected)
                    offset = FONT_BASE + words[index] * GLYPH_SIZE
                    self.assertEqual(self.target[offset:offset + GLYPH_SIZE], glyphs[expected])
                counts[expected] += 1
                source_counts[code] += 1
                if code == 0x03BD and expected == "麵":
                    observed_food_face_records.add(record["offset"])
        self.assertEqual(observed_food_face_records, food_face_records)
        self.assertEqual(source_counts, {0x03BD: 151, 0x04CB: 0})
        self.assertEqual(counts, {"面": 76, "麵": 75})
        self.assertEqual(len(audited), 147)
        self.assertFalse(any(character in text for text in audited.values() for character in "麪麺"))
        for offset, fragment in {
            0xDC2708: "不是炸醬麵 是じやじや麵！",
            0xDC36B6: "雞骨高湯配冬粉麵！",
            0xDCAA54: "麵與湯很搭！", 0xDD2D62: "麵與湯很搭！",
            0xDCAC28: "獨特的捲曲麵", 0xDD2F28: "獨特的捲曲麵",
            0xDCACEC: "加麵(替玉)的制度", 0xDD2FEC: "加麵(替玉)的制度",
            0xDCE6AA: "長崎強棒麵！",
        }.items():
            self.assertIn(fragment, audited[offset])

    def test_potato_question_and_noodle_screenshots(self):
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        changes = {int(change["code"], 16): change for change in self.report["font_changes"]}
        for code, source, target, count in ((0x3AD5, "薯", "薯", 5), (0x39A5, "问", "問", 13)):
            with self.subTest(code=f"{code:04X}"):
                self.assertEqual(reading(self.mapping[code], False), source)
                self.assertEqual(sum(record["words"].count(code) for record in records), count)
                self.assertEqual((changes[code]["source"], changes[code]["target"]), (source, target))
                self.assertTrue(changes[code]["source_verified"])
                offset = changes[code]["offset"]
                self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(target))
        converter = OpenCC("s2t")
        for offset, expected in {
            0xDB513E: "馬鈴薯田\n",
            0xDB5472: "福薯店\n",
            0xDB56C4: "麵片火鍋店\n",
            0xDBE398: "音效顧問\n",
            0xDA9626: "「{ARG:0}先生\n 抵達目的地\n 只是時間問題呀！」\n",
        }.items():
            record = next(record for record in records if record["offset"] == offset)
            self.assertEqual(convert_traditional(render(record["words"], self.mapping, True), converter), expected)
        self.assertEqual(convert_traditional(render([0x37F2, 0x39A5, 0x39A6], self.mapping, True), converter), "間問題")
        self.assertEqual(convert_traditional("看着著作", converter), "看著著作")
        noodle_change = next(change for change in self.report["context_changes"] if change["offset"] == 0xDB56C4)
        self.assertEqual((noodle_change["source"], noodle_change["target"]), ("面", "麵"))
        code = int(noodle_change["new_code"], 16)
        self.assertEqual(struct.unpack_from("<H", self.target, 0xDB56C4)[0], code)
        offset = FONT_BASE + code * GLYPH_SIZE
        self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("麵"))

    def test_ma_particle_and_genuine_ma(self):
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        self.assertEqual(reading(self.mapping[0x38E9], False), "嘛")
        self.assertEqual(reading(self.mapping[0x056B], True), "麻")
        self.assertEqual(sum(record["words"].count(0x38E9) for record in records), 19)
        for code, character in ((0x38E9, "嘛"), (0x056B, "麻")):
            change = next(change for change in self.report["font_changes"] if int(change["code"], 16) == code)
            self.assertEqual((change["source"], change["target"]), (character, character))
            offset = FONT_BASE + code * GLYPH_SIZE
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(character))
            for record in records:
                for index, word in enumerate(record["words"]):
                    if word == code:
                        self.assertEqual(struct.unpack_from("<H", self.target, record["offset"] + index * 2)[0], code)
        converter = OpenCC("s2t")
        for source, expected in {
            "就是嘛！": "就是嘛！",
            "干嘛呀你！": "幹嘛呀你！",
            "还挺能干的嘛！": "還挺能幹的嘛！",
            "麻烦 麻雀 麻糬 稲井田麻由": "麻煩 麻雀 麻糬 稲井田麻由",
        }.items():
            self.assertEqual(convert_traditional(source, converter), expected)

    def test_senryobako_and_genuine_shao(self):
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        self.assertEqual(reading(self.mapping[0x0364], False), "箱")
        self.assertEqual(reading(self.mapping[0x3943], True), "稍")
        for code, character in ((0x0364, "箱"), (0x3943, "稍")):
            offset = FONT_BASE + code * GLYPH_SIZE
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(character))
            for record in records:
                for index, word in enumerate(record["words"]):
                    if word == code:
                        self.assertEqual(struct.unpack_from("<H", self.target, record["offset"] + index * 2)[0], code)
        card = next(record for record in records if record["offset"] == 0xDB0590)
        self.assertEqual(convert_traditional(render(card["words"], self.mapping, True), OpenCC("s2t")), "千兩箱卡\n")

    def test_zuo_classifier_and_genuine_rate(self):
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        self.assertEqual(reading(self.mapping[0x0640], False), "座")
        self.assertEqual(reading(self.mapping[0x038D], True), "率")
        self.assertEqual(sum(record["words"].count(0x0640) for record in records), 19)
        self.assertEqual(sum(record["words"].count(0x038D) for record in records), 42)
        for code, character in ((0x0640, "座"), (0x038D, "率")):
            offset = FONT_BASE + code * GLYPH_SIZE
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(character))
            for record in records:
                for index, word in enumerate(record["words"]):
                    if word == code:
                        self.assertEqual(struct.unpack_from("<H", self.target, record["offset"] + index * 2)[0], code)
        converter = OpenCC("s2t")
        for offset, expected in {
            0xDC789E: "{STYLE_2}「在世界遺產宮島\n 覆蓋整座島的山櫻\n 美得格外動人！」\n",
            0xDC79EE: "{STYLE_2}「京都整座城鎮\n 都是賞櫻名所！」\n",
            0xDF2EE8: "「再來築一座城吧！」\n",
        }.items():
            record = next(record for record in records if record["offset"] == offset)
            self.assertEqual(convert_traditional(render(record["words"], self.mapping, True), converter), expected)

    def test_all_gan_contexts_and_correct_gan_preservation(self):
        dry_records = {
            0xD94432, 0xD9B85A, 0xDB57AE, 0xDB596C, 0xDB5FF0, 0xDB6004,
            0xDB623E, 0xDB68B2, 0xDBB430, 0xDC260A, 0xDCDE60, 0xDD8C56,
            0xDDFA48, 0xDE3E6E,
        }
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        output_characters = {int(glyph["code"], 16): glyph["target"] for glyph in self.report["font_changes"]}
        output_characters.update({int(glyph["code"], 16): glyph["character"] for glyph in self.report["allocated_glyphs"]})
        count = 0
        for record in records:
            for index, word in enumerate(record["words"]):
                if word != 0x04FD:
                    continue
                expected = "乾" if record["offset"] in dry_records else "幹"
                offset = record["offset"] + index * 2
                actual_code = struct.unpack_from("<H", self.target, offset)[0]
                self.assertEqual(output_characters[actual_code], expected, f"{offset:08X}")
                glyph_offset = FONT_BASE + actual_code * GLYPH_SIZE
                self.assertEqual(self.target[glyph_offset:glyph_offset + GLYPH_SIZE], self.renderer.encode(expected))
                count += 1
        self.assertEqual(count, 40)
        converter = OpenCC("s2t")
        for source, expected in {
            "干涉 干扰 干预": "干涉 干擾 干預",
            "干嘛 能干 干劲 新干线": "幹嘛 能幹 幹勁 新幹線",
            "干脆 干净 半干 饼干 梅干 葡萄干 干杯": "乾脆 乾淨 半乾 餅乾 梅乾 葡萄乾 乾杯",
        }.items():
            self.assertEqual(convert_traditional(source, converter), expected)

    def test_second_screenshot_mappings_and_contexts(self):
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        for code, character, count in (
            (0x3830, "扔", 18), (0x02AF, "敷", 5),
            (0x39FA, "毫", 32), (0x3AEC, "涮", 1), (0x3B4A, "鹮", 2),
        ):
            with self.subTest(code=f"{code:04X}"):
                self.assertEqual(reading(self.mapping[code], False), character)
                self.assertEqual(sum(record["words"].count(code) for record in records), count)
        self.assertEqual(render([0x3ABB, 0x3ACB, 0x3B45], self.mapping, True), "护童童")
        converter = OpenCC("s2t")
        for offset, expected in {
            0xD968E8: "倉敷卡\n",
            0xDB7FD4: "「咕嘿嘿！ 是{ARG:0}呢！\n 就把{ARG:1}\n 扔掉吧！ 高興吧！」\n",
            0xDC4E52: "「毫無意義地試著笑了！\n 挺有趣的嘛！」\n",
            0xDB50A0: "章魚涮鍋店\n",
            0xDB5FC8: "朱䴉周邊店\n",
            0xDB5FF0: "一夜乾魷魚店\n",
            0xDB6004: "一夜乾魷魚店\n",
            0xDB6924: "手工素麵店\n",
        }.items():
            record = next(record for record in records if record["offset"] == offset)
            self.assertEqual(convert_traditional(render(record["words"], self.mapping, True), converter), expected)
        effective = {code: convert_traditional(reading(record, True), converter)
                     for code, record in self.mapping.items() if reading(record, True)}
        effective.update({int(glyph["code"], 16): glyph["character"] for glyph in self.report["allocated_glyphs"]})
        for start, length, expected in (
            (0xDB5FF0, 6, "一夜乾魷魚店"),
            (0xDB6004, 6, "一夜乾魷魚店"),
            (0xDB6924, 5, "手工素麵店"),
        ):
            words = struct.unpack_from(f"<{length}H", self.target, start)
            self.assertEqual("".join(effective[word] for word in words), expected)

    def test_overcome_and_genuine_stock_glyphs(self):
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        for code, character, count in ((0x0541, "服", 22), (0x3A94, "股", 11)):
            self.assertEqual(reading(self.mapping[code], True), character)
            self.assertEqual(sum(record["words"].count(code) for record in records), count)
            offset = FONT_BASE + code * GLYPH_SIZE
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(character))
        self.assertEqual(reading(self.mapping[0x0541], False), "服")
        record = next(record for record in records if record["offset"] == 0xDDDED0)
        text = convert_traditional(render(record["words"], self.mapping, True), OpenCC("s2t"))
        self.assertIn("克服了", text)
        self.assertNotIn("克股", text)
        for offset, expected in ((0xD96330, "舒服"), (0xD9E9CE, "服務"), (0xDC924A, "說服"),
                                 (0xDB9BAC, "佩服"), (0xDE858A, "征服"), (0xDCA774, "股票"),
                                 (0xD99D5A, "一股")):
            record = next(record for record in records if record["offset"] == offset)
            self.assertIn(expected, convert_traditional(render(record["words"], self.mapping, True), OpenCC("s2t")))

    def test_creature_count_classifier(self):
        converter = OpenCC("s2t")
        for source, target in (("窮神1只", "窮神1隻"), ("总共13只", "總共13隻"),
                               ("3只豆鬼", "3隻豆鬼"), ("几只恶魔", "幾隻惡魔"),
                               ("只有一只", "只有一隻"), ("只要", "只要"), ("只能", "只能"),
                               ("说不定是只有当地人", "說不定是只有當地人"), ("只好在原地", "只好在原地")):
            self.assertEqual(convert_traditional(source, converter), target)
        changes = {change["offset"]: change for change in self.report["context_changes"]}
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        count_records = {0xD98386, 0xD983B6, 0xD98572, 0xD98694, 0xD9884C, 0xD989BC,
                         0xD9E86C, 0xD9E89C, 0xD9E8D0, 0xD9E8F4, 0xDA2D70, 0xDA2F4E,
                         0xDA3EA0, 0xDA407E, 0xDB089C, 0xDB846C, 0xDB848C, 0xDB84A6,
                         0xDB850E, 0xDDCD3A, 0xDE6EDE}
        count = 0
        for record in records:
            for index, word in enumerate(record["words"]):
                if word != 0x3864:
                    continue
                offset = record["offset"] + index * 2
                is_classifier = record["offset"] in count_records
                # 只能派...隻惡魔 contains both the adverb and the classifier.
                if record["offset"] in {0xDA2F4E, 0xDA407E}:
                    is_classifier = index > 0 and record["words"][index - 1] == 0x8100
                if is_classifier:
                    self.assertEqual(changes[offset]["target"], "隻")
                    count += 1
                else:
                    self.assertNotIn(offset, changes)
                    self.assertEqual(struct.unpack_from("<H", self.target, offset)[0], word)
        self.assertEqual(count, 24)

    def test_narrow_currency_font(self):
        changes = self.report["currency_font_changes"]
        self.assertEqual([(c["offset"], c["target"]) for c in changes],
                         [(offset, target) for offset, _, target, _ in CURRENCY_FONT_SLOTS + RED_CURRENCY_FONT_SLOTS])
        self.assertEqual(self.report["summary"]["currency_font_slots_replaced"], 6)
        for change in changes:
            offset = change["offset"]
            self.assertEqual(change["size"], 64)
            self.assertEqual(hashlib.sha256(self.source[offset:offset + 64]).hexdigest(), change["source_sha256"])
            bitmap = CURRENCY_PIXEL_GLYPHS[change["target"]]
            self.assertEqual(len(bitmap), 16)
            self.assertTrue(all(len(row) == 8 and set(row) <= {".", "#"} for row in bitmap))
            mask = Image.new("L", (8, 16))
            mask.putdata([255 if pixel == "#" else 0 for row in bitmap for pixel in row])
            encoded = encode_mask(mask)
            red = offset in {slot[0] for slot in RED_CURRENCY_FONT_SLOTS}
            self.assertEqual(change["palette"], "red" if red else "black")
            if red:
                encoded = bytes(value + 0x33 for value in encoded)
            self.assertEqual(self.target[offset:offset + 64], encoded)
            self.assertEqual(hashlib.sha256(encoded).hexdigest(), change["output_sha256"])
            self.assertNotEqual(encoded, self.source[offset:offset + 64])
        # Keep all narrow digits, minus and 兆 exactly as shipped.
        self.assertEqual(self.source[0xE43754:0xE43A94], self.target[0xE43754:0xE43A94])
        self.assertEqual(self.source[0xE43330:0xE43670], self.target[0xE43330:0xE43670])

    def test_red_currency_matches_black_with_its_own_palette(self):
        for black, red in zip(CURRENCY_FONT_SLOTS, RED_CURRENCY_FONT_SLOTS):
            black_bytes = self.target[black[0]:black[0] + 64]
            red_bytes = self.target[red[0]:red[0] + 64]
            self.assertEqual(red_bytes, bytes(value + 0x33 for value in black_bytes))
            self.assertEqual({nibble for value in red_bytes for nibble in (value & 15, value >> 4)}, {4, 5, 6})

    def test_all_context_rewrites_resolve_to_rendered_glyphs(self):
        allocations = {int(glyph["code"], 16): glyph for glyph in self.report["allocated_glyphs"]}
        for change in self.report["context_changes"]:
            with self.subTest(offset=f'{change["offset"]:08X}'):
                code = int(change["new_code"], 16)
                self.assertEqual(struct.unpack_from("<H", self.target, change["offset"])[0], code)
                self.assertEqual(allocations[code]["character"], change["target"])
                offset = allocations[code]["offset"]
                self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(change["target"]))

    def test_mochi_glyph_legibility_and_rom(self):
        self.assertEqual(reading(self.mapping[0x3B1C], False), "糬")
        for bitmap in SILVER_19_PIXEL_GLYPHS.values():
            self.assertEqual(len(bitmap), 16)
            self.assertTrue(all(len(row) == 12 and set(row) <= {".", "#"} for row in bitmap))
        self.assertEqual(self.report["font"]["pixel_glyph_overrides"], sorted(SILVER_19_PIXEL_GLYPHS))
        self.assertNotIn("糬", {entry["character"] for entry in self.report["font_fallbacks"]})
        for size, baseline in ((12, None), (19, 0)):
            renderer = GlyphRenderer(self.renderer.path, size=size, baseline_y=baseline)
            with self.assertRaisesRegex(ValueError, "Font lacks target glyph"):
                renderer.encode_primary("糬")
        pixels = []
        for value in self.renderer.encode("糬"):
            pixels.extend((value & 15, value >> 4))
        rows = ["".join("#" if pixel == 3 else "." for pixel in pixels[y * 12:(y + 1) * 12]) for y in range(16)]
        self.assertEqual(rows[1][6:], "######")
        self.assertEqual(rows[2][6:], "#.##.#")
        self.assertEqual(rows[3][6:], "######")
        self.assertEqual(rows[10][8:], "#..#")
        self.assertEqual(rows[11][8:], "####")
        self.assertEqual(rows[12][8:], "#..#")
        self.assertEqual(rows[13][8:], "####")
        change = next(change for change in self.report["font_changes"] if change["code"] == "3B1C")
        self.assertEqual((change["source"], change["target"]), ("糬", "糬"))
        offset = change["offset"]
        self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("糬"))
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        self.assertEqual(sum(record["words"].count(0x3B1C) for record in records), 11)
        record = next(record for record in records if record["offset"] == 0xDB65A0)
        self.assertEqual(render(record["words"], self.mapping, True), "福福麻糬店\n")

    def test_v32_reported_text_and_glyphs(self):
        expected = {
            0x067D: ("副", "副", 5),
            0x3B9D: ("寞", "寞", 3),
            0x38C6: ("虑", "慮", 12),
            0x39D5: ("恢", "恢", 8),
            0x3799: ("选", "選", 144),
        }
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        changes = {int(change["code"], 16): change for change in self.report["font_changes"]}
        effective = {code: {"verified": True, "character": change["target"]} for code, change in changes.items()}
        effective.update({int(glyph["code"], 16): {"verified": True, "character": glyph["character"]}
                          for glyph in self.report["allocated_glyphs"]})
        for code, (source, target, count) in expected.items():
            with self.subTest(code=f"{code:04X}"):
                self.assertEqual(reading(self.mapping[code], False), source)
                self.assertEqual(sum(record["words"].count(code) for record in records), count)
                change = changes[code]
                self.assertEqual((change["source"], change["target"]), (source, target))
                self.assertTrue(change["source_verified"])
                self.assertEqual(self.target[change["offset"]:change["offset"] + GLYPH_SIZE], self.renderer.encode(target))
        texts = {
            0xDB83B4: "「明明和本大爺在一起\n 卻一副寂寞的樣子！」\n",
            0xD9CE32: "{STYLE_0}「{ARG:0}先生！ 好好\n 考慮 有用的\n 用法吧！」\n",
            0xDBC2D6: "{STYLE_0}「選是就結束遊戲！\n 選否可以\n 再欣賞一次結局！」\n",
            0xDECE7C: "信息        {ARG:0}\n列車        {ARG:1}\n全部恢復初始狀態 \n",
            0xDECF34: "要將速度設定\n恢復初始狀態嗎？\n",
            0xDECF64: "速度設定\n已恢復初始狀態！\n",
        }
        for offset, expected_text in texts.items():
            record = next(record for record in records if record["offset"] == offset)
            words = struct.unpack_from(f"<{len(record['words'])}H", self.target, offset)
            self.assertEqual(render(words, effective), expected_text)
        self.assertEqual(reading(self.mapping[0x067C], False), "迎")
        bitmap = SILVER_19_PIXEL_GLYPHS["選"]
        self.assertEqual(bitmap[0][4:], "###.###.")
        self.assertEqual(bitmap[2][4:], "###.###.")
        self.assertEqual(bitmap[4][4:], "###.###.")
        self.assertNotIn("選", {entry["character"] for entry in self.report["font_fallbacks"]})

    def test_swimming_and_tourism_contexts(self):
        converter = OpenCC("s2t")
        for source, target in {
            "游泳": "游泳", "能游4-5公里": "能游4-5公里",
            "或许会游海": "或許會游海", "游动的身影": "游動的身影",
            "悠游水中的": "悠游水中的", "卡片都没游": "卡片都沒有",
            "游戏": "遊戲", "周游卡": "周遊卡", "旅游": "旅遊",
            "游船": "遊船", "游客": "遊客", "游行": "遊行", "游玩": "遊玩",
        }.items():
            with self.subTest(source=source):
                self.assertEqual(convert_traditional(source, converter), target)
        effective = {int(change["code"], 16): {"verified": True, "character": change["target"]}
                     for change in self.report["font_changes"]}
        effective.update({int(glyph["code"], 16): {"verified": True, "character": glyph["character"]}
                          for glyph in self.report["allocated_glyphs"]})
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        checked = 0
        for record in records:
            source_text = render(record["words"], self.mapping, True)
            if "游" not in source_text and "遊" not in source_text:
                continue
            words = struct.unpack_from(f"<{len(record['words'])}H", self.target, record["offset"])
            self.assertEqual(render(words, effective), convert_traditional(source_text, converter))
            checked += 1
        self.assertEqual(checked, 162)

    def test_speed_label_offsets(self):
        self.assertEqual(len(self.report["code_fixes"]), len(SPEED_LABEL_FIXES))
        for offset, source, target, reason in SPEED_LABEL_FIXES:
            self.assertEqual(struct.unpack_from("<H", self.source, offset)[0], source)
            self.assertEqual(struct.unpack_from("<H", self.target, offset)[0], target)
            self.assertIn({"offset": offset, "source": source, "target": target, "reason": reason},
                          self.report["code_fixes"])
        effective = {int(change["code"], 16): {"verified": True, "character": change["target"]}
                     for change in self.report["font_changes"]}
        offsets = [0] + [struct.unpack_from("<H", self.target, offset)[0] & 255
                         for offset, _, _, _ in SPEED_LABEL_FIXES]
        for offset, expected in zip(offsets, ("慢", "普通", "快")):
            # The menu copies three halfwords, then stops at the first newline.
            words = list(struct.unpack_from("<3H", self.target, 0xDED0E6 + offset))
            self.assertEqual(render(words[:words.index(0x8000)], effective), expected)

    def test_event_banner(self):
        manifest = json.loads((ROOT / "analysis/event-graphics-source/label-locations.json").read_text())
        label = manifest["labels"][0]
        self.assertEqual((label["source"], label["target"]), ("イベント編", "事件篇"))
        output, allowed = bytearray(self.source), bytearray(len(self.source))
        changes = replace_labels(self.source, output, allowed, self.renderer, [manifest])
        self.assertEqual(len(changes), 2)
        for change in changes:
            offset, size = change["offset"], change["size"]
            self.assertEqual(size, 288)
            self.assertEqual(self.target[offset:offset + size], output[offset:offset + size])
            self.assertNotEqual(self.target[offset:offset + size], self.source[offset:offset + size])
            self.assertLessEqual({p for b in output[offset:offset + size] for p in (b & 15, b >> 4)}, {1, 2, 12, 13})
        self.assertTrue(all(before == after or allowed[offset]
                            for offset, (before, after) in enumerate(zip(self.source, output))))
        label["background_rows"] = [16] * 16
        with self.assertRaisesRegex(ValueError, "background"):
            replace_labels(self.source, bytearray(self.source), bytearray(len(self.source)), self.renderer, [manifest])

    def test_v33_dirty_tactics_and_quote_pairs(self):
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        changes = {int(change["code"], 16): change for change in self.report["font_changes"]}
        for code, source, target, count in ((0x3D01, "肮", "骯", 1),
                                             (0x0493, "『", "『", 17),
                                             (0x0494, "』", "』", 17)):
            with self.subTest(code=f"{code:04X}"):
                self.assertEqual(reading(self.mapping[code], False), source)
                self.assertEqual(sum(record["words"].count(code) for record in records), count)
                change = changes[code]
                self.assertEqual((change["source"], change["target"]), (source, target))
                self.assertTrue(change["source_verified"])
                self.assertEqual(self.target[change["offset"]:change["offset"] + GLYPH_SIZE], self.renderer.encode(target))
        self.assertEqual(reading(self.mapping[0x042B], True), "航")
        self.assertEqual(sum(record["words"].count(0x042B) for record in records), 9)
        self.assertEqual((changes[0x01F8]["target"], changes[0x01FB]["target"]), ("「", "」"))
        for record in records:
            self.assertEqual(record["words"].count(0x0493), record["words"].count(0x0494))
        reviews = json.loads((ROOT / "analysis/original-font/review.json").read_text())["glyphs"]
        self.assertEqual(sum(entry["code"] == "0493" for entry in reviews), 1)
        effective = {code: {"verified": True, "character": change["target"]} for code, change in changes.items()}
        effective.update({int(glyph["code"], 16): {"verified": True, "character": glyph["character"]}
                          for glyph in self.report["allocated_glyphs"]})
        for offset, expected in {
            0xDE9754: "阿修羅性格上討厭\n用骯髒手段取勝\n所以不用卑劣的卡！\n",
            0xDBBF0E: "想製作新牌組\n 就要玩『平時的桃鐵』\n 而不是『桃鐵3年決戰！』！\n",
            0xDBC004: "在『桃鐵3年決戰！』\n 若一開始就設置\n 這樣保存的牌組⋯⋯\n",
        }.items():
            record = next(record for record in records if record["offset"] == offset)
            words = struct.unpack_from(f"<{len(record['words'])}H", self.target, offset)
            self.assertEqual(render(words, effective), expected)

    def test_default_deck_name_hook_and_glyphs(self):
        label = self.report["default_deck_label"]
        self.assertEqual(label["source_name_bytes"], DEFAULT_DECK_NAME.hex())
        self.assertEqual(label["target"], "系統推薦")
        codes = [int(code, 16) for code in label["codes"]]
        self.assertEqual(len(DECK_NAME_ROUTINE), 64)
        self.assertEqual(DECK_NAME_ROUTINE[-8:], DEFAULT_DECK_NAME + b"\0")
        self.assertEqual(struct.unpack_from("<6H", self.target, DECK_NAME_ROUTINE_OFFSET + 64),
                         (*codes, 0x8000, 0xFFFF))
        output, allowed = bytearray(self.source), bytearray(len(self.source))
        patches = replace_default_deck_name(self.source, output, allowed, codes)
        self.assertEqual(patches, self.report["runtime_text_patches"])
        self.assertEqual([(p["offset"], p["size"]) for p in patches],
                         [(DECK_NAME_HOOK_OFFSET, 8), (DECK_NAME_ROUTINE_OFFSET, 76)])
        for patch in patches:
            offset, size = patch["offset"], patch["size"]
            self.assertEqual(self.target[offset:offset + size], output[offset:offset + size])
        self.assertTrue(all(before == after or allowed[offset]
                            for offset, (before, after) in enumerate(zip(self.source, output))))
        for code, character in zip(codes, label["target"]):
            offset = FONT_BASE + code * GLYPH_SIZE
            self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(character))
        # Existing save/name bytes and the shared 8-bit character table stay compatible.
        self.assertEqual(self.target[0xC253C:0xC257A], self.source[0xC253C:0xC257A])
        table = TEXT_START + 0x29C * 2
        self.assertEqual(self.target[table:table + 512], self.source[table:table + 512])
        self.assertEqual(self.target[0xFFFF80:], self.source[0xFFFF80:])

    def test_default_deck_name_patch_guards(self):
        codes = [0x0156, 0x0076, 0x38D5, 0x38D6]
        for offset in (DECK_NAME_HOOK_OFFSET, DECK_NAME_ROUTINE_OFFSET):
            stale = bytearray(self.source)
            stale[offset] ^= 1
            output, allowed = bytearray(stale), bytearray(len(stale))
            with self.assertRaisesRegex(ValueError, "Deck-name patch source mismatch"):
                replace_default_deck_name(stale, output, allowed, codes)
            self.assertEqual(output, stale)
            self.assertFalse(any(allowed))
        for invalid in (codes[:3], [0x8000] * 4, [-1] * 4):
            with self.assertRaisesRegex(ValueError, "four valid glyph codes"):
                replace_default_deck_name(self.source, bytearray(self.source), bytearray(len(self.source)), invalid)

    def test_screenshot_glyph_mappings_and_contexts(self):
        expected = {
            0x0557: ("慢", "慢", 38),
            0x3CDC: ("汹", "洶", 1),
            0x3B4D: ("馎", "餺", 1),
            0x3B4E: ("饦", "飥", 1),
            0x390D: ("ー", "ー", 126),
        }
        records = split_records(self.source[TEXT_START:TEXT_END], TEXT_START)
        changes = {int(change["code"], 16): change for change in self.report["font_changes"]}
        for code, (source, target, count) in expected.items():
            with self.subTest(code=f"{code:04X}"):
                self.assertEqual(reading(self.mapping[code], False), source)
                self.assertEqual(sum(record["words"].count(code) for record in records), count)
                change = changes[code]
                self.assertEqual((change["source"], change["target"]), (source, target))
                self.assertTrue(change["source_verified"])
                offset = change["offset"]
                self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode(target))
        converter = OpenCC("s2t")
        for offset, expected_text in {
            0xDB6054: "餺飥鍋店\n",
            0xDDEA68: "「玄界灘的洶湧大海！\n 小倉！」\n",
            0xDED0E6: "慢\n普通\n快\n",
            0xDED792: "<慢>是這個速度！\n",
            0xDC8310: "「啊哈哈！ 哇哈哈！\n 不對啦ーーー！」\n",
        }.items():
            record = next(record for record in records if record["offset"] == offset)
            self.assertEqual(convert_traditional(render(record["words"], self.mapping, True), converter), expected_text)
        self.assertEqual(render([0x0061, 0x02B6], self.mapping, True), "一博")

    def test_dense_glyph_redraws(self):
        for character in "啊姬糰餺飥涮䴉":
            with self.subTest(character=character):
                bitmap = SILVER_19_PIXEL_GLYPHS[character]
                encoded = self.renderer.encode(character)
                foreground = [(encoded[i // 2] >> (4 * (i % 2))) & 15 == 3 for i in range(192)]
                self.assertEqual(foreground, [pixel == "#" for row in bitmap for pixel in row])
                ink_rows = [i // 12 for i, value in enumerate(foreground) if value]
                self.assertGreaterEqual(max(ink_rows) - min(ink_rows) + 1, 12 if character == "姬" else 13)
                self.assertNotIn(character, {entry["character"] for entry in self.report["font_fallbacks"]})
                slots = [change for change in self.report["font_changes"] if change["target"] == character]
                slots += [change for change in self.report["allocated_glyphs"] if change["character"] == character]
                self.assertTrue(slots)
                for slot in slots:
                    offset = slot["offset"]
                    self.assertEqual(self.target[offset:offset + GLYPH_SIZE], encoded)
        ji = SILVER_19_PIXEL_GLYPHS["姬"]
        self.assertEqual(ji[1][6:], "......")
        self.assertEqual(ji[13][6:], "......")
        self.assertEqual(ji[2][6:], "#####.")
        self.assertEqual(ji[12][6:], "#####.")
        for y in (3, 10, 11):
            self.assertEqual(ji[y][6:], "#..#..")
        for y in (4, 9):
            self.assertEqual(ji[y][6:], "#.###.")
        for y in range(5, 9):
            self.assertEqual(ji[y][6:], "#.#.#.")
        self.assertEqual([row[:6] for row in ji],
                         ["......", "..#...", "..#...", "..#...", "#####.", ".#..#.",
                          ".#..#.", "#...#.", ".#.#..", "..##..", "..#...", ".#.#..",
                          "#...#.", "......", "......", "......"])
        right_rows = [y for y, row in enumerate(ji) if "#" in row[6:]]
        self.assertEqual((min(right_rows), max(right_rows), len(right_rows)), (2, 12, 11))
        self.assertTrue(all(row[11] == "." for row in ji))
        bitmap = SILVER_19_PIXEL_GLYPHS["糰"]
        ink_rows = [y for y, row in enumerate(bitmap) if "#" in row]
        self.assertEqual(max(ink_rows) - min(ink_rows) + 1, 15)
        self.assertEqual(bitmap[4][5:], "#.#.#.#")
        self.assertTrue(all("." in row[6:11] for row in bitmap[2:14]))
        self.assertLessEqual(sum(row[6:11].count("#") for row in bitmap[2:14]), 22)

    def test_dango_property_names_share_redrawn_glyph(self):
        allocated = {glyph["character"]: int(glyph["code"], 16) for glyph in self.report["allocated_glyphs"]}
        code = allocated["糰"]
        for offset in (0xDB5F84, 0xDB6374, 0xDB6A00, 0xDB6DC4, 0xDB70F6):
            self.assertEqual(struct.unpack_from("<H", self.target, offset)[0], code)
        offset = FONT_BASE + code * GLYPH_SIZE
        self.assertEqual(self.target[offset:offset + GLYPH_SIZE], self.renderer.encode("糰"))

    def test_reported_dialogue_has_final_newline(self):
        offset = 0xDE9830
        self.assertEqual(struct.unpack_from("<HH", self.source, offset), (0xFFFF, 0xFFFF))
        self.assertEqual(struct.unpack_from("<HH", self.target, offset), (0x8000, 0xFFFF))
        record = next(record for record in split_records(self.target[TEXT_START:TEXT_END], TEXT_START)
                      if record["offset"] == 0xDE9804)
        self.assertEqual(record["words"][-2:], [0x01FB, 0x8000])
        self.assertEqual(len(self.report["text_control_fixes"]), 1)
        fix = self.report["text_control_fixes"][0]
        self.assertEqual((fix["offset"], fix["source"], fix["target"]), (offset, 0xFFFF, 0x8000))

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
        self.assertEqual(self.report["character_overrides"], {"着": "著", "渋": "澀", "麪": "麵"})
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
        self.assertEqual(self.source[0xFE0000:DECK_NAME_ROUTINE_OFFSET], self.target[0xFE0000:DECK_NAME_ROUTINE_OFFSET])
        tail = DECK_NAME_ROUTINE_OFFSET + len(DECK_NAME_ROUTINE) + 12
        self.assertEqual(self.source[tail:], self.target[tail:])
        allowed = bytearray(len(self.source))
        for group, size in (("font_changes", GLYPH_SIZE), ("context_changes", 2), ("allocated_glyphs", GLYPH_SIZE), ("text_control_fixes", 2), ("code_fixes", 2)):
            for change in self.report[group]:
                offset = change["offset"]
                allowed[offset:offset + size] = b"\x01" * size
        for change in self.report["graphics_changes"] + self.report["currency_font_changes"] + self.report["runtime_text_patches"]:
            offset, size = change["offset"], change["size"]
            allowed[offset:offset + size] = b"\x01" * size
            self.assertEqual(hashlib.sha256(self.source[offset:offset + size]).hexdigest(), change["source_sha256"])
        self.assertTrue(all(before == after or allowed[offset] for offset, (before, after) in enumerate(zip(self.source, self.target))))
        for offset in range(TEXT_START, TEXT_END, 2):
            if int.from_bytes(self.source[offset:offset + 2], "little") >= 0x8000:
                if offset == 0xDE9830:
                    self.assertEqual(self.target[offset:offset + 2], b"\x00\x80")
                else:
                    self.assertEqual(self.source[offset:offset + 2], self.target[offset:offset + 2])
        for glyph in self.report["allocated_glyphs"]:
            offset = FONT_BASE + int(glyph["code"], 16) * GLYPH_SIZE
            self.assertEqual(offset, glyph["offset"])
            self.assertEqual(self.source[offset:offset + GLYPH_SIZE], b"\xff" * GLYPH_SIZE)


if __name__ == "__main__":
    unittest.main()