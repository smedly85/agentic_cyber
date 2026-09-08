#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <sys/stat.h>
#include <dirent.h>

__attribute__((noreturn))
static void fail_msg(const char *msg) {
    fprintf(stderr, "new_grep: %s\n", msg);
    exit(2);
}

__attribute__((noreturn))
static void oom(void) {
    fprintf(stderr, "new_grep: out of memory\n");
    exit(2);
}

__attribute__((noreturn))
static void write_err(void) {
    fprintf(stderr, "new_grep: write error\n");
    exit(2);
}

static int bytes_contains(const uint8_t *hay, size_t hay_len,
                          const uint8_t *needle, size_t needle_len) {
    if (needle_len == 0) return 1;
    if (needle_len > hay_len) return 0;
    for (size_t i = 0; i + needle_len <= hay_len; i++) {
        if (memcmp(hay + i, needle, needle_len) == 0)
            return 1;
    }
    return 0;
}

static int cmp_byte_names(const void *a, const void *b) {
    const char *na = *(const char *const *)a;
    const char *nb = *(const char *const *)b;
    size_t la = strlen(na), lb = strlen(nb);
    size_t min = la < lb ? la : lb;
    int c = memcmp(na, nb, min);
    if (c) return c;
    if (la < lb) return -1;
    if (la > lb) return 1;
    return 0;
}

static void search_stream(FILE *fp, const char *prefix,
                          const uint8_t *pat, size_t pat_len, int *has_match);

static void traverse(const char *base, const uint8_t *pat, size_t pat_len,
                     int do_prefix, int *has_match, int *has_error) {
    DIR *dp = opendir(base);
    if (!dp) {
        fprintf(stderr, "new_grep: %s: %s\n", base, strerror(errno));
        *has_error = 1;
        return;
    }

    char **names = NULL;
    size_t n = 0, cap = 0;
    struct dirent *entry;
    while ((entry = readdir(dp)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (n == cap) {
            cap = cap ? cap * 2 : 16;
            char **tmp = realloc(names, cap * sizeof(char *));
            if (!tmp) {
                for (size_t k = 0; k < n; k++) free(names[k]);
                free(names); closedir(dp); oom();
            }
            names = tmp;
        }
        names[n] = strdup(entry->d_name);
        if (!names[n]) {
            for (size_t k = 0; k < n; k++) free(names[k]);
            free(names); closedir(dp); oom();
        }
        n++;
    }
    closedir(dp);

    qsort(names, n, sizeof(char *), cmp_byte_names);

    for (size_t i = 0; i < n; i++) {
        size_t blen = strlen(base);
        int has_slash = (blen > 0 && base[blen - 1] == '/');
        size_t plen = blen + (has_slash ? 0 : 1) + strlen(names[i]) + 1;
        char *full = malloc(plen);
        if (!full) {
            for (size_t k = 0; k < n; k++) free(names[k]);
            free(names); oom();
        }
        if (has_slash)
            snprintf(full, plen, "%s%s", base, names[i]);
        else
            snprintf(full, plen, "%s/%s", base, names[i]);

        struct stat st;
        if (lstat(full, &st) != 0) {
            free(full);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            /* skip symlinks during traversal */
        } else if (S_ISREG(st.st_mode)) {
            FILE *fp = fopen(full, "rb");
            if (!fp) {
                fprintf(stderr, "new_grep: %s: %s\n", full, strerror(errno));
                *has_error = 1;
            } else {
                const char *pfx = do_prefix ? full : NULL;
                search_stream(fp, pfx, pat, pat_len, has_match);
                if (ferror(fp)) {
                    fprintf(stderr, "new_grep: %s: read error\n", full);
                    *has_error = 1;
                }
                fclose(fp);
            }
        } else if (S_ISDIR(st.st_mode)) {
            traverse(full, pat, pat_len, do_prefix, has_match, has_error);
        }

        free(full);
    }

    for (size_t i = 0; i < n; i++) free(names[i]);
    free(names);
}

static uint8_t *read_line(FILE *fp, size_t *out_len) {
    size_t cap = 256, len = 0;
    uint8_t *buf = malloc(cap);
    if (!buf) oom();
    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (c == '\n') { *out_len = len; return buf; }
        if (len == cap) {
            if (cap > (size_t)-1 / 2) oom();
            cap *= 2;
            uint8_t *nb = realloc(buf, cap);
            if (!nb) { free(buf); oom(); }
            buf = nb;
        }
        buf[len++] = (uint8_t)c;
    }
    if (len == 0) { free(buf); *out_len = 0; return NULL; }
    *out_len = len;
    return buf;
}

