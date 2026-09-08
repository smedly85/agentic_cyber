#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef struct {
    unsigned char *data;
    size_t len;
} Line;

static void die(const char *msg) {
    fprintf(stderr, "new_sort: %s\n", msg);
    exit(1);
}

static int reverse_flag = 0;
static int ignore_case_flag = 0;

static unsigned char fold_byte(unsigned char c) {
    if (c >= 'a' && c <= 'z') return c - 'a' + 'A';
    return c;
}

static int cmp_lines(const void *a, const void *b) {
    const Line *la = (const Line *)a;
    const Line *lb = (const Line *)b;
    int result = 0;

    if (ignore_case_flag) {
        size_t minlen = la->len < lb->len ? la->len : lb->len;
        for (size_t i = 0; i < minlen; i++) {
            unsigned char fa = fold_byte(la->data[i]);
            unsigned char fb = fold_byte(lb->data[i]);
            if (fa < fb) { result = -1; break; }
            if (fa > fb) { result = 1; break; }
        }
        if (result == 0) {
            if (la->len < lb->len) result = -1;
            else if (la->len > lb->len) result = 1;
        }
        if (result == 0) {
            for (size_t i = 0; i < la->len; i++) {
                if (la->data[i] < lb->data[i]) { result = -1; break; }
                if (la->data[i] > lb->data[i]) { result = 1; break; }
            }
        }
    } else {
        size_t minlen = la->len < lb->len ? la->len : lb->len;
        for (size_t i = 0; i < minlen; i++) {
            if (la->data[i] < lb->data[i]) { result = -1; break; }
            if (la->data[i] > lb->data[i]) { result = 1; break; }
        }
        if (result == 0) {
            if (la->len < lb->len) result = -1;
            else if (la->len > lb->len) result = 1;
        }
    }

    return reverse_flag ? -result : result;
}

static void usage(void) {
    fprintf(stderr, "usage: new_sort [-r] [-f] [--reverse] [--ignore-case]\n");
    exit(2);
}

static int parse_args(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--reverse") == 0) {
            reverse_flag = 1;
        } else if (strcmp(argv[i], "--ignore-case") == 0) {
            ignore_case_flag = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            for (const char *p = argv[i] + 1; *p; p++) {
                if (*p == 'r') {
                    reverse_flag = 1;
                } else if (*p == 'f') {
                    ignore_case_flag = 1;
                } else {
                    usage();
                }
            }
        } else {
            usage();
        }
    }
    return 0;
}

int main(int argc, char *argv[]) {
    parse_args(argc, argv);

    Line *lines = NULL;
    size_t line_count = 0;
    size_t line_cap = 0;

    unsigned char *buf = NULL;
    size_t buf_len = 0;
    size_t buf_cap = 0;

    int ch = fgetc(stdin);

    while (ch != EOF) {
        buf_len = 0;

        while (ch != EOF && ch != '\n') {
            if (buf_len == buf_cap) {
                size_t new_cap = 0;
                if (buf_cap == 0) {
                    new_cap = 256;
                } else if (buf_cap > SIZE_MAX / 2) {
                    die("allocation size overflow");
                } else {
                    new_cap = buf_cap * 2;
                }
                unsigned char *tmp = realloc(buf, new_cap);
                if (!tmp) die("memory allocation failure");
                buf = tmp;
                buf_cap = new_cap;
            }
            buf[buf_len++] = (unsigned char)ch;
            ch = fgetc(stdin);
        }

        if (ferror(stdin)) die("input error");

        if (buf_len > 0 || ch == '\n') {
            if (line_count == line_cap) {
                size_t new_cap = 0;
                if (line_cap == 0) {
                    new_cap = 64;
                } else if (line_cap > SIZE_MAX / (2 * sizeof(Line))) {
                    die("allocation size overflow");
                } else {
                    new_cap = line_cap * 2;
                }
                Line *tmp = realloc(lines, new_cap * sizeof(Line));
                if (!tmp) die("memory allocation failure");
                lines = tmp;
                line_cap = new_cap;
            }

            unsigned char *line_data = NULL;
            if (buf_len > 0) {
                line_data = malloc(buf_len);
                if (!line_data) die("memory allocation failure");
                memcpy(line_data, buf, buf_len);
            }
            lines[line_count].data = line_data;
            lines[line_count].len = buf_len;
            line_count++;
        }

        if (ch == EOF) break;

        ch = fgetc(stdin);
    }

    if (ferror(stdin)) die("input error");

    if (line_count > 1) {
        qsort(lines, line_count, sizeof(Line), cmp_lines);
    }

    for (size_t i = 0; i < line_count; i++) {
        if (lines[i].len > 0) {
            if (fwrite(lines[i].data, 1, lines[i].len, stdout) != lines[i].len) {
                die("output error");
            }
        }
        if (fputc('\n', stdout) == EOF) {
            die("output error");
        }
    }

    if (fflush(stdout) != 0) {
        die("output error");
    }

    for (size_t i = 0; i < line_count; i++) {
        free(lines[i].data);
    }
    free(lines);
    free(buf);

    return 0;
}
