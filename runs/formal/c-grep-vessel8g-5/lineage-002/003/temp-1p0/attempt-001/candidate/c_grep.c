#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>

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

/* Join base and rel into out (NUL-terminated). Avoids doubling a separator
   if base already ends with '/'. Returns 0 on success, -1 if the result
   would not fit in out_cap bytes. */
static int join_path_safe(char *out, size_t out_cap,
                          const char *base, const char *rel)
{
    size_t bl = strlen(base), rl = strlen(rel);
    int slash = (bl > 0 && base[bl - 1] != '/') ? 1 : 0;
    if (bl + (size_t)slash + rl + 1 > out_cap)
        return -1;
    memcpy(out, base, bl);
    if (slash)
        out[bl++] = '/';
    memcpy(out + bl, rel, rl + 1);
    return 0;
}

static int dirent_name_cmp(const void *a, const void *b)
{
    const struct dirent *da = (const struct dirent *)a;
    const struct dirent *db = (const struct dirent *)b;
    return strcmp(da->d_name, db->d_name);
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

static void traverse_dir(const char *path, const char *display,
                         const unsigned char *pattern, size_t pattern_len,
                         int use_prefix, int *any_match, int *any_error)
{
    DIR *d = opendir(path);
    if (!d) {
        fprintf(stderr, "c_grep: %s: cannot open directory\n", path);
        *any_error = 1;
        return;
    }

    struct dirent *entries = NULL;
    size_t nent = 0, cap = 0;
    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (nent >= cap) {
            size_t nc = cap ? cap * 2 : 16;
            struct dirent *ne = realloc(entries, nc * sizeof(struct dirent));
            if (!ne) {
                free(entries);
                closedir(d);
                *any_error = 1;
                return;
            }
            entries = ne;
            cap = nc;
        }
        entries[nent++] = *ent;
    }

    qsort(entries, nent, sizeof(*entries), dirent_name_cmp);

    for (size_t i = 0; i < nent; i++) {
        if (strcmp(entries[i].d_name, ".") == 0 ||
            strcmp(entries[i].d_name, "..") == 0)
            continue;

        char full_path[4096];
        if (join_path_safe(full_path, sizeof(full_path), path, entries[i].d_name) != 0) {
            fprintf(stderr, "c_grep: %s/%s: path too long\n", path, entries[i].d_name);
            *any_error = 1;
            continue;
        }

        char disp_path[4096];
        if (join_path_safe(disp_path, sizeof(disp_path), display, entries[i].d_name) != 0) {
            fprintf(stderr, "c_grep: %s/%s: path too long\n", display, entries[i].d_name);
            *any_error = 1;
            continue;
        }

        struct stat st;
        if (lstat(full_path, &st) != 0) {
            fprintf(stderr, "c_grep: %s: cannot stat\n", full_path);
            *any_error = 1;
            continue;
        }

        if (S_ISLNK(st.st_mode))
            continue;

        if (S_ISREG(st.st_mode)) {
            FILE *fp = fopen(full_path, "rb");
            if (!fp) {
                fprintf(stderr, "c_grep: %s: cannot open\n", full_path);
                *any_error = 1;
                continue;
            }
            unsigned char *pfx = NULL;
            size_t pfx_len = 0;
            if (use_prefix) {
                pfx_len = strlen(disp_path) + 1;
                pfx = malloc(pfx_len);
                if (!pfx) {
                    fclose(fp);
                    *any_error = 1;
                    continue;
                }
                memcpy(pfx, disp_path, strlen(disp_path));
                pfx[strlen(disp_path)] = ':';
            }
            int rc = search_stream(fp, pattern, pattern_len, pfx, pfx_len);
            free(pfx);
            fclose(fp);
            if (rc == 0)
                *any_match = 1;
            else if (rc < 0)
                *any_error = 1;
        } else if (S_ISDIR(st.st_mode)) {
            traverse_dir(full_path, disp_path, pattern, pattern_len,
                         use_prefix, any_match, any_error);
        }
        /* else: skip FIFOs, sockets, devices, etc. */
    }

    free(entries);
    closedir(d);
}

int main(int argc, char *argv[])
{
    const char *pattern = NULL;
    const char **files = NULL;
    size_t nfiles = 0, files_cap = 0;
    int options_done = 0;
    int filename_mode = 0; /* 0=default, 1=force(-H), -1=suppress(-h) */
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!options_done) {
            if (strcmp(arg, "--") == 0) {
                options_done = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (arg[1] == '-') {
                    /* Long option */
                    if (strcmp(arg, "--with-filename") == 0) {
                        filename_mode = 1;
                        continue;
                    }
                    if (strcmp(arg, "--no-filename") == 0) {
                        filename_mode = -1;
                        continue;
                    }
                    if (strcmp(arg, "--recursive") == 0) {
                        recursive = 1;
                        continue;
                    }
                    fprintf(stderr, "c_grep: unsupported option '%s'\n", arg);
                    fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
                    free(files);
                    return 2;
                }
                /* Short option cluster: every character must be 'H' or 'h' */
                {
                    int bad = 0;
                    for (size_t j = 1; arg[j] != '\0'; j++) {
                        if (arg[j] == 'H')
                            filename_mode = 1;
                        else if (arg[j] == 'h')
                            filename_mode = -1;
                        else if (arg[j] == 'r')
                            recursive = 1;
                        else {
                            bad = 1;
                            break;
                        }
                    }
                    if (bad) {
                        fprintf(stderr, "c_grep: unsupported option '%s'\n", arg);
                        fprintf(stderr, "usage: c_grep PATTERN [FILE...]\n");
                        free(files);
                        return 2;
                    }
                }
                continue;
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
        unsigned char *pfx = NULL;
        size_t pfx_len = 0;
        if (filename_mode == 1) {
            const char *label = "(standard input)";
            pfx_len = strlen(label) + 1;
            pfx = malloc(pfx_len);
            if (!pfx) {
                fprintf(stderr, "c_grep: out of memory\n");
                return 2;
            }
            memcpy(pfx, label, strlen(label));
            pfx[strlen(label)] = ':';
        }
        int rc = search_stream(stdin, (const unsigned char *)pattern, plen,
                               pfx, pfx_len);
        free(pfx);
        if (rc == 0)
            any_match = 1;
        else if (rc < 0)
            any_error = 1;
    } else {
        int any_dir = 0;
        for (size_t i = 0; i < nfiles; i++) {
            struct stat st;
            if (stat(files[i], &st) == 0 && S_ISDIR(st.st_mode) && recursive)
                any_dir = 1;
        }

        int use_prefix;
        if (filename_mode == 1)
            use_prefix = 1;
        else if (filename_mode == -1)
            use_prefix = 0;
        else
            use_prefix = (nfiles >= 2) || any_dir;

        for (size_t i = 0; i < nfiles; i++) {
            const char *name = files[i];
            struct stat st;
            if (stat(name, &st) != 0) {
                fprintf(stderr, "c_grep: %s: cannot access\n", name);
                any_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "c_grep: %s: is a directory\n", name);
                    any_error = 1;
                    continue;
                }
                traverse_dir(name, name, (const unsigned char *)pattern, plen,
                             use_prefix, &any_match, &any_error);
                continue;
            }
            if (!S_ISREG(st.st_mode)) {
                fprintf(stderr, "c_grep: %s: not a regular file\n", name);
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
