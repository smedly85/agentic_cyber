#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>

#define CHUNK_SIZE 4096

static char fold_byte(char b) {
    unsigned char c = (unsigned char)b;
    if (c >= 'A' && c <= 'Z') {
        return (char)(c | 0x20);
    }
    return b;
}

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

    if (len >= capacity - 1) {
        char *new_buf = realloc(buf, len + 2);
        if (!new_buf) {
            free(buf);
            return NULL;
        }
        buf = new_buf;
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
            char folded_line_char = fold_byte(line[i + j]);
            char folded_pattern_char = fold_byte(pattern[j]);
            if (folded_line_char != folded_pattern_char) {
                found = 0;
                break;
            }
        }
        if (found) return 1;
    }
    return 0;
}

static int write_line_with_prefix(const char *filename, const char *line, size_t len) {
    FILE *out = stdout;
    size_t written = 0;
    size_t prefix_len = strlen(filename);

    while (written < prefix_len) {
        size_t n = fwrite(filename + written, 1, prefix_len - written, out);
        if (n == 0) return -1;
        written += n;
    }

    if (fputc(':', out) == EOF) return -1;

    size_t pos = 0;
    while (pos < len) {
        size_t n = fwrite(line + pos, 1, len - pos, out);
        if (n == 0) return -1;
        pos += n;
    }

    if (fputc('\n', out) == EOF) return -1;

    return 0;
}

static int write_line(const char *line, size_t len) {
    FILE *out = stdout;
    size_t pos = 0;
    while (pos < len) {
        size_t n = fwrite(line + pos, 1, len - pos, out);
        if (n == 0) return -1;
        pos += n;
    }
    if (fputc('\n', out) == EOF) return -1;
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int ignore_case) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return -1;
    }

    int matched_at_least_once = 0;
    size_t line_len;
    char *line;

    while ((line = read_line(fp, &line_len)) != NULL) {
        int match;
        if (ignore_case) {
            match = matches_ignore_case(line, line_len, pattern, pat_len);
        } else {
            match = matches(line, line_len, pattern, pat_len);
        }
        if (match) {
            matched_at_least_once = 1;
            int rc;
            if (prefix_filename) {
                rc = write_line_with_prefix(filename, line, line_len);
            } else {
                rc = write_line(line, line_len);
            }
            if (rc < 0) {
                fprintf(stderr, "write error\n");
                free(line);
                fclose(fp);
                return -2;
            }
        }
        free(line);
    }

    fclose(fp);
    return matched_at_least_once ? 0 : 1;
}

static int search_recursive(const char *operand, const char *pattern, size_t pat_len,
                            int prefix_filename, int ignore_case);

static int compare_names(const void *a, const void *b) {
    const char *na = *(const char **)a;
    const char *nb = *(const char **)b;
    return strcmp(na, nb);
}

