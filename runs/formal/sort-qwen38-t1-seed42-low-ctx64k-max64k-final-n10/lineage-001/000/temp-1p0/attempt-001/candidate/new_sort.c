#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef struct {
    unsigned char *data;
    size_t len;
    size_t cap;
} Line;

static void free_all(Line *lines, size_t count) {
    for (size_t i = 0; i < count; i++)
        free(lines[i].data);
    free(lines);
}

static int compare_lines(const Line *a, const Line *b) {
    size_t min_len = a->len < b->len ? a->len : b->len;
    if (min_len > 0) {
        int r = memcmp(a->data, b->data, min_len);
        if (r != 0) return r < 0 ? -1 : 1;
    }
    if (a->len < b->len) return -1;
    if (a->len > b->len) return 1;
    return 0;
}

static int qsort_cmp(const void *pa, const void *pb) {
    const Line *a = (const Line *)pa;
    const Line *b = (const Line *)pb;
    return compare_lines(a, b);
}

static int grow_collection(Line **lines, size_t *cap) {
    size_t new_cap;
    if (*cap == 0) {
        new_cap = 8;
    } else {
        if (*cap > SIZE_MAX / (2 * sizeof(Line))) return -1;
        new_cap = *cap * 2;
    }
    Line *nl = realloc(*lines, new_cap * sizeof(Line));
    if (!nl) return -1;
    *lines = nl;
    *cap = new_cap;
    return 0;
}

static int grow_line(Line *l) {
    size_t new_cap;
    if (l->cap == 0) {
        new_cap = 64;
    } else {
        if (l->cap > SIZE_MAX / 2) return -1;
        new_cap = l->cap * 2;
    }
    unsigned char *nd = realloc(l->data, new_cap);
    if (!nd) return -1;
    l->data = nd;
    l->cap = new_cap;
    return 0;
}

static int read_all(FILE *in, Line **out_lines, size_t *out_count) {
    Line *lines = NULL;
    size_t count = 0;
    size_t cap = 0;
    Line cur = {NULL, 0, 0};

    int c;
    while ((c = fgetc(in)) != EOF) {
        unsigned char byte = (unsigned char)c;
        if (byte == '\n') {
            if (count == cap) {
                if (grow_collection(&lines, &cap) != 0) goto fail;
            }
            lines[count].data = cur.data;
            lines[count].len = cur.len;
            lines[count].cap = cur.cap;
            count++;
            cur.data = NULL;
            cur.len = 0;
            cur.cap = 0;
        } else {
            if (cur.len == cur.cap) {
                if (grow_line(&cur) != 0) goto fail;
            }
            cur.data[cur.len++] = byte;
        }
    }

    if (ferror(in)) goto fail;

    if (cur.len > 0) {
        if (count == cap) {
            if (grow_collection(&lines, &cap) != 0) goto fail;
        }
        lines[count].data = cur.data;
        lines[count].len = cur.len;
        lines[count].cap = cur.cap;
        count++;
    } else {
        free(cur.data);
    }

    *out_lines = lines;
    *out_count = count;
    return 0;

fail:
    free(cur.data);
    free_all(lines, count);
    return -1;
}

static int write_all(Line *lines, size_t count) {
    for (size_t i = 0; i < count; i++) {
        if (lines[i].len > 0) {
            if (fwrite(lines[i].data, 1, lines[i].len, stdout) != lines[i].len)
                return -1;
        }
        if (fputc('\n', stdout) != '\n')
            return -1;
    }
    if (ferror(stdout)) return -1;
    return 0;
}

int main(int argc, char *argv[]) {
    (void)argv;
    if (argc != 1) {
        fprintf(stderr, "usage: new_sort\n");
        return 2;
    }

    Line *lines = NULL;
    size_t count = 0;

    if (read_all(stdin, &lines, &count) != 0) {
        fprintf(stderr, "new_sort: error reading input\n");
        return 1;
    }

    if (count > 1)
        qsort(lines, count, sizeof(Line), qsort_cmp);

    if (write_all(lines, count) != 0) {
        fprintf(stderr, "new_sort: error writing output\n");
        free_all(lines, count);
        return 1;
    }

    free_all(lines, count);
    return 0;
}
