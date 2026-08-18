#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <limits.h>

#define CHUNK_SIZE 4096

static char *read_line(FILE *fp, size_t *len_out) {
    size_t capacity = CHUNK_SIZE;
    size_t len = 0;
    char *buf = malloc(capacity);
    if (!buf) return NULL;

    while (1) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (len > 0) {
                break;
            }
            free(buf);
            return NULL;
        }
        if (c == '\n') {
            break;
        }
        if (len >= capacity - 1) {
            size_t new_cap = capacity * 2;
            if (new_cap <= capacity) {
                free(buf);
                return NULL;
            }
            char *new_buf = realloc(buf, new_cap);
            if (!new_buf) {
                free(buf);
                return NULL;
            }
            buf = new_buf;
            capacity = new_cap;
        }
        buf[len++] = (char)c;
    }

    if (len >= capacity - 1) {
        char *new_buf = realloc(buf, len + 1);
        if (!new_buf) {
            free(buf);
            return NULL;
        }
        buf = new_buf;
    }
    buf[len] = '\0';
    *len_out = len;
    return buf;
}

static int matches(const char *line, size_t line_len, const char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    return memmem(line, line_len, pattern, pat_len) != NULL;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                       int prefix_filename, int *match_found, int *error_occurred) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        return 0;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "%s: Is a directory\n", filename);
        fclose(fp);
        *error_occurred = 1;
        return 0;
    }

    size_t line_len;
    char *line;
    while ((line = read_line(fp, &line_len)) != NULL) {
        if (matches(line, line_len, pattern, pat_len)) {
            if (prefix_filename) {
                fprintf(stdout, "%s:", filename);
            }
            fwrite(line, 1, line_len, stdout);
            fputc('\n', stdout);
            *match_found = 1;
        }
        free(line);
    }

    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        fclose(fp);
        *error_occurred = 1;
        return 0;
    }

    fclose(fp);
    return 1;
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s PATTERN [FILE...]\n", prog);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage(argv[0]);
        return 2;
    }

    int i = 1;
    while (i < argc && argv[i][0] == '-' && strcmp(argv[i], "--") != 0) {
        if (strcmp(argv[i], "-") == 0) {
            break;
        }
        fprintf(stderr, "%s: unrecognized option '%s'\n", argv[0], argv[i]);
        return 2;
    }

    if (i < argc && strcmp(argv[i], "--") == 0) {
        i++;
    }

    const char *pattern = argv[i++];
    size_t pat_len = strlen(pattern);

    int file_count = argc - i;
    int prefix_filename = (file_count > 1) ? 1 : 0;

    int match_found = 0;
    int error_occurred = 0;

    if (file_count == 0) {
        size_t line_len;
        char *line;
        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (matches(line, line_len, pattern, pat_len)) {
                fwrite(line, 1, line_len, stdout);
                fputc('\n', stdout);
                match_found = 1;
            }
            free(line);
        }
        if (ferror(stdin)) {
            fprintf(stderr, "stdin: %s\n", strerror(errno));
            error_occurred = 1;
        }
    } else {
        for (; i < argc; i++) {
            const char *filename = argv[i];
            search_file(filename, pattern, pat_len, prefix_filename,
                        &match_found, &error_occurred);
        }
    }

    if (error_occurred) return 2;
    return match_found ? 0 : 1;
}
