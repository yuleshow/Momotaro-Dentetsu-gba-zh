# Momotaro Dentetsu G: Experimental Traditional Chinese Build

## Public Repository Contents

This repository publishes conversion tools, reviewed mapping data, graphics
replacement metadata, and replay scenarios. It does not distribute game ROMs,
ROM archives, BIOS files, saves, fonts, or generated build artifacts. Supply
your own legally obtained source ROM and the required fonts before rebuilding.
See [the Silver attribution notes](assets/Silver-ATTRIBUTION.md) for its source.

Links below to ROMs, IPS patches, build reports, screenshots, and other analysis
artifacts describe the local development workspace; those files are not included
in this public repository. Tests require the local inputs and rebuilt artifacts
described below and will not pass on a source-only checkout.

This is a working conversion prototype, **not a verified complete-ROM translation**.
Both original ROMs are unchanged. Generated ROMs, IPS patches, and change reports
are under `build/`.

## Stable Testing Filename

Open [build/Momotarō Dentetsu.gba](build/Momotarō%20Dentetsu.gba) in mGBA for testing.
The matching [IPS patch](build/Momotarō%20Dentetsu.ips) and
[change report](build/Momotarō%20Dentetsu.json) use the same stable basename.
Use the file in `build/`, not the same-named original ROM in `assets/`.
The previous static basename is no longer refreshed; existing files are retained.
These are regular copies, currently identical to v12; numbered builds remain
available as archives. Refresh these three files after validating each new
build, then reload the ROM in mGBA. Do not overwrite or delete save files when
publishing an update. Existing saves under a previous ROM name may need to be imported once
when switching to the stable filename.

## Silver Font Test

- [Silver test ROM](build/momotetsu-zh-Hant.silver-test.gba)
- [Silver IPS patch](build/momotetsu-zh-Hant.silver-test.ips)
- [Screenshots](analysis/preview-silver.png)
- [Previous font versus Silver](analysis/font-comparison-silver.png)
- [Verification report](analysis/verification-silver.json)
- [Local Silver font](assets/Silver.ttf) and [attribution](assets/Silver-ATTRIBUTION.md)

This rendering, now approved for v5, redraws **all 3,269 mapped font slots**, not just characters
that change during Traditional Chinese conversion. Unchanged Chinese, kana,
Latin letters, digits, spaces, and punctuation use the same font path. Silver
is rendered at its native 19-point grid into the existing 12x16 cells, retaining
punctuation's vertical placement. The seven traced graphic labels use Silver too.

As approved for this test, **51 distinct characters use Heiti TC fallback**:
49 missing from Silver and two whose actual ink exceeds the cell width. Each
fallback and its reason is listed in the build JSON. In that prototype, the three
unidentified used glyph codes remain original, as do untraced graphical text assets.
This is not a claim that every decorative bitmap in the game has been restyled.

Replacing all mapped glyphs also exposes more unverified OCR readings than v4:
3,060 slot replacements rely on OCR. This is a visual test build, not a completed
glyph-identification audit. Original ROMs and earlier builds are unchanged.

Rebuild to a new output path:

```sh
python3 tools/build_traditional.py assets/Momotar*.gba build/silver-rebuilt.gba \
  --map analysis/font-map-consolidated.json \
  --map analysis/original-font/vision-map.json \
  --review analysis/original-font/review.json \
  --review analysis/font-audit-01.json \
  --font assets/Silver.ttf --font-size 19 --baseline-y 1 \
  --fallback-font '/System/Library/Fonts/STHeiti Medium.ttc' \
  --replace-all --allow-ocr \
  --graphics analysis/menu-graphics-oam/label-locations.json \
  --graphics analysis/mode-graphics-source/label-locations.json \
  --graphics analysis/title-graphics-source/subtitle-locations.json
```

The Silver prototype passed the original ten tests, including complete
mapped-slot coverage, punctuation placement, fallback equality, and the IPS
round trip. The current suite additionally requires the v6 opponent graphics;
the prototype and v5 are expected to fail that new coverage check.

The Silver ROM also completed the recorded 12,908-frame mGBA scenario through
an opening board turn, with diagnostic counts and captured messages matching
the source baseline described below.

## Current Build

- [Experimental v12 ROM](build/momotetsu-zh-Hant.experimental-v12.gba)
- [Experimental v12 IPS patch](build/momotetsu-zh-Hant.experimental-v12.ips)
- [Exact change report](build/momotetsu-zh-Hant.experimental-v12.json)
- [Verification report](analysis/verification-v12.json)
- [Corrected opponent screen](analysis/preview-v6-opponents.png)
- [All eight opponent selections](analysis/opponent-selection-v6-complete/all-selections.png)

