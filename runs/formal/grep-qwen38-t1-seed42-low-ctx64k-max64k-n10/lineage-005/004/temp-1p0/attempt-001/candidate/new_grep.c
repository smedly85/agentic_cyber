#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>
#include <dirent.h>

typedef struct {
    unsigned char *buf;
    size_t len;
    size_t cap;
} ByteBuf;

static int buf_reserve(ByteBuf *b, size_t need) {
    if (b->cap >= need) return 0;
    size_t newcap = b->cap ? b->cap : 256;
    while (newcap < need) newcap *= 2;
    unsigned char *p = realloc(b->buf, newcap);
    if (!p) return -1;
    b->buf = p;
    b->cap = newcap;
    return 0;
}

static int buf_push(ByteBuf *b, unsigned char c) {
    if (buf_reserve(b, b->len + 1) != 0) return -1;
    b->buf[b->len++] = c;
    return 0;
}

static int read_line(FILE *fp, ByteBuf *line) {
    line->len = 0;
    int c;
    int got_any = 0;
    while ((c = getc(fp)) != EOF) {
        got_any = 1;
        if (c == '\n') break;
        if (buf_push(line, (unsigned char)c) != 0) return -2;
    }
    if (c == EOF && !got_any) return -1;
    return 0;
}

static int fixed_match(const unsigned char *hay, size_t haylen,
                       const unsigned char *pat, size_t patlen) {
    if (patlen == 0) return 1;
    if (patlen > haylen) return 0;
    for (size_t i = 0; i <= haylen - patlen; i++) {
        if (memcmp(hay + i, pat, patlen) == 0) return 1;
    }
    return 0;
}

static unsigned char fold_byte(unsigned char c) {
    if (c >= 0x41 && c <= 0x5A) return c + 0x20;
    return c;
}

static int fixed_match_ci(const unsigned char *hay, size_t haylen,
                          const unsigned char *pat, size_t patlen) {
    if (patlen == 0) return 1;
    if (patlen > haylen) return 0;
    for (size_t i = 0; i <= haylen - patlen; i++) {
        int match = 1;
        for (size_t j = 0; j < patlen; j++) {
            if (fold_byte(hay[i + j]) != fold_byte(pat[j])) {
                match = 0;
                break;
            }
        }
        if (match) return 1;
    }
    return 0;
}

static int write_line(const unsigned char *data, size_t len, const char *prefix) {
    if (prefix) {
        if (fputs(prefix, stdout) == EOF) return -1;
        if (putc(':', stdout) == EOF) return -1;
    }
    if (len > 0) {
        if (fwrite(data, 1, len, stdout) != len) return -1;
    }
    if (putc('\n', stdout) == EOF) return -1;
    return 0;
}

static void print_usage(void) {
    fprintf(stderr, "usage: grep PATTERN [FILE...]\n");
}

static int name_compare(const void *a, const void *b) {
    const char *sa = *(const char * const *)a;
    const char *sb = *(const char * const *)b;
    return strcmp(sa, sb);
}

static char *join_path(const char *base, const char *name) {
    size_t blen = strlen(base);
    int need_sep = (blen > 0 && base[blen - 1] != '/');
    size_t nlen = strlen(name);
    size_t total = blen + (size_t)(need_sep ? 1 : 0) + nlen + 1;
    char *result = malloc(total);
    if (!result) return NULL;
    memcpy(result, base, blen);
    size_t pos = blen;
    if (need_sep) result[pos++] = '/';
    memcpy(result + pos, name, nlen + 1);
    return result;
}

#define MAX_RECURSION_DEPTH 1024

