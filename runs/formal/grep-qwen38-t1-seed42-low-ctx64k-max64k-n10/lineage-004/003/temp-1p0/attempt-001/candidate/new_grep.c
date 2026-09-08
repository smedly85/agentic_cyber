#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <dirent.h>

static void *xrealloc(void *old, size_t size) {
    void *p = realloc(old, size);
    if (!p) {
        fprintf(stderr, "new_grep: out of memory\n");
        exit(2);
    }
    return p;
}

static int line_matches(const unsigned char *line, size_t len,
                        const unsigned char *pat, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (len < pat_len) return 0;
    for (size_t i = 0; i <= len - pat_len; i++) {
        if (memcmp(line + i, pat, pat_len) == 0)
            return 1;
    }
    return 0;
}

/* Returns 0 on success, -1 on write error. */
static int write_selected(const char *filename,
                          const unsigned char *line, size_t line_len) {
    if (filename) {
        size_t flen = strlen(filename);
        if (write(STDOUT_FILENO, filename, flen) != (ssize_t)flen) return -1;
        if (write(STDOUT_FILENO, ":", 1) != 1) return -1;
    }
    if (line_len > 0) {
        if (write(STDOUT_FILENO, line, line_len) != (ssize_t)line_len) return -1;
    }
    if (write(STDOUT_FILENO, "\n", 1) != 1) return -1;
    return 0;
}

/* Returns 0=ok, -1=read error (operand), -2=write error (fatal). */
static int process_stream(int fd, const unsigned char *pat, size_t pat_len,
                          const char *filename, int *found) {
    unsigned char *line = NULL;
    size_t line_len = 0, cap = 0;
    unsigned char buf[8192];

    for (;;) {
        ssize_t n;
        do {
            n = read(fd, buf, sizeof(buf));
        } while (n < 0 && errno == EINTR);

        if (n < 0) {
            free(line);
            return -1;
        }
        if (n == 0) {
            if (line_len > 0) {
                if (line_matches(line, line_len, pat, pat_len)) {
                    if (write_selected(filename, line, line_len) < 0) {
                        free(line);
                        return -2;
                    }
                    *found = 1;
                }
            }
            free(line);
            return 0;
        }

        for (ssize_t i = 0; i < n; i++) {
            if (buf[i] == '\n') {
                if (line_matches(line, line_len, pat, pat_len)) {
                    if (write_selected(filename, line, line_len) < 0) {
                        free(line);
                        return -2;
                    }
                    *found = 1;
                }
                line_len = 0;
            } else {
                if (line_len + 1 > cap) {
                    size_t newcap = cap ? cap * 2 : 256;
                    line = xrealloc(line, newcap);
                    cap = newcap;
                }
                line[line_len++] = buf[i];
            }
        }
    }
}

/* Compare function for qsort to sort strings in byte order */
static int cmp_str(const void *a, const void *b) {
    return strcmp(*(const char **)a, *(const char **)b);
}

/* Maximum recursion depth */
#define MAX_DEPTH 1024

/* Process a directory recursively */
static int traverse_dir(const char *dir_path, int depth,
                        const unsigned char *pat, size_t pat_len,
                        const char *prefix_base, int use_prefix, int *found, int *had_error) {
    if (depth >= MAX_DEPTH) {
        fprintf(stderr, "new_grep: %s: directory too deep\n", dir_path);
        return -1;
    }
    
    DIR *d = opendir(dir_path);
    if (!d) {
        fprintf(stderr, "new_grep: %s: %s\n", dir_path, strerror(errno));
        *had_error = 1;
        return -1;
    }
    
    /* Read all entries */
    char **names = NULL;
    int n = 0, cap = 0;
    struct dirent *ent;
    
    while ((ent = readdir(d)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0) continue;
        if (n >= cap) {
            cap = cap ? cap * 2 : 16;
            names = xrealloc(names, cap * sizeof(*names));
        }
        names[n++] = strdup(ent->d_name);
    }
    closedir(d);
    
    /* Sort entries in byte order */
    qsort(names, n, sizeof(*names), cmp_str);
    
    /* Process each entry */
    for (int i = 0; i < n; i++) {
        char *full = malloc(strlen(dir_path) + 1 + strlen(names[i]) + 1);
        if (!full) {
            fprintf(stderr, "new_grep: out of memory\n");
            exit(2);
        }
        size_t dl = strlen(dir_path);
        if (dl > 1 && dir_path[dl - 1] == '/')
            sprintf(full, "%s%s", dir_path, names[i]);
        else
            sprintf(full, "%s/%s", dir_path, names[i]);
        
        struct stat st;
        if (lstat(full, &st) != 0) {
            fprintf(stderr, "new_grep: %s: %s\n", full, strerror(errno));
            free(full);
            free(names[i]);
            *had_error = 1;
            continue;
        }
        
        if (S_ISLNK(st.st_mode)) {
            /* Skip symlinks during traversal */
        } else if (S_ISREG(st.st_mode)) {
            int fd = open(full, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "new_grep: %s: %s\n", full, strerror(errno));
                free(full);
                free(names[i]);
                *had_error = 1;
                continue;
            }
            
            const char *prefix = use_prefix ? full : NULL;
            int local_found = 0;
            int rc = process_stream(fd, pat, pat_len, prefix, &local_found);
            close(fd);
            
            if (rc == -1) {
                fprintf(stderr, "new_grep: %s: read error\n", full);
                *had_error = 1;
            } else if (rc == -2) {
                *had_error = 1;
                free(full);
                free(names[i]);
                return -2;
            }
            if (local_found) *found = 1;
        } else if (S_ISDIR(st.st_mode)) {
            /* Recurse into subdirectory */
            int rc = traverse_dir(full, depth + 1, pat, pat_len, prefix_base, use_prefix, found, had_error);
            if (rc == -2) {
                free(full);
                free(names[i]);
                return -2;
            }
        }
        
        free(full);
        free(names[i]);
    }
    
    free(names);
    return 0;
}

