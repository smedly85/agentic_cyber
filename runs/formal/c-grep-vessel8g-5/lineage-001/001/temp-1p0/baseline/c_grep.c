#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/stat.h>

/* Fixed-byte substring search: returns pointer to first occurrence or NULL. */
static const unsigned char *find_sub(const unsigned char *hay, size_t hlen,
                                     const unsigned char *needle, size_t nlen) {
    if (nlen == 0) return hay;
    if (nlen > hlen) return NULL;
    for (size_t i = 0; i + nlen <= hlen; i++) {
        if (memcmp(hay + i, needle, nlen) == 0)
            return hay + i;
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
                  const char *prefix, size_t prefix_len) {
    int found = 0;
    unsigned char *line = NULL;
    size_t line_len = 0, line_cap = 0;
    int c;

    while ((c = fgetc(fp)) != EOF) {
        if (c == '\n') {
            if (plen == 0 || find_sub(line, line_len, pattern, plen)) {
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
        if (plen == 0 || find_sub(line, line_len, pattern, plen)) {
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

static void usage(void) {
    fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    const char **args = NULL;
    int count = 0;
    int after_ddash = 0;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                usage();
                free(args);
                return 2;
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
        int r = search_stream(stdin, (const unsigned char *)pattern, plen, NULL, 0);
        if (r < 0) {
            fprintf(stderr, "c_grep: read error\n");
            any_error = 1;
        } else if (r) {
            any_found = 1;
        }
    } else {
        int multi = (file_count >= 2);
        for (int f = 0; f < file_count; f++) {
            const char *path = args[1 + f];
            size_t pathlen = strlen(path);

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

            /* Diagnose directories explicitly */
            int fd = fileno(fp);
            struct stat st;
            if (fd >= 0 && fstat(fd, &st) == 0 && S_ISDIR(st.st_mode)) {
                fprintf(stderr, "c_grep: %s: Is a directory\n", path);
                fclose(fp);
                free(prefix);
                any_error = 1;
                continue;
            }

            int r = search_stream(fp, (const unsigned char *)pattern, plen,
                                  prefix, prefix_len);
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
