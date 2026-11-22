#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <dirent.h>
#include <unistd.h>

static unsigned char to_lower_uc(unsigned char c)
{
    if (c >= 'A' && c <= 'Z')
        return (unsigned char)(c - 'A' + 'a');
    return c;
}

static int contains_bytes(const unsigned char *haystack, size_t hlen,
                          const unsigned char *needle, size_t nlen,
                          int ignore_case)
{
    if (nlen == 0) return 1;
    if (nlen > hlen) return 0;
    size_t limit = hlen - nlen;
    for (size_t i = 0; i <= limit; i++) {
        int found = 1;
        if (ignore_case) {
            for (size_t j = 0; j < nlen; j++) {
                if (to_lower_uc(haystack[i + j]) != to_lower_uc(needle[j])) {
                    found = 0;
                    break;
                }
            }
        } else {
            found = (memcmp(haystack + i, needle, nlen) == 0);
        }
        if (found) return 1;
    }
    return 0;
}

static int cmp_dirent_name(const void *a, const void *b)
{
    const struct dirent *da = *(const struct dirent * const *)a;
    const struct dirent *db = *(const struct dirent * const *)b;
    return strcmp(da->d_name, db->d_name);
}

static int search_stream(FILE *fp, const unsigned char *pattern, size_t pattern_len,
                         const char *prefix, size_t prefix_len, int *had_error,
                         int ignore_case);

static int search_recursive(const char *dir_path, size_t dir_path_len,
                            const unsigned char *pattern, size_t pattern_len,
                            int use_prefix, int *had_error, int ignore_case)
{
    int matched = 0;
    DIR *dp = opendir(dir_path);
    if (!dp) {
        fprintf(stderr, "c_grep: %s: %s\n", dir_path, strerror(errno));
        *had_error = 1;
        return 0;
    }

    struct dirent **entries = NULL;
    size_t entry_count = 0;
    size_t entry_cap = 0;

    struct dirent *dent;
    while ((dent = readdir(dp)) != NULL) {
        if (strcmp(dent->d_name, ".") == 0 || strcmp(dent->d_name, "..") == 0)
            continue;
        if (entry_count >= entry_cap) {
            size_t new_cap = entry_cap ? entry_cap * 2 : 16;
            struct dirent **ne = realloc(entries, new_cap * sizeof *ne);
            if (!ne) {
                *had_error = 1;
                for (size_t i = 0; i < entry_count; i++) free(entries[i]);
                free(entries);
                closedir(dp);
                return matched;
            }
            entries = ne;
            entry_cap = new_cap;
        }
        struct dirent *copy = malloc(sizeof *copy);
        if (!copy) {
            *had_error = 1;
            for (size_t i = 0; i < entry_count; i++) free(entries[i]);
            free(entries);
            closedir(dp);
            return matched;
        }
        *copy = *dent;
        entries[entry_count++] = copy;
    }
    closedir(dp);

    if (entry_count > 1)
        qsort(entries, entry_count, sizeof *entries, cmp_dirent_name);

    int has_trailing_slash = (dir_path_len > 0 && dir_path[dir_path_len - 1] == '/');
    size_t sep_len = has_trailing_slash ? 0 : 1;

    for (size_t i = 0; i < entry_count; i++) {
        const char *name = entries[i]->d_name;
        size_t name_len = strlen(name);
        size_t full_len = dir_path_len + sep_len + name_len;
        char *full_path = malloc(full_len + 1);
        if (!full_path) {
            *had_error = 1;
            continue;
        }
        memcpy(full_path, dir_path, dir_path_len);
        if (sep_len > 0) full_path[dir_path_len] = '/';
        memcpy(full_path + dir_path_len + sep_len, name, name_len);
        full_path[full_len] = '\0';

        struct stat sb;
        if (lstat(full_path, &sb) != 0) {
            fprintf(stderr, "c_grep: %s: %s\n", full_path, strerror(errno));
            *had_error = 1;
            free(full_path);
            continue;
        }

        if (S_ISLNK(sb.st_mode)) {
            free(full_path);
            continue;
        }

        if (S_ISREG(sb.st_mode)) {
            int fd = open(full_path, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "c_grep: %s: %s\n", full_path, strerror(errno));
                *had_error = 1;
                free(full_path);
                continue;
            }
            FILE *fp = fdopen(fd, "r");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: %s\n", full_path, strerror(errno));
                close(fd);
                free(full_path);
                continue;
            }
            const char *prefix = NULL;
            size_t prefix_len = 0;
            char *prefix_buf = NULL;
            if (use_prefix) {
                prefix_buf = malloc(full_len + 2);
                if (!prefix_buf) {
                    fprintf(stderr, "c_grep: %s: memory allocation failed\n", full_path);
                    *had_error = 1;
                    fclose(fp);
                    free(full_path);
                    continue;
                }
                memcpy(prefix_buf, full_path, full_len);
                prefix_buf[full_len] = ':';
                prefix_buf[full_len + 1] = '\0';
                prefix = prefix_buf;
                prefix_len = full_len + 1;
            }
            matched += search_stream(fp, pattern, pattern_len, prefix, prefix_len, had_error, ignore_case);
            free(prefix_buf);
            fclose(fp);
        } else if (S_ISDIR(sb.st_mode)) {
            matched += search_recursive(full_path, full_len, pattern, pattern_len,
                                        use_prefix, had_error, ignore_case);
        }
        free(full_path);
    }

    for (size_t i = 0; i < entry_count; i++)
        free(entries[i]);
    free(entries);
    return matched;
}

