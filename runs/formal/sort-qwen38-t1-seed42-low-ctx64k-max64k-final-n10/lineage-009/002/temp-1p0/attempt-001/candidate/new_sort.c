#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>

struct line {
    unsigned char *data;
    size_t len;
};

static int reverse_flag = 0;
static int fold_flag = 0;

static int compare_lines(const void *a, const void *b) {
    const struct line *la = *(const struct line *const *)a;
    const struct line *lb = *(const struct line *const *)b;
    size_t minlen = la->len < lb->len ? la->len : lb->len;
    int cmp = 0;

    if (fold_flag) {
        // Compare with case folding (treat a-z as A-Z)
        for (size_t i = 0; i < minlen; i++) {
            unsigned char ca = la->data[i];
            unsigned char cb = lb->data[i];
            
            // Fold lowercase to uppercase for comparison
            if (ca >= 'a' && ca <= 'z') ca = ca - 'a' + 'A';
            if (cb >= 'a' && cb <= 'z') cb = cb - 'a' + 'A';
            
            if (ca != cb) {
                cmp = (int)ca - (int)cb;
                break;
            }
        }
        
        if (cmp == 0) {
            // All compared bytes are equal after folding
            if (la->len < lb->len) {
                cmp = -1;
            } else if (la->len > lb->len) {
                cmp = 1;
            } else {
                // Same length: use original bytes as tiebreaker
                cmp = memcmp(la->data, lb->data, minlen);
            }
        }
    } else {
        // Normal comparison
        cmp = memcmp(la->data, lb->data, minlen);
        if (cmp == 0) {
            if (la->len < lb->len) {
                cmp = -1;
            } else if (la->len > lb->len) {
                cmp = 1;
            }
        }
    }

    return reverse_flag ? -cmp : cmp;
}

int main(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--reverse") == 0) {
            reverse_flag = 1;
        } else if (strcmp(argv[i], "--ignore-case") == 0) {
            fold_flag = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0' && argv[i][1] != '-') {
            for (const char *p = argv[i] + 1; *p != '\0'; p++) {
                if (*p == 'r') {
                    reverse_flag = 1;
                } else if (*p == 'f') {
                    fold_flag = 1;
                } else {
                    fprintf(stderr, "usage: new_sort [-r | --reverse] [-f | --ignore-case]\n");
                    return 2;
                }
            }
        } else {
            fprintf(stderr, "usage: new_sort [-r | --reverse] [-f | --ignore-case]\n");
            return 2;
        }
    }

    struct line **lines = NULL;
    size_t line_count = 0;
    size_t line_cap = 0;

    unsigned char *cur = NULL;
    size_t cur_len = 0;
    size_t cur_cap = 0;

    enum { CHUNK = 8192 };
    unsigned char *chunk = malloc(CHUNK);
    if (!chunk) {
        fprintf(stderr, "new_sort: out of memory\n");
        return 1;
    }

    int rc = 0;
    int eof = 0;

    while (!eof) {
        size_t n = fread(chunk, 1, CHUNK, stdin);
        if (n == 0) {
            if (ferror(stdin)) {
                fprintf(stderr, "new_sort: read error\n");
                rc = 1;
                goto done;
            }
            eof = 1;
            break;
        }
        for (size_t i = 0; i < n; i++) {
            if (chunk[i] == '\n') {
                if (line_count >= line_cap) {
                    size_t new_cap = line_cap ? line_cap * 2 : 64;
                    if (new_cap < line_cap || new_cap > SIZE_MAX / sizeof(*lines)) {
                        fprintf(stderr, "new_sort: out of memory\n");
                        rc = 1;
                        goto done;
                    }
                    struct line **tmp = realloc(lines, new_cap * sizeof(*lines));
                    if (!tmp) {
                        fprintf(stderr, "new_sort: out of memory\n");
                        rc = 1;
                        goto done;
                    }
                    lines = tmp;
                    line_cap = new_cap;
                }
                struct line *l = malloc(sizeof(*l));
                if (!l) {
                    fprintf(stderr, "new_sort: out of memory\n");
                    rc = 1;
                    goto done;
                }
                if (cur_len == 0) {
                    l->data = NULL;
                    l->len = 0;
                } else {
                    l->data = malloc(cur_len);
                    if (!l->data) {
                        free(l);
                        fprintf(stderr, "new_sort: out of memory\n");
                        rc = 1;
                        goto done;
                    }
                    memcpy(l->data, cur, cur_len);
                    l->len = cur_len;
                }
                lines[line_count++] = l;
                cur_len = 0;
            } else {
                if (cur_len >= cur_cap) {
                    size_t new_cap = cur_cap ? cur_cap * 2 : 256;
                    if (new_cap < cur_cap) {
                        fprintf(stderr, "new_sort: out of memory\n");
                        rc = 1;
                        goto done;
                    }
                    unsigned char *tmp = realloc(cur, new_cap);
                    if (!tmp) {
                        fprintf(stderr, "new_sort: out of memory\n");
                        rc = 1;
                        goto done;
                    }
                    cur = tmp;
                    cur_cap = new_cap;
                }
                cur[cur_len++] = chunk[i];
            }
        }
    }

    if (cur_len > 0) {
        if (line_count >= line_cap) {
            size_t new_cap = line_cap ? line_cap * 2 : 64;
            if (new_cap < line_cap || new_cap > SIZE_MAX / sizeof(*lines)) {
                fprintf(stderr, "new_sort: out of memory\n");
                rc = 1;
                goto done;
            }
            struct line **tmp = realloc(lines, new_cap * sizeof(*lines));
            if (!tmp) {
                fprintf(stderr, "new_sort: out of memory\n");
                rc = 1;
                goto done;
            }
            lines = tmp;
            line_cap = new_cap;
        }
        struct line *l = malloc(sizeof(*l));
        if (!l) {
            fprintf(stderr, "new_sort: out of memory\n");
            rc = 1;
            goto done;
        }
        l->data = malloc(cur_len);
        if (!l->data) {
            free(l);
            fprintf(stderr, "new_sort: out of memory\n");
            rc = 1;
            goto done;
        }
        memcpy(l->data, cur, cur_len);
        l->len = cur_len;
        lines[line_count++] = l;
    }

    free(chunk);
    chunk = NULL;

    if (line_count > 1) {
        qsort(lines, line_count, sizeof(*lines), compare_lines);
    }

    for (size_t i = 0; i < line_count; i++) {
        if (lines[i]->len > 0) {
            if (fwrite(lines[i]->data, 1, lines[i]->len, stdout) != lines[i]->len) {
                fprintf(stderr, "new_sort: write error\n");
                rc = 1;
                goto done;
            }
        }
        if (fputc('\n', stdout) == EOF) {
            fprintf(stderr, "new_sort: write error\n");
            rc = 1;
            goto done;
        }
    }

    if (fflush(stdout) == EOF) {
        fprintf(stderr, "new_sort: write error\n");
        rc = 1;
        goto done;
    }

done:
    for (size_t i = 0; i < line_count; i++) {
        free(lines[i]->data);
        free(lines[i]);
    }
    free(lines);
    free(cur);
    free(chunk);
    return rc;
}
