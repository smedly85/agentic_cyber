#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef struct {
    unsigned char *data;
    size_t len;
    size_t input_index;
} Line;

typedef struct {
    Line *lines;
    size_t count;
    size_t cap;
} LineCollection;

static int g_reverse = 0;
static int g_ignore_case = 0;
static int g_unique = 0;

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
    c->lines[c->count].input_index = c->count;
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

static unsigned char fold_byte(unsigned char c) {
    if (c >= 'a' && c <= 'z') return c - 'a' + 'A';
    return c;
}

static int compare_lines(const void *a, const void *b) {
    const Line *la = (const Line *)a;
    const Line *lb = (const Line *)b;
    int result;

    if (g_ignore_case) {
        size_t minlen = la->len < lb->len ? la->len : lb->len;
        int cmp = 0;
        for (size_t i = 0; i < minlen; i++) {
            unsigned char fa = fold_byte(la->data[i]);
            unsigned char fb = fold_byte(lb->data[i]);
            if (fa != fb) {
                cmp = (int)fa - (int)fb;
                break;
            }
        }
        if (cmp != 0) {
            result = cmp < 0 ? -1 : 1;
        } else if (la->len < lb->len) {
            result = -1;
        } else if (la->len > lb->len) {
            result = 1;
        } else {
            int cmp2 = (int)memcmp(la->data, lb->data, la->len);
            result = cmp2 < 0 ? -1 : (cmp2 > 0 ? 1 : 0);
        }
    } else {
        size_t minlen = la->len < lb->len ? la->len : lb->len;
        int cmp = (int)memcmp(la->data, lb->data, minlen);
        if (cmp != 0) {
            result = cmp < 0 ? -1 : 1;
        } else if (la->len < lb->len) {
            result = -1;
        } else if (la->len > lb->len) {
            result = 1;
        } else {
            result = 0;
        }
    }

    return g_reverse ? -result : result;
}

static int lines_equal(const Line *a, const Line *b) {
    if (a->len != b->len) return 0;
    if (g_ignore_case) {
        for (size_t i = 0; i < a->len; i++) {
            if (fold_byte(a->data[i]) != fold_byte(b->data[i])) return 0;
        }
    } else {
        if (a->len > 0 && memcmp(a->data, b->data, a->len) != 0) return 0;
    }
    return 1;
}

static void dedup_inplace(LineCollection *c) {
    size_t n = 0;
    size_t i = 0;
    while (i < c->count) {
        size_t best = i;
        size_t j = i + 1;
        while (j < c->count && lines_equal(&c->lines[i], &c->lines[j])) {
            if (c->lines[j].input_index < c->lines[best].input_index) {
                best = j;
            }
            j++;
        }
        Line kept = c->lines[best];
        for (size_t k = i; k < j; k++) {
            if (k != best) free(c->lines[k].data);
        }
        c->lines[n] = kept;
        n++;
        i = j;
    }
    c->count = n;
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

static int parse_arg(const char *arg) {
    if (strcmp(arg, "--reverse") == 0) {
        g_reverse = 1;
        return 0;
    }
    if (strcmp(arg, "--ignore-case") == 0) {
        g_ignore_case = 1;
        return 0;
    }
    if (strcmp(arg, "--unique") == 0) {
        g_unique = 1;
        return 0;
    }
    if (arg[0] == '-' && arg[1] != '\0' && arg[1] != '-') {
        for (const char *p = arg + 1; *p; p++) {
            if (*p == 'r') {
                g_reverse = 1;
            } else if (*p == 'f') {
                g_ignore_case = 1;
            } else if (*p == 'u') {
                g_unique = 1;
            } else {
                return -1;
            }
        }
        return 0;
    }
    return -1;
}

int main(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        if (parse_arg(argv[i]) != 0) {
            fprintf(stderr, "usage: new_sort [-r] [-f] [-u] [--reverse] [--ignore-case] [--unique]\n");
            return 2;
        }
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

    if (g_unique && c.count > 1) {
        dedup_inplace(&c);
    }

    if (write_all_lines(&c) != 0) {
        fprintf(stderr, "new_sort: error writing output\n");
        collection_free(&c);
        return 1;
    }

    collection_free(&c);
    return 0;
}
