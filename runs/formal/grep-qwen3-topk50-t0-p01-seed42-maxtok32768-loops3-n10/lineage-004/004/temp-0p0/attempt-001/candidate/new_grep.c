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

static int fold_byte(int c) {
    if ((unsigned char)c >= 0x41 && (unsigned char)c <= 0x5A) {
        return c | 0x20;
    }
    return c;
}

static int matches(const char *line, size_t line_len, const char *pattern, size_t pat_len, int ignore_case) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;

    if (!ignore_case) {
        return memmem(line, line_len, pattern, pat_len) != NULL;
    }

    for (size_t i = 0; i <= line_len - pat_len; i++) {
        int match = 1;
        for (size_t j = 0; j < pat_len; j++) {
            if (fold_byte((unsigned char)line[i + j]) != fold_byte((unsigned char)pattern[j])) {
                match = 0;
                break;
            }
        }
        if (match) return 1;
    }
    return 0;
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
                        int prefix_filename, int ignore_case) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    int matched_at_least_once = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && errno != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            fclose(fp);
            return 2;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len, ignore_case)) {
            matched_at_least_once = 1;
            if (prefix_filename) {
                if (write_line_with_prefix(filename, line, line_len) < 0) {
                    perror("new_grep");
                    free(line);
                    fclose(fp);
                    return 2;
                }
            } else {
                if (write_line(line, line_len) < 0) {
                    perror("new_grep");
                    free(line);
                    fclose(fp);
                    return 2;
                }
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

static int is_symlink(const char *path) {
    struct stat st;
    if (lstat(path, &st) != 0) return 0;
    return S_ISLNK(st.st_mode);
}

struct dir_entry {
    char *name;
};

static int compare_entries(const void *a, const void *b) {
    const struct dir_entry *ea = (const struct dir_entry *)a;
    const struct dir_entry *eb = (const struct dir_entry *)b;
    return strcmp(ea->name, eb->name);
}

static int search_directory_recursive(const char *dirpath, const char *pattern,
                                       size_t pat_len, int prefix_filename, int ignore_case);

static int process_dir_entries(const char *dirpath, const char *pattern,
                                size_t pat_len, int prefix_filename, int ignore_case) {
    DIR *dir = opendir(dirpath);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
        return 2;
    }

    struct dirent *entry;
    size_t count = 0;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        count++;
    }

    closedir(dir);

    if (count == 0) {
        return 1;
    }

    struct dir_entry *entries = malloc(count * sizeof(struct dir_entry));
    if (!entries) {
        fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
        return 2;
    }

    dir = opendir(dirpath);
    if (!dir) {
        free(entries);
        fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
        return 2;
    }

    count = 0;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        entries[count].name = strdup(entry->d_name);
        if (!entries[count].name) {
            fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
            closedir(dir);
            for (size_t i = 0; i < count; i++) free(entries[i].name);
            free(entries);
            return 2;
        }
        count++;
    }

    closedir(dir);

    qsort(entries, count, sizeof(struct dir_entry), compare_entries);

    int error_occurred = 0;
    int matched_anywhere = 0;

    for (size_t i = 0; i < count; i++) {
        char *fullpath = malloc(strlen(dirpath) + strlen(entries[i].name) + 2);
        if (!fullpath) {
            fprintf(stderr, "%s/%s: %s\n", dirpath, entries[i].name, strerror(errno));
            error_occurred = 1;
            free(entries[i].name);
            continue;
        }

        strcpy(fullpath, dirpath);
        size_t len = strlen(dirpath);
        if (len > 0 && dirpath[len - 1] != '/') {
            strcat(fullpath, "/");
        }
        strcat(fullpath, entries[i].name);

        if (is_symlink(fullpath)) {
            free(entries[i].name);
            free(fullpath);
            continue;
        }

        if (is_directory(fullpath)) {
            int status = search_directory_recursive(fullpath, pattern, pat_len, prefix_filename, ignore_case);
            if (status == 2) error_occurred = 1;
            else if (status == 1) matched_anywhere = 0;
        } else {
            int status = search_file(fullpath, pattern, pat_len, prefix_filename, ignore_case);
            if (status == 2) error_occurred = 1;
            else if (status == 0) matched_anywhere = 1;
        }

        free(entries[i].name);
        free(fullpath);
    }

    free(entries);

    return error_occurred ? 2 : (matched_anywhere ? 0 : 1);
}

static int search_directory_recursive(const char *dirpath, const char *pattern,
                                       size_t pat_len, int prefix_filename, int ignore_case) {
    struct stat st;
    if (lstat(dirpath, &st) != 0) {
        fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
        return 2;
    }

    if (is_symlink(dirpath)) {
        return 1;
    }

    if (!S_ISDIR(st.st_mode)) {
        return search_file(dirpath, pattern, pat_len, prefix_filename, ignore_case);
    }

    return process_dir_entries(dirpath, pattern, pat_len, prefix_filename, ignore_case);
}

