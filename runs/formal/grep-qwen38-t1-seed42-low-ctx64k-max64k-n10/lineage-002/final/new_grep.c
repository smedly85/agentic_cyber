#define _POSIX_C_SOURCE 200809L
#include <dirent.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

typedef struct {
    char *path;
    size_t path_len;
    size_t path_cap;
} PathBuf;

static void pathbuf_init(PathBuf *pb) {
    pb->path = NULL;
    pb->path_len = 0;
    pb->path_cap = 0;
}

static bool pathbuf_append(PathBuf *pb, const char *s, size_t len) {
    size_t new_len = pb->path_len + len;
    if (new_len + 1 > pb->path_cap) {
        size_t new_cap = pb->path_cap ? pb->path_cap * 2 : 256;
        while (new_len + 1 > new_cap) new_cap *= 2;
        char *new_path = realloc(pb->path, new_cap);
        if (!new_path) return false;
        pb->path = new_path;
        pb->path_cap = new_cap;
    }
    memcpy(pb->path + pb->path_len, s, len);
    pb->path_len = new_len;
    pb->path[pb->path_len] = '\0';
    return true;
}

static bool pathbuf_append_char(PathBuf *pb, char c) {
    return pathbuf_append(pb, &c, 1);
}

static bool pathbuf_append_str(PathBuf *pb, const char *s) {
    return pathbuf_append(pb, s, strlen(s));
}

static void pathbuf_truncate(PathBuf *pb, size_t new_len) {
    pb->path_len = new_len;
    pb->path[new_len] = '\0';
}

static void pathbuf_free(PathBuf *pb) {
    free(pb->path);
    pb->path = NULL;
}

static void usage_exit(void) {
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
    exit(2);
}

static void *xrealloc(void *old, size_t size) {
    if (size < 1) size = 1;
    void *p = realloc(old, size);
    if (!p) {
        fprintf(stderr, "new_grep: out of memory\n");
        exit(2);
    }
    return p;
}

static int compare_names(const void *a, const void *b) {
    return strcmp(*(const char * const *)a, *(const char * const *)b);
}

static unsigned char fold_byte(unsigned char c) {
    if (c >= 0x41 && c <= 0x5A) return c + 0x20;
    return c;
}

static bool line_matches(const unsigned char *line, size_t len,
                         const unsigned char *pat, size_t plen, bool ci) {
    if (plen == 0) return true;
    if (plen > len) return false;
    for (size_t i = 0; i <= len - plen; i++) {
        bool match = true;
        for (size_t j = 0; j < plen; j++) {
            unsigned char lb = ci ? fold_byte(line[i + j]) : line[i + j];
            if (lb != pat[j]) { match = false; break; }
        }
        if (match) return true;
    }
    return false;
}

static bool write_selected(const char *prefix, bool has_prefix,
                           const unsigned char *line, size_t len) {
    if (has_prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, stdout) != plen) return false;
        if (fputc(':', stdout) == EOF) return false;
    }
    if (len > 0 && fwrite(line, 1, len, stdout) != len) return false;
    return fputc('\n', stdout) != EOF;
}

static int search_stream(FILE *f, const unsigned char *pat, size_t plen,
                         const char *prefix, bool has_prefix, bool ci,
                         bool *found) {
    unsigned char *buf = NULL;
    size_t len = 0, cap = 0;
    int c;

    while ((c = getc(f)) != EOF) {
        if (c == '\n') {
            if (line_matches(buf, len, pat, plen, ci)) {
                if (!write_selected(prefix, has_prefix, buf, len)) {
                    free(buf);
                    return -1;
                }
                *found = true;
            }
            len = 0;
        } else {
            if (len + 1 > cap) {
                cap = cap ? cap * 2 : 256;
                buf = xrealloc(buf, cap);
            }
            buf[len++] = (unsigned char)c;
        }
    }

    if (len > 0) {
        if (line_matches(buf, len, pat, plen, ci)) {
            if (!write_selected(prefix, has_prefix, buf, len)) {
                free(buf);
                return -1;
            }
            *found = true;
        }
    }

    free(buf);
    return 0;
}

static int search_file(const char *path, const unsigned char *pat, size_t plen,
                       const char *prefix, bool has_prefix, bool ci, bool *found) {
    struct stat st;
    if (stat(path, &st) != 0) {
        fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
        return -1;
    }
    if (S_ISDIR(st.st_mode)) {
        fprintf(stderr, "new_grep: %s: is a directory\n", path);
        return -1;
    }
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
        return -1;
    }
    int rc = search_stream(f, pat, plen, prefix, has_prefix, ci, found);
    if (fclose(f) != 0) rc = -1;
    return rc;
}