static void search_stream(FILE *fp, const char *prefix,
                          const uint8_t *pat, size_t pat_len, int *has_match) {
    uint8_t *line; size_t line_len;
    while ((line = read_line(fp, &line_len)) != NULL) {
        if (bytes_contains(line, line_len, pat, pat_len)) {
            if (prefix) {
                size_t pl = strlen(prefix);
                if (fwrite(prefix, 1, pl, stdout) != pl) write_err();
                if (fputc(':', stdout) == EOF) write_err();
            }
            if (line_len > 0 && fwrite(line, 1, line_len, stdout) != line_len)
                write_err();
            if (fputc('\n', stdout) == EOF) write_err();
            *has_match = 1;
        }
        free(line);
    }
}

int main(int argc, char *argv[]) {
    const char *pattern = NULL;
    const char *files[256];
    int nfiles = 0;
    int prefix_mode = -1; /* -1=unspecified, 0=-h won, 1=-H won */
    int after_ddash = 0;
    int pattern_seen = 0;
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (strcmp(argv[i], "--with-filename") == 0) {
                    prefix_mode = 1;
                    continue;
                }
                if (strcmp(argv[i], "--no-filename") == 0) {
                    prefix_mode = 0;
                    continue;
                }
                if (strcmp(argv[i], "--recursive") == 0) {
                    recursive = 1;
                    continue;
                }
                if (argv[i][1] != '-') {
                    for (size_t j = 1; argv[i][j] != '\0'; j++) {
                        if (argv[i][j] == 'H')
                            prefix_mode = 1;
                        else if (argv[i][j] == 'h')
                            prefix_mode = 0;
                        else if (argv[i][j] == 'r')
                            recursive = 1;
                        else
                            fail_msg("unknown option");
                    }
                    continue;
                }
                fail_msg("unknown option");
            }
        }
        if (!pattern_seen) {
            pattern = argv[i];
            pattern_seen = 1;
        } else {
            if (nfiles >= 256) fail_msg("too many files");
            files[nfiles++] = argv[i];
        }
    }

    if (!pattern_seen) fail_msg("missing PATTERN");

    size_t pat_len = strlen(pattern);
    const uint8_t *pat = (const uint8_t *)pattern;
    int has_match = 0, has_error = 0;

    if (nfiles == 0) {
        const char *pfx = (prefix_mode == 1) ? "(standard input)" : NULL;
        search_stream(stdin, pfx, pat, pat_len, &has_match);
    } else {
        int do_prefix;
        if (prefix_mode == 0)
            do_prefix = 0;
        else if (prefix_mode == 1)
            do_prefix = 1;
        else if (nfiles >= 2)
            do_prefix = 1;
        else if (recursive) {
            do_prefix = 0;
            for (int i = 0; i < nfiles; i++) {
                struct stat st2;
                if (stat(files[i], &st2) == 0 && S_ISDIR(st2.st_mode)) {
                    do_prefix = 1;
                    break;
                }
            }
        } else
            do_prefix = 0;

        for (int i = 0; i < nfiles; i++) {
            const char *fname = files[i];
            struct stat st;
            if (stat(fname, &st) != 0) {
                fprintf(stderr, "new_grep: %s: %s\n", fname, strerror(errno));
                has_error = 1; continue;
            }
            if (S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "new_grep: %s: is a directory\n", fname);
                    has_error = 1; continue;
                }
                traverse(fname, pat, pat_len, do_prefix, &has_match, &has_error);
            } else {
                FILE *fp = fopen(fname, "rb");
                if (!fp) {
                    fprintf(stderr, "new_grep: %s: %s\n", fname, strerror(errno));
                    has_error = 1; continue;
                }
                const char *pfx = do_prefix ? fname : NULL;
                search_stream(fp, pfx, pat, pat_len, &has_match);
                if (ferror(fp)) {
                    fprintf(stderr, "new_grep: %s: read error\n", fname);
                    has_error = 1;
                }
                fclose(fp);
            }
        }
    }

    fflush(stdout);
    if (ferror(stdout)) {
        fprintf(stderr, "new_grep: write error\n");
        return 2;
    }
    if (has_error) return 2;
    if (has_match) return 0;
    return 1;
}
