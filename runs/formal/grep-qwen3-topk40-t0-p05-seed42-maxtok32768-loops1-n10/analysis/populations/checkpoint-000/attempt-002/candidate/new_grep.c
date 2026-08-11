#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

#define INITIAL_LINE_CAPACITY 256

typedef struct {
    char *data;
    size_t len;
    size_t capacity;
} LineBuffer;

static int
init_line_buffer(LineBuffer *buf)
{
    buf->data = malloc(INITIAL_LINE_CAPACITY);
    if (!buf->data) {
        return -1;
    }
    buf->len = 0;
    buf->capacity = INITIAL_LINE_CAPACITY;
    return 0;
}

static void
free_line_buffer(LineBuffer *buf)
{
    free(buf->data);
    buf->data = NULL;
}

static int
grow_line_buffer(LineBuffer *buf, size_t needed)
{
    size_t new_capacity = buf->capacity;
    while (new_capacity < buf->len + needed) {
        if (new_capacity > SIZE_MAX / 2) {
            return -1;
        }
        new_capacity *= 2;
    }
    char *new_data = realloc(buf->data, new_capacity);
    if (!new_data) {
        return -1;
    }
    buf->data = new_data;
    buf->capacity = new_capacity;
    return 0;
}

static int
read_line(LineBuffer *buf, FILE *fp)
{
    buf->len = 0;

    while (1) {
        if (grow_line_buffer(buf, 1) < 0) {
            fprintf(stderr, "memory allocation failed\n");
            return -3;
        }
        int c = fgetc(fp);
        if (c == EOF) {
            if (buf->len == 0) {
                return 0;
            }
            break;
        }
        buf->data[buf->len++] = (char)c;
        if (c == '\n') {
            buf->len--;
            break;
        }
    }

    if (grow_line_buffer(buf, 1) < 0) {
        fprintf(stderr, "memory allocation failed\n");
        return -3;
    }
    buf->data[buf->len] = '\0';
    return 1;
}

static int
match_pattern(const char *line, size_t line_len, const char *pattern, size_t pattern_len)
{
    if (pattern_len == 0) {
        return 1;
    }
    if (pattern_len > line_len) {
        return 0;
    }

    for (size_t i = 0; i <= line_len - pattern_len; i++) {
        int found = 1;
        for (size_t j = 0; j < pattern_len; j++) {
            if (line[i + j] != pattern[j]) {
                found = 0;
                break;
            }
        }
        if (found) {
            return 1;
        }
    }
    return 0;
}

static int
search_file(const char *filename, const char *pattern, size_t pattern_len,
            int prefix_filename, int *match_found, int *error_occurred)
{
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "%s: Is a directory\n", filename);
        fclose(fp);
        *error_occurred = 1;
        return 2;
    }

    LineBuffer buf;
    if (init_line_buffer(&buf) < 0) {
        fprintf(stderr, "memory allocation failed\n");
        fclose(fp);
        *error_occurred = 1;
        return 2;
    }

    int result = 0;

    while (1) {
        int status = read_line(&buf, fp);
        if (status == -3) {
            result = 2;
            break;
        }
        if (status == 0) {
            break;
        }

        if (match_pattern(buf.data, buf.len, pattern, pattern_len)) {
            *match_found = 1;
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    fprintf(stderr, "write error\n");
                    result = 2;
                    break;
                }
            }
            if (buf.len > 0) {
                if (fwrite(buf.data, 1, buf.len, stdout) != buf.len) {
                    fprintf(stderr, "write error\n");
                    result = 2;
                    break;
                }
            }
            if (putc('\n', stdout) == EOF) {
                fprintf(stderr, "write error\n");
                result = 2;
                break;
            }
        }
    }

    free_line_buffer(&buf);
    fclose(fp);

    return result;
}

static void
print_usage(void)
{
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
}

int
main(int argc, char *argv[])
{
    if (argc < 2) {
        print_usage();
        return 2;
    }

    int i = 1;
    int saw_double_dash = 0;

    while (i < argc) {
        if (!saw_double_dash && strcmp(argv[i], "--") == 0) {
            saw_double_dash = 1;
            i++;
            continue;
        }
        if (!saw_double_dash && argv[i][0] == '-' && argv[i][1] != '\0') {
            print_usage();
            return 2;
        }
        break;
    }

    const char *pattern = argv[i];
    size_t pattern_len = strlen(pattern);
    i++;

    int num_files = argc - i;
    int prefix_filename = (num_files > 1) ? 1 : 0;

    int match_found = 0;
    int error_occurred = 0;
    int exit_code = 0;

    if (num_files == 0) {
        LineBuffer buf;
        if (init_line_buffer(&buf) < 0) {
            fprintf(stderr, "memory allocation failed\n");
            return 2;
        }

        while (1) {
            int status = read_line(&buf, stdin);
            if (status == -3) {
                exit_code = 2;
                break;
            }
            if (status == 0) {
                break;
            }
            if (match_pattern(buf.data, buf.len, pattern, pattern_len)) {
                match_found = 1;
                if (buf.len > 0) {
                    if (fwrite(buf.data, 1, buf.len, stdout) != buf.len) {
                        fprintf(stderr, "write error\n");
                        exit_code = 2;
                        break;
                    }
                }
                if (putc('\n', stdout) == EOF) {
                    fprintf(stderr, "write error\n");
                    exit_code = 2;
                    break;
                }
            }
        }

        free_line_buffer(&buf);
    } else {
        for (; i < argc; i++) {
            int result = search_file(argv[i], pattern, pattern_len,
                                     prefix_filename, &match_found, &error_occurred);
            if (result == 2) {
                exit_code = 2;
            }
        }
    }

    if (exit_code != 2 && match_found) {
        return 0;
    } else if (exit_code != 2) {
        return 1;
    } else {
        return 2;
    }
}
