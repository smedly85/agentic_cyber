#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

static int contains_bytes(const unsigned char *haystack, size_t hlen,
                          const unsigned char *needle, size_t nlen)
{
    if (nlen == 0) return 1;
    if (nlen > hlen) return 0;
    size_t limit = hlen - nlen;
    for (size_t i = 0; i <= limit; i++) {
        if (memcmp(haystack + i, needle, nlen) == 0) return 1;
    }
    return 0;
}

static int search_stream(FILE *fp, const unsigned char *pattern, size_t pattern_len,
                         const char *prefix, size_t prefix_len, int *had_error)
{
    int matched = 0;
    unsigned char *line = NULL;
    size_t line_len = 0;
    size_t line_cap = 0;

    for (;;) {
        int c = fgetc(fp);
        if (c == EOF) break;
        if (c == '\n') {
            if (pattern_len == 0 || contains_bytes(line, line_len, pattern, pattern_len)) {
                if (prefix_len > 0 &&
                    fwrite(prefix, 1, prefix_len, stdout) != prefix_len) {
                    *had_error = 1;
                    free(line);
                    return matched;
                }
                if (line_len > 0 &&
                    fwrite(line, 1, line_len, stdout) != line_len) {
                    *had_error = 1;
                    free(line);
                    return matched;
                }
                if (fputc('\n', stdout) == EOF) {
                    *had_error = 1;
                    free(line);
                    return matched;
                }
                matched++;
            }
            line_len = 0;
        } else {
            if (line_len + 1 > line_cap) {
                if (line_cap > SIZE_MAX / 2) {
                    *had_error = 1;
                    free(line);
                    return matched;
                }
                size_t new_cap = line_cap ? line_cap * 2 : 4096;
                unsigned char *new_line = realloc(line, new_cap);
                if (!new_line) {
                    *had_error = 1;
                    free(line);
                    return matched;
                }
                line = new_line;
                line_cap = new_cap;
            }
            line[line_len++] = (unsigned char)c;
        }
    }

    if (ferror(fp)) {
        *had_error = 1;
    }

    if (line_len > 0) {
        if (pattern_len == 0 || contains_bytes(line, line_len, pattern, pattern_len)) {
            if (prefix_len > 0 &&
                fwrite(prefix, 1, prefix_len, stdout) != prefix_len) {
                *had_error = 1;
                free(line);
                return matched;
            }
            if (fwrite(line, 1, line_len, stdout) != line_len) {
                *had_error = 1;
                free(line);
                return matched;
            }
            if (fputc('\n', stdout) == EOF) {
                *had_error = 1;
                free(line);
                return matched;
            }
            matched++;
        }
    }

    free(line);
    return matched;
}

int main(int argc, char *argv[])
{
    const char *pattern = NULL;
    const char **files = NULL;
    int file_count = 0;
    int file_cap = 0;
    int in_operands = 0;
    int prefix_mode = 0; /* 0=auto, 1=force (-H), 2=suppress (-h) */

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!in_operands) {
            if (strcmp(arg, "--") == 0) {
                in_operands = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (strcmp(arg, "--with-filename") == 0) {
                    prefix_mode = 1;
                    continue;
                }
                if (strcmp(arg, "--no-filename") == 0) {
                    prefix_mode = 2;
                    continue;
                }
                int has_prefix_opt = 0;
                int valid = 1;
                for (const char *p = arg + 1; *p; p++) {
                    if (*p == 'H') {
                        prefix_mode = 1;
                        has_prefix_opt = 1;
                    } else if (*p == 'h') {
                        prefix_mode = 2;
                        has_prefix_opt = 1;
                    } else {
                        valid = 0;
                        break;
                    }
                }
                if (!valid) {
                    fprintf(stderr, "c_grep: unsupported option '%s'\n", arg);
                    fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
                    return 2;
                }
                if (has_prefix_opt) {
                    continue;
                }
                fprintf(stderr, "c_grep: unsupported option '%s'\n", arg);
                fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
                return 2;
            }
        }
        if (pattern == NULL) {
            pattern = arg;
        } else {
            if (file_count >= file_cap) {
                int new_cap = file_cap ? file_cap * 2 : 8;
                const char **new_files = realloc(files,
                                                 (size_t)new_cap * sizeof *files);
                if (!new_files) {
                    free(files);
                    return 2;
                }
                files = new_files;
                file_cap = new_cap;
            }
            files[file_count++] = arg;
        }
    }

    if (pattern == NULL) {
        fprintf(stderr, "c_grep: missing PATTERN\n");
        fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
        return 2;
    }

    size_t pattern_len = strlen(pattern);
    int use_prefix;
    if (prefix_mode == 1) use_prefix = 1;
    else if (prefix_mode == 2) use_prefix = 0;
    else use_prefix = (file_count >= 2);
    int had_error = 0;
    int total_matched = 0;

    if (file_count == 0) {
        const char *si_prefix = use_prefix ? "(standard input):" : NULL;
        size_t si_prefix_len = use_prefix ? strlen("(standard input):") : 0;
        total_matched += search_stream(stdin, (const unsigned char *)pattern,
                                       pattern_len, si_prefix, si_prefix_len, &had_error);
    } else {
        for (int i = 0; i < file_count; i++) {
            const char *path = files[i];
            struct stat sb;
            if (stat(path, &sb) == 0 && S_ISDIR(sb.st_mode)) {
                fprintf(stderr, "c_grep: %s: Is a directory\n", path);
                had_error = 1;
                continue;
            }
            int fd = open(path, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "c_grep: %s: %s\n", path, strerror(errno));
                had_error = 1;
                continue;
            }
            FILE *fp = fdopen(fd, "r");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: %s\n", path, strerror(errno));
                close(fd);
                had_error = 1;
                continue;
            }

            const char *prefix = NULL;
            size_t prefix_len = 0;
            char *prefix_buf = NULL;
            if (use_prefix) {
                size_t plen = strlen(path);
                prefix_buf = malloc(plen + 2);
                if (!prefix_buf) {
                    fprintf(stderr, "c_grep: %s: memory allocation failed\n", path);
                    had_error = 1;
                    fclose(fp);
                    continue;
                }
                memcpy(prefix_buf, path, plen);
                prefix_buf[plen] = ':';
                prefix_buf[plen + 1] = '\0';
                prefix = prefix_buf;
                prefix_len = plen + 1;
            }

            total_matched += search_stream(fp, (const unsigned char *)pattern,
                                           pattern_len, prefix, prefix_len, &had_error);
            free(prefix_buf);
            fclose(fp);
        }
    }

    free(files);

    if (had_error) return 2;
    return total_matched > 0 ? 0 : 1;
}
