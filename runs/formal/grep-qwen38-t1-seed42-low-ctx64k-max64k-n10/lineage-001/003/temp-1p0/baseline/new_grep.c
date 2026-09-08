#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>

static int contains_pattern(const unsigned char *line, size_t len,
                            const unsigned char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > len) return 0;
    for (size_t i = 0; i <= len - pat_len; i++) {
        if (memcmp(line + i, pattern, pat_len) == 0)
            return 1;
    }
    return 0;
}

static int write_line(const unsigned char *line, size_t len,
                      const char *prefix) {
    if (prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, stdout) != plen) return -1;
        if (fputc(':', stdout) == EOF) return -1;
    }
    if (len > 0 && fwrite(line, 1, len, stdout) != len) return -1;
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int search_stream(FILE *fp, const unsigned char *pattern, size_t pat_len,
                         const char *prefix) {
    int found = 0;
    size_t cap = 256, size = 0;
    unsigned char *buf = malloc(cap);
    if (!buf) return -1;

    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (size + 1 > cap) {
            size_t new_cap = cap * 2;
            unsigned char *tmp = realloc(buf, new_cap);
            if (!tmp) { free(buf); return -1; }
            buf = tmp;
            cap = new_cap;
        }
        if (c == '\n') {
            if (contains_pattern(buf, size, pattern, pat_len)) {
                if (write_line(buf, size, prefix) != 0) { free(buf); return -1; }
                found = 1;
            }
            size = 0;
        } else {
            buf[size++] = (unsigned char)c;
        }
    }
    if (ferror(fp)) { free(buf); return -1; }

    if (size > 0) {
        if (contains_pattern(buf, size, pattern, pat_len)) {
            if (write_line(buf, size, prefix) != 0) { free(buf); return -1; }
            found = 1;
        }
    }

    free(buf);
    return found ? 0 : 1;
}

static int search_file(const char *filename, const unsigned char *pattern,
                       size_t pat_len, const char *prefix) {
    struct stat st;
    if (stat(filename, &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "new_grep: %s: Is a directory\n", filename);
        return -1;
    }
    FILE *fp = fopen(filename, "r");
    if (!fp) {
        fprintf(stderr, "new_grep: %s: %s\n", filename, strerror(errno));
        return -1;
    }
    int result = search_stream(fp, pattern, pat_len, prefix);
    fclose(fp);
    return result;
}

static void usage(void) {
    fprintf(stderr, "Usage: new_grep [-H|-h|--with-filename|--no-filename] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    int show_filename = -1;
    int i = 1;
    int pattern_idx = -1;

    while (i < argc) {
        const char *arg = argv[i];

        if (strcmp(arg, "--") == 0) {
            i++;
            if (i >= argc) {
                usage();
                return 2;
            }
            pattern_idx = i;
            break;
        }

        if (arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "--with-filename") == 0) {
                show_filename = 1;
                i++;
                continue;
            }
            if (strcmp(arg, "--no-filename") == 0) {
                show_filename = 0;
                i++;
                continue;
            }
            if (arg[1] != '\0' && arg[2] != '\0' && arg[0] == '-' && arg[1] != '-') {
                int valid = 1;
                for (const char *p = arg + 1; *p; p++) {
                    if (*p != 'H' && *p != 'h') { valid = 0; break; }
                }
                if (valid) {
                    for (const char *p = arg + 1; *p; p++)
                        show_filename = (*p == 'H') ? 1 : 0;
                    i++;
                    continue;
                }
            }
            if (arg[1] == 'H' && arg[2] == '\0') {
                show_filename = 1;
                i++;
                continue;
            }
            if (arg[1] == 'h' && arg[2] == '\0') {
                show_filename = 0;
                i++;
                continue;
            }
            usage();
            return 2;
        }

        pattern_idx = i;
        break;
    }

    if (pattern_idx == -1) {
        usage();
        return 2;
    }

    const char *pattern = argv[pattern_idx];
    size_t pat_len = strlen(pattern);
    int file_start = pattern_idx + 1;
    int file_count = argc - file_start;

    int use_prefix;
    if (show_filename == 1)
        use_prefix = 1;
    else if (show_filename == 0)
        use_prefix = 0;
    else
        use_prefix = (file_count >= 2);

    if (file_count == 0) {
        const char *prefix = use_prefix ? "(standard input)" : NULL;
        int result = search_stream(stdin, (const unsigned char *)pattern, pat_len, prefix);
        if (result == -1) return 2;
        return result;
    }

    int has_error = 0;
    int found_any = 0;

    for (int j = 0; j < file_count; j++) {
        const char *fn = argv[file_start + j];
        const char *prefix = use_prefix ? fn : NULL;
        int result = search_file(fn, (const unsigned char *)pattern, pat_len, prefix);
        if (result == -1)
            has_error = 1;
        else if (result == 0)
            found_any = 1;
    }

    if (has_error) return 2;
    return found_any ? 0 : 1;
}
