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
            if (len > 0) {
                break;
            }
            free(buf);
            return NULL;
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

static int fold_char(int c) {
    if ((unsigned char)c >= 0x41 && (unsigned char)c <= 0x5A) {
        return c | 0x20;
    }
    return c;
}

static int contains_pattern(const char *line, size_t line_len, const char *pattern, size_t pat_len, int ignore_case) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;

    if (!ignore_case) {
        for (size_t i = 0; i <= line_len - pat_len; i++) {
            if (memcmp(line + i, pattern, pat_len) == 0) {
                return 1;
            }
        }
        return 0;
    }

    unsigned char *folded_line = malloc(line_len);
    unsigned char *folded_pattern = malloc(pat_len);
    if (!folded_line || !folded_pattern) {
        free(folded_line);
        free(folded_pattern);
        return 0;
    }

    for (size_t i = 0; i < line_len; i++) {
        folded_line[i] = (unsigned char)fold_char(line[i]);
    }
    for (size_t i = 0; i < pat_len; i++) {
        folded_pattern[i] = (unsigned char)fold_char(pattern[i]);
    }

    for (size_t i = 0; i <= line_len - pat_len; i++) {
        if (memcmp(folded_line + i, folded_pattern, pat_len) == 0) {
            free(folded_line);
            free(folded_pattern);
            return 1;
        }
    }

    free(folded_line);
    free(folded_pattern);
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len, int prefix_filename, int recursive, int ignore_case);

static int process_entry(const char *path, const char *pattern, size_t pat_len, int prefix_filename, int *exit_status, int recursive, int ignore_case);
static int traverse_directory(const char *dirpath, const char *pattern, size_t pat_len, int prefix_filename, int *exit_status, int recursive, int ignore_case);

static int search_file(const char *filename, const char *pattern, size_t pat_len, int prefix_filename, int recursive, int ignore_case) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "new_grep: cannot open '%s': %s\n", filename, strerror(errno));
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fclose(fp);
        int local_status = 1;
        traverse_directory(filename, pattern, pat_len, prefix_filename, &local_status, recursive, ignore_case);
        return local_status;
    }

    int matched = 0;
    int error_occurred = 0;
    size_t len;
    char *line;

    while ((line = read_line(fp, &len)) != NULL) {
        if (contains_pattern(line, len, pattern, pat_len, ignore_case)) {
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    error_occurred = 1;
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

    fclose(fp);

    if (error_occurred) {
        fprintf(stderr, "new_grep: write error\n");
        return 2;
    }

    return matched ? 0 : 1;
}

static int process_entry(const char *path, const char *pattern, size_t pat_len, int prefix_filename, int *exit_status, int recursive, int ignore_case) {
    struct stat st;
    if (lstat(path, &st) < 0) {
        fprintf(stderr, "new_grep: cannot access '%s': %s\n", path, strerror(errno));
        return 2;
    }

    if (S_ISLNK(st.st_mode)) {
        return 0;
    }

    if (S_ISDIR(st.st_mode)) {
        if (!recursive) {
            fprintf(stderr, "new_grep: %s: is a directory (use -r to search it)\n", path);
            if (exit_status) *exit_status = 2;
            return 2;
        }
        return traverse_directory(path, pattern, pat_len, prefix_filename, exit_status, recursive, ignore_case);
    }

    if (S_ISREG(st.st_mode)) {
        int status = search_file(path, pattern, pat_len, prefix_filename, recursive, ignore_case);
        if (status == 2) {
            if (exit_status) *exit_status = 2;
            return 2;
        }
        if (status == 0 && exit_status && *exit_status != 2) {
            *exit_status = 0;
        }
        return status;
    }

    return 0;
}

static int traverse_directory(const char *dirpath, const char *pattern, size_t pat_len, int prefix_filename, int *exit_status, int recursive, int ignore_case) {
    DIR *dir = opendir(dirpath);
    if (!dir) {
        fprintf(stderr, "new_grep: cannot open directory '%s': %s\n", dirpath, strerror(errno));
        if (exit_status) *exit_status = 2;
        return 2;
    }

    struct dirent *entry;
    char **names = NULL;
    size_t count = 0;
    size_t capacity = 0;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (count >= capacity) {
            size_t new_cap = capacity == 0 ? 16 : capacity * 2;
            char **new_names = realloc(names, new_cap * sizeof(char *));
            if (!new_names) {
                for (size_t i = 0; i < count; i++) free(names[i]);
                free(names);
                closedir(dir);
                return 2;
            }
            names = new_names;
            capacity = new_cap;
        }
        size_t len = strlen(entry->d_name);
        char *name = malloc(len + 1);
        if (!name) {
            for (size_t i = 0; i < count; i++) free(names[i]);
            free(names);
            closedir(dir);
            return 2;
        }
        memcpy(name, entry->d_name, len + 1);
        names[count++] = name;
    }
    closedir(dir);

    for (size_t i = 0; i < count; i++) {
        for (size_t j = i + 1; j < count; j++) {
            if (strcmp(names[i], names[j]) > 0) {
                char *tmp = names[i];
                names[i] = names[j];
                names[j] = tmp;
            }
        }
    }

    int local_status = 1;
    for (size_t i = 0; i < count; i++) {
        size_t dir_len = strlen(dirpath);
        size_t name_len = strlen(names[i]);
        char *path = malloc(dir_len + 1 + name_len + 2);
        if (!path) {
            for (size_t j = i; j < count; j++) free(names[j]);
            free(names);
            return 2;
        }
        memcpy(path, dirpath, dir_len);
        int needs_slash = dir_len > 0 && dirpath[dir_len - 1] != '/';
        size_t offset = needs_slash ? dir_len : dir_len - 1;
        path[offset] = '/';
        memcpy(path + offset + 1, names[i], name_len + 1);
        free(names[i]);

        int status = process_entry(path, pattern, pat_len, prefix_filename, exit_status ? exit_status : &local_status, recursive, ignore_case);
        if (status == 2) {
            if (exit_status) *exit_status = 2;
            local_status = 2;
        } else if (status == 0 && local_status != 2) {
            local_status = 0;
        }

        free(path);
    }

    free(names);

    return local_status;
}