V12 corrects the character name to **閻魔**: `001F` is 閻 and `0020` is 魔,
both user-confirmed. This supersedes the earlier tentative 閰 reading, which
was never published. The main font no longer renders these codes as 赤寬;
the opponent-menu graphics already used 閻魔 and remain unchanged. Silver
supports both characters, so no additional fallback or name override is needed.
All seventeen tests pass. Exactly 109 bytes within the two font slots differ
from v11; all other ROM bytes, including text words and graphics, are identical.

V11 incorporated four user-confirmed readings: `0289` is Japanese 渋, `028A` is
谷, `04EE` is 梅, and `067C` is 迎. The original reading 渋 is preserved in the
review; output normalizes it to 澀. This repairs 澀谷 and 谷底 without replacing
every 谷 with 穀. Three occurrences of 谷仓 become 穀倉 through OpenCC's phrase
conversion, using one additional contextual glyph.

There are now **zero unmapped used codes in the identified text region**. This
does not mean every mapping is correct or the entire ROM has been identified.
All seventeen tests pass on the archive and stable copy, and the recorded
12,908-frame gameplay replay matches source diagnostics. V10 was an unpublished
draft; the fixed testing filename moved directly from v9 to v11. All earlier
archives and save files are retained.

V9 corrected six more punctuation OCR errors: the double quote (`0006`), dollar
sign (`0008`), apostrophe (`000B`), asterisk (`000E`), plus (`000F`), and period
(`0012`). Their original bitmaps match the Japanese ROM; text contexts include
apostrophes in `Let'S`, arithmetic signs, and warning markers. The
[side-by-side audit](analysis/original-font/punctuation-audit-v8.png) preserves
the original-versus-v8 evidence. Exactly 171 bytes in those six font slots differ
from v8; all other ROM bytes are unchanged. Fifteen tests pass against both the
archive and stable testing copy, and the full recorded gameplay path was rerun.

V8 fixed the right parenthesis misidentified as `0` in station readings such as
`(ゆざわ)`. Original glyph `000D` is now verified as `)` using its
[original bitmap](analysis/original-font/parentheses-review.png), identical
Japanese glyph, and text contexts. The genuine zero at `0014` is unchanged.
Exactly 36 bytes within the one 96-byte glyph differ from v7; all other ROM
bytes are identical. The code occurs 64 times in the identified text region,
without implying that every occurrence is runtime-reachable. All fourteen tests
pass. The [previous v7 ROM](build/momotetsu-zh-Hant.experimental-v7.gba) is retained.

V7 applied the user's explicit **着 -> 著** preference after OpenCC conversion,
both for individual glyph defaults and context-sensitive spans. Slot `022E`
now renders 著 wherever used, including 135 occurrences in the identified text
region; that scan does not prove every occurrence is reachable during play.
Exactly 52 bytes within that one 96-byte glyph differ from v6. All other ROM
bytes are identical, including the opponent graphics. All thirteen tests pass.
The [previous v6 ROM](build/momotetsu-zh-Hant.experimental-v6.gba) is unchanged.

V6 fixed the Simplified Chinese opponent grid reported in v5. Those names were
separate sprites, not entries in the main dialogue font. Twelve checksum-guarded
sprite pieces now render all eight names in Silver: 豆鬼, 赤鬼, 馬鬼, 餓鬼,
風神, 阿修羅, 閻魔, and 佐久間. Selection palettes, stars, portraits, and frames
are preserved. The small three-character name uses a reduced size to fit its
original 32-pixel sprite. Japanese banner artwork remains unchanged.

V6 passed eleven tests, including a check that the opponent sprite replacements
actually appear in the output ROM. All eight distinct highlighted opponents
were exercised in mGBA, with pixel comparisons against v5 outside the names.
The full 12,908-frame gameplay scenario was also rerun for v6.

V6 retains the approved Silver body font and the same 51 Heiti TC fallback
characters. The previous [v5 ROM](build/momotetsu-zh-Hant.experimental-v5.gba)
and [v5 patch](build/momotetsu-zh-Hant.experimental-v5.ips) are unchanged.

The previous [v4 ROM](build/momotetsu-zh-Hant.experimental-v4.gba) and
[v4 IPS patch](build/momotetsu-zh-Hant.experimental-v4.ips) remain available.
V6 retains v4's [high-usage accuracy audit](analysis/font-audit-01.json), including
the corrected extracted reading of `0130` from 狗 to 的 in 2,649 occurrences.

Use the ROM directly in mGBA, or apply the IPS patch to the exact Simplified
Chinese source ROM. Do not apply it to the Japanese ROM or a previous build.
The required source SHA-256 is:

