#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>

/* Fold a single byte for case-insensitive comparison: ASCII A-Z (0x41-0x5A)
   maps to a-z (0x61-0x7A); all other bytes are unchanged. */
static unsigned char fold_byte(unsigned char c) {
    if (c >= 0x41 && c <= 0x5A)
        return (unsigned char)(c + 0x20);
    return c;
}

/* Byte-level fixed substring test.  Returns 1 if pattern occurs in line. */
static int line_matches(const unsigned char *line, size_t line_len,
                        const unsigned char *pattern, size_t pattern_len,
                        int ignore_case) {
    if (pattern_len == 0)
        return 1;
    if (line_len < pattern_len)
        return 0;
    if (ignore_case) {
        for (size_t i = 0; i + pattern_len <= line_len; i++) {
            int found = 1;
            for (size_t j = 0; j < pattern_len; j++) {
                if (fold_byte(line[i + j]) != fold_byte(pattern[j])) {
                    found = 0;
                    break;
                }
            }
            if (found)
                return 1;
        }
    } else {
        for (size_t i = 0; i + pattern_len <= line_len; i++)
            if (memcmp(line + i, pattern, pattern_len) == 0)
                return 1;
    }
    return 0;
}

/*
 * Core line-selection: scan `stream` for lines containing `pattern`.
 * If `prefix` is non-NULL and `prefix_len > 0`, each emitted line is
 * prefixed with prefix + ':'.
 * Returns 1 (at least one match), 0 (no match), or -1 (error).
 */
int search_stream(FILE *stream, const char *pattern,
                  const char *prefix, size_t prefix_len,
                  int ignore_case) {
    const size_t pattern_len = strlen(pattern);
    int has_match = 0;
    int had_error = 0;

    unsigned char *line = NULL;
    size_t line_len = 0;
    size_t line_cap = 0;

    unsigned char buf[8192];
    size_t buf_len;

    while ((buf_len = fread(buf, 1, sizeof(buf), stream)) > 0) {
        size_t pos = 0;
        while (pos < buf_len) {
            if (buf[pos] == '\n') {
                /* Emit the completed line if it matches. */
                if (line_matches(line, line_len,
                                 (const unsigned char *)pattern, pattern_len, ignore_case)) {
                    if (prefix && prefix_len > 0) {
                        if (fwrite(prefix, 1, prefix_len, stdout) != prefix_len)
                            had_error = 1;
                        if (fputc(':', stdout) == EOF)
                            had_error = 1;
                    }
                    if (line_len > 0) {
                        if (fwrite(line, 1, line_len, stdout) != line_len)
                            had_error = 1;
                    }
                    if (fputc('\n', stdout) == EOF)
                        had_error = 1;
                    has_match = 1;
                }
                line_len = 0;
                pos++;
            } else {
                /* Grow line buffer if needed. */
                if (line_len == line_cap) {
                    size_t new_cap;
                    if (line_cap == 0)
                        new_cap = 4096;
                    else if (line_cap > SIZE_MAX / 2) {
                        free(line);
                        line = NULL;
                        had_error = 1;
                        goto cleanup;
                    } else {
                        new_cap = line_cap * 2;
                    }
                    unsigned char *nl = realloc(line, new_cap);
                    if (!nl) {
                        free(line);
                        line = NULL;
                        had_error = 1;
                        goto cleanup;
                    }
                    line = nl;
                    line_cap = new_cap;
                }
                line[line_len++] = buf[pos++];
            }
        }
    }

    if (ferror(stream))
        had_error = 1;

    /* Final unterminated line (no trailing newline in input). */
    if (!had_error && line_len > 0) {
        if (line_matches(line, line_len,
                         (const unsigned char *)pattern, pattern_len, ignore_case)) {
            if (prefix && prefix_len > 0) {
                if (fwrite(prefix, 1, prefix_len, stdout) != prefix_len)
                    had_error = 1;
                if (fputc(':', stdout) == EOF)
                    had_error = 1;
            }
            if (fwrite(line, 1, line_len, stdout) != line_len)
                had_error = 1;
            if (fputc('\n', stdout) == EOF)
                had_error = 1;
            has_match = 1;
        }
    }

cleanup:
    free(line);
    if (had_error)
        return -1;
    return has_match ? 1 : 0;
}

