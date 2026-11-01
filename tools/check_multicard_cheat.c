#include <mgba/flags.h>
#include <mgba/core/cheats.h>
#include <mgba/core/core.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/internal/arm/isa-inlines.h>
#include <mgba-util/vfs.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

static bool normalize(struct mCheatSet *set) {
    char joined[2048] = "";
    for (size_t i = 0; i < StringListSize(&set->lines); ++i) {
        const char *line = *StringListGetPointer(&set->lines, i);
        if (strlen(joined) + strlen(line) + 2 > sizeof(joined)) return false;
        if (i) strcat(joined, "+");
        strcat(joined, line);
    }
    mCheatListClear(&set->list);
    mCheatPatchListClear(&set->romPatches);
    char line[18];
    size_t position = 0;
    for (size_t i = 0; i <= strlen(joined); ++i) {
        line[position] = isspace((unsigned char)joined[i]) || joined[i] == '+' ? ' ' : joined[i];
        if ((position == 13 && (line[position] == ' ' || !line[position])) || position == 17) {
            line[position] = '\0';
            if (!mCheatAddLine(set, line, 0)) return false;
            position = 0;
        } else ++position;
    }
    return true;
}

static bool run_case(struct mCore *core, unsigned player, unsigned slot, unsigned result, bool enabled) {
    struct ARMCore *cpu = core->cpu;
    const uint32_t stack = 0x03007000;
    for (unsigned i = 0; i < 16; ++i) cpu->gprs[i] = 0x100 + i;
    cpu->gprs[7] = player;
    cpu->gprs[10] = result;
    cpu->gprs[13] = stack;
    for (unsigned i = 0; i < 21; ++i) core->busWrite32(core, stack + i * 4, 0x400 + i);
    core->busWrite32(core, stack + 32, slot);
    core->busWrite32(core, stack + 80, 0x08000101);
    _ARMSetMode(cpu, MODE_THUMB);
    cpu->gprs[15] = 0x0803720E;
    ThumbWritePC(cpu);
    unsigned steps = 0;
    while ((uint32_t)cpu->gprs[15] != 0x08000102 && steps++ < 40) core->step(core);
    unsigned expected = enabled && player == 0 && slot >= 5 && result == 8 ? 0 : result;
    if (steps >= 40 || (unsigned)cpu->gprs[0] != expected || (uint32_t)cpu->gprs[13] != stack + 84) {
        fprintf(stderr, "Return/stack mismatch: enabled=%u player=%u slot=%u result=%u actual=%08X\n",
                enabled, player, slot, result, (uint32_t)cpu->gprs[0]);
        return false;
    }
    for (unsigned r = 4; r <= 10; ++r) {
        unsigned saved_index = r <= 7 ? r + 12 : r + 5;
        if ((uint32_t)cpu->gprs[r] != 0x400 + saved_index) {
            fprintf(stderr, "Callee-saved r%u corrupted\n", r);
            return false;
        }
    }
    if (cpu->gprs[11] != 0x10B) {
        fprintf(stderr, "Callee-saved r11 corrupted\n");
        return false;
    }
    return true;
}

