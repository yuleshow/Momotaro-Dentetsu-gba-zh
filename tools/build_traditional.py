import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

from fontTools.ttLib import TTFont
from opencc import OpenCC
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from extract_text import CONTROLS, extract, load_mapping
from inspect_font import read_rom
from map_font import FONT_BASE, GLYPH_SIZE, SOURCE_SHA256


NEW_GLYPH_START = 0x3D74
NEW_GLYPH_END = 0x51CE
CHARACTER_OVERRIDES = {"着": "著", "渋": "澀", "麪": "麵"}
PHRASE_OVERRIDES = {"一夜干": "一夜乾", "素面": "素麵", "面片": "麵片",
                    "じやじや面": "じやじや麵", "冬粉面": "冬粉麵",
                    "面與湯": "麵與湯", "捲曲面": "捲曲麵",
                    "加面(替玉)": "加麵(替玉)", "強棒面": "強棒麵",
                    "萝ト": "蘿蔔", "蘿卜": "蘿蔔",
                    "1只": "1隻", "3只": "3隻", "几只": "幾隻",
                    "遊動": "游動", "遊海": "游海", "遊4-5公里": "游4-5公里",
                    "悠遊水中": "悠游水中", "没游": "沒有"}
SPEED_LABEL_FIXES = (
    (0x89C7C, 0x3008, 0x3004, "Normal speed starts after 慢 and its newline."),
    (0x89C96, 0x3010, 0x300A, "Fast speed starts after 慢/普通 and their newlines."),
)
DEFAULT_DECK_NAME = bytes.fromhex("05 1f 06 0e 00 00 00")
DECK_NAME_HOOK_OFFSET = 0xB8AE8
DECK_NAME_ROUTINE_OFFSET = 0xFFFF00
# ARMv4T: save r4-r6/lr, compare seven name bytes, copy six halfwords on
# a match; otherwise resume the original decoder with its prologue restored.
DECK_NAME_ROUTINE = bytes.fromhex(
    "70b5 0500 0e00 0ca2 0024 285d 115d 8842 0cd1 0134 072c f8d1 "
    "09a2 0024 105b 3053 0234 0c2c fad1 70bc 01bc 0047 "
    "a720 014b 1847 c046 f18a0b08 051f060e00000000"
)
SILVER_19_PIXEL_GLYPHS = {
    "選": (
        "....###.###.",
        "......#...#.",
        "....###.###.",
        ".#..#...#...",
        "..#.###.###.",
        "............",
        "###..#...#..",
        "..#.#######.",
        ".#...#...#..",
        "..#.#######.",
        "..#...#.#...",
        "..#..#...#..",
        ".#.#........",
        "#...#######.",
        "............",
        "............",
    ),
    "涮": (
        "............",
        ".#..#####..#",
        "..#.#...#..#",
        "....#...#..#",
        "#...#####.##",
        ".#..#.#...##",
        "....#.###.##",
        "....#.#.#.##",
        "..#.#.#.#.##",
        ".#..#.#.#.##",
        ".#..#.#.#.##",
        "#..##.#.#..#",
        "#..#..#.#..#",
        "#.....#....#",
        "......#...##",
        "............",
    ),
    "䴉": (
        "............",
        "######...#..",
        "#.##.#..###.",
        "######..#.#.",
        "........###.",
        "######..#.#.",
        ".####...###.",
        ".#..#...#...",
        ".####...####",
        "..#..#..#...",
        ".##.#...####",
        "#.##....#..#",
        "..#.#......#",
        "..##.#.#.#.#",
        "..#..#.....#",
        "............",
    ),
    "啊": (
        "............",
        "....###.....",
        "....#.######",
        "....##.....#",
        "###.#.#....#",
        "#.#.#.####.#",
        "#.#.##.#.#.#",
        "#.#.#..#.#.#",
        "#.#.##.###.#",
        "#.#.#.#....#",
        "###.#.#....#",
        "....##.....#",
        "....#.....##",
        "....#.......",
        "....#.......",
        "............",
    ),
    "姬": (
        "............",
        "..#.........",
        "..#...#####.",
        "..#...#..#..",
        "#####.#.###.",
        ".#..#.#.#.#.",
        ".#..#.#.#.#.",
        "#...#.#.#.#.",
        ".#.#..#.#.#.",
        "..##..#.###.",
        "..#...#..#..",
        ".#.#..#..#..",
        "#...#.#####.",
        "............",
        "............",
        "............",
    ),
    "糰": (
        "..#..#######",
        "..#..#..#..#",
        "#.#..#..#..#",
        ".###.#.###.#",
        "..#..#.#.#.#",
        "####.#.###.#",
        "..#..#..#..#",
        ".###.#...#.#",
        "#.#..#.###.#",
        "..#..#...#.#",
        "..#..#...#.#",
        "..#..##..#.#",
        "..#..#..##.#",
        "..#..#.....#",
        ".....#######",
        "............",
    ),
    "餺": (
        "............",
        "..#.....#.#.",
        ".#.#..######",
        "#...#...#...",
        ".###..######",
        ".#.#..#.#..#",
        ".###..######",
        ".#.#..#.#..#",
        ".###..######",
        ".#........#.",
        ".#.#..######",
        ".#..#..#..#.",
        ".##.......#.",
        ".#..#....##.",
        "............",
        "............",
    ),
    "飥": (
        "............",
        "..#.......#.",
        ".#.#....##..",
        "#...#.##....",
        ".###....#...",
        ".#.#....#...",
        ".###..######",
        ".#.#....#...",
        ".###....#...",
        ".#......#...",
        ".#.#....#...",
        ".#..#...#..#",
        ".##.....#..#",
        ".#..#...####",
        "............",
        "............",
    ),
    "糬": (
        "............",
        "......######",
        "......#.##.#",
        "#.#.#.######",
        ".###....#...",
        "..#....####.",
        "#####...#.#.",
        ".###..######",
        "#.#.#...##..",
        "..#....#####",
        "..#...#.#..#",
        "..#.....####",
        "..#.....#..#",
        "........####",
        "............",
        "............",
    ),
}

