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

static int mul_overflow(size_t a, size_t b, size_t *result) {
    if (a != 0 && b > SIZE_MAX / a) return 1;
    *result = a * b;
    return 0;
}

static void *xrealloc(void *ptr, size_t size) {
    void *p = realloc(ptr, size);
    if (!p) die("out of memory");
    return p;
}

static Line *lines = NULL;
static size_t line_count = 0;
static size_t line_cap = 0;

static void add_line(const unsigned char *data, size_t len) {
    if (line_count == line_cap) {
        size_t new_cap;
        if (line_cap == 0) {
            new_cap = 16;
        } else {
            if (mul_overflow(line_cap, 2, &new_cap)) die("out of memory");
        }
        size_t alloc_size;
        if (mul_overflow(new_cap, sizeof(Line), &alloc_size)) die("out of memory");
        lines = (Line *)xrealloc(lines, alloc_size);
        line_cap = new_cap;
    }
    unsigned char *buf = NULL;
    if (len > 0) {
        buf = (unsigned char *)xrealloc(NULL, len);
        memcpy(buf, data, len);
    }
    lines[line_count].data = buf;
    lines[line_count].len = len;
    line_count++;
}

static void read_lines(void) {
    unsigned char *cur = NULL;
    size_t cur_len = 0;
    size_t cur_cap = 0;

    for (;;) {
        int c = fgetc(stdin);
        if (c == EOF) {
            if (ferror(stdin)) die("read error");
            if (cur_len > 0) {
                add_line(cur, cur_len);
            }
            break;
        }
        if (c == '\n') {
            add_line(cur, cur_len);
            cur_len = 0;
        } else {
            if (cur_len == cur_cap) {
                size_t new_cap;
                if (cur_cap == 0) {
                    new_cap = 256;
                } else {
                    if (mul_overflow(cur_cap, 2, &new_cap)) die("out of memory");
                }
                cur = (unsigned char *)xrealloc(cur, new_cap);
                cur_cap = new_cap;
            }
            cur[cur_len++] = (unsigned char)c;
        }
    }
    free(cur);
}

static int compare_lines(const void *a, const void *b) {
    const Line *la = (const Line *)a;
    const Line *lb = (const Line *)b;
    size_t min_len = la->len < lb->len ? la->len : lb->len;

    for (size_t i = 0; i < min_len; i++) {
        unsigned char ba = la->data[i];
        unsigned char bb = lb->data[i];
        if (ba != bb)
            return (ba < bb) ? -1 : 1;
    }
    if (la->len < lb->len) return -1;
    if (la->len > lb->len) return 1;
    return 0;
}

static void write_lines(void) {
    for (size_t i = 0; i < line_count; i++) {
        if (lines[i].len > 0) {
            if (fwrite(lines[i].data, 1, lines[i].len, stdout) != lines[i].len)
                die("write error");
        }
        if (fputc('\n', stdout) == EOF)
            die("write error");
    }
    if (fflush(stdout) != 0)
        die("write error");
}

static void free_all(void) {
    for (size_t i = 0; i < line_count; i++) {
        free(lines[i].data);
    }
    free(lines);
}

int main(int argc, char **argv) {
    if (argc != 1) {
        fprintf(stderr, "usage: new_sort\n");
        return 2;
    }

    read_lines();

    if (line_count > 1)
        qsort(lines, line_count, sizeof(Line), compare_lines);

    write_lines();
    free_all();
    return 0;
}
