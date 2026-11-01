#include <mgba/flags.h>
#include <mgba/core/core.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/internal/arm/isa-inlines.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const uint8_t default_name[8] = {5, 31, 6, 14, 0, 0, 0, 0};
static const uint16_t translated[6] = {0x0156, 0x0076, 0x38D5, 0x38D6, 0x8000, 0xFFFF};

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

static bool run_case(struct mCore *core, const uint8_t name[8], unsigned alignment, unsigned output_alignment) {
    const uint32_t source = 0x0203E000 + alignment;
    const uint32_t destination = 0x0203E100 + output_alignment;
    const uint32_t stack = 0x03007000;
    struct ARMCore *cpu = core->cpu;
    for (unsigned i = 0; i < 8; ++i) core->busWrite8(core, source + i, name[i]);
    for (unsigned i = 0; i < 32; ++i) core->busWrite8(core, destination - 4 + i, 0xCC);
    uint16_t expected[9];
    unsigned length;
    if (!memcmp(name, default_name, 7)) {
        memcpy(expected, translated, sizeof(translated));
        length = 6;
    } else {
        length = 7;
        while (length && !name[length - 1]) --length;
        for (unsigned i = 0; i < length; ++i)
            expected[i] = core->busRead16(core, 0x08D91F78 + name[i] * 2);
        expected[length++] = 0x8000;
        expected[length++] = 0xFFFF;
    }
    for (unsigned i = 0; i < 16; ++i) cpu->gprs[i] = 0x100 + i;
    cpu->gprs[0] = source;
    cpu->gprs[1] = destination;
    cpu->gprs[13] = stack;
    cpu->gprs[14] = 0x08000101;
    _ARMSetMode(cpu, MODE_THUMB);
    cpu->gprs[15] = 0x080B8AE8;
    ThumbWritePC(cpu);
    unsigned steps = 0;
    while ((uint32_t)cpu->gprs[15] != 0x08000102 && steps++ < 2000) core->step(core);
    if (steps >= 2000 || (uint32_t)cpu->gprs[13] != stack) return false;
    for (unsigned i = 4; i <= 11; ++i)
        if ((uint32_t)cpu->gprs[i] != 0x100 + i) return false;
    for (unsigned i = 0; i < 8; ++i)
        if (core->busRead8(core, source + i) != name[i]) return false;
    for (unsigned i = 0; i < 32; ++i) {
        uint8_t want = 0xCC;
        if (i >= 4 && i < 4 + length * 2)
            want = expected[(i - 4) / 2] >> (8 * ((i - 4) % 2));
        if (core->busRead8(core, destination - 4 + i) != want) return false;
    }
    return true;
}

int main(int argc, char **argv) {
    if (argc != 2) return fail("Usage: check_deck_name ROM");
    struct mCore *core = mCoreFind(argv[1]);
    if (!core || !core->init(core)) return fail("Cannot initialize mGBA");
    mCoreInitConfig(core, NULL);
    if (!mCoreLoadFile(core, argv[1])) return fail("Cannot load ROM");
    color_t *pixels = calloc(240 * 160, sizeof(color_t));
    if (!pixels) return fail("Cannot allocate video buffer");
    core->setVideoBuffer(core, pixels, 240);
    core->reset(core);
    core->busWrite32(core, 0x03001E80, 0x08D91A40);
    unsigned cases = 0;
    for (unsigned alignment = 0; alignment < 4; ++alignment) {
        for (unsigned output_alignment = 0; output_alignment <= 2; output_alignment += 2) {
            for (unsigned position = 0; position < 8; ++position) {
                for (unsigned value = 0; value < 256; ++value) {
                    uint8_t name[8];
                    memcpy(name, default_name, sizeof(name));
                    name[position] = value;
                    if (!run_case(core, name, alignment, output_alignment)) {
                        fprintf(stderr, "Name mutation failed: input alignment=%u output alignment=%u byte=%u value=%u\n",
                                alignment, output_alignment, position, value);
                        return 1;
                    }
                    ++cases;
                }
            }
            for (unsigned value = 0; value < 256; ++value) {
                uint8_t name[8];
                memset(name, value, sizeof(name));
                if (!run_case(core, name, alignment, output_alignment))
                    return fail("Empty/full custom-name decoding failed");
                ++cases;
            }
        }
    }
    printf("PASS: %u ARM cases; default label, custom names, all byte values, alignment, bounds, input, stack and registers\n", cases);
    mCoreConfigDeinit(&core->config);
    core->deinit(core);
    free(pixels);
    return 0;
}
