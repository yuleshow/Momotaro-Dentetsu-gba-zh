import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

from inspect_font import read_rom
from map_font import FONT_BASE, GLYPH_SIZE, SOURCE_SHA256


ADDED_START = 0x3783
ADDED_END = 0x3D73
TEXT_START = 0xD91A40
TEXT_END = 0xDF5298


def consolidate(rom, directory):
    digest = hashlib.sha256(rom).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("This layout is only verified for the analyzed Chinese ROM")
    drafts = {}
    reviews = {}
    for pattern, destination, is_review in (
        ("vision-map-*.json", drafts, False),
        ("character-review-*.json", reviews, True),
    ):
        for path in sorted(directory.glob(pattern)):
            if is_review and not re.fullmatch(r"character-review-\d+\.json", path.name):
                continue
            report = json.loads(path.read_text(encoding="utf-8"))
            if report["source_sha256"] != digest:
                raise ValueError(f"Source checksum mismatch: {path}")
            for record in report["glyphs"]:
                code = int(record["code"], 16)
                if code == ADDED_START - 1 and not is_review:
                    continue
                if not ADDED_START <= code < ADDED_END:
                    raise ValueError(f"Unexpected added-font code: {path}: {code:04X}")
                offset = FONT_BASE + code * GLYPH_SIZE
                if int(record["offset"], 16) != offset:
                    raise ValueError(f"Glyph offset mismatch: {path}: {code:04X}")
                glyph_hash = hashlib.sha256(rom[offset:offset + GLYPH_SIZE]).hexdigest()
                if not is_review and record["glyph_sha256"] != glyph_hash:
                    raise ValueError(f"Glyph checksum mismatch: {path}: {code:04X}")
                if code in destination:
                    raise ValueError(f"Duplicate glyph record: {path}: {code:04X}")
                destination[code] = (record, path.name)
    if set(drafts) != set(range(ADDED_START, ADDED_END)):
        raise ValueError("OCR drafts do not cover all 1,520 added glyph slots")

    counts = Counter(word[0] for word in struct.iter_unpack("<H", rom[TEXT_START:TEXT_END]))
    glyphs = []
    for code in range(ADDED_START, ADDED_END):
        draft, draft_file = drafts[code]
        review, review_file = reviews.get(code, ({}, None))
        verified = review.get("verified", False)
        character = review.get("character") if verified else None
        if verified and (not isinstance(character, str) or len(character) != 1):
            raise ValueError(f"Invalid confirmed character: {code:04X}")
        if not verified and review.get("character") is not None:
            raise ValueError(f"Unconfirmed character must be null: {code:04X}")
        state = "confirmed" if verified else "unresolved" if review_file else "ocr_only"
        glyphs.append({
            "code": f"{code:04X}",
            "offset": draft["offset"],
            "glyph_sha256": draft["glyph_sha256"],
            "character": character,
            "verified": verified,
            "state": state,
            "ocr_candidate": draft["candidate"],
            "ocr_source": draft_file,
            "review_source": review_file,
            "review": review or None,
            "text_word_occurrences": counts[code],
        })
    states = Counter(record["state"] for record in glyphs)
    return {
        "source_sha256": digest,
        "font_base": f"0x{FONT_BASE:08X}",
        "glyph_size": GLYPH_SIZE,
        "summary": {
            "added_slots": len(glyphs),
            "confirmed": states["confirmed"],
            "ocr_only": states["ocr_only"],
            "unresolved": states["unresolved"],
            "added_codes_seen_in_text_scan": sum(counts[code] > 0 for code in drafts),
            "unconfirmed_added_codes_seen": sum(
                record["text_word_occurrences"] > 0 and not record["verified"] for record in glyphs
            ),
        },
        "text_scan": {
            "start": f"0x{TEXT_START:08X}",
            "end_exclusive": f"0x{TEXT_END:08X}",
            "unmapped_low_words": [
                {"code": f"{code:04X}", "count": count}
                for code, count in sorted(counts.items()) if code < ADDED_START
            ],
            "limitation": "Raw aligned little-endian 16-bit words, not parsed dialogue. Low words may include controls or metadata. No whole-ROM coverage claim.",
        },
        "glyphs": glyphs,
    }


def main():
    parser = argparse.ArgumentParser(description="Consolidate added-font OCR and reviews without editing the ROM")
    parser.add_argument("rom", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--analysis-dir", type=Path, default=Path("analysis"))
    args = parser.parse_args()
    report = consolidate(read_rom(args.rom), args.analysis_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()