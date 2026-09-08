#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <dirent.h>

#define READ_CHUNK 8192
#define MAX_DEPTH 4096

static void fail_oom(void) {
    fprintf(stderr, "new_grep: out of memory\n");
    exit(2);
}

static void *xrealloc(void *p, size_t n) {
    void *r = realloc(p, n);
    if (!r) fail_oom();
    return r;
}

static unsigned char fold_byte(unsigned char b) {
    return (b >= 'A' && b <= 'Z') ? (unsigned char)(b | 0x20) : b;
}

static int contains_pattern(const unsigned char *hay, size_t hay_len,
                            const unsigned char *pat, size_t pat_len,
                            int ci) {
    if (pat_len == 0) return 1;
    if (pat_len > hay_len) return 0;
    for (size_t i = 0; i <= hay_len - pat_len; i++) {
        int ok = 1;
        for (size_t j = 0; j < pat_len; j++) {
            unsigned char hb = ci ? fold_byte(hay[i + j]) : hay[i + j];
            if (hb != pat[j]) { ok = 0; break; }
        }
        if (ok) return 1;
    }
    return 0;
}

static int write_output(const char *prefix, const unsigned char *line, size_t line_len) {
    if (prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, stdout) != plen) return -1;
        if (fputc(':', stdout) == EOF) return -1;
    }
    if (line_len > 0) {
        if (fwrite(line, 1, line_len, stdout) != line_len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int search_fd(int fd, const unsigned char *pat, size_t pat_len,
                     const char *prefix, int ci, int *found) {
    unsigned char *chunk = NULL;
    unsigned char *line = NULL;
    size_t line_len = 0, line_cap = 0;
    size_t cpos = 0, clen = 0;
    int rc = 0;

    chunk = xrealloc(NULL, READ_CHUNK);

    for (;;) {
        if (cpos >= clen) {
            ssize_t n;
            do {
                n = read(fd, chunk, READ_CHUNK);
            } while (n < 0 && errno == EINTR);
            if (n < 0) { rc = -1; goto done; }
            if (n == 0) {
                if (line_len > 0) {
                    if (contains_pattern(line, line_len, pat, pat_len, ci)) {
                        if (write_output(prefix, line, line_len) != 0) { rc = -1; goto done; }
                        *found = 1;
                    }
                }
                break;
            }
            clen = (size_t)n;
            cpos = 0;
        }

        unsigned char b = chunk[cpos++];
        if (b == '\n') {
            if (contains_pattern(line, line_len, pat, pat_len, ci)) {
                if (write_output(prefix, line, line_len) != 0) { rc = -1; goto done; }
                *found = 1;
            }
            line_len = 0;
        } else {
            if (line_len + 1 > line_cap) {
                size_t ncap = line_cap ? line_cap * 2 : 256;
                if (ncap < line_len + 1) ncap = line_len + 1;
                line = xrealloc(line, ncap);
                line_cap = ncap;
            }
            line[line_len++] = b;
        }
    }

done:
    free(chunk);
    free(line);
    return rc;
}

static int cmp_entry_names(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

static void traverse_dir(const char *dir_path, const unsigned char *pat, size_t pat_len,
                         int use_prefix, int ci, int *found, int *error, int depth) {
    if (depth >= MAX_DEPTH) return;

    DIR *d = opendir(dir_path);
    if (!d) return;

    char **names = NULL;
    int count = 0, cap = 0;

    for (;;) {
        struct dirent *ent;
        errno = 0;
        ent = readdir(d);
        if (!ent) break;
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0)
            continue;

        if (count >= cap) {
            cap = cap ? cap * 2 : 16;
            names = xrealloc(names, (size_t)cap * sizeof(char *));
        }
        size_t nlen = strlen(ent->d_name) + 1;
        names[count] = xrealloc(NULL, nlen);
        memcpy(names[count], ent->d_name, nlen);
        count++;
    }
    closedir(d);

    qsort(names, (size_t)count, sizeof(char *), cmp_entry_names);

    size_t dlen = strlen(dir_path);
    int need_sep = (dlen > 0 && dir_path[dlen - 1] == '/') ? 0 : 1;

    for (int i = 0; i < count; i++) {
        size_t path_len = dlen + (need_sep ? 1 : 0) + strlen(names[i]) + 1;
        char *full = xrealloc(NULL, path_len);
        if (need_sep)
            snprintf(full, path_len, "%s/%s", dir_path, names[i]);
        else
            snprintf(full, path_len, "%s%s", dir_path, names[i]);

        struct stat st;
        if (lstat(full, &st) == 0) {
            if (S_ISREG(st.st_mode)) {
                int fd = open(full, O_RDONLY);
                if (fd < 0) {
                    fprintf(stderr, "new_grep: %s: %s\n", full, strerror(errno));
                    *error = 1;
                } else {
                    if (search_fd(fd, pat, pat_len,
                                  use_prefix ? full : NULL, ci, found) != 0) {
                        *error = 1;
                    }
                    close(fd);
                }
            } else if (S_ISDIR(st.st_mode)) {
                traverse_dir(full, pat, pat_len, use_prefix, ci, found, error, depth + 1);
            }
            /* S_ISLNK and other types: skip */
        }

        free(full);
        free(names[i]);
    }

    free(names);
}

static void usage(void) {
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int saw_terminator = 0;
    int prefix_mode = -1;
    int recursive = 0;
    int ignore_case = 0;
    int pattern_idx = -1;
    char **file_args = NULL;
    int file_count = 0;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];

        if (!saw_terminator) {
            if (strcmp(arg, "--") == 0) {
                saw_terminator = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (arg[1] == '-') {
                    if (strcmp(arg, "--with-filename") == 0) {
                        prefix_mode = 1;
                    } else if (strcmp(arg, "--no-filename") == 0) {
                        prefix_mode = 0;
                    } else if (strcmp(arg, "--recursive") == 0) {
                        recursive = 1;
                    } else if (strcmp(arg, "--ignore-case") == 0) {
                        ignore_case = 1;
                    } else {
                        usage();
                        return 2;
                    }
                    continue;
                }
                for (const char *c = arg + 1; *c; c++) {
                    if (*c == 'H') {
                        prefix_mode = 1;
                    } else if (*c == 'h') {
                        prefix_mode = 0;
                    } else if (*c == 'r') {
                        recursive = 1;
                    } else if (*c == 'i') {
                        ignore_case = 1;
                    } else {
                        usage();
                        return 2;
                    }
                }
                continue;
            }
        }

        if (pattern_idx == -1) {
            pattern_idx = i;
        } else {
            file_args = xrealloc(file_args, (size_t)(file_count + 1) * sizeof(char *));
            file_args[file_count++] = (char *)arg;
        }
    }

    if (pattern_idx == -1) {
        usage();
        return 2;
    }

    const char *pattern = argv[pattern_idx];
    size_t pattern_len = strlen(pattern);

    unsigned char *folded_pat = NULL;
    if (ignore_case && pattern_len > 0) {
        folded_pat = xrealloc(NULL, pattern_len);
        for (size_t i = 0; i < pattern_len; i++)
            folded_pat[i] = fold_byte((unsigned char)pattern[i]);
        pattern = (const char *)folded_pat;
    }

    int use_prefix;
    if (prefix_mode == 1)
        use_prefix = 1;
    else if (prefix_mode == 0)
        use_prefix = 0;
    else if (file_count >= 2)
        use_prefix = 1;
    else if (recursive) {
        use_prefix = 0;
        for (int i = 0; i < file_count; i++) {
            struct stat st;
            if (stat(file_args[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                use_prefix = 1;
                break;
            }
        }
    } else
        use_prefix = 0;

    int any_found = 0;
    int had_error = 0;

    if (file_count == 0) {
        const char *stdin_prefix = use_prefix ? "(standard input)" : NULL;
        if (search_fd(0, (const unsigned char *)pattern, pattern_len, stdin_prefix, ignore_case, &any_found) != 0)
            had_error = 1;
    } else {
        for (int i = 0; i < file_count; i++) {
            const char *path = file_args[i];

            struct stat st;
            if (stat(path, &st) != 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                had_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "new_grep: %s: is a directory\n", path);
                    had_error = 1;
                    continue;
                }
                traverse_dir(path, (const unsigned char *)pattern, pattern_len,
                             use_prefix, ignore_case, &any_found, &had_error, 0);
                continue;
            }

            int fd = open(path, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                had_error = 1;
                continue;
            }

            const char *prefix = use_prefix ? path : NULL;
            if (search_fd(fd, (const unsigned char *)pattern, pattern_len, prefix, ignore_case, &any_found) != 0)
                had_error = 1;
            close(fd);
        }
    }

    free(folded_pat);
    free(file_args);

    if (had_error) return 2;
    return any_found ? 0 : 1;
}
