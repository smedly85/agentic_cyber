#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>

enum { PREFIX_AUTO, PREFIX_ON, PREFIX_OFF };

static char *read_line(FILE *fp, size_t *out_len) {
    size_t capacity = 256;
    size_t len = 0;
    char *buf = malloc(capacity);
    if (!buf) return NULL;

    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (len + 1 >= capacity) {
            capacity *= 2;
            char *tmp = realloc(buf, capacity);
            if (!tmp) { free(buf); return NULL; }
            buf = tmp;
        }
        buf[len++] = (char)c;
        if (c == '\n') break;
    }

    if (len == 0) {
        free(buf);
        return NULL;
    }
    *out_len = len;
    return buf;
}

static int mem_contains(const char *hay, size_t hay_len,
                        const char *pat, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > hay_len) return 0;
    for (size_t i = 0; i <= hay_len - pat_len; i++) {
        if (memcmp(hay + i, pat, pat_len) == 0) return 1;
    }
    return 0;
}

static int write_selected_line(const char *line, size_t len,
                               const char *prefix, size_t prefix_len) {
    size_t out_len = len;
    if (out_len > 0 && line[out_len - 1] == '\n') out_len--;

    if (prefix_len > 0) {
        if (fwrite(prefix, 1, prefix_len, stdout) != prefix_len) return -1;
        if (fputc(':', stdout) == EOF) return -1;
    }
    if (out_len > 0) {
        if (fwrite(line, 1, out_len, stdout) != out_len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int grep_file_named(const char *open_path, const char *display_name,
                           const char *pattern, size_t pattern_len,
                           int expect_prefix) {
    FILE *fp = fopen(open_path, "rb");
    if (fp == NULL) {
        fprintf(stderr, "new_grep: %s: No such file or directory\n",
                display_name);
        return 2;
    }

    int found = 0;
    size_t line_len;
    while (1) {
        char *line = read_line(fp, &line_len);
        if (!line) break;
        if (mem_contains(line, line_len, pattern, pattern_len)) {
            if (write_selected_line(line, line_len,
                    expect_prefix ? display_name : "",
                    expect_prefix ? strlen(display_name) : 0) != 0) {
                free(line);
                fclose(fp);
                fprintf(stderr, "new_grep: write error\n");
                return 2;
            }
            found = 1;
        }
        free(line);
    }
    fclose(fp);
    return found ? 0 : 1;
}

static int grep_file(const char *filename, const char *pattern,
                     size_t pattern_len, int expect_prefix) {
    struct stat st;
    if (stat(filename, &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "new_grep: %s: Is a directory\n", filename);
        return 2;
    }
    return grep_file_named(filename, filename, pattern, pattern_len,
                           expect_prefix);
}

static int cmp_names(const void *a, const void *b) {
    const char *sa = *(const char *const *)a;
    const char *sb = *(const char *const *)b;
    size_t la = strlen(sa), lb = strlen(sb);
    size_t min = la < lb ? la : lb;
    int c = memcmp(sa, sb, min);
    if (c != 0) return c;
    return (int)la - (int)lb;
}

static char *join_path(const char *base, const char *name) {
    size_t blen = strlen(base);
    while (blen > 0 && base[blen - 1] == '/') blen--;
    size_t nlen = strlen(name);
    char *buf = malloc(blen + 1 + nlen + 1);
    if (!buf) return NULL;
    memcpy(buf, base, blen);
    buf[blen] = '/';
    memcpy(buf + blen + 1, name, nlen + 1);
    return buf;
}

static void grep_dir_recursive(const char *path, const char *pattern,
                               size_t pattern_len, int expect_prefix,
                               int *any_match, int *any_error) {
    DIR *dp = opendir(path);
    if (!dp) {
        fprintf(stderr, "new_grep: %s: No such file or directory\n", path);
        *any_error = 1;
        return;
    }

    struct dirent *entry;
    char **names = NULL;
    int count = 0, capacity = 0;

    while ((entry = readdir(dp)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 ||
            strcmp(entry->d_name, "..") == 0)
            continue;
        if (count >= capacity) {
            int newcap = capacity ? capacity * 2 : 16;
            char **tmp = realloc(names, (size_t)newcap * sizeof(char *));
            if (!tmp) {
                for (int i = 0; i < count; i++) free(names[i]);
                free(names);
                closedir(dp);
                return;
            }
            names = tmp;
            capacity = newcap;
        }
        names[count] = strdup(entry->d_name);
        if (!names[count]) {
            for (int i = 0; i < count; i++) free(names[i]);
            free(names);
            closedir(dp);
            return;
        }
        count++;
    }
    closedir(dp);

    qsort(names, (size_t)count, sizeof(char *), cmp_names);

    for (int i = 0; i < count; i++) {
        char *full = join_path(path, names[i]);
        if (!full) { free(names[i]); continue; }

        struct stat st;
        if (lstat(full, &st) != 0) {
            free(full);
            free(names[i]);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(full);
            free(names[i]);
            continue;
        }

        if (S_ISDIR(st.st_mode)) {
            grep_dir_recursive(full, pattern, pattern_len, expect_prefix,
                               any_match, any_error);
        } else if (S_ISREG(st.st_mode)) {
            int result = grep_file_named(full, full, pattern, pattern_len,
                                         expect_prefix);
            if (result == 0) *any_match = 1;
            else if (result == 2) *any_error = 1;
        }

        free(full);
        free(names[i]);
    }
    free(names);
}

static int grep_stdin(const char *pattern, size_t pattern_len, int with_filename) {
    static const char *stdin_name = "(standard input)";
    int found = 0;
    size_t line_len;
    while (1) {
        char *line = read_line(stdin, &line_len);
        if (!line) break;
        if (mem_contains(line, line_len, pattern, pattern_len)) {
            if (write_selected_line(line, line_len,
                    with_filename ? stdin_name : "",
                    with_filename ? strlen(stdin_name) : 0) != 0) {
                free(line);
                fprintf(stderr, "new_grep: write error\n");
                return 2;
            }
            found = 1;
        }
        free(line);
    }
    return found ? 0 : 1;
}

static void print_usage(void) {
    fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    argc--;
    argv++;

    int prefix_mode = PREFIX_AUTO;
    int recursive = 0;
    int after_separator = 0;
    const char *pattern = NULL;
    const char *files[1024];
    int file_count = 0;

    for (int i = 0; i < argc; i++) {
        if (!after_separator) {
            if (strcmp(argv[i], "--") == 0) {
                after_separator = 1;
                continue;
            }
            if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
                if (argv[i][1] == '-') {
                    /* long option */
                    if (strcmp(argv[i], "--with-filename") == 0) {
                        prefix_mode = PREFIX_ON;
                        continue;
                    }
                    if (strcmp(argv[i], "--no-filename") == 0) {
                        prefix_mode = PREFIX_OFF;
                        continue;
                    }
                    if (strcmp(argv[i], "--recursive") == 0) {
                        recursive = 1;
                        continue;
                    }
                    fprintf(stderr, "new_grep: invalid option -- %s\n", argv[i]);
                    print_usage();
                    return 2;
                }
                /* short option cluster: e.g. -H, -h, -r, -Hh, -hH, -rh, -rH */
                int ok = 1;
                for (size_t j = 1; argv[i][j] != '\0'; j++) {
                    if (argv[i][j] == 'H') {
                        prefix_mode = PREFIX_ON;
                    } else if (argv[i][j] == 'h') {
                        prefix_mode = PREFIX_OFF;
                    } else if (argv[i][j] == 'r') {
                        recursive = 1;
                    } else {
                        fprintf(stderr, "new_grep: invalid option -- %c\n",
                                argv[i][j]);
                        ok = 0;
                        break;
                    }
                }
                if (!ok) { print_usage(); return 2; }
                continue;
            }
        }

        if (pattern == NULL) {
            pattern = argv[i];
        } else {
            if (file_count < 1024) {
                files[file_count++] = argv[i];
            }
        }
    }

    if (pattern == NULL) {
        print_usage();
        return 2;
    }

    size_t pattern_len = strlen(pattern);

    if (file_count == 0) {
        return grep_stdin(pattern, pattern_len, prefix_mode == PREFIX_ON);
    }

    /* Determine prefix mode */
    int expect_prefix;
    if (prefix_mode == PREFIX_ON) {
        expect_prefix = 1;
    } else if (prefix_mode == PREFIX_OFF) {
        expect_prefix = 0;
    } else if (file_count >= 2) {
        expect_prefix = 1;
    } else if (recursive) {
        /* -r given and at least one operand is a directory */
        expect_prefix = 0;
        for (int i = 0; i < file_count; i++) {
            struct stat st;
            if (stat(files[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                expect_prefix = 1;
                break;
            }
        }
    } else {
        expect_prefix = 0;
    }

    int exit_code = 1;

    for (int i = 0; i < file_count; i++) {
        int result;
        if (recursive) {
            struct stat st;
            if (stat(files[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                int any_match = 0, any_error = 0;
                grep_dir_recursive(files[i], pattern, pattern_len,
                                   expect_prefix, &any_match, &any_error);
                if (any_error) result = 2;
                else if (any_match) result = 0;
                else result = 1;
            } else {
                result = grep_file(files[i], pattern, pattern_len,
                                   expect_prefix);
            }
        } else {
            result = grep_file(files[i], pattern, pattern_len, expect_prefix);
        }

        if (result == 2) {
            exit_code = 2;
        } else if (result == 0 && exit_code != 2) {
            exit_code = 0;
        }
    }
    return exit_code;
}
