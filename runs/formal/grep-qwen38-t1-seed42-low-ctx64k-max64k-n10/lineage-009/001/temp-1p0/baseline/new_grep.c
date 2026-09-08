#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <sys/stat.h>

__attribute__((noreturn))
static void fail_msg(const char *msg) {
    fprintf(stderr, "new_grep: %s\n", msg);
    exit(2);
}

__attribute__((noreturn))
static void oom(void) {
    fprintf(stderr, "new_grep: out of memory\n");
    exit(2);
}

__attribute__((noreturn))
static void write_err(void) {
    fprintf(stderr, "new_grep: write error\n");
    exit(2);
}

static int bytes_contains(const uint8_t *hay, size_t hay_len,
                          const uint8_t *needle, size_t needle_len) {
    if (needle_len == 0) return 1;
    if (needle_len > hay_len) return 0;
    for (size_t i = 0; i + needle_len <= hay_len; i++) {
        if (memcmp(hay + i, needle, needle_len) == 0)
            return 1;
    }
    return 0;
}

static uint8_t *read_line(FILE *fp, size_t *out_len) {
    size_t cap = 256, len = 0;
    uint8_t *buf = malloc(cap);
    if (!buf) oom();
    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (c == '\n') { *out_len = len; return buf; }
        if (len == cap) {
            if (cap > (size_t)-1 / 2) oom();
            cap *= 2;
            uint8_t *nb = realloc(buf, cap);
            if (!nb) { free(buf); oom(); }
            buf = nb;
        }
        buf[len++] = (uint8_t)c;
    }
    if (len == 0) { free(buf); *out_len = 0; return NULL; }
    *out_len = len;
    return buf;
}

static void search_stream(FILE *fp, const char *prefix,
                          const uint8_t *pat, size_t pat_len, int *has_match) {
    uint8_t *line; size_t line_len;
    while ((line = read_line(fp, &line_len)) != NULL) {
        if (bytes_contains(line, line_len, pat, pat_len)) {
            if (prefix) {
                size_t pl = strlen(prefix);
                if (fwrite(prefix, 1, pl, stdout) != pl) write_err();
                if (fputc(':', stdout) == EOF) write_err();
            }
            if (line_len > 0 && fwrite(line, 1, line_len, stdout) != line_len)
                write_err();
            if (fputc('\n', stdout) == EOF) write_err();
            *has_match = 1;
        }
        free(line);
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) fail_msg("missing PATTERN");

    const char *pattern;
    char **files;
    int nfiles;

    if (strcmp(argv[1], "--") == 0) {
        if (argc < 3) fail_msg("missing PATTERN after --");
        pattern = argv[2];
        files = &argv[3];
        nfiles = argc - 3;
    } else if (argv[1][0] == '-' && argv[1][1] != '\0') {
        fail_msg("unknown option");
    } else {
        pattern = argv[1];
        files = &argv[2];
        nfiles = argc - 2;
    }

    size_t pat_len = strlen(pattern);
    const uint8_t *pat = (const uint8_t *)pattern;
    int has_match = 0, has_error = 0;

    if (nfiles == 0) {
        search_stream(stdin, NULL, pat, pat_len, &has_match);
    } else {
        for (int i = 0; i < nfiles; i++) {
            const char *fname = files[i];
            struct stat st;
            if (stat(fname, &st) != 0) {
                fprintf(stderr, "new_grep: %s: %s\n", fname, strerror(errno));
                has_error = 1; continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "new_grep: %s: is a directory\n", fname);
                has_error = 1; continue;
            }
            FILE *fp = fopen(fname, "rb");
            if (!fp) {
                fprintf(stderr, "new_grep: %s: %s\n", fname, strerror(errno));
                has_error = 1; continue;
            }
            const char *pfx = (nfiles >= 2) ? fname : NULL;
            search_stream(fp, pfx, pat, pat_len, &has_match);
            if (ferror(fp)) {
                fprintf(stderr, "new_grep: %s: read error\n", fname);
                has_error = 1;
            }
            fclose(fp);
        }
    }

    fflush(stdout);
    if (ferror(stdout)) {
        fprintf(stderr, "new_grep: write error\n");
        return 2;
    }
    if (has_error) return 2;
    if (has_match) return 0;
    return 1;
}
