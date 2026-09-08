#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <sys/stat.h>
#include <dirent.h>

static void die_usage(void) {
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
    exit(2);
}

static unsigned char fold_byte(unsigned char c) {
    if (c >= 0x41 && c <= 0x5A) return c + 0x20;
    return c;
}

static unsigned char *fold_copy(const unsigned char *src, size_t len) {
    unsigned char *dst = malloc(len);
    if (!dst) return NULL;
    for (size_t i = 0; i < len; i++)
        dst[i] = fold_byte(src[i]);
    return dst;
}

static bool line_matches(const unsigned char *line, size_t len,
                         const unsigned char *pat, size_t plen,
                         bool ignore_case) {
    if (plen == 0) return true;
    if (plen > len) return false;
    for (size_t i = 0; i + plen <= len; i++) {
        bool match = true;
        for (size_t j = 0; j < plen; j++) {
            unsigned char c = line[i + j];
            if (ignore_case) c = fold_byte(c);
            if (c != pat[j]) { match = false; break; }
        }
        if (match) return true;
    }
    return false;
}

typedef struct {
    unsigned char *buf;
    size_t len;
    size_t cap;
} linebuf_t;

static void lb_reset(linebuf_t *lb) {
    lb->len = 0;
}

static void lb_append(linebuf_t *lb, unsigned char c) {
    if (lb->len + 1 > lb->cap) {
        size_t newcap = lb->cap ? lb->cap * 2 : 256;
        unsigned char *newbuf = realloc(lb->buf, newcap);
        if (!newbuf) {
            fprintf(stderr, "new_grep: out of memory\n");
            free(lb->buf);
            exit(2);
        }
        lb->buf = newbuf;
        lb->cap = newcap;
    }
    lb->buf[lb->len++] = c;
}

static int emit_line(const unsigned char *line, size_t len,
                     const char *prefix, FILE *out) {
    if (prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, out) != plen) return -1;
        if (fputc(':', out) == EOF) return -1;
    }
    if (len > 0 && fwrite(line, 1, len, out) != len) return -1;
    if (fputc('\n', out) == EOF) return -1;
    return 0;
}

static int search_stream(FILE *fp, const unsigned char *pat, size_t plen,
                         const char *prefix, bool *found,
                         bool ignore_case) {
    linebuf_t lb = {NULL, 0, 0};
    unsigned char chunk[8192];
    size_t n;

    while ((n = fread(chunk, 1, sizeof(chunk), fp)) > 0) {
        for (size_t i = 0; i < n; i++) {
            if (chunk[i] == '\n') {
                if (line_matches(lb.buf, lb.len, pat, plen, ignore_case)) {
                    if (emit_line(lb.buf, lb.len, prefix, stdout) != 0) {
                        fprintf(stderr, "new_grep: write error\n");
                        free(lb.buf);
                        return -1;
                    }
                    *found = true;
                }
                lb_reset(&lb);
            } else {
                lb_append(&lb, chunk[i]);
            }
        }
    }

    if (ferror(fp)) {
        fprintf(stderr, "new_grep: read error\n");
        free(lb.buf);
        return -1;
    }

    if (lb.len > 0) {
        if (line_matches(lb.buf, lb.len, pat, plen, ignore_case)) {
            if (emit_line(lb.buf, lb.len, prefix, stdout) != 0) {
                fprintf(stderr, "new_grep: write error\n");
                free(lb.buf);
                return -1;
            }
            *found = true;
        }
    }

    free(lb.buf);
    return 0;
}

/* --- recursive traversal --- */

#define MAX_DEPTH 1024

static int cmp_names(const void *a, const void *b) {
    const char *x = *(const char *const *)a;
    const char *y = *(const char *const *)b;
    size_t lx = strlen(x), ly = strlen(y);
    size_t min = lx < ly ? lx : ly;
    int c = memcmp(x, y, min);
    if (c) return c;
    if (lx < ly) return -1;
    if (lx > ly) return 1;
    return 0;
}

static void traverse_dir(const char *dirpath, const unsigned char *pat,
                         size_t plen, bool use_prefix, bool *found,
                         bool *error, int depth, bool ignore_case) {
    if (depth > MAX_DEPTH) {
        fprintf(stderr, "new_grep: %s: directory too deep\n", dirpath);
        *error = true;
        return;
    }

    DIR *d = opendir(dirpath);
    if (!d) {
        fprintf(stderr, "new_grep: %s: cannot open directory\n", dirpath);
        *error = true;
        return;
    }

    char **entries = NULL;
    int nentries = 0;
    int cap = 0;

    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0)
            continue;
        if (nentries >= cap) {
            int newcap = cap ? cap * 2 : 16;
            char **ne = realloc(entries, (size_t)newcap * sizeof(char *));
            if (!ne) {
                closedir(d);
                for (int i = 0; i < nentries; i++) free(entries[i]);
                free(entries);
                *error = true;
                return;
            }
            entries = ne;
            cap = newcap;
        }
        entries[nentries] = strdup(ent->d_name);
        if (!entries[nentries]) {
            closedir(d);
            for (int i = 0; i < nentries; i++) free(entries[i]);
            free(entries);
            *error = true;
            return;
        }
        nentries++;
    }
    closedir(d);

    qsort(entries, (size_t)nentries, sizeof(char *), cmp_names);

    /* Normalize dirpath: strip trailing slashes (but keep at least one char) */
    size_t dlen = strlen(dirpath);
    while (dlen > 1 && dirpath[dlen - 1] == '/') dlen--;

    for (int i = 0; i < nentries; i++) {
        size_t name_len = strlen(entries[i]);
        char *fullpath = malloc(dlen + 1 + name_len + 1);
        if (!fullpath) {
            fprintf(stderr, "new_grep: out of memory\n");
            for (int j = 0; j < nentries; j++) free(entries[j]);
            free(entries);
            *error = true;
            return;
        }
        memcpy(fullpath, dirpath, dlen);
        fullpath[dlen] = '/';
        memcpy(fullpath + dlen + 1, entries[i], name_len);
        fullpath[dlen + 1 + name_len] = '\0';

        struct stat st;
        if (lstat(fullpath, &st) != 0) {
            fprintf(stderr, "new_grep: %s: cannot stat\n", fullpath);
            *error = true;
            free(fullpath);
            free(entries[i]);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(fullpath);
            free(entries[i]);
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            FILE *fp = fopen(fullpath, "rb");
            if (!fp) {
                fprintf(stderr, "new_grep: %s: cannot open\n", fullpath);
                *error = true;
                free(fullpath);
                free(entries[i]);
                continue;
            }
            const char *prefix = use_prefix ? fullpath : NULL;
            if (search_stream(fp, pat, plen, prefix, found,
                              ignore_case) != 0) {
                *error = true;
            }
            fclose(fp);
        } else if (S_ISDIR(st.st_mode)) {
            traverse_dir(fullpath, pat, plen, use_prefix, found, error,
                         depth + 1, ignore_case);
        }

        free(fullpath);
        free(entries[i]);
    }

    free(entries);
}