CURRENCY_PIXEL_GLYPHS = {
    "億": (
        "........",
        ".#..#...",
        "#.#####.",
        "#..#.#..",
        ".#.###..",
        ".#.#.#..",
        ".######.",
        ".#.###..",
        ".#.#.#..",
        ".#.###..",
        ".#......",
        ".#..#...",
        ".##.#.#.",
        ".##...#.",
        ".#.###..",
        "........",
    ),
    "萬": (
        "........",
        "..#.#...",
        "#######.",
        "..#.#...",
        ".#####..",
        ".#.#.#..",
        ".#####..",
        ".#.#.#..",
        ".#####..",
        "...#....",
        "#######.",
        "#..#..#.",
        "#.###.#.",
        "#...#.#.",
        "#....##.",
        "........",
    ),
    "元": (
        "........",
        "........",
        ".#####..",
        "........",
        "........",
        "#######.",
        "..#.#...",
        "..#.#...",
        "..#.#...",
        "..#.#...",
        "..#.#...",
        ".#..#...",
        ".#..#.#.",
        "#...#.#.",
        "....###.",
        "........",
    ),
}
CURRENCY_FONT_SLOTS = (
    (0xE43A94, "亿", "億", "88f6c133fdc1cf3d50389ae1a35e889725b87b11c16b64e01a765b68267875a5"),
    (0xE43AD4, "万", "萬", "b0b1219c9d132b925ad72443bd91f37919fef2b9b2d4aa8ab42fa50e346ba3f9"),
    (0xE43B14, "円", "元", "3fd9266157380ed0f03caad3071a27fcce85c512fafe8aca011915ae57804670"),
)
RED_CURRENCY_FONT_SLOTS = (
    (0xE43670, "亿", "億", "f34db101d0bf9b879b99f159873e81c567a983e9714d22c0b4add18b16b39b82"),
    (0xE436B0, "万", "萬", "5d2a8393c7aef544bd3af734375db15b3c56cf1b4f12ca85a0e17562bbbc3313"),
    (0xE436F0, "円", "元", "cb36e0e5807ce99bec5a66273eadcc0c7c7843b7f87f539e4d5a83c22e31ff72"),
)


def encode_mask(mask):
    width, height = mask.size
    foreground = [value >= 96 for value in mask.tobytes()]
    if not any(foreground):
        raise ValueError("Empty glyph mask")
    pixels = [1] * (width * height)
    for row in range(height - 1):
        for column in range(width - 1):
            if foreground[row * width + column]:
                pixels[(row + 1) * width + column + 1] = 2
    for index, visible in enumerate(foreground):
        if visible:
            pixels[index] = 3
    return bytes(pixels[index] | (pixels[index + 1] << 4) for index in range(0, len(pixels), 2))


