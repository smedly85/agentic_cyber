#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>

typedef struct {
    unsigned char *buf;
    size_t len;
    size_t cap;
} ByteBuf;

static int buf_reserve(ByteBuf *b, size_t need) {
    if (b->cap >= need) return 0;
    size_t newcap = b->cap ? b->cap : 256;
    while (newcap < need) newcap *= 2;
    unsigned char *p = realloc(b->buf, newcap);
    if (!p) return -1;
    b->buf = p;
    b->cap = newcap;
    return 0;
}

static int buf_push(ByteBuf *b, unsigned char c) {
    if (buf_reserve(b, b->len + 1) != 0) return -1;
    b->buf[b->len++] = c;
    return 0;
}

static int read_line(FILE *fp, ByteBuf *line) {
    line->len = 0;
    int c;
    int got_any = 0;
    while ((c = getc(fp)) != EOF) {
        got_any = 1;
        if (c == '\n') break;
        if (buf_push(line, (unsigned char)c) != 0) return -2;
    }
    if (c == EOF && !got_any) return -1;
    return 0;
}

static int fixed_match(const unsigned char *hay, size_t haylen,
                       const unsigned char *pat, size_t patlen) {
    if (patlen == 0) return 1;
    if (patlen > haylen) return 0;
    for (size_t i = 0; i <= haylen - patlen; i++) {
        if (memcmp(hay + i, pat, patlen) == 0) return 1;
    }
    return 0;
}

static int write_line(const unsigned char *data, size_t len, const char *prefix) {
    if (prefix) {
        if (fputs(prefix, stdout) == EOF) return -1;
        if (putc(':', stdout) == EOF) return -1;
    }
    if (len > 0) {
        if (fwrite(data, 1, len, stdout) != len) return -1;
    }
    if (putc('\n', stdout) == EOF) return -1;
    return 0;
}

static void print_usage(void) {
    fprintf(stderr, "usage: grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_usage();
        return 2;
    }

    int prefix_mode = 0;
    int after_terminator = 0;
    const char *pattern = NULL;
    const char **files = malloc((size_t)argc * sizeof *files);
    if (!files) return 2;
    int file_count = 0;

    for (int i = 1; i < argc; i++) {
        if (after_terminator) {
            if (!pattern) {
                pattern = argv[i];
            } else {
                files[file_count++] = argv[i];
            }
        } else if (strcmp(argv[i], "--") == 0) {
            after_terminator = 1;
        } else if (strcmp(argv[i], "--with-filename") == 0) {
            prefix_mode = 1;
        } else if (strcmp(argv[i], "--no-filename") == 0) {
            prefix_mode = -1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            for (const char *p = argv[i] + 1; *p; p++) {
                if (*p == 'H') {
                    prefix_mode = 1;
                } else if (*p == 'h') {
                    prefix_mode = -1;
                } else {
                    free(files);
                    print_usage();
                    return 2;
                }
            }
        } else if (!pattern) {
            pattern = argv[i];
        } else {
            files[file_count++] = argv[i];
        }
    }

    if (!pattern) {
        free(files);
        print_usage();
        return 2;
    }

    size_t patlen = strlen(pattern);
    int use_prefix;
    if (prefix_mode > 0) use_prefix = 1;
    else if (prefix_mode < 0) use_prefix = 0;
    else use_prefix = (file_count >= 2);
    int any_match = 0;
    int any_error = 0;

    if (file_count == 0) {
        const char *prefix = use_prefix ? "(standard input)" : NULL;
        ByteBuf line = {0};
        int rc;
        while ((rc = read_line(stdin, &line)) == 0) {
            if (fixed_match(line.buf, line.len, (const unsigned char *)pattern, patlen)) {
                if (write_line(line.buf, line.len, prefix) != 0) {
                    free(line.buf);
                    free(files);
                    return 2;
                }
                any_match = 1;
            }
        }
        if (rc == -2) {
            fprintf(stderr, "grep: error reading input\n");
            free(line.buf);
            free(files);
            return 2;
        }
        free(line.buf);
    } else {
        for (int i = 0; i < file_count; i++) {
            const char *filename = files[i];

            struct stat st;
            if (stat(filename, &st) != 0) {
                fprintf(stderr, "grep: %s: %s\n", filename, strerror(errno));
                any_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "grep: %s: Is a directory\n", filename);
                any_error = 1;
                continue;
            }

            FILE *fp = fopen(filename, "rb");
            if (!fp) {
                fprintf(stderr, "grep: %s: %s\n", filename, strerror(errno));
                any_error = 1;
                continue;
            }

            ByteBuf line = {0};
            int rc;
            const char *prefix = use_prefix ? filename : NULL;
            while ((rc = read_line(fp, &line)) == 0) {
                if (fixed_match(line.buf, line.len, (const unsigned char *)pattern, patlen)) {
                    if (write_line(line.buf, line.len, prefix) != 0) {
                        free(line.buf);
                        fclose(fp);
                        free(files);
                        return 2;
                    }
                    any_match = 1;
                }
            }
            if (rc == -2) {
                fprintf(stderr, "grep: %s: read error\n", filename);
                free(line.buf);
                fclose(fp);
                any_error = 1;
                continue;
            }
            free(line.buf);
            fclose(fp);
        }
    }

    free(files);

    if (any_error) return 2;
    return any_match ? 0 : 1;
}