/* --- end recursive traversal --- */

int main(int argc, char *argv[]) {
    if (argc < 2) {
        die_usage();
    }

    typedef enum { PREFIX_DEFAULT, PREFIX_ON, PREFIX_OFF } pmode_t;
    pmode_t pmode = PREFIX_DEFAULT;
    bool recursive = false;
    bool ignore_case = false;
    bool seen_terminator = false;
    char *operands[512];
    int nops = 0;

    for (int i = 1; i < argc; i++) {
        if (!seen_terminator) {
            if (strcmp(argv[i], "--") == 0) {
                seen_terminator = true;
                continue;
            }
            if (strcmp(argv[i], "--with-filename") == 0) {
                pmode = PREFIX_ON;
                continue;
            }
            if (strcmp(argv[i], "--no-filename") == 0) {
                pmode = PREFIX_OFF;
                continue;
            }
            if (strcmp(argv[i], "--recursive") == 0) {
                recursive = true;
                continue;
            }
            if (strcmp(argv[i], "--ignore-case") == 0) {
                ignore_case = true;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                const char *p = argv[i] + 1;
                for (; *p; p++) {
                    if (*p == 'H') pmode = PREFIX_ON;
                    else if (*p == 'h') pmode = PREFIX_OFF;
                    else if (*p == 'r') recursive = true;
                    else if (*p == 'i') ignore_case = true;
                    else {
                        fprintf(stderr, "new_grep: unknown option '%s'\n", argv[i]);
                        exit(2);
                    }
                }
                continue;
            }
        }
        operands[nops++] = argv[i];
    }

    if (nops == 0) die_usage();

    const char *pattern = operands[0];
    char **files = operands + 1;
    int nfiles = nops - 1;

    size_t patlen = strlen(pattern);

    /* Pre-fold the pattern once if case-insensitive matching is requested */
    unsigned char *search_pat = (unsigned char *)(uintptr_t)pattern;
    unsigned char *folded_pat = NULL;
    if (ignore_case && patlen > 0) {
        folded_pat = fold_copy((const unsigned char *)pattern, patlen);
        if (!folded_pat) {
            fprintf(stderr, "new_grep: out of memory\n");
            exit(2);
        }
        search_pat = folded_pat;
    }

    /* Decide prefix mode */
    bool use_prefix;
    if (pmode == PREFIX_ON) {
        use_prefix = true;
    } else if (pmode == PREFIX_OFF) {
        use_prefix = false;
    } else if (nfiles >= 2) {
        use_prefix = true;
    } else if (recursive) {
        /* Check if at least one operand is a directory (follow symlinks) */
        use_prefix = false;
        for (int i = 0; i < nfiles; i++) {
            struct stat st;
            if (stat(files[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                use_prefix = true;
                break;
            }
        }
    } else {
        use_prefix = false;
    }

    bool found = false;
    bool error = false;

    if (nfiles == 0) {
        const char *prefix = use_prefix ? "(standard input)" : NULL;
        if (search_stream(stdin, search_pat, patlen, prefix,
                          &found, ignore_case) != 0) {
            error = true;
        }
    } else {
        for (int i = 0; i < nfiles; i++) {
            struct stat st;
            if (stat(files[i], &st) != 0) {
                fprintf(stderr, "new_grep: %s: No such file or directory\n",
                        files[i]);
                error = true;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "new_grep: %s: Is a directory\n", files[i]);
                    error = true;
                    continue;
                }
                traverse_dir(files[i], search_pat, patlen, use_prefix,
                             &found, &error, 0, ignore_case);
                continue;
            }
            FILE *fp = fopen(files[i], "rb");
            if (!fp) {
                fprintf(stderr, "new_grep: %s: cannot open\n", files[i]);
                error = true;
                continue;
            }
            const char *prefix = use_prefix ? files[i] : NULL;
            if (search_stream(fp, search_pat, patlen, prefix,
                              &found, ignore_case) != 0) {
                error = true;
            }
            fclose(fp);
        }
    }

    free(folded_pat);

    if (error) return 2;
    if (found) return 0;
    return 1;
}