```text
073a385c1ba1bcd517e2cfea659e54d9e2a87cc3ea5f6f17fe0ba169083ec28f
```

The current build redraws 3,272 font slots, adjusts 404 context-dependent text
words, and adds 60 contextual glyphs in verified empty space. Seven embedded
graphic labels are converted: five main-menu entries, the three-year mode
label, and the title subtitle. V6 adds the eight opponent names, bringing the
total to 45 graphical pieces. Their original frames, palettes, dimensions,
and tile layouts are retained. The ROM remains 16 MiB.

## Important Limits

- **3,050 font replacements depend on unverified OCR readings.** The change report
  marks each replacement's source verification status. These need a glyph and
  language audit before a release can be called complete or reliable.
- The three previously unmapped used original-font codes are now user-confirmed.
  Seven unresolved added-font review entries have no occurrences in the
  identified text region and remain unchanged. Mapping all used codes in that
  region does not establish complete-ROM coverage or OCR accuracy.
- Two long terminator-delimited records and one trailing unterminated word are
  excluded from context-specific rewriting. Global font replacements still
  apply wherever the game draws those glyph codes.
- Only the seven earlier graphical labels and the eight opponent-grid names
  have been audited and converted. Other embedded graphics may still contain
  Simplified Chinese or Japanese, including the opponent-name banner artwork.
- OpenCC `s2t` plus the 着 -> 著 and Japanese 渋 -> 澀 overrides is used for
  conversion. This is not a general Taiwan-specific localization,
  a retranslation of Japanese text, or a manual semantic review.
- The text extractor identifies terminator-delimited candidates and preserves
  control words. It does not establish every candidate's runtime reachability
  or prove that all ROM text lives in the identified region.

## Rebuild

