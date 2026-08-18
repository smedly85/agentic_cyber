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
                        int prefix_filename, int recursive, int from_traversal);

static void free_string_array(char **arr, int count) {
    for (int i = 0; i < count; i++) {
        free(arr[i]);
    }
    free(arr);
}

static int compare_strings(const void *a, const void *b) {
    const char *s1 = *(const char **)a;
    const char *s2 = *(const char **)b;
    return strcmp(s1, s2);
}

static int search_directory(const char *dirname, const char *pattern, size_t pat_len,
                            int prefix_filename, int recursive);

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int recursive, int from_traversal) {
    struct stat st;
    if (lstat(filename, &st) != 0) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    if (S_ISLNK(st.st_mode)) {
        if (from_traversal) {
            return 1;
        }
    }

    if (S_ISDIR(st.st_mode)) {
        if (recursive) {
            char *dir_path = NULL;
            size_t len = strlen(filename);
            if (len > 0 && filename[len - 1] == '/') {
                dir_path = strdup(filename);
            } else {
                dir_path = malloc(len + 2);
                strcpy(dir_path, filename);
                strcat(dir_path, "/");
            }
            int result = search_directory(dir_path, pattern, pat_len, prefix_filename, recursive);
            free(dir_path);
            return result;
        } else {
            fprintf(stderr, "%s: Is a directory\n", filename);
            return 2;
        }
    }

    if (!S_ISREG(st.st_mode)) {
        return 1;
    }

    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    int matched = 0;
    int error_occurred = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && ferror(fp)) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            error_occurred = 1;
            break;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len)) {
            matched = 1;
            if (prefix_filename) {
                if (write_line_with_prefix(filename, line, line_len) < 0) {
                    error_occurred = 1;
                    break;
                }
            } else {
                if (write_line(line, line_len) < 0) {
                    error_occurred = 1;
                    break;
                }
            }
        }
        free(line);
    }

    fclose(fp);

    if (error_occurred) return 2;
    return matched ? 0 : 1;
}

static int search_directory(const char *dirname, const char *pattern, size_t pat_len,
                            int prefix_filename, int recursive) {
    DIR *dir = opendir(dirname);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirname, strerror(errno));
        return 2;
    }

    struct dirent *entry;
    int entry_count = 0;
    char **names = NULL;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        names = realloc(names, sizeof(char *) * (entry_count + 1));
        if (!names) {
            closedir(dir);
            return 2;
        }
        names[entry_count] = strdup(entry->d_name);
        if (!names[entry_count]) {
            free_string_array(names, entry_count);
            free(names);
            closedir(dir);
            return 2;
        }
        entry_count++;
    }

    closedir(dir);

    if (entry_count > 0) {
        qsort(names, entry_count, sizeof(char *), compare_strings);
    }

    int error_occurred = 0;
    int matched_at_least_once = 0;

    for (int i = 0; i < entry_count; i++) {
        char *name = names[i];
        char *full_path = NULL;

        size_t dir_len = strlen(dirname);
        size_t name_len = strlen(name);

        if (dirname[dir_len - 1] == '/') {
            full_path = malloc(dir_len + name_len + 1);
            strcpy(full_path, dirname);
            strcat(full_path, name);
        } else {
            full_path = malloc(dir_len + 1 + name_len + 1);
            strcpy(full_path, dirname);
            strcat(full_path, "/");
            strcat(full_path, name);
        }

        struct stat st;
        if (lstat(full_path, &st) != 0) {
            fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
            error_occurred = 1;
            free(full_path);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(full_path);
            continue;
        }

        if (S_ISDIR(st.st_mode)) {
            int result = search_directory(full_path, pattern, pat_len, prefix_filename, recursive);
            if (result == 0) matched_at_least_once = 1;
            if (result == 2) error_occurred = 1;
        } else if (S_ISREG(st.st_mode)) {
            FILE *fp = fopen(full_path, "rb");
            if (!fp) {
                fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
                error_occurred = 1;
            } else {
                int matched = 0;
                while (1) {
                    size_t line_len;
                    char *line = read_line(fp, &line_len);
                    if (!line && ferror(fp)) {
                        fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
                        error_occurred = 1;
                        break;
                    }
                    if (!line) break;

                    if (matches(line, line_len, pattern, pat_len)) {
                        matched = 1;
                        if (prefix_filename) {
                            if (write_line_with_prefix(full_path, line, line_len) < 0) {
                                error_occurred = 1;
                                free(line);
                                break;
                            }
                        } else {
                            if (write_line(line, line_len) < 0) {
                                error_occurred = 1;
                                free(line);
                                break;
                            }
                        }
                    }
                    free(line);
                }
                fclose(fp);
                if (matched) matched_at_least_once = 1;
            }
        }

        free(full_path);
    }

    free_string_array(names, entry_count);
    free(names);

    if (error_occurred) return 2;
    return matched_at_least_once ? 0 : 1;
}

