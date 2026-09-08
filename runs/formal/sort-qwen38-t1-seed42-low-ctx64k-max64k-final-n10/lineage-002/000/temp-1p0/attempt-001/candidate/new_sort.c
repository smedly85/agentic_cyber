#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    uint8_t *data;
    size_t len;
    size_t cap;
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

static int line_compare(const void *a, const void *b) {
    const Line *la = (const Line *)a;
    const Line *lb = (const Line *)b;
    size_t min_len = la->len < lb->len ? la->len : lb->len;
    if (min_len > 0) {
        int cmp = memcmp(la->data, lb->data, min_len);
        if (cmp < 0) return -1;
        if (cmp > 0) return 1;
    }
    if (la->len < lb->len) return -1;
    if (la->len > lb->len) return 1;
    return 0;
}

static void free_all(Lines *lines) {
    for (size_t i = 0; i < lines->count; i++)
        free(lines->lines[i].data);
    free(lines->lines);
}

int main(int argc, char *argv[]) {
    (void)argv;
    if (argc > 1) {
        fprintf(stderr, "usage: new_sort\n");
        return 2;
    }

    Lines lines = {NULL, 0, 0};
    Line cur = {NULL, 0, 0};

    int c;
    while ((c = fgetc(stdin)) != EOF) {
        if (c == '\n') {
            lines_push(&lines, &cur);
            cur = (Line){NULL, 0, 0};
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
        lines_push(&lines, &cur);
    }

    if (lines.count > 1) {
        qsort(lines.lines, lines.count, sizeof(Line), line_compare);
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
