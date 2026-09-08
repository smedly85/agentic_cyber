#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <sys/stat.h>

static void die_usage(void) {
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
    exit(2);
}

static bool line_matches(const unsigned char *line, size_t len,
                         const unsigned char *pat, size_t plen) {
    if (plen == 0) return true;
    if (plen > len) return false;
    for (size_t i = 0; i + plen <= len; i++) {
        if (memcmp(line + i, pat, plen) == 0) return true;
    }
    return false;
}

typedef struct {
    unsigned char *buf;
    size_t len;
    size_t cap;
} linebuf_t;

static void lb_reset(linebuf_t *lb) {
    lb->len = 0;
}

static void lb_append(linebuf_t *lb, unsigned char c) {
    if (lb->len + 1 > lb->cap) {
        size_t newcap = lb->cap ? lb->cap * 2 : 256;
        unsigned char *newbuf = realloc(lb->buf, newcap);
        if (!newbuf) {
            fprintf(stderr, "new_grep: out of memory\n");
            free(lb->buf);
            exit(2);
        }
        lb->buf = newbuf;
        lb->cap = newcap;
    }
    lb->buf[lb->len++] = c;
}

static int emit_line(const unsigned char *line, size_t len,
                     const char *prefix, FILE *out) {
    if (prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, out) != plen) return -1;
        if (fputc(':', out) == EOF) return -1;
    }
    if (len > 0 && fwrite(line, 1, len, out) != len) return -1;
    if (fputc('\n', out) == EOF) return -1;
    return 0;
}

static int search_stream(FILE *fp, const unsigned char *pat, size_t plen,
                         const char *prefix, bool *found) {
    linebuf_t lb = {NULL, 0, 0};
    unsigned char chunk[8192];
    size_t n;

    while ((n = fread(chunk, 1, sizeof(chunk), fp)) > 0) {
        for (size_t i = 0; i < n; i++) {
            if (chunk[i] == '\n') {
                if (line_matches(lb.buf, lb.len, pat, plen)) {
                    if (emit_line(lb.buf, lb.len, prefix, stdout) != 0) {
                        fprintf(stderr, "new_grep: write error\n");
                        free(lb.buf);
                        return -1;
                    }
                    *found = true;
                }
                lb_reset(&lb);
            } else {
                lb_append(&lb, chunk[i]);
            }
        }
    }

    if (ferror(fp)) {
        fprintf(stderr, "new_grep: read error\n");
        free(lb.buf);
        return -1;
    }

    if (lb.len > 0) {
        if (line_matches(lb.buf, lb.len, pat, plen)) {
            if (emit_line(lb.buf, lb.len, prefix, stdout) != 0) {
                fprintf(stderr, "new_grep: write error\n");
                free(lb.buf);
                return -1;
            }
            *found = true;
        }
    }

    free(lb.buf);
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        die_usage();
    }

    bool force_prefix = false;
    bool seen_terminator = false;
    char *operands[512];
    int nops = 0;

    for (int i = 1; i < argc; i++) {
        if (!seen_terminator) {
            if (strcmp(argv[i], "--") == 0) {
                seen_terminator = true;
                continue;
            }
            if (strcmp(argv[i], "-H") == 0 ||
                strcmp(argv[i], "--with-filename") == 0) {
                force_prefix = true;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "new_grep: unknown option '%s'\n", argv[i]);
                exit(2);
            }
        }
        operands[nops++] = argv[i];
    }

    if (nops == 0) die_usage();

    const char *pattern = operands[0];
    char **files = operands + 1;
    int nfiles = nops - 1;

    size_t patlen = strlen(pattern);
    bool use_prefix = force_prefix || (nfiles >= 2);
    bool found = false;
    bool error = false;

    if (nfiles == 0) {
        const char *prefix = force_prefix ? "(standard input)" : NULL;
        if (search_stream(stdin, (const unsigned char *)pattern, patlen,
                          prefix, &found) != 0) {
            error = true;
        }
    } else {
        for (int i = 0; i < nfiles; i++) {
            struct stat st;
            if (stat(files[i], &st) != 0) {
                fprintf(stderr, "new_grep: %s: No such file or directory\n",
                        files[i]);
                error = true;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "new_grep: %s: Is a directory\n", files[i]);
                error = true;
                continue;
            }
            FILE *fp = fopen(files[i], "rb");
            if (!fp) {
                fprintf(stderr, "new_grep: %s: cannot open\n", files[i]);
                error = true;
                continue;
            }
            const char *prefix = use_prefix ? files[i] : NULL;
            if (search_stream(fp, (const unsigned char *)pattern, patlen,
                              prefix, &found) != 0) {
                error = true;
            }
            fclose(fp);
        }
    }

    if (error) return 2;
    if (found) return 0;
    return 1;
}
