#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>

/* Fixed-byte substring search: returns pointer to first occurrence or NULL. */
static const unsigned char *find_sub(const unsigned char *hay, size_t hlen,
                                     const unsigned char *needle, size_t nlen,
                                     int icase) {
    if (nlen == 0) return hay;
    if (nlen > hlen) return NULL;
    if (!icase) {
        for (size_t i = 0; i + nlen <= hlen; i++) {
            if (memcmp(hay + i, needle, nlen) == 0)
                return hay + i;
        }
        return NULL;
    }
    for (size_t i = 0; i + nlen <= hlen; i++) {
        int ok = 1;
        for (size_t j = 0; j < nlen; j++) {
            unsigned char a = hay[i + j];
            unsigned char b = needle[j];
            if (a >= 0x41 && a <= 0x5A) a += 0x20;
            if (b >= 0x41 && b <= 0x5A) b += 0x20;
            if (a != b) { ok = 0; break; }
        }
        if (ok) return hay + i;
    }
    return NULL;
}

/* Emit a matched line (with optional prefix) to stdout. Returns 0 on success, -1 on I/O error. */
static int emit_line(const unsigned char *line, size_t len,
                     const char *prefix, size_t prefix_len) {
    if (prefix_len > 0) {
        if (fwrite(prefix, 1, prefix_len, stdout) < prefix_len)
            return -1;
    }
    if (len > 0) {
        if (fwrite(line, 1, len, stdout) < len)
            return -1;
    }
    if (fputc('\n', stdout) == EOF)
        return -1;
    return 0;
}

/* Core line-selection: reads lines from fp, emits those containing the fixed
   byte substring pattern. An empty pattern matches every line.
   Returns 1 if any line matched, 0 if none, -1 on error. */
int search_stream(FILE *fp, const unsigned char *pattern, size_t plen,
                  const char *prefix, size_t prefix_len, int icase) {
    int found = 0;
    unsigned char *line = NULL;
    size_t line_len = 0, line_cap = 0;
    int c;

    while ((c = fgetc(fp)) != EOF) {
        if (c == '\n') {
            if (plen == 0 || find_sub(line, line_len, pattern, plen, icase)) {
                if (emit_line(line, line_len, prefix, prefix_len) != 0) {
                    free(line);
                    return -1;
                }
                found = 1;
            }
            line_len = 0;
        } else {
            if (line_len + 1 > line_cap) {
                if (line_cap > SIZE_MAX / 2) { free(line); return -1; }
                size_t newcap = line_cap ? line_cap * 2 : 256;
                unsigned char *nl = realloc(line, newcap);
                if (!nl) { free(line); return -1; }
                line = nl;
                line_cap = newcap;
            }
            line[line_len++] = (unsigned char)c;
        }
    }

    if (ferror(fp)) {
        free(line);
        return -1;
    }

    /* Final unterminated line */
    if (line_len > 0) {
        if (plen == 0 || find_sub(line, line_len, pattern, plen, icase)) {
            if (emit_line(line, line_len, prefix, prefix_len) != 0) {
                free(line);
                return -1;
            }
            found = 1;
        }
    }

    free(line);
    return found;
}

static int cmp_name(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

static void traverse_dir(const char *base,
                         const unsigned char *pattern, size_t plen,
                         int multi, int *found, int *error,
                         int depth, int icase) {
    if (depth > 1024) {
        fprintf(stderr, "c_grep: %s: directory hierarchy too deep\n", base);
        *error = 1;
        return;
    }
    DIR *dp = opendir(base);
    if (!dp) {
        fprintf(stderr, "c_grep: %s: %s\n", base, strerror(errno));
        *error = 1;
        return;
    }

    char **names = NULL;
    size_t n = 0, cap = 0;
    struct dirent *de;
    int alloc_fail = 0;

    while ((de = readdir(dp)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0)
            continue;
        size_t len = strlen(de->d_name);
        char *dup = malloc(len + 1);
        if (!dup) { alloc_fail = 1; break; }
        memcpy(dup, de->d_name, len + 1);
        if (n == cap) {
            cap = cap ? cap * 2 : 16;
            char **tmp = realloc(names, cap * sizeof(*tmp));
            if (!tmp) { free(dup); alloc_fail = 1; break; }
            names = tmp;
        }
        names[n++] = dup;
    }
    closedir(dp);

    if (alloc_fail) {
        fprintf(stderr, "c_grep: %s: cannot allocate memory\n", base);
        *error = 1;
        for (size_t i = 0; i < n; i++) free(names[i]);
        free(names);
        return;
    }

    qsort(names, n, sizeof(*names), cmp_name);

    size_t blen = strlen(base);
    int need_slash = (blen > 0 && base[blen - 1] != '/');

    for (size_t i = 0; i < n; i++) {
        size_t elen = strlen(names[i]);
        size_t flen = blen + (need_slash ? 1 : 0) + elen + 1;
        char *full = malloc(flen);
        if (!full) {
            fprintf(stderr, "c_grep: %s: cannot allocate memory\n", names[i]);
            *error = 1;
            continue;
        }
        memcpy(full, base, blen);
        size_t off = blen;
        if (need_slash) full[off++] = '/';
        memcpy(full + off, names[i], elen + 1);

        struct stat st;
        if (lstat(full, &st) != 0) {
            fprintf(stderr, "c_grep: %s: %s\n", full, strerror(errno));
            *error = 1;
        } else if (S_ISLNK(st.st_mode)) {
            /* skip symlinks during traversal */
        } else if (S_ISREG(st.st_mode)) {
            FILE *fp = fopen(full, "rb");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: %s\n", full, strerror(errno));
                *error = 1;
            } else {
                int r;
                if (multi) {
                    size_t plen2 = flen - 1; /* strlen(full) */
                    char *prefix = malloc(plen2 + 2);
                    if (!prefix) {
                        fprintf(stderr, "c_grep: %s: cannot allocate memory\n", full);
                        *error = 1;
                        r = -1;
                    } else {
                        memcpy(prefix, full, plen2);
                        prefix[plen2] = ':';
                        prefix[plen2 + 1] = '\0';
                        r = search_stream(fp, pattern, plen, prefix, plen2 + 1, icase);
                        free(prefix);
                    }
                } else {
                    r = search_stream(fp, pattern, plen, NULL, 0, icase);
                }
                if (r < 0) {
                    fprintf(stderr, "c_grep: %s: read error\n", full);
                    *error = 1;
                } else if (r) {
                    *found = 1;
                }
                fclose(fp);
            }
        } else if (S_ISDIR(st.st_mode)) {
            traverse_dir(full, pattern, plen, multi, found, error, depth + 1, icase);
        }
        /* else: FIFO, socket, device — skip */

        free(full);
    }

    for (size_t i = 0; i < n; i++) free(names[i]);
    free(names);
}

