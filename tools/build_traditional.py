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
CHARACTER_OVERRIDES = {"着": "著", "渋": "澀"}


def convert_traditional(text, converter):
    return converter.convert(text).translate(str.maketrans(CHARACTER_OVERRIDES))


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
        if len(character) != 1 or ord(character) not in self.characters:
            raise ValueError(f"Font lacks target glyph: {character!r}")
        if character.isspace():
            self.cache[character] = b"\x11" * GLYPH_SIZE
            return self.cache[character]
        mask = Image.new("L", (12, 16))
        if self.baseline_y is None:
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
        foreground = [value >= 96 for value in mask.tobytes()]
        if not any(foreground):
            raise ValueError(f"Empty target glyph: {character!r}")
        pixels = [1] * 192
        for row in range(15):
            for column in range(11):
                if foreground[row * 12 + column]:
                    pixels[(row + 1) * 12 + column + 1] = 2
        for index, visible in enumerate(foreground):
            if visible:
                pixels[index] = 3
        encoded = bytes(pixels[index] | (pixels[index + 1] << 4) for index in range(0, 192, 2))
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
            indexed = Image.new("L", mask.size)
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
            context_verified = all(mapping[code].get("verified") for code in span)
            for index, (code, target_character) in enumerate(zip(span, target_text)):
                if target_character == defaults[code]:
                    continue
                new_code = allocate(target_character)
                offset = record["offset"] + (start + index) * 2
                struct.pack_into("<H", output, offset, new_code)
                allowed[offset:offset + 2] = b"\x01\x01"
                context_changes.append({"offset": offset, "old_code": f"{code:04X}", "new_code": f"{new_code:04X}", "source": characters[code], "target": target_character, "context_source": source_text, "context_target": target_text, "context_verified": context_verified})

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
        "allow_unverified_ocr": allow_ocr,
        "replace_all_mapped_glyphs": replace_all,
        "summary": {
            "font_slots_replaced": len(font_changes),
            "graphic_label_pieces_replaced": len(graphics_changes),
            "ocr_dependent_font_replacements": sum(not change["source_verified"] for change in font_changes),
            "context_word_replacements": len(context_changes),
            "new_glyph_slots": len(allocations),
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
        "context_changes": context_changes,
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