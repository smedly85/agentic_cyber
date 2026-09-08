#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef struct {
    const unsigned char *data;
    size_t len;
} Line;

static int reverse_flag = 0;

static int line_cmp(const void *pa, const void *pb) {
    const Line *a = (const Line *)pa;
    const Line *b = (const Line *)pb;
    int dir = reverse_flag ? -1 : 1;
    size_t minlen = a->len < b->len ? a->len : b->len;
    for (size_t i = 0; i < minlen; i++) {
        if (a->data[i] != b->data[i])
            return (a->data[i] < b->data[i] ? -1 : 1) * dir;
    }
    if (a->len < b->len) return -dir;
    if (a->len > b->len) return dir;
    return 0;
}

int main(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--reverse") == 0) {
            reverse_flag = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            if (arg[1] == '-') {
                fprintf(stderr, "usage: new_sort [-r | --reverse]\n");
                return 2;
            }
            for (const char *p = arg + 1; *p; p++) {
                if (*p != 'r') {
                    fprintf(stderr, "usage: new_sort [-r | --reverse]\n");
                    return 2;
                }
            }
            reverse_flag = 1;
        } else {
            fprintf(stderr, "usage: new_sort [-r | --reverse]\n");
            return 2;
        }
    }

    unsigned char *buf = NULL;
    size_t buf_len = 0;
    size_t buf_cap = 0;
    unsigned char rbuf[8192];
    size_t n;
    int read_err = 0;

    while ((n = fread(rbuf, 1, sizeof(rbuf), stdin)) > 0) {
        if (buf_len + n > buf_cap) {
            size_t new_cap;
            if (buf_cap > SIZE_MAX / 2) {
                if (buf_len + n > SIZE_MAX) { read_err = 1; break; }
                new_cap = buf_len + n;
            } else {
                new_cap = buf_cap ? buf_cap * 2 : sizeof(rbuf);
                if (new_cap < buf_len + n) new_cap = buf_len + n;
            }
            unsigned char *tmp = realloc(buf, new_cap);
            if (!tmp) { read_err = 1; break; }
            buf = tmp;
            buf_cap = new_cap;
        }
        memcpy(buf + buf_len, rbuf, n);
        buf_len += n;
    }
    if (ferror(stdin)) read_err = 1;

    if (read_err) {
        fprintf(stderr, "new_sort: %s\n",
                ferror(stdin) ? "read error" : "out of memory");
        free(buf);
        return 1;
    }

    size_t line_count = 0;
    if (buf_len > 0) {
        for (size_t i = 0; i < buf_len; i++)
            if (buf[i] == '\n') line_count++;
        if (buf[buf_len - 1] != '\n') line_count++;
    }

    Line *lines = NULL;
    if (line_count > 0) {
        if (line_count > SIZE_MAX / sizeof(Line)) {
            fprintf(stderr, "new_sort: out of memory\n");
            free(buf);
            return 1;
        }
        lines = malloc(line_count * sizeof(Line));
        if (!lines) {
            fprintf(stderr, "new_sort: out of memory\n");
            free(buf);
            return 1;
        }
    }

    size_t idx = 0;
    size_t start = 0;
    for (size_t i = 0; i < buf_len; i++) {
        if (buf[i] == '\n') {
            lines[idx].data = buf + start;
            lines[idx].len = i - start;
            idx++;
            start = i + 1;
        }
    }
    if (start < buf_len) {
        lines[idx].data = buf + start;
        lines[idx].len = buf_len - start;
        idx++;
    }

    if (line_count > 1)
        qsort(lines, line_count, sizeof(Line), line_cmp);

    int write_err = 0;
    for (size_t i = 0; i < line_count; i++) {
        if (lines[i].len > 0) {
            if (fwrite(lines[i].data, 1, lines[i].len, stdout) != lines[i].len) {
                write_err = 1;
                break;
            }
        }
        if (fputc('\n', stdout) == EOF) {
            write_err = 1;
            break;
        }
    }
    if (!write_err && fflush(stdout) != 0)
        write_err = 1;

    free(lines);
    free(buf);

    if (write_err) {
        fprintf(stderr, "new_sort: write error\n");
        return 1;
    }
    return 0;
}
