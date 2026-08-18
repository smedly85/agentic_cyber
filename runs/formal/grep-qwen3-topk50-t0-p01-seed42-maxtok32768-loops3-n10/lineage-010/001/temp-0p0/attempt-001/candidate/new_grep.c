#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>

#define INITIAL_LINE_CAPACITY 256

typedef struct {
    char *data;
    size_t len;
    size_t capacity;
} LineBuffer;

static int
alloc_line_buffer(LineBuffer *buf)
{
    buf->capacity = INITIAL_LINE_CAPACITY;
    buf->data = malloc(buf->capacity);
    if (!buf->data) {
        return -1;
    }
    buf->len = 0;
    return 0;
}

static void
free_line_buffer(LineBuffer *buf)
{
    free(buf->data);
    buf->data = NULL;
    buf->len = 0;
    buf->capacity = 0;
}

static int
grow_line_buffer(LineBuffer *buf, size_t needed)
{
    size_t new_cap = buf->capacity;
    while (new_cap < buf->len + needed) {
        if (new_cap > SIZE_MAX / 2) {
            return -1;
        }
        new_cap *= 2;
    }
    char *new_data = realloc(buf->data, new_cap);
    if (!new_data) {
        return -1;
    }
    buf->data = new_data;
    buf->capacity = new_cap;
    return 0;
}

static int
read_line(FILE *fp, LineBuffer *buf)
{
    buf->len = 0;

    for (;;) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (ferror(fp)) {
                return -1;
            }
            if (buf->len == 0) {
                return 0;
            }
            return 1;
        }
        if (c == '\n') {
            return 1;
        }
        if (grow_line_buffer(buf, 1) < 0) {
            return -1;
        }
        buf->data[buf->len] = (char)c;
        buf->len++;
    }
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
is_directory(const char *path)
{
    struct stat st;
    if (lstat(path, &st) < 0) {
        return 0;
    }
    if (S_ISLNK(st.st_mode)) {
        if (stat(path, &st) < 0) {
            return 0;
        }
    }
    return S_ISDIR(st.st_mode);
}

static int
search_file(const char *filename, const char *pattern, size_t pattern_len,
            int prefix_filename, LineBuffer *buf)
{
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    int matched_at_least_once = 0;

    while (1) {
        int result = read_line(fp, buf);
        if (result < 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            fclose(fp);
            return 2;
        }
        if (result == 0) {
            break;
        }

        if (match_pattern(buf->data, buf->len, pattern, pattern_len)) {
            if (prefix_filename) {
                fprintf(stdout, "%s:", filename);
            }
            fwrite(buf->data, 1, buf->len, stdout);
            fputc('\n', stdout);
            matched_at_least_once = 1;
        }
    }

    fclose(fp);

    if (matched_at_least_once) {
        return 0;
    }
    return 1;
}

static void
usage(void)
{
    fprintf(stderr, "Usage: new_grep [-H] [--with-filename] PATTERN [FILE...]\n");
}

int
main(int argc, char *argv[])
{
    if (argc < 2) {
        usage();
        return 2;
    }

    const char *pattern;
    size_t pattern_len;
    int num_files;
    int force_filename = 0;

    int arg_idx = 1;
    while (arg_idx < argc && argv[arg_idx][0] == '-' && argv[arg_idx][1] != '\0') {
        if (strcmp(argv[arg_idx], "-H") == 0 || strcmp(argv[arg_idx], "--with-filename") == 0) {
            force_filename = 1;
            arg_idx++;
        } else if (strcmp(argv[arg_idx], "--") == 0) {
            arg_idx++;
            break;
        } else {
            usage();
            return 2;
        }
    }

    if (arg_idx >= argc) {
        usage();
        return 2;
    }

    pattern = argv[arg_idx];
    pattern_len = strlen(pattern);
    
    int file_start = arg_idx + 1;
    num_files = 0;
    for (int i = file_start; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            continue;
        }
        num_files++;
    }

    LineBuffer buf;
    if (alloc_line_buffer(&buf) < 0) {
        fprintf(stderr, "memory allocation failed\n");
        return 2;
    }

    int exit_status = 1;
    int has_error = 0;

    if (num_files == 0) {
        while (1) {
            int result = read_line(stdin, &buf);
            if (result < 0) {
                fprintf(stderr, "(standard input): %s\n", strerror(errno));
                has_error = 1;
                break;
            }
            if (result == 0) {
                break;
            }
            if (match_pattern(buf.data, buf.len, pattern, pattern_len)) {
                if (force_filename) {
                    fprintf(stdout, "(standard input):");
                }
                fwrite(buf.data, 1, buf.len, stdout);
                fputc('\n', stdout);
                exit_status = 0;
            }
        }
    } else {
        int prefix_filename = force_filename ? 1 : ((num_files > 1) ? 1 : 0);

        for (int i = file_start; i < argc; i++) {
            if (strcmp(argv[i], "--") == 0) {
                continue;
            }
            const char *filename = argv[i];

            if (is_directory(filename)) {
                fprintf(stderr, "%s: is a directory\n", filename);
                has_error = 1;
                continue;
            }

            int status = search_file(filename, pattern, pattern_len,
                                     prefix_filename, &buf);
            if (status == 2) {
                has_error = 1;
            } else if (status == 0 && exit_status == 1) {
                exit_status = 0;
            }
        }
    }

    free_line_buffer(&buf);

    return has_error ? 2 : exit_status;
}