def convert_traditional(text, converter):
    for source, target in PHRASE_OVERRIDES.items():
        text = text.replace(source, target)
    converted = converter.convert(text).translate(str.maketrans(CHARACTER_OVERRIDES))
    for source, target in PHRASE_OVERRIDES.items():
        converted = converted.replace(source, target)
    if len(converted) == len(text):
        converted = "".join("只" if text[index:index + 2] == "只有" else character
                            for index, character in enumerate(converted))
    return converted


def reading(record, allow_ocr):
    if record.get("verified"):
        return record.get("character")
    if not allow_ocr or record.get("state") == "unresolved":
        return None
    candidate = record.get("ocr_candidate", record.get("candidate"))
    return candidate if isinstance(candidate, str) and len(candidate) == 1 else None


class GlyphRenderer:
    def __init__(self, path, face=0, size=12, baseline_y=None, fallback=None):
        self.path = path
        self.face = face
        self.size = size
        self.baseline_y = baseline_y
        self.fallback = fallback
        self.fallbacks = {}
        self.font = ImageFont.truetype(str(path), size, index=face)
        with TTFont(path, fontNumber=face) as font:
            self.characters = set(font.getBestCmap())
        self.cache = {}

    def encode(self, character):
        if character in self.cache:
            return self.cache[character]
        try:
            encoded = self.encode_primary(character)
        except ValueError as error:
            if self.fallback is None:
                raise
            encoded = self.fallback.encode(character)
            self.fallbacks[character] = str(error)
        self.cache[character] = encoded
        return encoded

    def encode_primary(self, character):
        pixel_glyph = SILVER_19_PIXEL_GLYPHS.get(character) if self.path.name == "Silver.ttf" and self.size == 19 and self.baseline_y == 1 else None
        if len(character) != 1 or (ord(character) not in self.characters and pixel_glyph is None):
            raise ValueError(f"Font lacks target glyph: {character!r}")
        if character.isspace():
            self.cache[character] = b"\x11" * GLYPH_SIZE
            return self.cache[character]
        mask = Image.new("L", (12, 16))
        # Keep dense components readable rather than shrinking to the fallback.
        if pixel_glyph is not None:
            mask.putdata([255 if pixel == "#" else 0 for row in pixel_glyph for pixel in row])
        elif self.baseline_y is None:
            bounds = self.font.getbbox(character)
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            if width > 12 or height > 15:
                raise ValueError(f"Glyph does not fit 12x16: {character!r}: {bounds}")
            ImageDraw.Draw(mask).text(((12 - width) // 2 - bounds[0], (15 - height) // 2 - bounds[1]), character, font=self.font, fill=255)
        else:
            scratch = Image.new("L", (64, 64))
            ImageDraw.Draw(scratch).text((24, 24), character, font=self.font, fill=255)
            ink = scratch.getbbox()
            if ink is None:
                raise ValueError(f"Empty target glyph: {character!r}")
            left, top, right, bottom = (value - 24 for value in ink)
            if right - left > 12 or bottom - top > 16:
                raise ValueError(f"Glyph ink does not fit 12x16: {character!r}: {(left, top, right, bottom)}")
            position_x = max(-left, min((12 - round(self.font.getlength(character))) // 2, 12 - right))
            position_y = max(-top, min(self.baseline_y, 16 - bottom))
            mask.paste(scratch.crop(ink), (position_x + left, position_y + top))
        encoded = encode_mask(mask)
        self.cache[character] = encoded
        return encoded


def make_ips(source, target):
    if len(source) != len(target) or len(target) > 0x1000000:
        raise ValueError("IPS builder requires equal sizes within the 24-bit address space")
    patch = bytearray(b"PATCH")
    offset = 0
    while offset < len(source):
        if source[offset] == target[offset]:
            offset += 1
            continue
        start = offset
        if start == 0x454F46:
            start -= 1
        while offset < len(source) and offset - start < 0xFFFF and source[offset] != target[offset]:
            offset += 1
        payload = target[start:offset]
        patch.extend(start.to_bytes(3, "big"))
        patch.extend(len(payload).to_bytes(2, "big"))
        patch.extend(payload)
    patch.extend(b"EOF")
    return bytes(patch)


def encode_tiles(image):
    width, height = image.size
    if width % 8 or height % 8:
        raise ValueError("Sprite dimensions must be multiples of eight")
    pixels = []
    for tile_y in range(height // 8):
        for tile_x in range(width // 8):
            for pixel_y in range(8):
                for pixel_x in range(8):
                    value = image.getpixel((tile_x * 8 + pixel_x, tile_y * 8 + pixel_y))
                    if not 0 <= value < 16:
                        raise ValueError("Sprite palette index exceeds 4bpp")
                    pixels.append(value)
    return bytes(pixels[index] | (pixels[index + 1] << 4) for index in range(0, len(pixels), 2))


def replace_labels(rom, output, allowed, renderer, manifests):
    changes = []
    occupied = set()
    for manifest in manifests:
        if manifest["source_sha256"] != SOURCE_SHA256:
            raise ValueError("Menu asset source checksum mismatch")
        for label in manifest["labels"]:
            width = max(piece["x"] + piece["width"] for piece in label["pieces"])
            height = label.get("height", 32)
            origin_x, origin_y = label.get("origin", (3, 3))
            advance = label.get("advance", 21)
            ink = label.get("foreground", 1)
            border = label.get("outline", 4)
            if not 0 < ink < 16 or not 0 < border < 16 or ink == border:
                raise ValueError("Invalid graphic label palette indices")
            label_size = int(label.get("font_size", 18) * renderer.size / 12 + 0.5)
            label_font = ImageFont.truetype(str(renderer.path), label_size, index=renderer.face)
            mask = Image.new("L", (width, height))
            draw = ImageDraw.Draw(mask)
            for index, character in enumerate(label["target"]):
                if ord(character) not in renderer.characters:
                    raise ValueError(f"Font lacks menu character: {character}")
                bounds = label_font.getbbox(character)
                if origin_x + index * advance + bounds[2] - bounds[0] + 1 > width or origin_y + bounds[3] - bounds[1] + 1 > height:
                    raise ValueError("Menu label exceeds its original sprite bounds")
                draw.text((origin_x + index * advance - bounds[0], origin_y - bounds[1]), character, font=label_font, fill=255)
            foreground = mask.point(lambda value: 255 if value >= 112 else 0)
            outline = foreground.filter(ImageFilter.MaxFilter(3))
            background_rows = label.get("background_rows", [0] * height)
            if len(background_rows) != height or any(not isinstance(value, int) or not 0 <= value < 16 for value in background_rows):
                raise ValueError("Invalid graphic label background rows")
            indexed = Image.new("L", mask.size)
            indexed.putdata([value for value in background_rows for _ in range(width)])
            indexed.paste(border, mask=outline)
            indexed.paste(ink, mask=foreground)
            for piece in label["pieces"]:
                offset = int(piece["offset"], 16)
                size = piece["width"] * piece["height"] // 2
                piece_y = piece.get("y", 0)
                if offset < 0 or offset + size > FONT_BASE or piece_y < 0 or piece_y + piece["height"] > height:
                    raise ValueError("Unexpected menu asset bounds")
                if any(position in occupied for position in range(offset, offset + size)):
                    raise ValueError("Overlapping menu asset pieces")
                occupied.update(range(offset, offset + size))
                if hashlib.sha256(rom[offset:offset + size]).hexdigest() != piece["sha256"]:
                    raise ValueError(f"Menu asset checksum mismatch at {offset:08X}")
                cropped = indexed.crop((piece["x"], piece_y, piece["x"] + piece["width"], piece_y + piece["height"]))
                encoded = encode_tiles(cropped)
                output[offset:offset + size] = encoded
                allowed[offset:offset + size] = b"\x01" * size
                changes.append({"source": label["source"], "target": label["target"], "offset": offset, "size": size, "source_sha256": piece["sha256"], "output_sha256": hashlib.sha256(encoded).hexdigest()})
    return changes


def replace_default_deck_name(rom, output, allowed, codes):
    if len(codes) != 4 or any(not 0 <= code < NEW_GLYPH_END for code in codes):
        raise ValueError("Default deck label requires four valid glyph codes")
    hook = bytes.fromhex("00 4b 18 47") + struct.pack("<I", 0x08000001 + DECK_NAME_ROUTINE_OFFSET)
    routine = DECK_NAME_ROUTINE + struct.pack("<6H", *codes, 0x8000, 0xFFFF)
    if DECK_NAME_ROUTINE_OFFSET + len(routine) > 0xFFFF80:
        raise ValueError("Deck-name routine overlaps the multi-card cheat reserve")
    patches = (
        (DECK_NAME_HOOK_OFFSET, bytes.fromhex("70 b5 05 1c 0e 1c a7 20"), hook),
        (DECK_NAME_ROUTINE_OFFSET, b"\xff" * len(routine), routine),
    )
    for offset, source, target in patches:
        if rom[offset:offset + len(source)] != source or any(allowed[offset:offset + len(target)]):
            raise ValueError(f"Deck-name patch source mismatch at {offset:08X}")
    changes = []
    for offset, source, target in patches:
        output[offset:offset + len(target)] = target
        allowed[offset:offset + len(target)] = b"\x01" * len(target)
        changes.append({
            "offset": offset, "size": len(target),
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "output_sha256": hashlib.sha256(target).hexdigest(),
        })
    return changes


def build(rom, mapping, renderer, allow_ocr=False, graphics=(), replace_all=False):
    if hashlib.sha256(rom).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unexpected source ROM checksum")
    converter = OpenCC("s2t")
    output = bytearray(rom)
    allowed = bytearray(len(rom))
    characters = {}
    defaults = {}
    font_changes = []
    for code, record in sorted(mapping.items()):
        offset = FONT_BASE + code * GLYPH_SIZE
        if int(record["offset"], 16) != offset:
            raise ValueError(f"Mapping offset mismatch: {code:04X}")
        if hashlib.sha256(rom[offset:offset + GLYPH_SIZE]).hexdigest() != record["glyph_sha256"]:
            raise ValueError(f"Mapping glyph checksum mismatch: {code:04X}")
        character = reading(record, allow_ocr)
        if not character:
            continue
        characters[code] = character
        traditional = convert_traditional(character, converter)
        if len(traditional) != 1:
            raise ValueError(f"Non-single default conversion: {character!r}")
        defaults[code] = traditional
        if traditional == character and not replace_all:
            continue
        output[offset:offset + GLYPH_SIZE] = renderer.encode(traditional)
        allowed[offset:offset + GLYPH_SIZE] = b"\x01" * GLYPH_SIZE
        font_changes.append({"code": f"{code:04X}", "offset": offset, "source": character, "target": traditional, "source_verified": bool(record.get("verified"))})

    graphics_changes = replace_labels(rom, output, allowed, renderer, graphics)
    currency_changes = []
    # Numeric displays use this separate 8x16 font, not the dialogue glyphs.
    for offset, source, target, source_sha256 in CURRENCY_FONT_SLOTS + RED_CURRENCY_FONT_SLOTS:
        if hashlib.sha256(rom[offset:offset + 64]).hexdigest() != source_sha256:
            raise ValueError(f"Currency font checksum mismatch at {offset:08X}")
        if any(allowed[offset:offset + 64]):
            raise ValueError("Currency font overlaps another declared replacement")
        mask = Image.new("L", (8, 16))
        mask.putdata([255 if pixel == "#" else 0 for row in CURRENCY_PIXEL_GLYPHS[target] for pixel in row])
        encoded = encode_mask(mask)
        palette = "red" if offset in {slot[0] for slot in RED_CURRENCY_FONT_SLOTS} else "black"
        if palette == "red":
            encoded = bytes(value + 0x33 for value in encoded)
        output[offset:offset + 64] = encoded
        allowed[offset:offset + 64] = b"\x01" * 64
        currency_changes.append({
            "offset": offset, "size": 64, "source": source, "target": target,
            "source_sha256": source_sha256, "output_sha256": hashlib.sha256(encoded).hexdigest(),
            "palette": palette,
        })
    extracted = extract(rom, mapping)
    allocations = {}
    context_changes = []
    skipped = []

    def allocate(character):
        if character in allocations:
            return allocations[character]
        code = NEW_GLYPH_START + len(allocations)
        if code >= NEW_GLYPH_END:
            raise ValueError("Reserved empty font span exhausted")
        offset = FONT_BASE + code * GLYPH_SIZE
        if rom[offset:offset + GLYPH_SIZE] != b"\xff" * GLYPH_SIZE:
            raise ValueError(f"Refusing to overwrite nonempty ROM data at {offset:08X}")
        output[offset:offset + GLYPH_SIZE] = renderer.encode(character)
        allowed[offset:offset + GLYPH_SIZE] = b"\x01" * GLYPH_SIZE
        allocations[character] = code
        return code

    for record in extracted["records"]:
        if not record["terminated"] or record["unknown_controls"] or not record["within_reader_limit"]:
            skipped.append({"offset": record["offset"], "reason": "unterminated, unknown control, or over reader limit", "word_count": len(record["words"])})
            continue
        words = record["words"]
        cursor = 0
        while cursor < len(words):
            if words[cursor] not in characters or words[cursor] in CONTROLS:
                cursor += 1
                continue
            start = cursor
            while cursor < len(words) and words[cursor] in characters and words[cursor] not in CONTROLS:
                cursor += 1
            span = words[start:cursor]
            source_text = "".join(characters[code] for code in span)
            target_text = convert_traditional(source_text, converter)
            if len(target_text) != len(span):
                skipped.append({"offset": record["offset"] + start * 2, "reason": "length-changing conversion", "source": source_text, "target": target_text})
                continue
            # Count arguments split text spans, hiding the classifier from OpenCC.
            if start > 0 and words[start - 1] == 0x8100 and source_text.startswith("只") and not source_text.startswith(("只有", "只好")):
                target_text = "隻" + target_text[1:]
            context_verified = all(mapping[code].get("verified") for code in span)
            for index, (code, target_character) in enumerate(zip(span, target_text)):
                if target_character == defaults[code]:
                    continue
                new_code = allocate(target_character)
                offset = record["offset"] + (start + index) * 2
                struct.pack_into("<H", output, offset, new_code)
                allowed[offset:offset + 2] = b"\x01\x01"
                context_changes.append({"offset": offset, "old_code": f"{code:04X}", "new_code": f"{new_code:04X}", "source": characters[code], "target": target_character, "context_source": source_text, "context_target": target_text, "context_verified": context_verified})

    record = next(record for record in extracted["records"] if record["offset"] == 0xDE9804)
    ending_offset = record["offset"] + len(record["words"]) * 2
    if ending_offset != 0xDE9830 or struct.unpack_from("<HH", rom, ending_offset) != (0xFFFF, 0xFFFF):
        raise ValueError("Reported dialogue lacks the expected spare terminator")
    # Animated dialogue stops a row at 8000, otherwise it draws FFFF as a glyph.
    struct.pack_into("<H", output, ending_offset, 0x8000)
    allowed[ending_offset:ending_offset + 2] = b"\x01\x01"
    text_control_fixes = [{
        "record_offset": record["offset"], "offset": ending_offset,
        "source": 0xFFFF, "target": 0x8000,
        "reason": "Terminate the final dialogue row before the retained FFFF terminator",
    }]

    code_fixes = []
    for offset, source, target, reason in SPEED_LABEL_FIXES:
        if struct.unpack_from("<H", rom, offset)[0] != source or any(allowed[offset:offset + 2]):
            raise ValueError(f"Speed-label instruction mismatch at {offset:08X}")
        struct.pack_into("<H", output, offset, target)
        allowed[offset:offset + 2] = b"\x01\x01"
        code_fixes.append({"offset": offset, "source": source, "target": target, "reason": reason})

    deck_label = "系統推薦"
    deck_codes = []
    for character in deck_label:
        code = next((code for code, target in defaults.items() if target == character), None)
        deck_codes.append(allocate(character) if code is None else code)
    runtime_text_patches = replace_default_deck_name(rom, output, allowed, deck_codes)

    if len(output) != len(rom) or output[:0xC0] != rom[:0xC0]:
        raise ValueError("ROM size or header changed unexpectedly")
    changed_bytes = 0
    for offset, (before, after) in enumerate(zip(rom, output)):
        if before != after:
            if not allowed[offset]:
                raise ValueError(f"Undeclared write at {offset:08X}")
            changed_bytes += 1
    counts = Counter(word for record in extracted["records"] for word in record["words"] if word not in CONTROLS)
    unresolved_used = [{"code": f"{code:04X}", "count": count} for code, count in counts.items() if code not in characters]
    return bytes(output), {
        "experimental": True,
        "source_sha256": SOURCE_SHA256,
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "conversion": "OpenCC s2t with user character overrides, glyph defaults plus length-preserving context variants",
        "character_overrides": CHARACTER_OVERRIDES.copy(),
        "phrase_overrides": PHRASE_OVERRIDES.copy(),
        "allow_unverified_ocr": allow_ocr,
        "replace_all_mapped_glyphs": replace_all,
        "summary": {
            "font_slots_replaced": len(font_changes),
            "graphic_label_pieces_replaced": len(graphics_changes),
            "currency_font_slots_replaced": len(currency_changes),
            "ocr_dependent_font_replacements": sum(not change["source_verified"] for change in font_changes),
            "context_word_replacements": len(context_changes),
            "new_glyph_slots": len(allocations),
            "text_control_fixes": len(text_control_fixes),
            "code_fixes": len(code_fixes),
            "runtime_text_patches": len(runtime_text_patches),
            "skipped_context_records_or_spans": len(skipped),
            "unmapped_used_codes": len(unresolved_used),
            "changed_bytes": changed_bytes,
        },
        "limitations": [
            "OCR candidates are not verified translations or glyph identities.",
            "Unmapped glyphs remain unchanged; unknown contexts use default glyph conversions.",
            "Only explicitly listed graphic labels have been converted; other embedded text remains unaudited.",
            "Text scan does not prove whole-ROM coverage or call-site reachability.",
            "Gameplay and visual review are required before release.",
        ],
        "font_changes": font_changes,
        "font_fallbacks": [{"character": character, "reason": reason} for character, reason in sorted(renderer.fallbacks.items())],
        "graphics_changes": graphics_changes,
        "currency_font_changes": currency_changes,
        "context_changes": context_changes,
        "text_control_fixes": text_control_fixes,
        "code_fixes": code_fixes,
        "runtime_text_patches": runtime_text_patches,
        "default_deck_label": {
            "source_name_bytes": DEFAULT_DECK_NAME.hex(),
            "target": deck_label,
            "codes": [f"{code:04X}" for code in deck_codes],
        },
        "allocated_glyphs": [{"character": character, "code": f"{code:04X}", "offset": FONT_BASE + code * GLYPH_SIZE} for character, code in allocations.items()],
        "skipped_context": skipped,
        "unmapped_used_codes": unresolved_used,
    }


def main():
    parser = argparse.ArgumentParser(description="Build an experimental Traditional Chinese ROM copy and IPS patch")
    parser.add_argument("rom", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--map", type=Path, action="append", required=True)
    parser.add_argument("--review", type=Path, action="append", default=[])
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--font-face", type=int, default=0)
    parser.add_argument("--font-size", type=int, default=12)
    parser.add_argument("--baseline-y", type=int, help="Keep the font's vertical glyph alignment at this cell offset")
    parser.add_argument("--fallback-font", type=Path, help="Optional 12-point fallback for glyphs missing from or too large in the primary font")
    parser.add_argument("--allow-ocr", action="store_true")
    parser.add_argument("--replace-all", action="store_true", help="Render all mapped characters in the chosen font, including unchanged characters, kana, Latin text, digits, and punctuation")
    parser.add_argument("--graphics", type=Path, action="append", default=[])
    args = parser.parse_args()
    paths = [args.output, args.output.with_suffix(".ips"), args.output.with_suffix(".json")]
    if any(path.exists() for path in paths):
        parser.error("Refusing to overwrite existing build outputs")
    source = read_rom(args.rom)
    mapping = load_mapping(args.map, args.review)
    graphics = [json.loads(path.read_text(encoding="utf-8")) for path in args.graphics]
    fallback = GlyphRenderer(args.fallback_font) if args.fallback_font else None
    renderer = GlyphRenderer(args.font, args.font_face, args.font_size, args.baseline_y, fallback)
    result, report = build(source, mapping, renderer, args.allow_ocr, graphics, args.replace_all)
    report["font"] = {"path": str(args.font), "sha256": hashlib.sha256(args.font.read_bytes()).hexdigest(), "face": args.font_face, "size": args.font_size, "baseline_y": args.baseline_y}
    if args.font.name == "Silver.ttf" and args.font_size == 19 and args.baseline_y == 1:
        report["font"]["pixel_glyph_overrides"] = sorted(SILVER_19_PIXEL_GLYPHS)
    if fallback:
        report["font"]["fallback"] = {"path": str(args.fallback_font), "sha256": hashlib.sha256(args.fallback_font.read_bytes()).hexdigest(), "face": 0, "size": 12}
    patch = make_ips(source, result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for path, data in zip(paths, (result, patch, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))):
        with path.open("xb") as output:
            output.write(data)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()