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

    buf[len] = '\0';
    *len_out = len;
    return buf;
}

static int matches(const char *line, size_t line_len, const char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    return memmem(line, line_len, pattern, pat_len) != NULL;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len, int prefix) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "%s: Is a directory\n", filename);
        fclose(fp);
        return 2;
    }

    int matched = 0;
    size_t len;
    char *line;

    while ((line = read_line(fp, &len)) != NULL) {
        if (matches(line, len, pattern, pat_len)) {
            if (prefix) {
                fprintf(stdout, "%s:", filename);
            }
            fwrite(line, 1, len, stdout);
            fputc('\n', stdout);
            matched = 1;
        }
        free(line);
    }

    int result = matched ? 0 : 1;

    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        result = 2;
    }

    fclose(fp);
    return result;
}



static void usage(void) {
    fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep -H PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep --with-filename PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int seen_dashdash = 0;
    int force_filename = 0;

    for (int i = 1; i < argc; i++) {
        if (!seen_dashdash && argv[i][0] == '-' && strcmp(argv[i], "-") != 0 && strcmp(argv[i], "--") != 0) {
            if (strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "-H") == 0) {
                force_filename = 1;
            } else {
                usage();
                return 2;
            }
        }
        if (strcmp(argv[i], "--") == 0) {
            seen_dashdash = 1;
        }
    }

    int pattern_idx = -1;

    for (int i = 1; i < argc; i++) {
        if (!seen_dashdash && argv[i][0] == '-' && strcmp(argv[i], "-") != 0 && strcmp(argv[i], "--") != 0) {
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            seen_dashdash = 1;
            continue;
        }
        pattern_idx = i;
        break;
    }

    if (pattern_idx < 0) {
        usage();
        return 2;
    }

    const char *pattern = argv[pattern_idx];
    size_t pat_len = strlen(pattern);

    int file_count = 0;
    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) continue;
        file_count++;
    }
    
    int prefix = force_filename || file_count > 1;

    if (file_count == 0) {
        int matched = 0;
        size_t len;
        char *line;

        while ((line = read_line(stdin, &len)) != NULL) {
            if (matches(line, len, pattern, pat_len)) {
                if (force_filename) {
                    fprintf(stdout, "(standard input):");
                }
                fwrite(line, 1, len, stdout);
                fputc('\n', stdout);
                matched = 1;
            }
            free(line);
        }

        return matched ? 0 : 1;
    }

    int status = 0;
    int matched_any = 0;

    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) continue;
        const char *filename = argv[i];
        int result = search_file(filename, pattern, pat_len, prefix);
        if (result == 0) {
            matched_any = 1;
        } else if (result == 2 && status != 2) {
            status = 2;
        }
    }

    return (matched_any || status == 2) ? status : 1;
}
