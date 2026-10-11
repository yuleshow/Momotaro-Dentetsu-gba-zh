#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>

#include <mgba/core/blip_buf.h>
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba-util/vfs.h>

static unsigned fatal_count = 0;
static unsigned error_count = 0;
static unsigned game_error_count = 0;

static void report_log(struct mLogger *logger, int category, enum mLogLevel level, const char *format, va_list arguments) {
    (void)logger;
    if (level == mLOG_FATAL) {
        ++fatal_count;
    } else if (level == mLOG_ERROR) {
        ++error_count;
    } else if (level == mLOG_GAME_ERROR) {
        ++game_error_count;
    }
    if (level == mLOG_FATAL || (level == mLOG_ERROR && error_count <= 5) ||
        (level == mLOG_GAME_ERROR && game_error_count <= 10)) {
        fprintf(stderr, "%s: ", mLogCategoryName(category));
        vfprintf(stderr, format, arguments);
        fputc('\n', stderr);
    }
}

static int dump_region(struct mCore *core, const char *directory, const char *name, uint32_t address, size_t size) {
    char path[4096];
    int length = snprintf(path, sizeof(path), "%s/%s", directory, name);
    if (length < 0 || (size_t)length >= sizeof(path)) {
        return 0;
    }
    struct VFile *file = VFileOpen(path, O_WRONLY | O_CREAT | O_EXCL);
    if (!file) {
        return 0;
    }
    uint8_t *buffer = malloc(size);
    if (!buffer) {
        file->close(file);
        return 0;
    }
    for (size_t offset = 0; offset < size; offset += 2) {
        uint16_t value = core->busRead16(core, address + offset);
        buffer[offset] = value & 255;
        buffer[offset + 1] = value >> 8;
    }
    int success = file->write(file, buffer, size) == (ssize_t)size;
    free(buffer);
    file->close(file);
    return success;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage: check_rom ROM OUTPUT_DIR FRAMES:KEY_MASK ...\n");
        return 2;
    }
    if (mkdir(argv[2], 0755) && errno != EEXIST) {
        perror("mkdir");
        return 2;
    }
    struct mLogger logger = {.log = report_log, .filter = NULL};
    mLogSetDefaultLogger(&logger);
    struct mCore *core = mCoreFind(argv[1]);
    if (!core || !core->init(core)) {
        fprintf(stderr, "Cannot initialize mGBA core\n");
        return 1;
    }
    mCoreInitConfig(core, NULL);
    if (!mCoreLoadFile(core, argv[1])) {
        fprintf(stderr, "Cannot load ROM\n");
        core->deinit(core);
        return 1;
    }
    unsigned width = 0;
    unsigned height = 0;
    core->desiredVideoDimensions(core, &width, &height);
    if (width != 240 || height != 160) {
        fprintf(stderr, "Unexpected video dimensions: %u x %u\n", width, height);
        core->deinit(core);
        return 1;
    }
    color_t *pixels = calloc(width * height, sizeof(color_t));
    if (!pixels) {
        core->deinit(core);
        return 1;
    }
    core->setVideoBuffer(core, pixels, width);
    core->setAudioBufferSize(core, 1024);
    core->reset(core);
    for (int segment = 3; segment < argc; ++segment) {
        unsigned frames = 0;
        unsigned keys = 0;
        char trailing = 0;
        if (sscanf(argv[segment], "%u:%u%c", &frames, &keys, &trailing) != 2 || !frames || frames > 36000 || keys > 1023) {
            fprintf(stderr, "Invalid input segment: %s\n", argv[segment]);
            free(pixels);
            core->deinit(core);
            return 2;
        }
        core->setKeys(core, keys);
        for (unsigned frame = 0; frame < frames; ++frame) {
            core->runFrame(core);
            blip_clear(core->getAudioChannel(core, 0));
            blip_clear(core->getAudioChannel(core, 1));
        }
        char path[4096];
        int length = snprintf(path, sizeof(path), "%s/%02d.png", argv[2], segment - 3);
        if (length < 0 || (size_t)length >= sizeof(path)) {
            fprintf(stderr, "Output path too long\n");
            free(pixels);
            core->deinit(core);
            return 2;
        }
        struct VFile *file = VFileOpen(path, O_WRONLY | O_CREAT | O_EXCL);
        if (!file || !mCoreTakeScreenshotVF(core, file)) {
            fprintf(stderr, "Cannot write screenshot: %s\n", path);
            if (file) {
                file->close(file);
            }
            free(pixels);
            core->deinit(core);
            return 1;
        }
        file->close(file);
        printf("frame=%u keys=%u screenshot=%s\n", core->frameCounter(core), keys, path);
    }
    if (!dump_region(core, argv[2], "vram.bin", 0x06000000, 0x18000) ||
        !dump_region(core, argv[2], "palette.bin", 0x05000000, 0x400) ||
        !dump_region(core, argv[2], "oam.bin", 0x07000000, 0x400) ||
        !dump_region(core, argv[2], "video-registers.bin", 0x04000000, 0x10)) {
        fprintf(stderr, "Cannot write video memory dumps\n");
        core->deinit(core);
        free(pixels);
        return 1;
    }
    mCoreConfigDeinit(&core->config);
    core->deinit(core);
    free(pixels);
    printf("fatal=%u errors=%u game_errors=%u\n", fatal_count, error_count, game_error_count);
    return fatal_count ? 1 : 0;
}