#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <limits.h>
#include <dirent.h>

#define CHUNK_SIZE 4096

static char *read_line(FILE *fp, size_t *len_out) {
    size_t capacity = CHUNK_SIZE;
    size_t len = 0;
    char *buf = malloc(capacity);
    if (!buf) return NULL;

    int got_data = 0;
    while (1) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (got_data) break;
            free(buf);
            return NULL;
        }
        if (c == '\n') {
            break;
        }
        got_data = 1;
        if (len >= capacity - 1) {
            size_t new_cap = capacity * 2;
            if (new_cap <= capacity) {
                free(buf);
                return NULL;
            }
            char *new_buf = realloc(buf, new_cap);
            if (!new_buf) {
                free(buf);
                return NULL;
            }
            buf = new_buf;
            capacity = new_cap;
        }
        buf[len++] = (char)c;
    }

    buf[len] = '\0';
    *len_out = len;
    return buf;
}

static int matches(const char *line, size_t line_len, const char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    return memmem(line, line_len, pattern, pat_len) != NULL;
}

static int write_line_with_prefix(const char *filename, const char *line, size_t len) {
    if (fprintf(stdout, "%s:", filename) < 0) return -1;
    if (len > 0) {
        if (fwrite(line, 1, len, stdout) != len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int write_line(const char *line, size_t len) {
    if (len > 0) {
        if (fwrite(line, 1, len, stdout) != len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                       int prefix_filename) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return -1;
    }

    int matched_at_least_once = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && errno != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            fclose(fp);
            return -1;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len)) {
            matched_at_least_once = 1;
            int rc;
            if (prefix_filename) {
                rc = write_line_with_prefix(filename, line, line_len);
            } else {
                rc = write_line(line, line_len);
            }
            if (rc < 0) {
                fprintf(stderr, "write error: %s\n", strerror(errno));
                free(line);
                fclose(fp);
                return -1;
            }
        }
        free(line);
    }

    fclose(fp);
    return matched_at_least_once ? 0 : 1;
}

static int is_directory(const char *path) {
    struct stat st;
    if (stat(path, &st) != 0) return 0;
    return S_ISDIR(st.st_mode);
}

struct path_entry {
    char *name;
    size_t name_len;
};

static int compare_entries(const void *a, const void *b) {
    const struct path_entry *ea = (const struct path_entry *)a;
    const struct path_entry *eb = (const struct path_entry *)b;
    return memcmp(ea->name, eb->name, ea->name_len < eb->name_len ? ea->name_len : eb->name_len);
}

static int search_recursive(const char *dirpath, const char *pattern, size_t pat_len,
                            int prefix_filename, int force_filename);

static int process_file(const char *filepath, const char *pattern, size_t pat_len,
                        int prefix_filename) {
    FILE *fp = fopen(filepath, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filepath, strerror(errno));
        return -1;
    }

    int matched_at_least_once = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && errno != 0) {
            fprintf(stderr, "%s: %s\n", filepath, strerror(errno));
            fclose(fp);
            return -1;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len)) {
            matched_at_least_once = 1;
            int rc;
            if (prefix_filename) {
                rc = write_line_with_prefix(filepath, line, line_len);
            } else {
                rc = write_line(line, line_len);
            }
            if (rc < 0) {
                fprintf(stderr, "write error: %s\n", strerror(errno));
                free(line);
                fclose(fp);
                return -1;
            }
        }
        free(line);
    }

    fclose(fp);
    return matched_at_least_once ? 0 : 1;
}

static int process_directory(const char *dirpath, const char *pattern, size_t pat_len,
                             int prefix_filename, int force_filename) {
    DIR *dp = opendir(dirpath);
    if (!dp) {
        fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
        return -1;
    }

    struct path_entry *entries = NULL;
    size_t entry_count = 0;

    while (1) {
        struct dirent *entry = readdir(dp);
        if (!entry) break;

        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;

        entries = realloc(entries, (entry_count + 1) * sizeof(struct path_entry));
        if (!entries) {
            fprintf(stderr, "memory allocation failed\n");
            closedir(dp);
            return -1;
        }
        entries[entry_count].name = strdup(entry->d_name);
        entries[entry_count].name_len = strlen(entry->d_name);
        entry_count++;
    }

    closedir(dp);

    if (entry_count > 0) {
        qsort(entries, entry_count, sizeof(struct path_entry), compare_entries);
    }

    int result = 1;
    int has_error = 0;
    for (size_t i = 0; i < entry_count; i++) {
        char *fullpath = NULL;
        size_t fullpath_len = 0;

        if (strlen(dirpath) > 0 && dirpath[strlen(dirpath) - 1] == '/') {
            fullpath_len = strlen(dirpath) + entries[i].name_len + 1;
            fullpath = malloc(fullpath_len);
            snprintf(fullpath, fullpath_len, "%s%s", dirpath, entries[i].name);
        } else {
            fullpath_len = strlen(dirpath) + 1 + entries[i].name_len + 1;
            fullpath = malloc(fullpath_len);
            snprintf(fullpath, fullpath_len, "%s/%s", dirpath, entries[i].name);
        }

        struct stat st;
        if (lstat(fullpath, &st) != 0) {
            fprintf(stderr, "%s: %s\n", fullpath, strerror(errno));
            free(fullpath);
            has_error = 1;
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int rc = process_file(fullpath, pattern, pat_len, prefix_filename);
            if (rc < 0) {
                has_error = 1;
            } else if (rc == 0) {
                result = 0;
            }
        } else if (S_ISDIR(st.st_mode)) {
            int rc = process_directory(fullpath, pattern, pat_len, prefix_filename, force_filename);
            if (rc < 0) {
                has_error = 1;
            } else if (rc == 0) {
                result = 0;
            }
        }

        free(fullpath);
    }

    for (size_t i = 0; i < entry_count; i++) {
        free(entries[i].name);
    }
    free(entries);

    return has_error ? -1 : result;
}