The build used Python 3.14 on macOS. Install the packages from
[requirements.txt](requirements.txt) in an isolated environment. Avoid installing
the separate `OpenCC` distribution into the same environment: both packages
provide the `opencc` import, and the build uses `opencc-python-reimplemented`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/build_traditional.py assets/*.gba build/rebuilt.experimental.gba \
  --map analysis/font-map-consolidated.json \
  --map analysis/original-font/vision-map.json \
  --review analysis/original-font/review.json \
  --review analysis/font-audit-01.json \
  --font assets/Silver.ttf --font-size 19 --baseline-y 1 \
  --fallback-font '/System/Library/Fonts/STHeiti Medium.ttc' \
  --replace-all --allow-ocr \
  --graphics analysis/menu-graphics-oam/label-locations.json \
  --graphics analysis/mode-graphics-source/label-locations.json \
  --graphics analysis/title-graphics-source/subtitle-locations.json \
  --graphics analysis/opponent-graphics-source/label-locations.json
```

The builder refuses existing output paths and validates the source ROM, font
slot checksums, and every graphics asset before writing. It creates a ROM,
an IPS patch relative to the original, and a JSON audit report. Omitting
`--allow-ocr` limits character conversion to confirmed mappings; it does not
produce a complete conversion.

After rebuilding to the new output path above, validate it and publish the
stable testing copies (the builder itself does not refresh them automatically):

```sh
TRANSLATION_CANDIDATE=build/rebuilt.experimental.gba \
  python3 -m unittest discover -s tools -p 'test_translation.py' -v &&
for extension in gba ips json; do
  cp "build/rebuilt.experimental.$extension" "build/Momotarō Dentetsu.$extension" || exit 1
done
```

The primary font is [Silver](assets/Silver.ttf); see its
[attribution and licensing notes](assets/Silver-ATTRIBUTION.md). The fallback is
macOS Heiti TC, collection face 0, which is not included in this repository.
The report records both fonts' paths and checksums. A different font may
change appearance or fail the glyph-coverage and size checks. Font licensing
and redistribution permissions are separate from this local build process.

## Text and Mapping Tools

- [Consolidation tool](tools/consolidate_font.py): merges the added-font OCR
  drafts with reviewed answers, preserving uncertainty and provenance.
- [Text extractor](tools/extract_text.py): exports original words, offsets,
  controls, confirmed text, and a separate OCR-based draft.
- [ROM builder](tools/build_traditional.py): changes glyphs and verified graphic
  assets, allocates contextual variants, and produces the ROM and IPS patch.

Example extraction to a new output file:

```sh
python3 tools/extract_text.py assets/*.gba analysis/text-with-original-reviews.json \
  --map analysis/font-map-consolidated.json \
  --map analysis/original-font/vision-map.json \
  --review analysis/original-font/review.json \
  --review analysis/font-audit-01.json
```

The verified font format is 12x16 pixels, 4bpp, row-major, low nibble first,
96 bytes per glyph, based at ROM offset `0xDF5298`. The identified text region
is `0xD91A40..0xDF5298` (end exclusive), using little-endian 16-bit words.
`FFFF` terminates a record; `8000` is a line break; `8100` inserts runtime text;
`8200`, `8300`, and `8400` change style. The extraction report records the
disassembly locations supporting those interpretations.

## Verification

Run all seventeen regression tests against the original ROMs and the stable
testing copy:

```sh
python3 -m unittest discover -s tools -p 'test_translation.py' -v
```

They check original checksums, review precedence, unresolved glyph handling,
text controls, glyph and sprite packing, stale-input rejection, IPS record
limits and round-trip reconstruction, and declared write boundaries.
They also check all-mapped-character coverage, Silver punctuation placement,
and fallback glyph equality. The opponent test verifies its unique source
matches, palette indices, Traditional targets, bounded writes, and output-ROM
bytes. `TRANSLATION_CANDIDATE` overrides the candidate, but older builds missing
these graphics or the 着 -> 著 policy are expected to fail the corresponding
new checks. The override tests cover both phrase conversion and output glyph
bytes, and reject 着 in converted defaults or contextual targets.
The parenthesis regression also checks `(ゆざわ)0` decoding and requires the
output ROM to render `000D` as `)`, so older builds fail that coverage check.
The punctuation regression verifies the six additional reviewed symbols.
All-mapped-font coverage now checks each build-record source reading against
the current mapping, so a stale OCR-based artifact cannot pass merely because
its output bytes match its own outdated report.
The six recently user-confirmed glyphs are checked against the review and ROM bytes.
The suite also checks 澀谷/谷底 versus 穀倉 and the three actual context-word
rewrites, and requires zero unmapped used codes in the current build report.

The optional headless runner uses the installed mGBA library. On the tested
Apple Silicon Homebrew installation:

```sh
clang -std=c11 -Wall -Wextra -Werror -I/opt/homebrew/include tools/check_rom.c \
  -L/opt/homebrew/lib -Wl,-rpath,/opt/homebrew/lib -lmgba -o analysis/check_rom
analysis/check_rom 'build/Momotarō Dentetsu.gba' \
  analysis/new-smoke-run 700:0 2:8 120:0
```

Each input is `frames:key_mask`. GBA masks include A=1, B=2, Start=8,
Right=16, Left=32, Up=64, and Down=128. The runner captures each segment's
screen and the final video memory. It does not autoload or write host save
files; the initial in-game save runs in emulator memory.

The recorded [longer scenario](analysis/emulator-v2-gameplay/scenario.json)
runs 12,908 frames through boot, menus, player setup, initial saving,
introductions, and an opening board turn. Source, Silver, v6, v9, and v11 report zero
fatal and ordinary emulator errors and 108 game-level bad-memory messages;
the first ten captured messages match. The separate
[opponent-selection scenario](analysis/opponent-selection-v6-complete/scenario.json)
visits all eight distinct highlighted cells. Both v5 and v6 report zero fatal,
ordinary, and game-level errors on that scenario. This is a source-baseline
caveat, not a clean full-game certification. No physical GBA test or full
playthrough has been performed.

V7 has not had a separate emulator replay. Its thirteen artifact tests pass,
and comparison with v6 proves that only the 96-byte `022E` font slot differs;
all text/control words, graphics, and program bytes remain identical.
V8 likewise has no separate emulator replay: fourteen artifact tests pass,
and comparison with v7 proves that only the `000D` parenthesis font slot differs.
V9's fresh 12,908-frame replay includes the earlier fixes. Its tracked diagnostic
counts and first ten game-error messages match the source baseline. This does
not prove every corrected glyph was shown during that recorded path.
V11 also completed that replay with the same source-baseline results. Its binary
changes relative to v9 are restricted to the four confirmed base glyphs and
contextual text/glyph allocations; other graphics and program data are unchanged.
V12 has no separate emulator replay. Its seventeen artifact tests pass and the
binary comparison proves that only the two name glyphs differ from v11.

### mGBA BIOS Warning

The user reported mGBA 0.10.5 displaying "This game uses a BIOS call that is not
implemented" during saving, and that play continues after clicking OK. This
notice concerns BIOS-call emulation. Configure mGBA to use an official GBA BIOS
dumped from your own console for better compatibility, as the dialog recommends.

The headless runner counts only fatal, error, and game-error log levels; it does
not establish that BIOS warnings or stub messages are absent. This particular
notice has not been reproduced and compared against the source ROM here. Playing
after dismissing it also does not verify persistent saves: test saving and
reloading before relying on progress. No BIOS-call code was changed by this fix.