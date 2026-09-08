#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static void usage_exit(void) {
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
    exit(2);
}

static void *xrealloc(void *old, size_t size) {
    if (size < 1) size = 1;
    void *p = realloc(old, size);
    if (!p) {
        fprintf(stderr, "new_grep: out of memory\n");
        exit(2);
    }
    return p;
}

static bool line_matches(const unsigned char *line, size_t len,
                         const unsigned char *pat, size_t plen) {
    if (plen == 0) return true;
    if (plen > len) return false;
    for (size_t i = 0; i <= len - plen; i++) {
        if (memcmp(line + i, pat, plen) == 0)
            return true;
    }
    return false;
}

static bool write_selected(const char *prefix, bool has_prefix,
                           const unsigned char *line, size_t len) {
    if (has_prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, stdout) != plen) return false;
        if (fputc(':', stdout) == EOF) return false;
    }
    if (len > 0 && fwrite(line, 1, len, stdout) != len) return false;
    return fputc('\n', stdout) != EOF;
}

static int search_stream(FILE *f, const unsigned char *pat, size_t plen,
                         const char *prefix, bool has_prefix, bool *found) {
    unsigned char *buf = NULL;
    size_t len = 0, cap = 0;
    int c;

    while ((c = getc(f)) != EOF) {
        if (c == '\n') {
            if (line_matches(buf, len, pat, plen)) {
                if (!write_selected(prefix, has_prefix, buf, len)) {
                    free(buf);
                    return -1;
                }
                *found = true;
            }
            len = 0;
        } else {
            if (len + 1 > cap) {
                cap = cap ? cap * 2 : 256;
                buf = xrealloc(buf, cap);
            }
            buf[len++] = (unsigned char)c;
        }
    }

    if (len > 0) {
        if (line_matches(buf, len, pat, plen)) {
            if (!write_selected(prefix, has_prefix, buf, len)) {
                free(buf);
                return -1;
            }
            *found = true;
        }
    }

    free(buf);
    return 0;
}

static int search_file(const char *path, const unsigned char *pat, size_t plen,
                       const char *prefix, bool has_prefix, bool *found) {
    struct stat st;
    if (stat(path, &st) != 0) {
        fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
        return -1;
    }
    if (S_ISDIR(st.st_mode)) {
        fprintf(stderr, "new_grep: %s: is a directory\n", path);
        return -1;
    }
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
        return -1;
    }
    int rc = search_stream(f, pat, plen, prefix, has_prefix, found);
    if (fclose(f) != 0) rc = -1;
    return rc;
}

int main(int argc, char **argv) {
    if (argc < 2)
        usage_exit();

    bool after_ddash = false;
    bool force_prefix = false;
    int pat_idx = -1, file_start = -1;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = true;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (strcmp(argv[i], "-H") == 0 ||
                    strcmp(argv[i], "--with-filename") == 0) {
                    force_prefix = true;
                    continue;
                }
                fprintf(stderr, "new_grep: unknown option: %s\n", argv[i]);
                fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
                exit(2);
            }
        }
        if (pat_idx == -1)
            pat_idx = i;
        else if (file_start == -1)
            file_start = i;
    }

    if (pat_idx == -1)
        usage_exit();

    const unsigned char *pat = (const unsigned char *)argv[pat_idx];
    size_t plen = strlen(argv[pat_idx]);

    int nfiles = (file_start == -1) ? 0 : argc - file_start;
    bool has_prefix = force_prefix || (nfiles >= 2);

    bool found = false;
    bool error = false;

    if (nfiles == 0) {
        const char *prefix = has_prefix ? "(standard input)" : NULL;
        if (search_stream(stdin, pat, plen, prefix, has_prefix, &found) != 0)
            error = true;
    } else {
        for (int i = file_start; i < argc; i++) {
            if (search_file(argv[i], pat, plen,
                            has_prefix ? argv[i] : NULL, has_prefix,
                            &found) != 0)
                error = true;
        }
    }

    if (error) return 2;
    return found ? 0 : 1;
}
