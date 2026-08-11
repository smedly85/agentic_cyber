#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>

#define CHUNK_SIZE 4096

static char *read_line(FILE *fp, size_t *len_out) {
    size_t capacity = CHUNK_SIZE;
    size_t len = 0;
    char *buf = malloc(capacity);
    if (!buf) return NULL;

    while (1) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (ferror(fp)) {
                free(buf);
                return NULL;
            }
            if (len == 0) {
                free(buf);
                return NULL;
            }
            break;
        }
        if (c == '\n') {
            break;
        }
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

static int matches_ignore_case(const char *line, size_t line_len, const char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    
    for (size_t i = 0; i <= line_len - pat_len; i++) {
        int found = 1;
        for (size_t j = 0; j < pat_len; j++) {
            unsigned char c_line = (unsigned char)line[i + j];
            unsigned char c_pat = (unsigned char)pattern[j];
            
            if (c_line >= 0x41 && c_line <= 0x5A) {
                c_line = c_line | 0x20;
            }
            if (c_pat >= 0x41 && c_pat <= 0x5A) {
                c_pat = c_pat | 0x20;
            }
            
            if (c_line != c_pat) {
                found = 0;
                break;
            }
        }
        if (found) return 1;
    }
    return 0;
}



static int search_file(const char *filename, const char *pattern, size_t pat_len, int ignore_case, int prefix_filename);

typedef struct {
    char **entries;
    int count;
    int capacity;
} EntryList;

static void add_entry(EntryList *list, const char *name) {
    if (list->count >= list->capacity) {
        int new_cap = list->capacity == 0 ? 16 : list->capacity * 2;
        char **new_entries = realloc(list->entries, new_cap * sizeof(char *));
        if (!new_entries) return;
        list->entries = new_entries;
        list->capacity = new_cap;
    }
    list->entries[list->count++] = strdup(name);
}

static int cmp_entries(const void *a, const void *b) {
    const char *ea = *(const char **)a;
    const char *eb = *(const char **)b;
    return strcmp(ea, eb);
}

static int search_directory(const char *dirname, const char *operand, const char *pattern, size_t pat_len, int ignore_case, int prefix_filename);

static int search_file(const char *filename, const char *pattern, size_t pat_len, int ignore_case, int prefix_filename) {
    struct stat st;
    if (lstat(filename, &st) != 0) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    if (S_ISLNK(st.st_mode)) {
        struct stat st2;
        if (stat(filename, &st2) != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            return 2;
        }
        if (S_ISDIR(st2.st_mode)) {
            fprintf(stderr, "%s: Is a directory\n", filename);
            return 2;
        }
    }

    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    if (S_ISDIR(st.st_mode)) {
        fclose(fp);
        fprintf(stderr, "%s: Is a directory\n", filename);
        return 2;
    }

    int matched = 0;
    int error_occurred = 0;
    size_t len;
    char *line;

    while ((line = read_line(fp, &len)) != NULL) {
        if (ignore_case ? matches_ignore_case(line, len, pattern, pat_len) : matches(line, len, pattern, pat_len)) {
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    error_occurred = 1;
                    free(line);
                    break;
                }
            }
            if (len > 0) {
                if (fwrite(line, 1, len, stdout) != len) {
                    error_occurred = 1;
                    free(line);
                    break;
                }
            }
            if (putc('\n', stdout) == EOF) {
                error_occurred = 1;
                free(line);
                break;
            }
            matched = 1;
        }
        free(line);
    }

    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        error_occurred = 1;
    }

    fclose(fp);
    return error_occurred ? 2 : (matched ? 0 : 1);
}

