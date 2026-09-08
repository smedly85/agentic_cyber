#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef struct {
    unsigned char *data;
    size_t len;
} Line;

typedef struct {
    Line *lines;
    size_t count;
    size_t cap;
} LineCollection;

static void collection_free(LineCollection *c) {
    for (size_t i = 0; i < c->count; i++) {
        free(c->lines[i].data);
    }
    free(c->lines);
}

static int collection_push(LineCollection *c, const unsigned char *data, size_t len) {
    if (c->count == c->cap) {
        size_t newcap;
        if (c->cap == 0) {
            newcap = 64;
        } else {
            if (c->cap > SIZE_MAX / 2) return -1;
            newcap = c->cap * 2;
        }
        if (newcap > SIZE_MAX / sizeof(Line)) return -1;
        Line *nl = realloc(c->lines, newcap * sizeof(Line));
        if (!nl) return -1;
        c->lines = nl;
        c->cap = newcap;
    }
    unsigned char *buf = NULL;
    if (len > 0) {
        buf = malloc(len);
        if (!buf) return -1;
        memcpy(buf, data, len);
    }
    c->lines[c->count].data = buf;
    c->lines[c->count].len = len;
    c->count++;
    return 0;
}

static int line_buf_append(unsigned char **buf, size_t *len, size_t *cap, unsigned char byte) {
    if (*len == *cap) {
        size_t newcap;
        if (*cap == 0) {
            newcap = 256;
        } else {
            if (*cap > SIZE_MAX / 2) return -1;
            newcap = *cap * 2;
        }
        if (newcap > SIZE_MAX) return -1;
        unsigned char *nb = realloc(*buf, newcap);
        if (!nb) return -1;
        *buf = nb;
        *cap = newcap;
    }
    (*buf)[(*len)++] = byte;
    return 0;
}

static int compare_lines(const void *a, const void *b) {
    const Line *la = (const Line *)a;
    const Line *lb = (const Line *)b;
    size_t minlen = la->len < lb->len ? la->len : lb->len;
    int cmp = (int)memcmp(la->data, lb->data, minlen);
    if (cmp != 0) return cmp;
    if (la->len < lb->len) return -1;
    if (la->len > lb->len) return 1;
    return 0;
}

static int read_all_lines(LineCollection *c) {
    unsigned char *buf = NULL;
    size_t len = 0, cap = 0;

    for (;;) {
        int ch = fgetc(stdin);
        if (ch == EOF) {
            if (ferror(stdin)) {
                free(buf);
                return -1;
            }
            if (len > 0) {
                if (collection_push(c, buf, len) != 0) {
                    free(buf);
                    return -1;
                }
            }
            free(buf);
            return 0;
        }
        if (ch == '\n') {
            if (collection_push(c, buf, len) != 0) {
                free(buf);
                return -1;
            }
            len = 0;
        } else {
            if (line_buf_append(&buf, &len, &cap, (unsigned char)ch) != 0) {
                free(buf);
                return -1;
            }
        }
    }
}

static int write_all_lines(const LineCollection *c) {
    for (size_t i = 0; i < c->count; i++) {
        const unsigned char *data = c->lines[i].data;
        size_t len = c->lines[i].len;
        if (len > 0) {
            if (fwrite(data, 1, len, stdout) != len) return -1;
        }
        if (fputc('\n', stdout) == EOF) return -1;
    }
    if (fflush(stdout) != 0) return -1;
    return 0;
}

int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;
    
    if (argc != 1) {
        fprintf(stderr, "usage: new_sort\n");
        return 2;
    }

    LineCollection c = {NULL, 0, 0};
    if (read_all_lines(&c) != 0) {
        fprintf(stderr, "new_sort: error reading input\n");
        collection_free(&c);
        return 1;
    }

    if (c.count > 1) {
        qsort(c.lines, c.count, sizeof(Line), compare_lines);
    }

    if (write_all_lines(&c) != 0) {
        fprintf(stderr, "new_sort: error writing output\n");
        collection_free(&c);
        return 1;
    }

    collection_free(&c);
    return 0;
}