static void usage(void) {
    fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    const char **args = NULL;
    int count = 0;
    int after_ddash = 0;
    int with_filename = -1;  /* -1=default, 0=suppress(-h), 1=force(-H) */
    int recursive = 0;
    int ignore_case = 0;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (strcmp(argv[i], "--with-filename") == 0) {
                    with_filename = 1;
                    continue;
                }
                if (strcmp(argv[i], "--no-filename") == 0) {
                    with_filename = 0;
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
                if (argv[i][1] == '-') {
                    /* Unknown long option */
                    usage();
                    free(args);
                    return 2;
                }
                /* Short option cluster: every character must be a supported short option */
                const char *cluster = argv[i] + 1;
                while (*cluster) {
                    if (*cluster == 'H') {
                        with_filename = 1;
                    } else if (*cluster == 'h') {
                        with_filename = 0;
                    } else if (*cluster == 'r') {
                        recursive = 1;
                    } else if (*cluster == 'i') {
                        ignore_case = 1;
                    } else {
                        usage();
                        free(args);
                        return 2;
                    }
                    cluster++;
                }
                continue;
            }
        }
        const char **newargs = realloc(args, (size_t)(count + 1) * sizeof(*args));
        if (!newargs) return 2;
        args = newargs;
        args[count++] = argv[i];
    }

    if (count < 1) {
        usage();
        free(args);
        return 2;
    }

    const char *pattern = args[0];
    size_t plen = strlen(pattern);
    int file_count = count - 1;

    int any_found = 0;
    int any_error = 0;

    if (file_count == 0) {
        const char *stdin_prefix = with_filename == 1 ? "(standard input):" : NULL;
        size_t stdin_prefix_len = with_filename == 1 ? strlen("(standard input):") : 0;
        int r = search_stream(stdin, (const unsigned char *)pattern, plen,
                              stdin_prefix, stdin_prefix_len, ignore_case);
        if (r < 0) {
            fprintf(stderr, "c_grep: read error\n");
            any_error = 1;
        } else if (r) {
            any_found = 1;
        }
    } else {
        int multi;
        if (with_filename == 1) {
            multi = 1;
        } else if (with_filename == 0) {
            multi = 0;
        } else if (recursive) {
            int any_dir = 0;
            for (int i = 1; i < count; i++) {
                struct stat st;
                if (stat(args[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                    any_dir = 1;
                    break;
                }
            }
            multi = (file_count >= 2) || any_dir;
        } else {
            multi = (file_count >= 2);
        }

        for (int f = 0; f < file_count; f++) {
            const char *path = args[1 + f];
            size_t pathlen = strlen(path);

            /* Determine if operand is a directory (follow symlinks) */
            struct stat st;
            if (stat(path, &st) == 0 && S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "c_grep: %s: Is a directory\n", path);
                    any_error = 1;
                    continue;
                }
                traverse_dir(path, (const unsigned char *)pattern, plen,
                             multi, &any_found, &any_error, 0, ignore_case);
                continue;
            }

            /* Non-directory operand: search as a file */
            char *prefix = NULL;
            size_t prefix_len = 0;
            if (multi) {
                prefix = malloc(pathlen + 2);
                if (!prefix) {
                    fprintf(stderr, "c_grep: %s: cannot allocate memory\n", path);
                    any_error = 1;
                    continue;
                }
                memcpy(prefix, path, pathlen);
                prefix[pathlen] = ':';
                prefix[pathlen + 1] = '\0';
                prefix_len = pathlen + 1;
            }

            FILE *fp = fopen(path, "rb");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: %s\n", path, strerror(errno));
                any_error = 1;
                free(prefix);
                continue;
            }

            int r = search_stream(fp, (const unsigned char *)pattern, plen,
                                  prefix, prefix_len, ignore_case);
            if (r < 0) {
                fprintf(stderr, "c_grep: %s: read error\n", path);
                any_error = 1;
            } else if (r) {
                any_found = 1;
            }
            fclose(fp);
            free(prefix);
        }
    }

    free(args);

    if (any_error) return 2;
    if (any_found) return 0;
    return 1;
}
