#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int reverse = 0;
static int ignore_case = 0;
static int unique_mode = 0;
static int check_mode = 0;

typedef struct {
    uint8_t *data;
    size_t len;
    size_t cap;
    size_t input_index;
} Line;

typedef struct {
    Line *lines;
    size_t count;
    size_t cap;
} Lines;

static void die(const char *msg) {
    fprintf(stderr, "new_sort: %s\n", msg);
    exit(1);
}

static void *xrealloc(void *ptr, size_t size) {
    if (size == 0) { free(ptr); return NULL; }
    void *p = realloc(ptr, size);
    if (!p) die("memory allocation failure");
    return p;
}

static void line_ensure(Line *line, size_t needed) {
    if (line->cap >= needed) return;
    size_t new_cap = line->cap ? line->cap : 64;
    while (new_cap < needed) {
        if (new_cap > (size_t)-1 / 2) { new_cap = needed; break; }
        new_cap *= 2;
    }
    line->data = xrealloc(line->data, new_cap);
    line->cap = new_cap;
}

static void lines_push(Lines *lines, Line *line) {
    if (lines->count == lines->cap) {
        size_t new_cap = lines->cap ? lines->cap : 16;
        if (new_cap > (size_t)-1 / 2) new_cap = (size_t)-1;
        else new_cap *= 2;
        if (new_cap > (size_t)-1 / sizeof(Line)) die("allocation size overflow");
        lines->cap = new_cap;
        lines->lines = xrealloc(lines->lines, new_cap * sizeof(Line));
    }
    lines->lines[lines->count++] = *line;
}

static uint8_t fold_byte(uint8_t b) {
    if (b >= 'a' && b <= 'z') return (uint8_t)(b - 'a' + 'A');
    return b;
}

static int line_compare(const void *a, const void *b) {
    const Line *la = (const Line *)a;
    const Line *lb = (const Line *)b;
    size_t min_len = la->len < lb->len ? la->len : lb->len;
    int cmp = 0;

    if (min_len > 0) {
        if (ignore_case) {
            for (size_t i = 0; i < min_len; i++) {
                uint8_t fa = fold_byte(la->data[i]);
                uint8_t fb = fold_byte(lb->data[i]);
                if (fa != fb) {
                    cmp = (fa < fb) ? -1 : 1;
                    break;
                }
            }
            if (cmp == 0) {
                cmp = memcmp(la->data, lb->data, min_len);
                if (cmp < 0) cmp = -1;
                else if (cmp > 0) cmp = 1;
                else cmp = 0;
            }
        } else {
            cmp = memcmp(la->data, lb->data, min_len);
            if (cmp < 0) cmp = -1;
            else if (cmp > 0) cmp = 1;
            else cmp = 0;
        }
    }

    if (cmp == 0) {
        if (la->len < lb->len) cmp = -1;
        else if (la->len > lb->len) cmp = 1;
    }

    if (reverse) cmp = -cmp;
    return cmp;
}

static int lines_equal(const Line *a, const Line *b) {
    if (a->len != b->len) return 0;
    if (a->len == 0) return 1;
    if (ignore_case) {
        for (size_t i = 0; i < a->len; i++) {
            if (fold_byte(a->data[i]) != fold_byte(b->data[i])) return 0;
        }
        return 1;
    }
    return memcmp(a->data, b->data, a->len) == 0;
}

static void free_all(Lines *lines) {
    for (size_t i = 0; i < lines->count; i++)
        free(lines->lines[i].data);
    free(lines->lines);
}

int main(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--reverse") == 0) {
            reverse = 1;
        } else if (strcmp(argv[i], "--ignore-case") == 0) {
            ignore_case = 1;
        } else if (strcmp(argv[i], "--unique") == 0) {
            unique_mode = 1;
        } else if (strcmp(argv[i], "--check") == 0) {
            check_mode = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0' && argv[i][1] != '-') {
            for (size_t j = 1; argv[i][j] != '\0'; j++) {
                if (argv[i][j] == 'r') {
                    reverse = 1;
                } else if (argv[i][j] == 'f') {
                    ignore_case = 1;
                } else if (argv[i][j] == 'u') {
                    unique_mode = 1;
                } else if (argv[i][j] == 'c') {
                    check_mode = 1;
                } else {
                    fprintf(stderr, "usage: new_sort [-rcfu | --reverse | --ignore-case | --unique | --check]\n");
                    return 2;
                }
            }
        } else {
            fprintf(stderr, "usage: new_sort [-rcfu | --reverse | --ignore-case | --unique | --check]\n");
            return 2;
        }
    }

    Lines lines = {NULL, 0, 0};
    Line cur = {NULL, 0, 0, 0};

    int c;
    size_t input_index = 0;
    while ((c = fgetc(stdin)) != EOF) {
        if (c == '\n') {
            cur.input_index = input_index++;
            lines_push(&lines, &cur);
            cur = (Line){NULL, 0, 0, 0};
        } else {
            line_ensure(&cur, cur.len + 1);
            cur.data[cur.len++] = (uint8_t)c;
        }
    }

    if (ferror(stdin)) {
        free_all(&lines);
        free(cur.data);
        die("input read error");
    }

    if (cur.len > 0) {
        cur.input_index = input_index++;
        lines_push(&lines, &cur);
    }

    if (check_mode) {
        for (size_t i = 1; i < lines.count; i++) {
            int cmp = line_compare(&lines.lines[i - 1], &lines.lines[i]);
            int violation = unique_mode ? (cmp >= 0) : (cmp > 0);
            if (violation) {
                fprintf(stderr, "new_sort: -:%zu: disorder: ", i + 1);
                fwrite(lines.lines[i].data, 1, lines.lines[i].len, stderr);
                fputc('\n', stderr);
                free_all(&lines);
                return 1;
            }
        }
        free_all(&lines);
        return 0;
    }

    for (size_t i = 0; i < lines.count; i++)
        lines.lines[i].input_index = i;

    if (lines.count > 1) {
        qsort(lines.lines, lines.count, sizeof(Line), line_compare);
        if (unique_mode) {
            size_t new_count = 0;
            size_t i = 0;
            while (i < lines.count) {
                size_t j = i + 1;
                while (j < lines.count && lines_equal(&lines.lines[i], &lines.lines[j]))
                    j++;
                size_t best = i;
                for (size_t k = i + 1; k < j; k++) {
                    if (lines.lines[k].input_index < lines.lines[best].input_index)
                        best = k;
                }
                for (size_t k = i; k < j; k++) {
                    if (k != best) free(lines.lines[k].data);
                }
                lines.lines[new_count++] = lines.lines[best];
                i = j;
            }
            lines.count = new_count;
        }
    }

    for (size_t i = 0; i < lines.count; i++) {
        if (lines.lines[i].len > 0) {
            if (fwrite(lines.lines[i].data, 1, lines.lines[i].len, stdout)
                != lines.lines[i].len) {
                free_all(&lines);
                die("output write error");
            }
        }
        if (fputc('\n', stdout) == EOF) {
            free_all(&lines);
            die("output write error");
        }
    }

    if (fflush(stdout) == EOF) {
        free_all(&lines);
        die("output write error");
    }

    free_all(&lines);
    return 0;
}