int main(int argc, char *argv[]) {
    int separator_idx = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            separator_idx = i;
            break;
        }
    }

    int first_operand_idx = (separator_idx >= 0) ? separator_idx + 1 : 1;

    int filename_flag = 0;
    int recursive_flag = 0;
    int ignore_case_flag = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            break;
        }
        if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
            filename_flag = 1;
        } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
            filename_flag = -1;
        } else if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
            recursive_flag = 1;
        } else if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--ignore-case") == 0) {
            ignore_case_flag = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            char *p = &argv[i][1];
            int all_options = 1;
            while (*p) {
                if (*p != 'H' && *p != 'h' && *p != 'r' && *p != 'i') {
                    all_options = 0;
                    break;
                }
                p++;
            }
            if (all_options) {
                char *q = &argv[i][1];
                while (*q) {
                    if (*q == 'H') {
                        filename_flag = 1;
                    } else if (*q == 'h') {
                        filename_flag = -1;
                    } else if (*q == 'r') {
                        recursive_flag = 1;
                    } else if (*q == 'i') {
                        ignore_case_flag = 1;
                    }
                    q++;
                }
                continue;
            }
        }
        if (i < first_operand_idx || (separator_idx >= 0 && i > separator_idx)) {
            fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
            return 2;
        }
    }

    int pattern_idx = -1;
    for (int i = first_operand_idx; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "-h") == 0 ||
                strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                continue;
            }
            if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
                continue;
            }
            if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--ignore-case") == 0) {
                continue;
            }
            char *p = &argv[i][1];
            int all_options = 1;
            while (*p) {
                if (*p != 'H' && *p != 'h' && *p != 'r' && *p != 'i') {
                    all_options = 0;
                    break;
                }
                p++;
            }
            if (all_options) {
                continue;
            }
        }
        pattern_idx = i;
        break;
    }

    if (pattern_idx < 0) {
        fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }

    const char *pattern = argv[pattern_idx];
    size_t pat_len = strlen(pattern);

    int file_count = 0;
    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "-h") == 0 ||
                strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                continue;
            }
            if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
                continue;
            }
            if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--ignore-case") == 0) {
                continue;
            }
            char *p = &argv[i][1];
            int all_options = 1;
            while (*p) {
                if (*p != 'H' && *p != 'h' && *p != 'r' && *p != 'i') {
                    all_options = 0;
                    break;
                }
                p++;
            }
            if (all_options) {
                continue;
            }
        }
        file_count++;
    }

    int has_directory_operand = 0;
    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            continue;
        }
        if (is_directory(argv[i])) {
            has_directory_operand = 1;
            break;
        }
    }

    int prefix_filename = (filename_flag == 1) ? 1 : ((filename_flag == -1) ? 0 :
                               ((file_count >= 2) ? 1 :
                                ((recursive_flag && has_directory_operand) ? 1 : 0)));

    char *folded_pattern = NULL;
    if (ignore_case_flag) {
        folded_pattern = malloc(pat_len);
        if (!folded_pattern) {
            fprintf(stderr, "new_grep: %s\n", strerror(errno));
            return 2;
        }
        for (size_t i = 0; i < pat_len; i++) {
            folded_pattern[i] = fold_byte((unsigned char)pattern[i]);
        }
    }

    if (file_count == 0) {
        int matched_at_least_once = 0;

        while (1) {
            size_t line_len;
            char *line = read_line(stdin, &line_len);
            if (!line && errno != 0) {
                perror("new_grep");
                return 2;
            }
            if (!line) break;

            if (matches(line, line_len, ignore_case_flag ? folded_pattern : pattern, pat_len, ignore_case_flag)) {
                matched_at_least_once = 1;
                if (prefix_filename) {
                    if (write_line_with_prefix("(standard input)", line, line_len) < 0) {
                        perror("new_grep");
                        free(line);
                        return 2;
                    }
                } else {
                    if (write_line(line, line_len) < 0) {
                        perror("new_grep");
                        free(line);
                        return 2;
                    }
                }
            }
            free(line);
        }

        free(folded_pattern);
        return matched_at_least_once ? 0 : 1;
    } else {
        int error_occurred = 0;
        int matched_anywhere = 0;

        for (int i = pattern_idx + 1; i < argc; i++) {
            if (strcmp(argv[i], "--") == 0) {
                break;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "-h") == 0 ||
                    strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                    continue;
                }
                if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
                    continue;
                }
                char *p = &argv[i][1];
                int all_options = 1;
                while (*p) {
                    if (*p != 'H' && *p != 'h' && *p != 'r') {
                        all_options = 0;
                        break;
                    }
                    p++;
                }
                if (all_options) {
                    continue;
                }
            }

            const char *filename = argv[i];

            if (recursive_flag && is_directory(filename)) {
                int dir_status = search_directory_recursive(filename, pattern, pat_len, prefix_filename, ignore_case_flag);
                if (dir_status == 2) error_occurred = 1;
                else if (dir_status == 0) matched_anywhere = 1;
            } else if (is_directory(filename)) {
                fprintf(stderr, "%s: Is a directory\n", filename);
                error_occurred = 1;
                continue;
            } else {
                int file_status = search_file(filename, pattern, pat_len, prefix_filename, ignore_case_flag);
                if (file_status == 2) {
                    error_occurred = 1;
                } else if (file_status == 0) {
                    matched_anywhere = 1;
                }
            }
        }

        free(folded_pattern);
        return error_occurred ? 2 : (matched_anywhere ? 0 : 1);
    }
}