static bool check_exorcism_card(struct mCore *core, struct mCheatDevice *device) {
    struct mCheatSet *set = *mCheatSetsGetPointer(&device->cheats, 8);
    for (size_t i = 0; i < 2; ++i) {
        const struct mCheat *write = mCheatListGetPointer(&set->list, i);
        if (write->type != CHEAT_ASSIGN || write->width != 2 ||
            write->address != 0x0201017C + i * 2 || write->operand != (i ? 0 : 0x3C))
            return false;
    }
    if (core->busRead32(core, 0x080F0128 + 0x3C * 12) != 0xF75A) return false;
    const uint16_t name[] = {0x3992, 0x03B8, 0x3786, 0x8000};
    for (size_t i = 0; i < sizeof(name) / sizeof(name[0]); ++i)
        if (core->busRead16(core, 0x08DB08F4 + i * 2) != name[i]) return false;

    const uint32_t neighbors[] = {0x02010178, 0x02010180, 0x0201026C};
    for (size_t i = 0; i < sizeof(neighbors) / sizeof(neighbors[0]); ++i)
        core->busWrite32(core, neighbors[i], 0xAABB0042);
    core->busWrite32(core, 0x0201017C, 0xFFFF0050);
    mCheatRefresh(device, set);
    if (core->busRead32(core, 0x0201017C) != 0xFFFF0050) return false;
    set->enabled = true;
    mCheatRefresh(device, set);
    if (core->busRead32(core, 0x0201017C) != 0x0000003C) return false;
    for (size_t i = 0; i < sizeof(neighbors) / sizeof(neighbors[0]); ++i)
        if (core->busRead32(core, neighbors[i]) != 0xAABB0042) return false;
    set->enabled = false;
    core->busWrite32(core, 0x0201017C, 0xABCD0050);
    mCheatRefresh(device, set);
    return core->busRead32(core, 0x0201017C) == 0xABCD0050;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "Usage: check_multicard_cheat ROM CHEAT_FILE\n");
        return 2;
    }
    struct mCore *core = mCoreFind(argv[1]);
    if (!core || !core->init(core)) return fail("Cannot initialize mGBA");
    mCoreInitConfig(core, NULL);
    if (!mCoreLoadFile(core, argv[1])) return fail("Cannot load ROM");
    color_t *pixels = calloc(240 * 160, sizeof(color_t));
    if (!pixels) return fail("Cannot allocate video buffer");
    core->setVideoBuffer(core, pixels, 240);
    core->reset(core);
    const uint8_t original[] = {
        0x50, 0x46, 0x0D, 0xB0, 0x38, 0xBC, 0x98, 0x46, 0xA1, 0x46,
        0xAA, 0x46, 0xF0, 0xBC, 0x02, 0xBC, 0x08, 0x47
    };
    for (size_t i = 0; i < sizeof(original); ++i) {
        if (core->busRead8(core, 0x0803720E + i) != original[i]) {
            fprintf(stderr, "Unsupported card-dispatch epilogue\n");
            return 1;
        }
    }
    for (unsigned i = 0; i < 64; ++i) {
        if (core->busRead8(core, 0x08FFFF80 + i) != 0xFF) {
            fprintf(stderr, "ROM tail is not unused padding\n");
            return 1;
        }
    }
    struct mCheatDevice *device = core->cheatDevice(core);
    struct VFile *file = VFileOpen(argv[2], O_RDONLY);
    if (!file || !mCheatParseLibretroFile(device, file)) return fail("Cannot parse cheat file");
    file->close(file);
    if (mCheatSetsSize(&device->cheats) != 9) return fail("Expected exactly nine cheats");
    for (size_t i = 0; i < 9; ++i) {
        struct mCheatSet *set = *mCheatSetsGetPointer(&device->cheats, i);
        if (set->enabled || !normalize(set)) return fail("Cheat must be disabled and normalize successfully");
        if (mCheatListSize(&set->list) != (i == 7 ? 0 : 2) ||
            mCheatPatchListSize(&set->romPatches) != (i == 7 ? 22 : 0))
            return fail("Unexpected RAM-write or ROM-patch count");
    }
    if (!check_exorcism_card(core, device))
        return fail("Exorcism card ID, slot, metadata clearing, isolation, or disable behavior failed");
    struct mCheatSet *multi = *mCheatSetsGetPointer(&device->cheats, 7);
    unsigned cases = 0;
    for (unsigned enabled = 0; enabled < 2; ++enabled) {
        multi->enabled = enabled;
        mCheatRefresh(device, multi);
        for (unsigned player = 0; player < 4; ++player)
            for (unsigned slot = 0; slot < 13; ++slot)
                for (unsigned result = 0; result < 16; ++result) {
                    if (!run_case(core, player, slot, result, enabled)) return 1;
                    ++cases;
                }
    }
    multi->enabled = false;
    mCheatRefresh(device, multi);
    for (size_t i = 0; i < sizeof(original); ++i)
        if (core->busRead8(core, 0x0803720E + i) != original[i])
            return fail("Disabling did not restore the card epilogue");
    for (unsigned i = 0; i < 64; ++i)
        if (core->busRead8(core, 0x08FFFF80 + i) != 0xFF)
            return fail("Disabling did not restore unused ROM padding");
    printf("PASS: 9 disabled entries, libretro normalization, exorcism card slot/metadata/isolation, %u ARM return/stack/register cases, patch restoration\n", cases);
    mCoreConfigDeinit(&core->config);
    core->deinit(core);
    free(pixels);
    return 0;
}
