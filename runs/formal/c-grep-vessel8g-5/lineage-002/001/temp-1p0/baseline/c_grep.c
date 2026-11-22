#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* Fixed byte substring search. Empty needle matches at position 0.
   Returns pointer into hay, or NULL if not found. */
static const unsigned char *find_sub(const unsigned char *hay, size_t hay_len,
                                     const unsigned char *needle, size_t needle_len)
{
    if (needle_len == 0)
        return hay;
    if (needle_len > hay_len)
        return NULL;
    for (size_t i = 0; i <= hay_len - needle_len; i++) {
        if (memcmp(hay + i, needle, needle_len) == 0)
            return hay + i;
    }
    return NULL;
}

/* Emit prefix (if any) + line bytes + '\n' to stdout. Returns 0 or -1. */
static int emit_line(const unsigned char *prefix, size_t prefix_len,
                     const unsigned char *line, size_t line_len)
{
    if (prefix_len > 0 &&
        fwrite(prefix, 1, prefix_len, stdout) != prefix_len)
        return -1;
    if (line_len > 0 && fwrite(line, 1, line_len, stdout) != line_len)
        return -1;
    if (fputc('\n', stdout) == EOF)
        return -1;
    return 0;
}

/* Core line-selection: read lines from fp (delimited by 0x0A), emit those
   containing pattern as a byte substring. Empty pattern matches every line.
   Returns 0 if at least one line matched, 1 if none matched, -1 on I/O error. */
int search_stream(FILE *fp, const unsigned char *pattern, size_t pattern_len,
                  const unsigned char *prefix, size_t prefix_len)
{
    int matched = 0;
    size_t buf_len = 0, buf_cap = 8192;
    unsigned char *buf = malloc(buf_cap);
    if (!buf)
        return -1;

    int c;
    while ((c = fgetc(fp)) != EOF) {
        unsigned char ch = (unsigned char)c;
        if (ch == 0x0A) {
            if (find_sub(buf, buf_len, pattern, pattern_len) != NULL) {
                matched = 1;
                if (emit_line(prefix, prefix_len, buf, buf_len) != 0) {
                    free(buf);
                    return -1;
                }
            }
            buf_len = 0;
        } else {
            if (buf_len >= buf_cap) {
                size_t new_cap = buf_cap * 2;
                if (new_cap < buf_cap) {
                    free(buf);
                    return -1;
                }
                unsigned char *nb = realloc(buf, new_cap);
                if (!nb) {
                    free(buf);
                    return -1;
                }
                buf = nb;
                buf_cap = new_cap;
            }
            buf[buf_len++] = ch;
        }
    }

    if (ferror(fp)) {
        free(buf);
        return -1;
    }

    if (buf_len > 0) {
        if (find_sub(buf, buf_len, pattern, pattern_len) != NULL) {
            matched = 1;
            if (emit_line(prefix, prefix_len, buf, buf_len) != 0) {
                free(buf);
                return -1;
            }
        }
    }

    free(buf);
    return matched ? 0 : 1;
}

int main(int argc, char *argv[])
{
    const char *pattern = NULL;
    const char **files = NULL;
    size_t nfiles = 0, files_cap = 0;
    int options_done = 0;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!options_done) {
            if (strcmp(arg, "--") == 0) {
                options_done = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                fprintf(stderr, "c_grep: unsupported option '%s'\n", arg);
                fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
                free(files);
                return 2;
            }
        }
        if (pattern == NULL) {
            pattern = arg;
        } else {
            if (nfiles >= files_cap) {
                size_t nc = files_cap ? files_cap * 2 : 4;
                const char **nf = realloc(files, nc * sizeof *nf);
                if (!nf) {
                    free(files);
                    fprintf(stderr, "c_grep: out of memory\n");
                    return 2;
                }
                files = nf;
                files_cap = nc;
            }
            files[nfiles++] = arg;
        }
    }

    if (pattern == NULL) {
        fprintf(stderr, "c_grep: missing PATTERN\n");
        fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
        return 2;
    }

    size_t plen = strlen(pattern);
    int any_match = 0;
    int any_error = 0;

    if (nfiles == 0) {
        int rc = search_stream(stdin, (const unsigned char *)pattern, plen,
                               NULL, 0);
        if (rc == 0)
            any_match = 1;
        else if (rc < 0)
            any_error = 1;
    } else {
        int use_prefix = (nfiles >= 2);
        for (size_t i = 0; i < nfiles; i++) {
            const char *name = files[i];
            struct stat st;
            if (stat(name, &st) != 0) {
                fprintf(stderr, "c_grep: %s: cannot access\n", name);
                any_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "c_grep: %s: is a directory\n", name);
                any_error = 1;
                continue;
            }
            FILE *fp = fopen(name, "rb");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: cannot open\n", name);
                any_error = 1;
                continue;
            }
            unsigned char *pfx = NULL;
            size_t pfx_len = 0;
            if (use_prefix) {
                pfx_len = strlen(name) + 1;
                pfx = malloc(pfx_len);
                if (!pfx) {
                    fclose(fp);
                    any_error = 1;
                    continue;
                }
                memcpy(pfx, name, strlen(name));
                pfx[strlen(name)] = ':';
            }
            int rc = search_stream(fp, (const unsigned char *)pattern, plen,
                                   pfx, pfx_len);
            free(pfx);
            fclose(fp);
            if (rc == 0)
                any_match = 1;
            else if (rc < 0)
                any_error = 1;
        }
        free(files);
    }

    if (any_error)
        return 2;
    return any_match ? 0 : 1;
}