static int search_directory(const char *dirpath, const char *pattern, size_t pat_len,
                            int prefix_filename, int has_trailing_slash, int ignore_case) {
    DIR *dp = opendir(dirpath);
    if (!dp) {
        fprintf(stderr, "%s: %s\n", dirpath, strerror(errno));
        return -1;
    }

    struct dirent *entry;
    char **names = NULL;
    size_t count = 0;
    size_t capacity = 0;

    while ((entry = readdir(dp)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;
        
        if (count >= capacity) {
            capacity = capacity ? capacity * 2 : 16;
            char **new_names = realloc(names, capacity * sizeof(char *));
            if (!new_names) {
                for (size_t i = 0; i < count; i++) free(names[i]);
                free(names);
                closedir(dp);
                return -1;
            }
            names = new_names;
        }
        
        size_t len = strlen(entry->d_name);
        names[count] = malloc(len + 1);
        if (!names[count]) {
            for (size_t i = 0; i < count; i++) free(names[i]);
            free(names);
            closedir(dp);
            return -1;
        }
        strcpy(names[count], entry->d_name);
        count++;
    }
    closedir(dp);

    qsort(names, count, sizeof(char *), compare_names);

    int result = 1;
    int has_error = 0;
    for (size_t i = 0; i < count; i++) {
        char *fullpath;
        if (has_trailing_slash) {
            size_t dirlen = strlen(dirpath);
            size_t namelen = strlen(names[i]);
            fullpath = malloc(dirlen + namelen + 1);
            if (!fullpath) {
                has_error = 1;
                break;
            }
            strcpy(fullpath, dirpath);
            strcat(fullpath, names[i]);
        } else {
            size_t dirlen = strlen(dirpath);
            size_t namelen = strlen(names[i]);
            fullpath = malloc(dirlen + 1 + namelen + 1);
            if (!fullpath) {
                has_error = 1;
                break;
            }
            strcpy(fullpath, dirpath);
            strcat(fullpath, "/");
            strcat(fullpath, names[i]);
        }

        struct stat st;
        if (lstat(fullpath, &st) != 0) {
            fprintf(stderr, "%s: %s\n", fullpath, strerror(errno));
            free(fullpath);
            has_error = 1;
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int rc = search_file(fullpath, pattern, pat_len, prefix_filename, ignore_case);
            if (rc == -2) {
                for (size_t j = i; j < count; j++) free(names[j]);
                free(names);
                return -2;
            }
            if (rc == 0) result = 0;
            if (rc < 0) has_error = 1;
        } else if (S_ISDIR(st.st_mode)) {
            int rc = search_recursive(fullpath, pattern, pat_len, prefix_filename, ignore_case);
            if (rc == -2) {
                for (size_t j = i; j < count; j++) free(names[j]);
                free(names);
                return -2;
            }
            if (rc == 0) result = 0;
            if (rc < 0) has_error = 1;
        }
        
        free(fullpath);
    }

    for (size_t i = 0; i < count; i++) free(names[i]);
    free(names);

    if (has_error) return -1;
    return result;
}

static int search_recursive(const char *operand, const char *pattern, size_t pat_len,
                            int prefix_filename, int ignore_case) {
    struct stat st;
    if (lstat(operand, &st) != 0) {
        fprintf(stderr, "%s: %s\n", operand, strerror(errno));
        return -1;
    }

    if (S_ISLNK(st.st_mode)) {
        return search_file(operand, pattern, pat_len, prefix_filename, ignore_case);
    }

    if (S_ISREG(st.st_mode)) {
        return search_file(operand, pattern, pat_len, prefix_filename, ignore_case);
    }

    if (S_ISDIR(st.st_mode)) {
        int has_trailing_slash = strlen(operand) > 0 && operand[strlen(operand)-1] == '/';
        return search_directory(operand, pattern, pat_len, prefix_filename, has_trailing_slash, ignore_case);
    }

    fprintf(stderr, "%s: %s\n", operand, "not a regular file or directory");
    return -1;

    fprintf(stderr, "%s: %s\n", operand, "not a regular file or directory");
    return -1;
}

static int is_directory(const char *path) {
    struct stat st;
    if (stat(path, &st) != 0) return 0;
    return S_ISDIR(st.st_mode);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }

    int seen_double_dash = 0;
    int filename_mode = 0;
    int recursive_mode = 0;
    int ignore_case = 0;
    int first_operand_index = -1;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];

        if (strcmp(arg, "--") == 0) {
            seen_double_dash = 1;
            continue;
        }
        if (!seen_double_dash && arg[0] == '-' && strlen(arg) > 1) {
            if (strcmp(arg, "--with-filename") == 0) {
                filename_mode = 1;
                continue;
            }
            if (strcmp(arg, "--no-filename") == 0) {
                filename_mode = -1;
                continue;
            }
            if (strcmp(arg, "--recursive") == 0) {
                recursive_mode = 1;
                continue;
            }
            if (strcmp(arg, "--ignore-case") == 0) {
                ignore_case = 1;
                continue;
            }
            if (arg[1] != '-') {
                int j = 1;
                while (arg[j]) {
                    if (arg[j] == 'H') {
                        filename_mode = 1;
                    } else if (arg[j] == 'h') {
                        filename_mode = -1;
                    } else if (arg[j] == 'r') {
                        recursive_mode = 1;
                    } else if (arg[j] == 'i') {
                        ignore_case = 1;
                    } else {
                        fprintf(stderr, "unknown option: %s\n", arg);
                        return 2;
                    }
                    j++;
                }
                continue;
            }
            fprintf(stderr, "unknown option: %s\n", arg);
            return 2;
        }
        if (first_operand_index < 0) {
            first_operand_index = i;
        }
    }

    int pattern_index = first_operand_index >= 0 ? first_operand_index : 1;
    const char *pattern = argv[pattern_index];
    size_t pat_len = strlen(pattern);

    int file_arg_count = argc - (pattern_index + 1);
    int has_file_args = file_arg_count > 0;

    int has_dir_operand = 0;
    if (recursive_mode) {
        for (int i = pattern_index + 1; i < argc; i++) {
            const char *arg = argv[i];
            if (strcmp(arg, "--") == 0) continue;
            if (!seen_double_dash && arg[0] == '-' && strlen(arg) > 1) continue;
            
            struct stat st;
            if (lstat(arg, &st) == 0 && S_ISDIR(st.st_mode)) {
                has_dir_operand = 1;
                break;
            }
        }
    }

    int prefix_filename = filename_mode == 1 ? 1 : (filename_mode == -1 ? 0 : (has_file_args && file_arg_count >= 2) ? 1 : (recursive_mode && has_dir_operand) ? 1 : 0);

    if (!has_file_args) {
        size_t line_len;
        char *line;
        int found_match = 0;
        while ((line = read_line(stdin, &line_len)) != NULL) {
            int match;
            if (ignore_case) {
                match = matches_ignore_case(line, line_len, pattern, pat_len);
            } else {
                match = matches(line, line_len, pattern, pat_len);
            }
            if (match) {
                found_match = 1;
                int rc;
                if (filename_mode == 1) {
                    rc = write_line_with_prefix("(standard input)", line, line_len);
                } else {
                    rc = write_line(line, line_len);
                }
                free(line);
                if (rc < 0) {
                    fprintf(stderr, "write error\n");
                    return 2;
                }
            } else {
                free(line);
            }
        }
        return found_match ? 0 : 1;
    }

    int found_match = 0;
    int has_error = 0;

    if (recursive_mode) {
        for (int i = pattern_index + 1; i < argc; i++) {
            const char *arg = argv[i];

            if (strcmp(arg, "--") == 0) continue;
            if (!seen_double_dash && arg[0] == '-' && strlen(arg) > 1) {
                int j = 1;
                while (arg[j]) {
                    if (arg[j] == 'H') filename_mode = 1;
                    else if (arg[j] == 'h') filename_mode = -1;
                    else if (arg[j] == 'r') recursive_mode = 1;
                    else if (arg[j] == 'i') ignore_case = 1;
                    else {
                        fprintf(stderr, "unknown option: %s\n", arg);
                        return 2;
                    }
                    j++;
                }
                continue;
            }

            struct stat st;
            if (lstat(arg, &st) != 0) {
                fprintf(stderr, "%s: %s\n", arg, strerror(errno));
                has_error = 1;
                continue;
            }

            if (S_ISLNK(st.st_mode)) {
                int rc = search_file(arg, pattern, pat_len, prefix_filename, ignore_case);
                if (rc == -2) return 2;
                if (rc == 0) found_match = 1;
                if (rc < 0) has_error = 1;
            } else if (S_ISREG(st.st_mode)) {
                int rc = search_file(arg, pattern, pat_len, prefix_filename, ignore_case);
                if (rc == -2) return 2;
                if (rc == 0) found_match = 1;
                if (rc < 0) has_error = 1;
            } else if (S_ISDIR(st.st_mode)) {
                int rc = search_recursive(arg, pattern, pat_len, prefix_filename, ignore_case);
                if (rc == -2) return 2;
                if (rc == 0) found_match = 1;
                if (rc < 0) has_error = 1;
            } else {
                fprintf(stderr, "%s: %s\n", arg, "not a regular file or directory");
                has_error = 1;
            }
        }
    } else {
        int file_start_index = pattern_index + 1;
        for (int i = file_start_index; i < argc; i++) {
            const char *arg = argv[i];

            if (strcmp(arg, "--") == 0) continue;
            if (!seen_double_dash && arg[0] == '-' && strlen(arg) > 1) {
                int j = 1;
                while (arg[j]) {
                    if (arg[j] == 'H') filename_mode = 1;
                    else if (arg[j] == 'h') filename_mode = -1;
                    else if (arg[j] == 'i') ignore_case = 1;
                    else {
                        fprintf(stderr, "unknown option: %s\n", arg);
                        return 2;
                    }
                    j++;
                }
                continue;
            }

            if (is_directory(arg)) {
                fprintf(stderr, "%s: is a directory\n", arg);
                has_error = 1;
                continue;
            }

            int rc = search_file(arg, pattern, pat_len, prefix_filename, ignore_case);
            if (rc == -2) return 2;
            if (rc == 0) found_match = 1;
            if (rc < 0) has_error = 1;
        }
    }

    if (has_error) return 2;
    return found_match ? 0 : 1;
}