static int search_directory(const char *dirname, const char *operand, const char *pattern, size_t pat_len, int ignore_case, int prefix_filename) {
    DIR *dir = opendir(dirname);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirname, strerror(errno));
        return 2;
    }

    EntryList entries = {NULL, 0, 0};

    struct dirent *de;
    while ((de = readdir(dir)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) continue;
        add_entry(&entries, de->d_name);
    }
    closedir(dir);

    qsort(entries.entries, entries.count, sizeof(char *), cmp_entries);

    size_t dir_len = strlen(dirname);
    int exit_status = 1;

    for (int i = 0; i < entries.count; i++) {
        const char *name = entries.entries[i];
        size_t name_len = strlen(name);

        int trailing_slash = (dir_len > 0 && dirname[dir_len - 1] == '/');
        size_t path_len = dir_len + (!trailing_slash ? 1 : 0) + name_len;
        char *path = malloc(path_len + 1);
        if (!path) {
            exit_status = 2;
            continue;
        }
        memcpy(path, dirname, dir_len);
        if (!trailing_slash) {
            path[dir_len] = '/';
            memcpy(path + dir_len + 1, name, name_len + 1);
        } else {
            memcpy(path + dir_len, name, name_len + 1);
        }

        struct stat st;
        if (lstat(path, &st) != 0) {
            fprintf(stderr, "%s: %s\n", path, strerror(errno));
            free(path);
            exit_status = 2;
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int status = search_file(path, pattern, pat_len, ignore_case, prefix_filename);
            if (status == 2) exit_status = 2;
            else if (status == 0 && exit_status != 2) exit_status = 0;
        } else if (S_ISDIR(st.st_mode)) {
            int status = search_directory(path, operand, pattern, pat_len, ignore_case, prefix_filename);
            if (status == 2) exit_status = 2;
            else if (status == 0 && exit_status != 2) exit_status = 0;
        }

        free(path);
    }

    for (int i = 0; i < entries.count; i++) {
        free(entries.entries[i]);
    }
    free(entries.entries);

    return exit_status;
}

static int search_file_recursive(const char *operand, const char *pattern, size_t pat_len, int ignore_case, int prefix_filename) {
    struct stat st;
    if (lstat(operand, &st) != 0) {
        fprintf(stderr, "%s: %s\n", operand, strerror(errno));
        return 2;
    }

    if (S_ISREG(st.st_mode)) {
        return search_file(operand, pattern, pat_len, ignore_case, prefix_filename);
    } else if (S_ISLNK(st.st_mode)) {
        if (stat(operand, &st) != 0) {
            fprintf(stderr, "%s: %s\n", operand, strerror(errno));
            return 2;
        }
        if (S_ISREG(st.st_mode)) {
            return search_file(operand, pattern, pat_len, ignore_case, prefix_filename);
        } else if (S_ISDIR(st.st_mode)) {
            return search_directory(operand, operand, pattern, pat_len, ignore_case, prefix_filename);
        } else {
            fprintf(stderr, "%s: %s\n", operand, strerror(EINVAL));
            return 2;
        }
    } else if (S_ISDIR(st.st_mode)) {
        return search_directory(operand, operand, pattern, pat_len, ignore_case, prefix_filename);
    } else {
        fprintf(stderr, "%s: %s\n", operand, strerror(EINVAL));
        return 2;
    }
}