static int search_dir_recursive(const char *dir_path, const unsigned char *pat, size_t plen,
                                bool has_prefix, bool ci, bool *found, bool *error) {
    DIR *dir = opendir(dir_path);
    if (!dir) {
        fprintf(stderr, "new_grep: %s: %s\n", dir_path, strerror(errno));
        *error = true;
        return -1;
    }

    char **names = NULL;
    size_t count = 0, cap = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (count + 1 > cap) {
            cap = cap ? cap * 2 : 16;
            names = xrealloc(names, cap * sizeof(*names));
        }
        size_t len = strlen(entry->d_name);
        names[count] = xrealloc(NULL, len + 1);
        memcpy(names[count], entry->d_name, len + 1);
        count++;
    }
    closedir(dir);

    qsort(names, count, sizeof(*names), compare_names);

    PathBuf pb;
    pathbuf_init(&pb);
    if (!pathbuf_append_str(&pb, dir_path)) {
        for (size_t i = 0; i < count; i++) free(names[i]);
        free(names);
        *error = true;
        return -1;
    }
    if (pb.path_len > 0 && pb.path[pb.path_len - 1] != '/') {
        if (!pathbuf_append_char(&pb, '/')) {
            for (size_t i = 0; i < count; i++) free(names[i]);
            free(names);
            *error = true;
            return -1;
        }
    }
    size_t dir_len = pb.path_len;

    for (size_t i = 0; i < count; i++) {
        size_t name_len = strlen(names[i]);
        if (!pathbuf_append(&pb, names[i], name_len)) {
            *error = true;
            pathbuf_truncate(&pb, dir_len);
            continue;
        }

        const char *full_path = pb.path;
        struct stat st;
        if (lstat(full_path, &st) == 0) {
            if (S_ISLNK(st.st_mode)) {
                /* skip symlinks */
            } else if (S_ISDIR(st.st_mode)) {
                if (search_dir_recursive(full_path, pat, plen, has_prefix, ci, found, error) != 0)
                    *error = true;
            } else if (S_ISREG(st.st_mode)) {
                const char *prefix = has_prefix ? full_path : NULL;
                if (search_file(full_path, pat, plen, prefix, has_prefix, ci, found) != 0)
                    *error = true;
            }
        }
        pathbuf_truncate(&pb, dir_len);
    }

    for (size_t i = 0; i < count; i++) free(names[i]);
    free(names);
    pathbuf_free(&pb);
    return *error ? -1 : 0;
}

int main(int argc, char **argv) {
    if (argc < 2)
        usage_exit();

    bool after_ddash = false;
    int prefix_mode = 0;
    bool recursive = false;
    bool ignore_case = false;
    int pat_idx = -1, file_start = -1;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = true;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (argv[i][1] == '-') {
                    if (strcmp(argv[i], "--with-filename") == 0) {
                        prefix_mode = 1;
                        continue;
                    }
                    if (strcmp(argv[i], "--no-filename") == 0) {
                        prefix_mode = -1;
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
                    fprintf(stderr, "new_grep: unknown option: %s\n", argv[i]);
                    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
                    exit(2);
                }
                for (const char *p = argv[i] + 1; *p; p++) {
                    if (*p == 'H') {
                        prefix_mode = 1;
                    } else if (*p == 'h') {
                        prefix_mode = -1;
                    } else if (*p == 'r') {
                        recursive = true;
                    } else if (*p == 'i') {
                        ignore_case = true;
                    } else {
                        fprintf(stderr, "new_grep: unknown option: -%c\n", *p);
                        fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
                        exit(2);
                    }
                }
                continue;
            }
        }
        if (pat_idx == -1)
            pat_idx = i;
        else if (file_start == -1)
            file_start = i;
    }

    if (pat_idx == -1)
        usage_exit();

    const unsigned char *pat = (const unsigned char *)argv[pat_idx];
    size_t plen = strlen(argv[pat_idx]);

    const unsigned char *match_pat = pat;
    unsigned char *folded_pat = NULL;
    if (ignore_case) {
        folded_pat = xrealloc(NULL, plen + 1);
        for (size_t j = 0; j < plen; j++)
            folded_pat[j] = fold_byte(pat[j]);
        folded_pat[plen] = '\0';
        match_pat = folded_pat;
    }

    int nfiles = (file_start == -1) ? 0 : argc - file_start;

    bool has_prefix;
    if (prefix_mode == 1)
        has_prefix = true;
    else if (prefix_mode == -1)
        has_prefix = false;
    else if (nfiles >= 2)
        has_prefix = true;
    else if (recursive && nfiles >= 1) {
        has_prefix = false;
        for (int i = file_start; i < argc; i++) {
            struct stat st;
            if (stat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                has_prefix = true;
                break;
            }
        }
    } else
        has_prefix = false;

    bool found = false;
    bool error = false;

    if (nfiles == 0) {
        const char *prefix = has_prefix ? "(standard input)" : NULL;
        if (search_stream(stdin, match_pat, plen, prefix, has_prefix, ignore_case, &found) != 0)
            error = true;
    } else {
        for (int i = file_start; i < argc; i++) {
            struct stat st;
            if (stat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                if (recursive) {
                    if (search_dir_recursive(argv[i], match_pat, plen, has_prefix, ignore_case, &found, &error) != 0)
                        error = true;
                } else {
                    fprintf(stderr, "new_grep: %s: is a directory\n", argv[i]);
                    error = true;
                }
            } else {
                if (search_file(argv[i], match_pat, plen,
                                has_prefix ? argv[i] : NULL, has_prefix,
                                ignore_case, &found) != 0)
                    error = true;
            }
        }
    }

    free(folded_pat);
    if (error) return 2;
    return found ? 0 : 1;
}