static void usage(void) {
    fprintf(stderr, "usage: new_grep [-H|-h] [-r] [-i] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int arg_idx = 1;
    int filename_mode = 0;
    int recursive = 0;
    int ignore_case = 0;

    while (arg_idx < argc) {
        if (strcmp(argv[arg_idx], "--") == 0) {
            arg_idx++;
            break;
        }
        if (argv[arg_idx][0] == '-' && argv[arg_idx][1] != '\0') {
            if (strcmp(argv[arg_idx], "-H") == 0 || strcmp(argv[arg_idx], "--with-filename") == 0) {
                filename_mode = 1;
                arg_idx++;
                continue;
            }
            if (strcmp(argv[arg_idx], "-h") == 0 || strcmp(argv[arg_idx], "--no-filename") == 0) {
                filename_mode = -1;
                arg_idx++;
                continue;
            }
            if (strcmp(argv[arg_idx], "-r") == 0 || strcmp(argv[arg_idx], "--recursive") == 0) {
                recursive = 1;
                arg_idx++;
                continue;
            }
            if (strcmp(argv[arg_idx], "-i") == 0 || strcmp(argv[arg_idx], "--ignore-case") == 0) {
                ignore_case = 1;
                arg_idx++;
                continue;
            }
            for (int i = 1; argv[arg_idx][i] != '\0'; i++) {
                char c = argv[arg_idx][i];
                if (c == 'H') {
                    filename_mode = 1;
                } else if (c == 'h') {
                    filename_mode = -1;
                } else if (c == 'r') {
                    recursive = 1;
                } else if (c == 'i') {
                    ignore_case = 1;
                } else {
                    usage();
                    return 2;
                }
            }
            arg_idx++;
            continue;
        }
        break;
    }

    if (arg_idx >= argc) {
        usage();
        return 2;
    }

    const char *pattern = argv[arg_idx];
    size_t pat_len = strlen(pattern);

    int file_count = argc - arg_idx - 1;

    int has_directory = 0;
    for (int i = 0; i < file_count; i++) {
        struct stat st;
        if (stat(argv[arg_idx + 1 + i], &st) == 0 && S_ISDIR(st.st_mode)) {
            has_directory = 1;
            break;
        }
    }

    int prefix_filename = filename_mode == 1;
    if (!prefix_filename && filename_mode != -1) {
        if (file_count > 1) {
            prefix_filename = 1;
        } else if (recursive && has_directory) {
            prefix_filename = 1;
        }
    }

    if (file_count == 0) {
        size_t len;
        char *line;
        int matched = 0;
        while ((line = read_line(stdin, &len)) != NULL) {
            if (contains_pattern(line, len, pattern, pat_len, ignore_case)) {
                if (prefix_filename) {
                    if (fprintf(stdout, "(standard input):") < 0) {
                        fprintf(stderr, "new_grep: write error\n");
                        free(line);
                        return 2;
                    }
                }
                if (len > 0) {
                    if (fwrite(line, 1, len, stdout) != len) {
                        fprintf(stderr, "new_grep: write error\n");
                        free(line);
                        return 2;
                    }
                }
                if (putc('\n', stdout) == EOF) {
                    fprintf(stderr, "new_grep: write error\n");
                    free(line);
                    return 2;
                }
                matched = 1;
            }
            free(line);
        }
        return matched ? 0 : 1;
    }

    int exit_status = 1;
    for (int i = 0; i < file_count; i++) {
        const char *filename = argv[arg_idx + 1 + i];
        struct stat st;
        if (lstat(filename, &st) == 0 && S_ISLNK(st.st_mode)) {
            int status = search_file(filename, pattern, pat_len, prefix_filename, recursive, ignore_case);
            if (status == 2) {
                exit_status = 2;
            } else if (status == 0 && exit_status != 2) {
                exit_status = 0;
            }
        } else {
            int status = process_entry(filename, pattern, pat_len, prefix_filename, &exit_status, recursive, ignore_case);
            if (status == 2) {
                exit_status = 2;
            } else if (status == 0 && exit_status != 2) {
                exit_status = 0;
            }
        }
    }

    return exit_status;
}
