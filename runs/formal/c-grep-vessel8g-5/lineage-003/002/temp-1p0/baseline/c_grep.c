#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>

/* Byte-level fixed substring test.  Returns 1 if pattern occurs in line. */
static int line_matches(const unsigned char *line, size_t line_len,
                        const unsigned char *pattern, size_t pattern_len) {
    if (pattern_len == 0)
        return 1;
    if (line_len < pattern_len)
        return 0;
    for (size_t i = 0; i + pattern_len <= line_len; i++)
        if (memcmp(line + i, pattern, pattern_len) == 0)
            return 1;
    return 0;
}

/*
 * Core line-selection: scan `stream` for lines containing `pattern`.
 * If `prefix` is non-NULL and `prefix_len > 0`, each emitted line is
 * prefixed with prefix + ':'.
 * Returns 1 (at least one match), 0 (no match), or -1 (error).
 */
int search_stream(FILE *stream, const char *pattern,
                  const char *prefix, size_t prefix_len) {
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
                                 (const unsigned char *)pattern, pattern_len)) {
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
                         (const unsigned char *)pattern, pattern_len)) {
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

int main(int argc, char *argv[]) {
    const char *pattern = NULL;
    char **files = NULL;
    int nfiles = 0;
    int options_done = 0;
    int with_filename = 0;

    for (int i = 1; i < argc; i++) {
        if (!options_done && argv[i][0] == '-' && strlen(argv[i]) > 1) {
            if (strcmp(argv[i], "--") == 0) {
                options_done = 1;
                continue;
            }
            if (strcmp(argv[i], "--with-filename") == 0) {
                with_filename = 1;
                continue;
            }
            /* Short option cluster: every char after '-' must be 'H'. */
            int valid = 1;
            for (const char *c = argv[i] + 1; *c; c++) {
                if (*c != 'H') { valid = 0; break; }
            }
            if (valid) {
                with_filename = 1;
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
        const char *pfx = with_filename ? "(standard input)" : NULL;
        size_t pfx_len = with_filename ? strlen("(standard input)") : 0;
        int r = search_stream(stdin, pattern, pfx, pfx_len);
        if (r < 0)
            overall_error = 1;
        else if (r > 0)
            overall_match = 1;
    } else {
        int use_prefix = (nfiles >= 2) || with_filename;
        for (int f = 0; f < nfiles; f++) {
            struct stat st;
            if (stat(files[f], &st) != 0) {
                fprintf(stderr, "c_grep: %s: %s\n", files[f], strerror(errno));
                overall_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "c_grep: %s: Is a directory\n", files[f]);
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
            int r = search_stream(fp, pattern, pfx, pfx_len);
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
