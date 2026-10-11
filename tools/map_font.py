import argparse
import ctypes
import ctypes.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

from inspect_font import decode_glyph, read_rom


FONT_BASE = 0xDF5298
GLYPH_SIZE = 96
SOURCE_SHA256 = "073a385c1ba1bcd517e2cfea659e54d9e2a87cc3ea5f6f17fe0ba169083ec28f"


class GlyphOCR:
    def __init__(self, tessdata):
        library = ctypes.util.find_library("tesseract")
        if not library:
            raise RuntimeError("The Tesseract shared library is required")
        self.library = ctypes.CDLL(library)
        signatures = {
            "TessBaseAPICreate": (ctypes.c_void_p, []),
            "TessBaseAPIInit3": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]),
            "TessBaseAPISetPageSegMode": (None, [ctypes.c_void_p, ctypes.c_int]),
            "TessBaseAPISetImage": (None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
            "TessBaseAPISetSourceResolution": (None, [ctypes.c_void_p, ctypes.c_int]),
            "TessBaseAPIGetUTF8Text": (ctypes.c_void_p, [ctypes.c_void_p]),
            "TessBaseAPIMeanTextConf": (ctypes.c_int, [ctypes.c_void_p]),
            "TessDeleteText": (None, [ctypes.c_void_p]),
            "TessBaseAPIDelete": (None, [ctypes.c_void_p]),
        }
        for name, (result_type, argument_types) in signatures.items():
            function = getattr(self.library, name)
            function.restype = result_type
            function.argtypes = argument_types
        self.handle = self.library.TessBaseAPICreate()
        if self.library.TessBaseAPIInit3(self.handle, str(tessdata).encode(), b"chi_sim"):
            self.close()
            raise RuntimeError("Could not initialize Chinese OCR")
        self.library.TessBaseAPISetPageSegMode(self.handle, 10)

    def close(self):
        if self.handle:
            self.library.TessBaseAPIDelete(self.handle)
            self.handle = None

    def recognize(self, glyph):
        enlarged = glyph.resize((72, 96), Image.Resampling.NEAREST)
        image = Image.new("L", (112, 136), 255)
        image.paste(enlarged, (20, 20))
        buffer = ctypes.create_string_buffer(image.tobytes())
        self.library.TessBaseAPISetImage(self.handle, buffer, image.width, image.height, 1, image.width)
        self.library.TessBaseAPISetSourceResolution(self.handle, 300)
        text_pointer = self.library.TessBaseAPIGetUTF8Text(self.handle)
        if not text_pointer:
            return "", 0
        try:
            text = ctypes.string_at(text_pointer).decode("utf-8").strip()
            confidence = self.library.TessBaseAPIMeanTextConf(self.handle)
            return text, confidence
        finally:
            self.library.TessDeleteText(text_pointer)


def vision_candidates(args):
    executable = args.vision_executable.resolve()
    if not executable.is_file():
        raise RuntimeError("Compile tools/recognize_font.swift and pass --vision-executable")
    pages = args.output.parent / "font-pages"
    pages.mkdir(parents=True, exist_ok=True)
    candidates = {}
    for start in range(args.start, args.start + args.count, 128):
        count = min(128, args.start + args.count - start)
        image = pages / f"{start:04X}.png"
        subprocess.run([
            sys.executable, str(Path(__file__).with_name("inspect_font.py")), str(args.rom), str(image),
            "--offset", hex(FONT_BASE + start * GLYPH_SIZE), "--width", "12", "--height", "16",
            "--count", str(count), "--scale", "6", "--no-labels",
        ], check=True, capture_output=True, text=True)
        result = subprocess.run([str(executable), str(image)], check=True, capture_output=True, text=True)
        observations = json.loads(result.stdout)
        for observation in observations:
            column = int((observation["x"] - 20) // 72)
            row = int((observation["y"] - 20) // 112)
            if not (0 <= column < 16 and 0 <= row < 8):
                continue
            code = start + row * 16 + column
            text = observation["text"].strip()
            if code >= start + count or not text:
                continue
            candidates.setdefault(code, []).append({"text": text, "confidence": round(observation["confidence"] * 100)})
        print(f"Recognized page {start:04X}; review image: {image}", flush=True)
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Draft an unverified Chinese ROM glyph map using local OCR")
    parser.add_argument("rom", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tessdata", type=Path, default=Path("analysis"))
    parser.add_argument("--start", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--engine", choices=("vision", "tesseract"), default="vision")
    parser.add_argument("--vision-executable", type=Path, default=Path("analysis/recognize_font"))
    args = parser.parse_args()
    rom = read_rom(args.rom)
    digest = hashlib.sha256(rom).hexdigest()
    if digest != SOURCE_SHA256:
        parser.error("This font layout is only verified for the analyzed Simplified Chinese ROM")
    if args.start < 0 or args.count <= 0 or FONT_BASE + (args.start + args.count) * GLYPH_SIZE > len(rom):
        parser.error("Requested glyph range is outside the ROM")
    records = []
    native_candidates = vision_candidates(args) if args.engine == "vision" else {}
    engine = GlyphOCR(args.tessdata.resolve()) if args.engine == "tesseract" else None
    try:
        for code in range(args.start, args.start + args.count):
            offset = FONT_BASE + code * GLYPH_SIZE
            data = rom[offset:offset + GLYPH_SIZE]
            observations = native_candidates.get(code, [])
            if engine:
                glyph = decode_glyph(data, 12, 16)
                candidate, confidence = engine.recognize(glyph)
                foreground = glyph.point(lambda value: 0 if value == 0 else 255)
                foreground_candidate, foreground_confidence = engine.recognize(foreground)
            else:
                candidate = observations[0]["text"] if len(observations) == 1 else ""
                confidence = observations[0]["confidence"] if len(observations) == 1 else 0
                foreground_candidate, foreground_confidence = "", 0
            records.append({
                "code": f"{code:04X}",
                "offset": f"0x{offset:08X}",
                "glyph_sha256": hashlib.sha256(data).hexdigest(),
                "candidate": candidate,
                "confidence": confidence,
                "foreground_candidate": foreground_candidate,
                "foreground_confidence": foreground_confidence,
                "agreement": len(candidate) == 1 and candidate == foreground_candidate,
                "verified": False,
                "observations": observations,
            })
    finally:
        if engine:
            engine.close()
    report = {"source_sha256": digest, "engine": args.engine, "font_base": f"0x{FONT_BASE:08X}", "glyph_size": GLYPH_SIZE, "glyphs": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    recognized = sum(len(record["candidate"]) == 1 for record in records)
    print(f"Drafted {len(records)} glyphs; {recognized} have single-character candidates. All require verification.")


if __name__ == "__main__":
    main()