/* Build "base/name" avoiding a doubled '/' if base already ends with one.
   Returns a malloc'd string, or NULL on allocation failure. */
static char *build_path(const char *base, const char *name) {
    size_t blen = strlen(base);
    size_t nlen = strlen(name);
    int need_slash = (blen > 0 && base[blen - 1] != '/');
    size_t total = blen + (need_slash ? (size_t)1 : (size_t)0) + nlen + 1;
    char *result = malloc(total);
    if (!result)
        return NULL;
    memcpy(result, base, blen);
    size_t pos = blen;
    if (need_slash)
        result[pos++] = '/';
    memcpy(result + pos, name, nlen + 1);
    return result;
}

/* qsort comparator: ascending raw-byte (unsigned char) order. */
static int compare_names(const void *a, const void *b) {
    const char *sa = *(const char *const *)a;
    const char *sb = *(const char *const *)b;
    size_t la = strlen(sa);
    size_t lb = strlen(sb);
    size_t minlen = la < lb ? la : lb;
    int cmp = (minlen > 0) ? memcmp(sa, sb, minlen) : 0;
    if (cmp != 0)
        return (cmp < 0) ? -1 : 1;
    if (la < lb) return -1;
    if (la > lb) return 1;
    return 0;
}

/* Pre-order recursive directory traversal.
   Visits immediate entries in ascending raw-byte name order.
   Searches regular files (via search_stream), recurses into subdirectories,
   skips symlinks and all other special files.
   Diagnoses and continues past unreadable entries. */
static void recursive_search(const char *dir_path, const char *pattern,
                             int use_prefix, int ignore_case,
                             int *overall_match, int *overall_error) {
    DIR *dp = opendir(dir_path);
    if (!dp) {
        fprintf(stderr, "c_grep: %s: %s\n", dir_path, strerror(errno));
        *overall_error = 1;
        return;
    }

    char **names = NULL;
    int n = 0, cap = 0;

    while (1) {
        errno = 0;
        struct dirent *entry = readdir(dp);
        if (!entry) {
            if (errno != 0) {
                fprintf(stderr, "c_grep: %s: %s\n", dir_path, strerror(errno));
                *overall_error = 1;
                for (int i = 0; i < n; i++) free(names[i]);
                free(names);
                closedir(dp);
                return;
            }
            break;
        }
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if ((size_t)n == (size_t)cap) {
            int ncap = cap ? cap * 2 : 64;
            char **nn = realloc(names, (size_t)ncap * sizeof(char *));
            if (!nn) {
                for (int i = 0; i < n; i++) free(names[i]);
                free(names);
                closedir(dp);
                *overall_error = 1;
                return;
            }
            names = nn;
            cap = ncap;
        }
        names[n] = strdup(entry->d_name);
        if (!names[n]) {
            for (int i = 0; i < n; i++) free(names[i]);
            free(names);
            closedir(dp);
            *overall_error = 1;
            return;
        }
        n++;
    }
    closedir(dp);

    qsort(names, (size_t)n, sizeof(char *), compare_names);

    for (int i = 0; i < n; i++) {
        char *full = build_path(dir_path, names[i]);
        if (!full) {
            *overall_error = 1;
            for (int j = i; j < n; j++) free(names[j]);
            free(names);
            return;
        }

        struct stat st;
        if (lstat(full, &st) != 0) {
            fprintf(stderr, "c_grep: %s: %s\n", full, strerror(errno));
            *overall_error = 1;
            free(full);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(full);
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            FILE *fp = fopen(full, "r");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: %s\n", full, strerror(errno));
                *overall_error = 1;
            } else {
                const char *pfx = use_prefix ? full : NULL;
                size_t pfx_len = use_prefix ? strlen(full) : 0;
                int r = search_stream(fp, pattern, pfx, pfx_len, ignore_case);
                fclose(fp);
                if (r < 0)
                    *overall_error = 1;
                else if (r > 0)
                    *overall_match = 1;
            }
        } else if (S_ISDIR(st.st_mode)) {
            recursive_search(full, pattern, use_prefix, ignore_case,
                             overall_match, overall_error);
        }
        /* fifo, socket, device: skipped silently. */

        free(full);
    }

    for (int i = 0; i < n; i++) free(names[i]);
    free(names);
}