static void usage(void) {
    fprintf(stderr, "Usage: new_grep [-H|-h] [-r] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    int first_operand_idx = 1;
    int filename_prefix_state = 0;
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            first_operand_idx = i + 1;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            if (strcmp(argv[i], "--recursive") == 0) {
                recursive = 1;
                continue;
            }
            if (strcmp(argv[i], "--with-filename") == 0) {
                filename_prefix_state = 1;
                continue;
            }
            if (strcmp(argv[i], "--no-filename") == 0) {
                filename_prefix_state = -1;
                continue;
            }
            if (argv[i][1] == 'r') {
                recursive = 1;
                for (int j = 1; argv[i][j]; j++) {
                    if (argv[i][j] == 'H') {
                        filename_prefix_state = 1;
                    } else if (argv[i][j] == 'h') {
                        filename_prefix_state = -1;
                    } else if (argv[i][j] != 'r') {
                        usage();
                        return 2;
                    }
                }
                continue;
            }
            if (argv[i][1] == 'H' || argv[i][1] == 'h') {
                for (int j = 1; argv[i][j]; j++) {
                    if (argv[i][j] == 'H') {
                        filename_prefix_state = 1;
                    } else if (argv[i][j] == 'h') {
                        filename_prefix_state = -1;
                    } else {
                        usage();
                        return 2;
                    }
                }
                continue;
            }
            usage();
            return 2;
        }
        first_operand_idx = i;
        break;
    }

    if (first_operand_idx >= argc) {
        usage();
        return 2;
    }

    const char *pattern = argv[first_operand_idx];
    size_t pat_len = strlen(pattern);

    int num_files = argc - first_operand_idx - 1;

    int has_directory = 0;
    for (int i = first_operand_idx + 1; i < argc; i++) {
        struct stat st;
        if (lstat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
            has_directory = 1;
            break;
        }
    }

    int prefix_filename = (filename_prefix_state == 1) || 
                          (filename_prefix_state == 0 && num_files > 1) ||
                          (recursive && has_directory);

    int matched_at_least_once = 0;
    int error_occurred = 0;

    if (num_files == 0) {
        while (1) {
            size_t line_len;
            char *line = read_line(stdin, &line_len);
            if (!line && ferror(stdin)) {
                fprintf(stderr, "(standard input): %s\n", strerror(errno));
                error_occurred = 1;
                break;
            }
            if (!line) break;

            if (matches(line, line_len, pattern, pat_len)) {
                matched_at_least_once = 1;
                if (prefix_filename) {
                    if (write_line_with_prefix("(standard input)", line, line_len) < 0) {
                        error_occurred = 1;
                        break;
                    }
                } else {
                    if (write_line(line, line_len) < 0) {
                        error_occurred = 1;
                        break;
                    }
                }
            }
            free(line);
        }
    } else {
        for (int i = first_operand_idx + 1; i < argc; i++) {
            int result = search_file(argv[i], pattern, pat_len, prefix_filename, recursive, 0);
            if (result == 0) matched_at_least_once = 1;
            if (result == 2) error_occurred = 1;
        }
    }

    if (error_occurred) return 2;
    return matched_at_least_once ? 0 : 1;
}