static void usage(void) {
    fprintf(stderr, "Usage: new_grep [-H|-h] [-r] [-i] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int i = 1;
    int filename_prefix = -1;
    int recursive = 0;
    int ignore_case = 0;

    while (i < argc && argv[i][0] == '-' && strcmp(argv[i], "--") != 0) {
        if (strcmp(argv[i], "-") == 0) {
            break;
        }
        char *arg = argv[i];
        if (strcmp(arg, "-r") == 0 || strcmp(arg, "--recursive") == 0) {
            recursive = 1;
            i++;
            continue;
        }
        if (strcmp(arg, "--with-filename") == 0) {
            filename_prefix = 1;
            i++;
            continue;
        }
        if (strcmp(arg, "--no-filename") == 0) {
            filename_prefix = 0;
            i++;
            continue;
        }
        if (strcmp(arg, "-i") == 0 || strcmp(arg, "--ignore-case") == 0) {
            ignore_case = 1;
            i++;
            continue;
        }
        for (int j = 1; arg[j]; j++) {
            if (arg[j] == 'H') {
                filename_prefix = 1;
            } else if (arg[j] == 'h') {
                filename_prefix = 0;
            } else if (arg[j] == 'r') {
                recursive = 1;
            } else if (arg[j] == 'i') {
                ignore_case = 1;
            } else {
                fprintf(stderr, "unknown option: %s\n", argv[i]);
                return 2;
            }
        }
        i++;
        continue;
    }

    while (i < argc && argv[i][0] == '-' && strcmp(argv[i], "--") != 0) {
        if (strcmp(argv[i], "-") == 0) {
            break;
        }
        char *arg = argv[i];
        if (strcmp(arg, "-r") == 0 || strcmp(arg, "--recursive") == 0) {
            recursive = 1;
            i++;
            continue;
        }
        if (strcmp(arg, "--with-filename") == 0) {
            filename_prefix = 1;
            i++;
            continue;
        }
        if (strcmp(arg, "--no-filename") == 0) {
            filename_prefix = 0;
            i++;
            continue;
        }
        if (strcmp(arg, "-i") == 0 || strcmp(arg, "--ignore-case") == 0) {
            ignore_case = 1;
            i++;
            continue;
        }
        fprintf(stderr, "unknown option: %s\n", argv[i]);
        return 2;
    }

    if (i < argc && strcmp(argv[i], "--") == 0) {
        i++;
    }

    const char *pattern = argv[i++];
    size_t pat_len = strlen(pattern);

    if (ignore_case) {
        char *folded_pattern = malloc(pat_len + 1);
        if (!folded_pattern) return 2;
        for (size_t k = 0; k < pat_len; k++) {
            unsigned char c = (unsigned char)pattern[k];
            if (c >= 0x41 && c <= 0x5A) {
                folded_pattern[k] = c | 0x20;
            } else {
                folded_pattern[k] = pattern[k];
            }
        }
        pattern = folded_pattern;
    }

    int file_count = argc - i;

    int has_directory_operand = 0;
    for (int j = i; j < argc; j++) {
        struct stat st;
        if (lstat(argv[j], &st) == 0 && S_ISDIR(st.st_mode)) {
            has_directory_operand = 1;
            break;
        }
    }

    int prefix_filename = filename_prefix;
    if (prefix_filename == -1) {
        if (file_count > 1 || (recursive && has_directory_operand)) {
            prefix_filename = 1;
        } else {
            prefix_filename = 0;
        }
    }

    int fold_allocated = ignore_case;
    if (!recursive && file_count > 0) {
        for (int j = i; j < argc; j++) {
            struct stat st;
            if (lstat(argv[j], &st) == 0 && S_ISDIR(st.st_mode)) {
                fprintf(stderr, "%s: Is a directory\n", argv[j]);
                return 2;
            }
        }
    }

    if (file_count == 0) {
        int matched = 0;
        int error_occurred = 0;
        size_t len;
        char *line;

        while ((line = read_line(stdin, &len)) != NULL) {
            if (ignore_case ? matches_ignore_case(line, len, pattern, pat_len) : matches(line, len, pattern, pat_len)) {
                if (prefix_filename) {
                    if (fprintf(stdout, "(standard input):") < 0) {
                        error_occurred = 1;
                        free(line);
                        break;
                    }
                }
                if (len > 0) {
                    if (fwrite(line, 1, len, stdout) != len) {
                        error_occurred = 1;
                        free(line);
                        break;
                    }
                }
                if (putc('\n', stdout) == EOF) {
                    error_occurred = 1;
                    free(line);
                    break;
                }
                matched = 1;
            }
            free(line);
        }

        if (ferror(stdin)) {
            fprintf(stderr, "stdin: %s\n", strerror(errno));
            error_occurred = 1;
        }

        if (fold_allocated) free((void *)pattern);
        return error_occurred ? 2 : (matched ? 0 : 1);
    } else {
        int exit_status = 0;
        int matched_at_least_once = 0;
        for (; i < argc; i++) {
            int status = search_file_recursive(argv[i], pattern, pat_len, ignore_case, prefix_filename);
            if (status == 2) {
                exit_status = 2;
            } else if (status == 0) {
                matched_at_least_once = 1;
            }
        }
        if (exit_status != 2) {
            exit_status = matched_at_least_once ? 0 : 1;
        }
        if (fold_allocated) free((void *)pattern);
        return exit_status;
    }
}
