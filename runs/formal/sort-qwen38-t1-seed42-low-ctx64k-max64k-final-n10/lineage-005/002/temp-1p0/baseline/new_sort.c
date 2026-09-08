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

static int cmp_lines(const void *a, const void *b) {
    const line_t *la = (const line_t *)a;
    const line_t *lb = (const line_t *)b;
    size_t minlen = la->len < lb->len ? la->len : lb->len;
    int cmp = memcmp(la->data, lb->data, minlen);
    if (cmp != 0) {
        return reverse_order ? -cmp : cmp;
    }
    if (la->len < lb->len) {
        return reverse_order ? 1 : -1;
    }
    if (la->len > lb->len) {
        return reverse_order ? -1 : 1;
    }
    return 0;
}

int main(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--reverse") == 0) {
            reverse_order = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            int valid = 1;
            for (size_t j = 1; arg[j] != '\0'; j++) {
                if (arg[j] != 'r') { valid = 0; break; }
            }
            if (valid) {
                reverse_order = 1;
            } else {
                fprintf(stderr, "hey, use: new_sort [-r | --reverse]\n");
                return 2;
            }
        } else {
            fprintf(stderr, "hey, use: new_sort [-r | --reverse]\n");
            return 2;
        }
    }

    line_t *lines = NULL;
    size_t count = 0;
    size_t capacity = 0;

    // Read all lines
    unsigned char *buffer = NULL;
    size_t buffer_capacity = 0;
    size_t buffer_len = 0;

    int c;
    while ((c = getchar()) != EOF) {
        if (c == '\n') {
            // End of line - store it
            if (buffer == NULL) {
                buffer = malloc(1);
                if (buffer == NULL) {
                    fprintf(stderr, "new_sort: out of memory\n");
                    return 1;
                }
                buffer[0] = '\0';
                buffer_len = 0;
            }

            // Grow lines array if needed
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
            // Add character to buffer
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

    // Handle final line without newline
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

    // Sort if we have more than one line
    if (count > 1) {
        qsort(lines, count, sizeof(line_t), cmp_lines);
    }

    // Output sorted lines
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

    // Cleanup
    for (size_t i = 0; i < count; i++) {
        free(lines[i].data);
    }
    free(lines);

    return 0;
}