int main(int argc, char *argv[]) {
    const char *pattern = NULL;
    char **files = NULL;
    int nfiles = 0;
    int options_done = 0;
    /* 0 = default, 1 = force (-H), 2 = suppress (-h); last occurrence wins */
    int prefix_mode = 0;
    int recursive = 0;
    int ignore_case = 0;

    for (int i = 1; i < argc; i++) {
        if (!options_done && argv[i][0] == '-' && strlen(argv[i]) > 1) {
            if (strcmp(argv[i], "--") == 0) {
                options_done = 1;
                continue;
            }
            if (strcmp(argv[i], "--with-filename") == 0) {
                prefix_mode = 1;
                continue;
            }
            if (strcmp(argv[i], "--no-filename") == 0) {
                prefix_mode = 2;
                continue;
            }
            if (strcmp(argv[i], "--recursive") == 0) {
                recursive = 1;
                continue;
            }
            if (strcmp(argv[i], "--ignore-case") == 0) {
                ignore_case = 1;
                continue;
            }
            /* Short option cluster: every char after '-' must be 'H', 'h', 'r', or 'i'. */
            int valid = 1;
            for (const char *c = argv[i] + 1; *c; c++) {
                if (*c != 'H' && *c != 'h' && *c != 'r' && *c != 'i') { valid = 0; break; }
            }
            if (valid) {
                for (const char *c = argv[i] + 1; *c; c++) {
                    if (*c == 'H') prefix_mode = 1;
                    else if (*c == 'h') prefix_mode = 2;
                    else if (*c == 'r') recursive = 1;
                    else if (*c == 'i') ignore_case = 1;
                }
                continue;
            }
            fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
            return 2;
        }
        if (pattern == NULL) {
            pattern = argv[i];
        } else {
            char **nf = realloc(files,
                                (size_t)(nfiles + 1) * sizeof(char *));
            if (!nf) {
                free(files);
                fprintf(stderr, "c_grep: memory allocation failed\n");
                return 2;
            }
            files = nf;
            files[nfiles++] = argv[i];
        }
    }

    if (pattern == NULL) {
        fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
        return 2;
    }

    int overall_match = 0;
    int overall_error = 0;

    if (nfiles == 0) {
        int use_prefix = (prefix_mode == 1);
        const char *pfx = use_prefix ? "(standard input)" : NULL;
        size_t pfx_len = use_prefix ? strlen("(standard input)") : 0;
        int r = search_stream(stdin, pattern, pfx, pfx_len, ignore_case);
        if (r < 0)
            overall_error = 1;
        else if (r > 0)
            overall_match = 1;
    } else {
        /* Determine whether any operand resolves to a directory (follows symlinks). */
        int any_dir = 0;
        for (int f = 0; f < nfiles; f++) {
            struct stat st;
            if (stat(files[f], &st) == 0 && S_ISDIR(st.st_mode)) {
                any_dir = 1;
                break;
            }
        }

        int use_prefix;
        if (prefix_mode == 1)
            use_prefix = 1;
        else if (prefix_mode == 2)
            use_prefix = 0;
        else if (recursive)
            use_prefix = (nfiles >= 2) || any_dir;
        else
            use_prefix = (nfiles >= 2);

        for (int f = 0; f < nfiles; f++) {
            struct stat st;
            if (stat(files[f], &st) != 0) {
                fprintf(stderr, "c_grep: %s: %s\n", files[f], strerror(errno));
                overall_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "c_grep: %s: Is a directory\n", files[f]);
                    overall_error = 1;
                    continue;
                }
                recursive_search(files[f], pattern, use_prefix, ignore_case,
                                 &overall_match, &overall_error);
                continue;
            }
            if (!S_ISREG(st.st_mode)) {
                fprintf(stderr, "c_grep: %s: Not a regular file\n", files[f]);
                overall_error = 1;
                continue;
            }
            FILE *fp = fopen(files[f], "r");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: %s\n", files[f], strerror(errno));
                overall_error = 1;
                continue;
            }
            const char *pfx = use_prefix ? files[f] : NULL;
            size_t pfx_len = use_prefix ? strlen(files[f]) : 0;
            int r = search_stream(fp, pattern, pfx, pfx_len, ignore_case);
            fclose(fp);
            if (r < 0)
                overall_error = 1;
            else if (r > 0)
                overall_match = 1;
        }
    }

    free(files);

    if (overall_error)
        return 2;
    return overall_match ? 0 : 1;
}