static int search_tree(const char *dirpath, const char *display,
                       const unsigned char *pattern, size_t patlen,
                       int use_prefix, int *any_match, int *any_error,
                       int depth, int ignore_case) {
    if (depth > MAX_RECURSION_DEPTH) {
        fprintf(stderr, "grep: %s: recursion depth exceeded\n", display);
        *any_error = 1;
        return -1;
    }

    DIR *dp = opendir(dirpath);
    if (!dp) {
        fprintf(stderr, "grep: %s: %s\n", display, strerror(errno));
        *any_error = 1;
        return -1;
    }

    char **names = NULL;
    int count = 0, cap = 0;
    struct dirent *de;
    int oom = 0;

    while ((de = readdir(dp)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0)
            continue;
        if (count == cap) {
            int newcap = cap ? cap * 2 : 16;
            char **tmp = realloc(names, (size_t)newcap * sizeof *tmp);
            if (!tmp) { oom = 1; break; }
            names = tmp;
            cap = newcap;
        }
        names[count] = strdup(de->d_name);
        if (!names[count]) { oom = 1; break; }
        count++;
    }
    closedir(dp);

    if (oom) {
        for (int i = 0; i < count; i++) free(names[i]);
        free(names);
        return -1;
    }

    qsort(names, (size_t)count, sizeof *names, name_compare);

    for (int i = 0; i < count; i++) {
        char *realpath = join_path(dirpath, names[i]);
        char *disp = join_path(display, names[i]);
        if (!realpath || !disp) {
            free(realpath);
            free(disp);
            for (int j = 0; j < count; j++) free(names[j]);
            free(names);
            return -1;
        }

        struct stat st;
        if (lstat(realpath, &st) != 0) {
            free(realpath);
            free(disp);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(realpath);
            free(disp);
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            FILE *fp = fopen(realpath, "rb");
            if (!fp) {
                fprintf(stderr, "grep: %s: %s\n", disp, strerror(errno));
                *any_error = 1;
            } else {
                ByteBuf line = {0};
                int rc;
                while ((rc = read_line(fp, &line)) == 0) {
                    int matched = ignore_case
                        ? fixed_match_ci(line.buf, line.len, pattern, patlen)
                        : fixed_match(line.buf, line.len, pattern, patlen);
                    if (matched) {
                        const char *prefix = use_prefix ? disp : NULL;
                        if (write_line(line.buf, line.len, prefix) != 0) {
                            free(line.buf);
                            fclose(fp);
                            free(realpath);
                            free(disp);
                            for (int j = 0; j < count; j++) free(names[j]);
                            free(names);
                            return -1;
                        }
                        *any_match = 1;
                    }
                }
                if (rc == -2) {
                    fprintf(stderr, "grep: %s: read error\n", disp);
                    *any_error = 1;
                }
                free(line.buf);
                fclose(fp);
            }
        } else if (S_ISDIR(st.st_mode)) {
            search_tree(realpath, disp, pattern, patlen,
                        use_prefix, any_match, any_error, depth + 1,
                        ignore_case);
        }

        free(realpath);
        free(disp);
    }

    for (int i = 0; i < count; i++) free(names[i]);
    free(names);
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_usage();
        return 2;
    }

    int prefix_mode = 0;
    int recursive = 0;
    int ignore_case = 0;
    int after_terminator = 0;
    const char *pattern = NULL;
    const char **files = malloc((size_t)argc * sizeof *files);
    if (!files) return 2;
    int file_count = 0;

    for (int i = 1; i < argc; i++) {
        if (after_terminator) {
            if (!pattern) {
                pattern = argv[i];
            } else {
                files[file_count++] = argv[i];
            }
        } else if (strcmp(argv[i], "--") == 0) {
            after_terminator = 1;
        } else if (strcmp(argv[i], "--with-filename") == 0) {
            prefix_mode = 1;
        } else if (strcmp(argv[i], "--no-filename") == 0) {
            prefix_mode = -1;
        } else if (strcmp(argv[i], "--recursive") == 0) {
            recursive = 1;
        } else if (strcmp(argv[i], "--ignore-case") == 0) {
            ignore_case = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            for (const char *p = argv[i] + 1; *p; p++) {
                if (*p == 'H') {
                    prefix_mode = 1;
                } else if (*p == 'h') {
                    prefix_mode = -1;
                } else if (*p == 'r') {
                    recursive = 1;
                } else if (*p == 'i') {
                    ignore_case = 1;
                } else {
                    free(files);
                    print_usage();
                    return 2;
                }
            }
        } else if (!pattern) {
            pattern = argv[i];
        } else {
            files[file_count++] = argv[i];
        }
    }

    if (!pattern) {
        free(files);
        print_usage();
        return 2;
    }

    size_t patlen = strlen(pattern);

    int use_prefix;
    if (prefix_mode > 0) {
        use_prefix = 1;
    } else if (prefix_mode < 0) {
        use_prefix = 0;
    } else if (file_count >= 2) {
        use_prefix = 1;
    } else if (recursive) {
        int any_dir = 0;
        for (int i = 0; i < file_count; i++) {
            struct stat st;
            if (stat(files[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                any_dir = 1;
                break;
            }
        }
        use_prefix = any_dir;
    } else {
        use_prefix = 0;
    }

    int any_match = 0;
    int any_error = 0;

    if (file_count == 0) {
        const char *prefix = use_prefix ? "(standard input)" : NULL;
        ByteBuf line = {0};
        int rc;
        while ((rc = read_line(stdin, &line)) == 0) {
            int matched = ignore_case
                ? fixed_match_ci(line.buf, line.len, (const unsigned char *)pattern, patlen)
                : fixed_match(line.buf, line.len, (const unsigned char *)pattern, patlen);
            if (matched) {
                if (write_line(line.buf, line.len, prefix) != 0) {
                    free(line.buf);
                    free(files);
                    return 2;
                }
                any_match = 1;
            }
        }
        if (rc == -2) {
            fprintf(stderr, "grep: error reading input\n");
            free(line.buf);
            free(files);
            return 2;
        }
        free(line.buf);
    } else {
        for (int i = 0; i < file_count; i++) {
            const char *filename = files[i];

            struct stat st;
            if (stat(filename, &st) != 0) {
                fprintf(stderr, "grep: %s: %s\n", filename, strerror(errno));
                any_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "grep: %s: Is a directory\n", filename);
                    any_error = 1;
                    continue;
                }
                char *display = strdup(filename);
                if (!display) { any_error = 1; continue; }
                size_t dlen = strlen(display);
                while (dlen > 1 && display[dlen - 1] == '/')
                    display[--dlen] = '\0';
                search_tree(filename, display,
                            (const unsigned char *)pattern, patlen,
                            use_prefix, &any_match, &any_error, 0,
                            ignore_case);
                free(display);
                continue;
            }

            FILE *fp = fopen(filename, "rb");
            if (!fp) {
                fprintf(stderr, "grep: %s: %s\n", filename, strerror(errno));
                any_error = 1;
                continue;
            }

            ByteBuf line = {0};
            int rc;
            const char *prefix = use_prefix ? filename : NULL;
            while ((rc = read_line(fp, &line)) == 0) {
                int matched = ignore_case
                    ? fixed_match_ci(line.buf, line.len, (const unsigned char *)pattern, patlen)
                    : fixed_match(line.buf, line.len, (const unsigned char *)pattern, patlen);
                if (matched) {
                    if (write_line(line.buf, line.len, prefix) != 0) {
                        free(line.buf);
                        fclose(fp);
                        free(files);
                        return 2;
                    }
                    any_match = 1;
                }
            }
            if (rc == -2) {
                fprintf(stderr, "grep: %s: read error\n", filename);
                free(line.buf);
                fclose(fp);
                any_error = 1;
                continue;
            }
            free(line.buf);
            fclose(fp);
        }
    }

    free(files);

    if (any_error) return 2;
    return any_match ? 0 : 1;
}
