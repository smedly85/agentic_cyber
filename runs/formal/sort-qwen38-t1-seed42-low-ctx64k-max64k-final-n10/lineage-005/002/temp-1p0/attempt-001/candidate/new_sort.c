#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

typedef struct {
    unsigned char *data;
    size_t len;
} line_t;

static int reverse_order = 0;
static int ignore_case = 0;

static unsigned char fold_byte(unsigned char c) {
    if (c >= 'a' && c <= 'z')
        return c - ('a' - 'A');
    return c;
}

static int cmp_lines(const void *a, const void *b) {
    const line_t *la = (const line_t *)a;
    const line_t *lb = (const line_t *)b;
    int result = 0;
    size_t minlen = la->len < lb->len ? la->len : lb->len;

    if (ignore_case) {
        for (size_t i = 0; i < minlen; i++) {
            unsigned char fa = fold_byte(la->data[i]);
            unsigned char fb = fold_byte(lb->data[i]);
            if (fa != fb) {
                result = (int)fa - (int)fb;
                break;
            }
        }
        if (result == 0) {
            int cmp = memcmp(la->data, lb->data, minlen);
            if (cmp != 0) {
                result = cmp;
            } else {
                if (la->len < lb->len) result = -1;
                else if (la->len > lb->len) result = 1;
            }
        }
    } else {
        int cmp = memcmp(la->data, lb->data, minlen);
        if (cmp != 0) {
            result = cmp;
        } else {
            if (la->len < lb->len) result = -1;
            else if (la->len > lb->len) result = 1;
        }
    }

    return reverse_order ? -result : result;
}

int main(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--reverse") == 0) {
            reverse_order = 1;
        } else if (strcmp(arg, "--ignore-case") == 0) {
            ignore_case = 1;
        } else if (arg[0] == '-' && arg[1] != '\0' && arg[1] != '-') {
            for (size_t j = 1; arg[j] != '\0'; j++) {
                if (arg[j] == 'r') {
                    reverse_order = 1;
                } else if (arg[j] == 'f') {
                    ignore_case = 1;
                } else {
                    fprintf(stderr, "hey, use: new_sort [-r] [-f] [--reverse] [--ignore-case]\n");
                    return 2;
                }
            }
        } else {
            fprintf(stderr, "hey, use: new_sort [-r] [-f] [--reverse] [--ignore-case]\n");
            return 2;
        }
    }

    line_t *lines = NULL;
    size_t count = 0;
    size_t capacity = 0;

    unsigned char *buffer = NULL;
    size_t buffer_capacity = 0;
    size_t buffer_len = 0;

    int c;
    while ((c = getchar()) != EOF) {
        if (c == '\n') {
            if (buffer == NULL) {
                buffer = malloc(1);
                if (buffer == NULL) {
                    fprintf(stderr, "new_sort: out of memory\n");
                    return 1;
                }
                buffer[0] = '\0';
                buffer_len = 0;
            }

            if (count >= capacity) {
                size_t new_capacity = capacity == 0 ? 16 : capacity * 2;
                if (new_capacity <= capacity) {
                    fprintf(stderr, "new_sort: out of memory\n");
                    free(buffer);
                    return 1;
                }
                line_t *new_lines = realloc(lines, new_capacity * sizeof(line_t));
                if (new_lines == NULL) {
                    fprintf(stderr, "new_sort: out of memory\n");
                    free(buffer);
                    return 1;
                }
                lines = new_lines;
                capacity = new_capacity;
            }

            lines[count].data = buffer;
            lines[count].len = buffer_len;
            count++;

            buffer = NULL;
            buffer_capacity = 0;
            buffer_len = 0;
        } else {
            if (buffer_len >= buffer_capacity) {
                size_t new_capacity = buffer_capacity == 0 ? 256 : buffer_capacity * 2;
                if (new_capacity <= buffer_capacity) {
                    fprintf(stderr, "new_sort: out of memory\n");
                    if (buffer != NULL) {
                        free(buffer);
                    }
                    return 1;
                }
                unsigned char *new_buffer = realloc(buffer, new_capacity);
                if (new_buffer == NULL) {
                    fprintf(stderr, "new_sort: out of memory\n");
                    free(buffer);
                    return 1;
                }
                buffer = new_buffer;
                buffer_capacity = new_capacity;
            }
            buffer[buffer_len++] = (unsigned char)c;
        }
    }

    if (buffer != NULL || buffer_len > 0) {
        if (buffer == NULL) {
            buffer = malloc(1);
            if (buffer == NULL) {
                fprintf(stderr, "new_sort: out of memory\n");
                return 1;
            }
            buffer[0] = '\0';
            buffer_len = 0;
        }

        if (count >= capacity) {
            size_t new_capacity = capacity == 0 ? 16 : capacity * 2;
            if (new_capacity <= capacity) {
                fprintf(stderr, "new_sort: out of memory\n");
                free(buffer);
                return 1;
            }
            line_t *new_lines = realloc(lines, new_capacity * sizeof(line_t));
            if (new_lines == NULL) {
                fprintf(stderr, "new_sort: out of memory\n");
                free(buffer);
                return 1;
            }
            lines = new_lines;
            capacity = new_capacity;
        }

        lines[count].data = buffer;
        lines[count].len = buffer_len;
        count++;
    }

    if (count > 1) {
        qsort(lines, count, sizeof(line_t), cmp_lines);
    }

    for (size_t i = 0; i < count; i++) {
        if (lines[i].len > 0) {
            if (fwrite(lines[i].data, 1, lines[i].len, stdout) != lines[i].len) {
                fprintf(stderr, "new_sort: write error\n");
                for (size_t j = 0; j < count; j++) {
                    free(lines[j].data);
                }
                free(lines);
                return 1;
            }
        }
        if (fputc('\n', stdout) == EOF) {
            fprintf(stderr, "new_sort: write error\n");
            for (size_t j = 0; j < count; j++) {
                free(lines[j].data);
            }
            free(lines);
            return 1;
        }
    }

    for (size_t i = 0; i < count; i++) {
        free(lines[i].data);
    }
    free(lines);

    return 0;
}