int main(int argc, char *argv[]) {
    const char **operands = NULL;
    int nop = 0;
    int seen_terminator = 0;
    int prefix_mode = -1;  /* -1=unset, 0=no-filename, 1=with-filename */
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!seen_terminator) {
            if (strcmp(arg, "--") == 0) {
                seen_terminator = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (strcmp(arg, "--with-filename") == 0) {
                    prefix_mode = 1;
                    continue;
                }
                if (strcmp(arg, "--no-filename") == 0) {
                    prefix_mode = 0;
                    continue;
                }
                if (strcmp(arg, "--recursive") == 0) {
                    recursive = 1;
                    continue;
                }
                if (arg[1] != '-') {
                    int ok = 1;
                    for (size_t j = 1; arg[j] != '\0'; j++) {
                        if (arg[j] == 'H') prefix_mode = 1;
                        else if (arg[j] == 'h') prefix_mode = 0;
                        else if (arg[j] == 'r') recursive = 1;
                        else { ok = 0; break; }
                    }
                    if (ok) continue;
                }
                fprintf(stderr, "new_grep: unknown option: %s\n", arg);
                fprintf(stderr, "usage: new_grep [-r] [-H|-h] [--] PATTERN [FILE...]\n");
                return 2;
            }
        }
        operands = xrealloc(operands, (size_t)(nop + 1) * sizeof(*operands));
        operands[nop++] = arg;
    }

    if (nop == 0) {
        fprintf(stderr, "new_grep: missing PATTERN\n");
        fprintf(stderr, "usage: new_grep [-r] [-H|-h] [--] PATTERN [FILE...]\n");
        return 2;
    }

    const char *pattern = operands[0];
    size_t pat_len = strlen(pattern);
    const char **files = operands + 1;
    int nfiles = nop - 1;

    int found = 0;
    int had_error = 0;

    /* Determine prefix mode */
    int use_prefix;
    if (prefix_mode == 1) use_prefix = 1;
    else if (prefix_mode == 0) use_prefix = 0;
    else if (nfiles >= 2) use_prefix = 1;
    else if (recursive) {
        /* Check if any operand is a directory */
        use_prefix = 0;
        for (int i = 0; i < nfiles; i++) {
            struct stat st;
            if (stat(files[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                use_prefix = 1;
                break;
            }
        }
    }
    else use_prefix = 0;

    if (nfiles == 0) {
        const char *name = (use_prefix) ? "(standard input)" : NULL;
        int rc = process_stream(STDIN_FILENO,
                                (const unsigned char *)pattern, pat_len,
                                name, &found);
        if (rc != 0) had_error = 1;
    } else {
        for (int i = 0; i < nfiles; i++) {
            const char *path = files[i];
            struct stat st;
            if (stat(path, &st) != 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                had_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                if (recursive) {
                    int rc = traverse_dir(path, 0,
                                          (const unsigned char *)pattern, pat_len,
                                          path, use_prefix, &found, &had_error);
                    if (rc == -2) had_error = 1;
                } else {
                    fprintf(stderr, "new_grep: %s: is a directory\n", path);
                    had_error = 1;
                }
                continue;
            }
            int fd = open(path, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                had_error = 1;
                continue;
            }
            int rc = process_stream(fd,
                                    (const unsigned char *)pattern, pat_len,
                                    use_prefix ? path : NULL, &found);
            close(fd);
            if (rc == -1) {
                fprintf(stderr, "new_grep: %s: read error\n", path);
                had_error = 1;
            } else if (rc == -2) {
                had_error = 1;
                break;
            }
        }
    }

    free(operands);

    if (had_error) return 2;
    return found ? 0 : 1;
}
