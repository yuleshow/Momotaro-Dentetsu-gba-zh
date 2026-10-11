import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

from consolidate_font import TEXT_START, TEXT_END
from inspect_font import read_rom
from map_font import SOURCE_SHA256


CONTROLS = {0x8000: "newline", 0x8100: "argument", 0x8200: "style_0", 0x8300: "style_1", 0x8400: "style_2"}


def split_records(data, base_offset):
    if len(data) % 2:
        raise ValueError("Text region must contain complete 16-bit words")
    records = []
    words = []
    start = base_offset
    for index, (word,) in enumerate(struct.iter_unpack("<H", data)):
        offset = base_offset + index * 2
        if word == 0xFFFF:
            if words:
                records.append({"offset": start, "words": words, "terminated": True})
                words = []
            start = offset + 2
        else:
            if not words:
                start = offset
            words.append(word)
    if words:
        records.append({"offset": start, "words": words, "terminated": False})
    return records


def render(words, mapping, allow_ocr=False):
    parts = []
    argument = 0
    for word in words:
        if word == 0x8000:
            parts.append("\n")
        elif word == 0x8100:
            parts.append(f"{{ARG:{argument}}}")
            argument += 1
        elif word in CONTROLS:
            parts.append(f"{{{CONTROLS[word].upper()}}}")
        else:
            record = mapping.get(word, {})
            character = record.get("character") if record.get("verified") else None
            if not character and allow_ocr and record.get("state") != "unresolved":
                candidate = record.get("ocr_candidate", record.get("candidate"))
                if isinstance(candidate, str) and len(candidate) == 1:
                    character = candidate
            parts.append(character or f"[{word:04X}]")
    return "".join(parts)


def extract(rom, mapping):
    if hashlib.sha256(rom).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unexpected source ROM checksum")
    records = split_records(rom[TEXT_START:TEXT_END], TEXT_START)
    for record in records:
        words = record["words"]
        invalid = sorted(set(word for word in words if word > 0x3D72 and word not in CONTROLS))
        record["word_index"] = (record["offset"] - TEXT_START) // 2
        record["unknown_controls"] = invalid
        record["within_reader_limit"] = len(words) <= 256
        record["confirmed_text"] = render(words, mapping)
        record["draft_text"] = render(words, mapping, allow_ocr=True)
    counts = Counter(word for record in records for word in record["words"] if word not in CONTROLS)
    return {
        "source_sha256": SOURCE_SHA256,
        "text_start": TEXT_START,
        "text_end_exclusive": TEXT_END,
        "controls": {f"{word:04X}": name for word, name in CONTROLS.items()},
        "evidence": {
            "text_index_addressing": "0x76428..0x7642E: text_base + index * 2",
            "substitution_and_styles": "0x76470..0x76524",
            "line_break": "0x76674..0x766A2",
            "terminator": "0x7651C..0x76522",
        },
        "limitation": "Terminator-delimited candidates, not proven call-site reachability. Draft text contains unverified OCR; controls and source words are retained.",
        "summary": {
            "records": len(records),
            "unterminated": sum(not record["terminated"] for record in records),
            "records_with_unknown_controls": sum(bool(record["unknown_controls"]) for record in records),
            "records_over_reader_limit": sum(not record["within_reader_limit"] for record in records),
            "unique_glyph_words": len(counts),
        },
        "glyph_usage": [{"code": f"{code:04X}", "count": count} for code, count in counts.most_common()],
        "records": records,
    }


def load_mapping(paths, review_paths=()):
    mapping = {}
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["source_sha256"] != SOURCE_SHA256:
            raise ValueError(f"Mapping source mismatch: {path}")
        for record in report["glyphs"]:
            code = int(record["code"], 16)
            if code in mapping:
                raise ValueError(f"Duplicate mapping: {code:04X}")
            mapping[code] = record
    for path in review_paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["source_sha256"] != SOURCE_SHA256:
            raise ValueError(f"Review source mismatch: {path}")
        for review in report["glyphs"]:
            code = int(review["code"], 16)
            if code not in mapping:
                raise ValueError(f"Review has no base mapping: {code:04X}")
            verified = review.get("verified") is True
            character = review.get("character")
            if verified and (not isinstance(character, str) or len(character) != 1):
                raise ValueError(f"Invalid reviewed character: {code:04X}")
            mapping[code] = {
                **mapping[code],
                "character": character if verified else None,
                "verified": verified,
                "state": "confirmed" if verified else "unresolved",
                "review_source": str(path),
                "review": review,
            }
    return mapping


def main():
    parser = argparse.ArgumentParser(description="Extract offset-preserving text candidates from the Chinese ROM")
    parser.add_argument("rom", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--map", type=Path, action="append", required=True)
    parser.add_argument("--review", type=Path, action="append", default=[])
    args = parser.parse_args()
    mapping = load_mapping(args.map, args.review)
    report = extract(read_rom(args.rom), mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()