static int search_stream(FILE *fp, const unsigned char *pattern, size_t pattern_len,
                         const char *prefix, size_t prefix_len, int *had_error,
                         int ignore_case)
{
    int matched = 0;
    unsigned char *line = NULL;
    size_t line_len = 0;
    size_t line_cap = 0;

    for (;;) {
        int c = fgetc(fp);
        if (c == EOF) break;
        if (c == '\n') {
            if (pattern_len == 0 || contains_bytes(line, line_len, pattern, pattern_len, ignore_case)) {
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
        if (pattern_len == 0 || contains_bytes(line, line_len, pattern, pattern_len, ignore_case)) {
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
    int recursive = 0;
    int ignore_case = 0;

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
                if (strcmp(arg, "--recursive") == 0) {
                    recursive = 1;
                    continue;
                }
                if (strcmp(arg, "--ignore-case") == 0) {
                    ignore_case = 1;
                    continue;
                }
                int saw_known_opt = 0;
                int valid = 1;
                for (const char *p = arg + 1; *p; p++) {
                    if (*p == 'H') {
                        prefix_mode = 1;
                        saw_known_opt = 1;
                    } else if (*p == 'h') {
                        prefix_mode = 2;
                        saw_known_opt = 1;
                    } else if (*p == 'r') {
                        recursive = 1;
                        saw_known_opt = 1;
                    } else if (*p == 'i') {
                        ignore_case = 1;
                        saw_known_opt = 1;
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
                if (saw_known_opt) {
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
    if (prefix_mode == 1) {
        use_prefix = 1;
    } else if (prefix_mode == 2) {
        use_prefix = 0;
    } else {
        int any_dir = 0;
        if (recursive) {
            for (int i = 0; i < file_count; i++) {
                struct stat sb;
                if (stat(files[i], &sb) == 0 && S_ISDIR(sb.st_mode)) {
                    any_dir = 1;
                    break;
                }
            }
        }
        use_prefix = (file_count >= 2) || any_dir;
    }
    int had_error = 0;
    int total_matched = 0;

    if (file_count == 0) {
        const char *si_prefix = use_prefix ? "(standard input):" : NULL;
        size_t si_prefix_len = use_prefix ? strlen("(standard input):") : 0;
        total_matched += search_stream(stdin, (const unsigned char *)pattern,
                                       pattern_len, si_prefix, si_prefix_len, &had_error,
                                       ignore_case);
    } else {
        for (int i = 0; i < file_count; i++) {
            const char *path = files[i];
            struct stat sb;
            if (stat(path, &sb) == 0 && S_ISDIR(sb.st_mode)) {
                if (recursive) {
                    size_t path_len = strlen(path);
                    total_matched += search_recursive(path, path_len,
                                                      (const unsigned char *)pattern, pattern_len,
                                                      use_prefix, &had_error, ignore_case);
                } else {
                    fprintf(stderr, "c_grep: %s: Is a directory\n", path);
                    had_error = 1;
                }
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
                                           pattern_len, prefix, prefix_len, &had_error,
                                           ignore_case);
            free(prefix_buf);
            fclose(fp);
        }
    }

    free(files);

    if (had_error) return 2;
    return total_matched > 0 ? 0 : 1;
}
