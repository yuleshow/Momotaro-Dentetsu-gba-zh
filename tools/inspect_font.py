import argparse
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw


def read_rom(path):
    if path.suffix.lower() != ".zip":
        return path.read_bytes()
    with ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".gba")]
        if len(names) != 1:
            raise ValueError("Expected exactly one GBA ROM in the archive")
        return archive.read(names[0])


def decode_glyph(data, width, height, tiled=False, high_first=False, strip_width=0):
    if width * height != len(data) * 2:
        raise ValueError("Glyph dimensions do not match its byte length")
    if tiled and (width % 8 or height % 8):
        raise ValueError("Tiled glyph dimensions must be multiples of eight")
    if strip_width < 0 or (strip_width and (width % strip_width or tiled)):
        raise ValueError("Strip width must divide the glyph width and cannot be combined with tiles")
    pixels = Image.new("L", (width, height))
    palette = (255, 255, 160, 0) + (96,) * 12
    for row in range(height):
        for column in range(width):
            if tiled:
                pixel_index = ((row // 8) * (width // 8) + column // 8) * 64
                pixel_index += (row % 8) * 8 + column % 8
            elif strip_width:
                pixel_index = (column // strip_width) * strip_width * height
                pixel_index += row * strip_width + column % strip_width
            else:
                pixel_index = row * width + column
            nibble_index = (pixel_index % 2) ^ int(high_first)
            value = (data[pixel_index // 2] >> (4 * nibble_index)) & 15
            pixels.putpixel((column, row), palette[value])
    return pixels


def main():
    parser = argparse.ArgumentParser(description="Render candidate GBA 4bpp font data without modifying the ROM")
    parser.add_argument("rom", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offset", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--count", type=int, default=128)
    parser.add_argument("--tiled", action="store_true")
    parser.add_argument("--high-first", action="store_true")
    parser.add_argument("--strip-width", type=int, default=0)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--no-labels", action="store_true")
    args = parser.parse_args()
    if min(args.width, args.height, args.count, args.scale) <= 0 or args.width * args.height % 2:
        parser.error("Dimensions and count must be positive, with an even pixel count")
    rom = read_rom(args.rom)
    glyph_size = args.width * args.height // 2
    if args.offset < 0 or args.offset + args.count * glyph_size > len(rom):
        parser.error("Requested glyphs extend beyond the ROM")
    columns = 16
    scale = args.scale
    padding = 20 if args.no_labels else 0
    cell_width = args.width * scale if args.no_labels else max(args.width * scale + 8, 54)
    cell_height = args.height * scale + (16 if args.no_labels else 22)
    sheet = Image.new("RGB", (columns * cell_width + padding * 2, ((args.count + columns - 1) // columns) * cell_height + padding * 2), "white")
    drawing = ImageDraw.Draw(sheet)
    for index in range(args.count):
        start = args.offset + index * glyph_size
        glyph = decode_glyph(rom[start:start + glyph_size], args.width, args.height, args.tiled, args.high_first, args.strip_width)
        column = padding + (index % columns) * cell_width
        row = padding + (index // columns) * cell_height
        sheet.paste(glyph.resize((args.width * scale, args.height * scale), Image.Resampling.NEAREST), (column, row))
        if not args.no_labels:
            drawing.text((column, row + args.height * scale + 2), f"{index:04X}", fill="black")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)
    print(f"Rendered {args.count} glyphs from {args.offset:#x} to {args.output}")


if __name__ == "__main__":
    main()