static int search_recursive(const char *dirpath, const char *pattern, size_t pat_len,
                            int prefix_filename, int force_filename) {
    struct stat st;
    if (lstat(dirpath, &st) != 0) {
        fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
        return -1;
    }

    if (S_ISLNK(st.st_mode)) {
        return process_file(dirpath, pattern, pat_len, prefix_filename);
    }

    if (S_ISDIR(st.st_mode)) {
        return process_directory(dirpath, pattern, pat_len, prefix_filename, force_filename);
    }

    return process_file(dirpath, pattern, pat_len, prefix_filename);
}

int main(int argc, char *argv[]) {
    const char *pattern = NULL;
    const char **filenames = NULL;
    int file_count = 0;
    int force_filename = 0;
    int recursive = 0;

    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
                force_filename = 1;
                i++;
            } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                force_filename = -1;
                i++;
            } else if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
                recursive = 1;
                i++;
            } else if (argv[i][1] == 'H' && strlen(argv[i]) == 2) {
                force_filename = 1;
                i++;
            } else if (argv[i][1] == 'h' && strlen(argv[i]) == 2) {
                force_filename = -1;
                i++;
            } else if (argv[i][1] == 'r' && strlen(argv[i]) == 2) {
                recursive = 1;
                i++;
            } else if (strlen(argv[i]) > 2 && argv[i][0] == '-' && argv[i][1] != '-') {
                for (size_t k = 1; k < strlen(argv[i]); k++) {
                    if (argv[i][k] == 'H') {
                        force_filename = 1;
                    } else if (argv[i][k] == 'h') {
                        force_filename = -1;
                    } else if (argv[i][k] == 'r') {
                        recursive = 1;
                    } else {
                        fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
                        return 2;
                    }
                }
                i++;
            } else {
                fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
                return 2;
            }
        } else {
            break;
        }
    }

    if (i >= argc) {
        fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }

    pattern = argv[i];
    i++;

    for (int j = i; j < argc; j++) {
        filenames = realloc(filenames, (file_count + 1) * sizeof(char *));
        if (!filenames) {
            fprintf(stderr, "memory allocation failed\n");
            return 2;
        }
        filenames[file_count++] = argv[j];
    }

    size_t pat_len = strlen(pattern);

    int has_directory_operand = 0;
    for (int j = 0; j < file_count; j++) {
        if (is_directory(filenames[j])) {
            has_directory_operand = 1;
            break;
        }
    }

    int use_prefix = 0;
    if (force_filename == 1) {
        use_prefix = 1;
    } else if (force_filename == -1) {
        use_prefix = 0;
    } else if (file_count >= 2) {
        use_prefix = 1;
    } else if (recursive && has_directory_operand) {
        use_prefix = 1;
    }

    int exit_status = 0;
    int matched_at_least_once = 0;

    if (file_count == 0) {
        while (1) {
            size_t line_len;
            char *line = read_line(stdin, &line_len);
            if (!line) break;

            if (matches(line, line_len, pattern, pat_len)) {
                matched_at_least_once = 1;
                int rc;
                if (force_filename == 1) {
                    rc = write_line_with_prefix("(standard input)", line, line_len);
                } else {
                    rc = write_line(line, line_len);
                }
                if (rc < 0) {
                    fprintf(stderr, "write error: %s\n", strerror(errno));
                    free(line);
                    free(filenames);
                    return 2;
                }
            }
            free(line);
        }
    } else {
        for (int j = 0; j < file_count; j++) {
            const char *fname = filenames[j];

            if (recursive) {
                int result = search_recursive(fname, pattern, pat_len, use_prefix, force_filename);
                if (result < 0) {
                    exit_status = 2;
                } else if (result == 0) {
                    matched_at_least_once = 1;
                }
            } else {
                if (is_directory(fname)) {
                    fprintf(stderr, "%s: Is a directory\n", fname);
                    exit_status = 2;
                    continue;
                }

                int result = search_file(fname, pattern, pat_len, use_prefix);
                if (result < 0) {
                    exit_status = 2;
                } else if (result == 0) {
                    matched_at_least_once = 1;
                }
            }
        }
    }

    free(filenames);

    if (exit_status != 0) return 2;
    return matched_at_least_once ? 0 : 1;
}
