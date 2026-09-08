#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

struct line {
    char *data;
    size_t len;
};

static struct line *lines = NULL;
static size_t line_count = 0;
static size_t line_capacity = 0;

static void die(int code, const char *msg) {
    fprintf(stderr, "new_sort: %s\n", msg);
    exit(code);
}

static void cleanup(void) {
    for (size_t i = 0; i < line_count; i++) {
        free(lines[i].data);
    }
    free(lines);
}

static void *xmalloc(size_t size) {
    void *p = malloc(size ? size : 1);
    if (!p) die(1, "Memory allocation failed");
    return p;
}

static void *xrealloc(void *ptr, size_t size) {
    void *p = realloc(ptr, size);
    if (!p) die(1, "Memory allocation failed");
    return p;
}

static size_t safe_double(size_t cap) {
    if (cap == 0) return 1024;
    if (cap > SIZE_MAX / 2) die(1, "Allocation size overflow");
    return cap * 2;
}

static void add_line(const char *data, size_t len) {
    if (line_count >= line_capacity) {
        size_t new_cap = safe_double(line_capacity);
        if (new_cap > SIZE_MAX / sizeof(struct line)) die(1, "Allocation size overflow");
        lines = xrealloc(lines, new_cap * sizeof(struct line));
        line_capacity = new_cap;
    }
    char *buf = NULL;
    if (len > 0) {
        buf = xmalloc(len);
        memcpy(buf, data, len);
    }
    lines[line_count].data = buf;
    lines[line_count].len = len;
    line_count++;
}

static int compare_lines(const void *a, const void *b) {
    const struct line *la = (const struct line *)a;
    const struct line *lb = (const struct line *)b;
    size_t minlen = la->len < lb->len ? la->len : lb->len;
    const unsigned char *pa = (const unsigned char *)la->data;
    const unsigned char *pb = (const unsigned char *)lb->data;
    for (size_t i = 0; i < minlen; i++) {
        if (pa[i] < pb[i]) return -1;
        if (pa[i] > pb[i]) return 1;
    }
    if (la->len < lb->len) return -1;
    if (la->len > lb->len) return 1;
    return 0;
}

int main(int argc, char *argv[]) {
    (void)argv;
    if (argc > 1) {
        fprintf(stderr, "usage: new_sort\n");
        return 2;
    }

    size_t buf_cap = 0;
    char *buf = NULL;
    size_t buf_len = 0;

    int c;
    while ((c = fgetc(stdin)) != EOF) {
        if (buf_len >= buf_cap) {
            size_t new_cap = safe_double(buf_cap);
            buf = xrealloc(buf, new_cap);
            buf_cap = new_cap;
        }
        if (c == '\n') {
            add_line(buf, buf_len);
            buf_len = 0;
        } else {
            buf[buf_len++] = (char)c;
        }
    }

    if (ferror(stdin)) {
        free(buf);
        cleanup();
        die(1, "Input error");
    }

    if (buf_len > 0) {
        add_line(buf, buf_len);
    }
    free(buf);

    if (line_count > 1) {
        qsort(lines, line_count, sizeof(struct line), compare_lines);
    }

    for (size_t i = 0; i < line_count; i++) {
        if (lines[i].len > 0) {
            if (fwrite(lines[i].data, 1, lines[i].len, stdout) != lines[i].len) {
                cleanup();
                die(1, "Output error");
            }
        }
        if (fputc('\n', stdout) == EOF) {
            cleanup();
            die(1, "Output error");
        }
    }

    if (fflush(stdout) == EOF) {
        cleanup();
        die(1, "Output error");
    }

    cleanup();
    return 0;
}
