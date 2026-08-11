#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>
#include <dirent.h>

#define INITIAL_LINE_CAPACITY 256

static inline unsigned char
fold_ascii(unsigned char c)
{
    if (c >= 'A' && c <= 'Z') {
        return c | 0x20;
    }
    return c;
}

typedef struct {
    char *data;
    size_t len;
    size_t capacity;
} LineBuffer;

static int
init_line_buffer(LineBuffer *buf)
{
    buf->data = malloc(INITIAL_LINE_CAPACITY);
    if (!buf->data) {
        return -1;
    }
    buf->len = 0;
    buf->capacity = INITIAL_LINE_CAPACITY;
    return 0;
}

static void
free_line_buffer(LineBuffer *buf)
{
    free(buf->data);
    buf->data = NULL;
}

static int
grow_line_buffer(LineBuffer *buf, size_t needed)
{
    size_t new_capacity = buf->capacity;
    while (new_capacity < buf->len + needed) {
        if (new_capacity > SIZE_MAX / 2) {
            return -1;
        }
        new_capacity *= 2;
    }
    char *new_data = realloc(buf->data, new_capacity);
    if (!new_data) {
        return -1;
    }
    buf->data = new_data;
    buf->capacity = new_capacity;
    return 0;
}

static int
read_line(LineBuffer *buf, FILE *fp)
{
    buf->len = 0;

    while (1) {
        if (grow_line_buffer(buf, 1) < 0) {
            fprintf(stderr, "memory allocation failed\n");
            return -3;
        }
        int c = fgetc(fp);
        if (c == EOF) {
            if (buf->len == 0) {
                return 0;
            }
            break;
        }
        buf->data[buf->len++] = (char)c;
        if (c == '\n') {
            buf->len--;
            break;
        }
    }

    if (grow_line_buffer(buf, 1) < 0) {
        fprintf(stderr, "memory allocation failed\n");
        return -3;
    }
    buf->data[buf->len] = '\0';
    return 1;
}

static int
match_pattern(const char *line, size_t line_len, const char *pattern, size_t pattern_len, int ignore_case)
{
    if (pattern_len == 0) {
        return 1;
    }
    if (pattern_len > line_len) {
        return 0;
    }

    if (!ignore_case) {
        for (size_t i = 0; i <= line_len - pattern_len; i++) {
            int found = 1;
            for (size_t j = 0; j < pattern_len; j++) {
                if (line[i + j] != pattern[j]) {
                    found = 0;
                    break;
                }
            }
            if (found) {
                return 1;
            }
        }
        return 0;
    }

    for (size_t i = 0; i <= line_len - pattern_len; i++) {
        int found = 1;
        for (size_t j = 0; j < pattern_len; j++) {
            if (fold_ascii((unsigned char)line[i + j]) != fold_ascii((unsigned char)pattern[j])) {
                found = 0;
                break;
            }
        }
        if (found) {
            return 1;
        }
    }
    return 0;
}

static int
search_file(const char *filename, const char *pattern, size_t pattern_len,
            int prefix_filename, int ignore_case, int *match_found, int *error_occurred, int *exit_code);

static void
free_string_array(char **arr, int count)
{
    for (int i = 0; i < count; i++) {
        free(arr[i]);
    }
    free(arr);
}

static int
compare_strings(const void *a, const void *b)
{
    return strcmp(*(const char **)a, *(const char **)b);
}

static int
collect_entries(const char *dirname, char ***entries_out, int *count_out)
{
    DIR *dir = opendir(dirname);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirname, strerror(errno));
        return -1;
    }

    int capacity = 16;
    int count = 0;
    char **entries = malloc(capacity * sizeof(char *));
    if (!entries) {
        closedir(dir);
        return -1;
    }

    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (count >= capacity) {
            capacity *= 2;
            char **new_entries = realloc(entries, capacity * sizeof(char *));
            if (!new_entries) {
                free_string_array(entries, count);
                closedir(dir);
                return -1;
            }
            entries = new_entries;
        }
        entries[count] = strdup(entry->d_name);
        if (!entries[count]) {
            free_string_array(entries, count);
            closedir(dir);
            return -1;
        }
        count++;
    }

    closedir(dir);

    qsort(entries, count, sizeof(char *), compare_strings);

    *entries_out = entries;
    *count_out = count;
    return 0;
}

static int
search_recursive(const char *operand, const char *pattern, size_t pattern_len,
                 int prefix_filename, int ignore_case, int *match_found, int *error_occurred, int *exit_code)
{
    struct stat st;
    if (lstat(operand, &st) == -1) {
        fprintf(stderr, "%s: %s\n", operand, strerror(errno));
        *error_occurred = 1;
        return 2;
    }

    if (S_ISLNK(st.st_mode)) {
        return search_file(operand, pattern, pattern_len, prefix_filename,
                           ignore_case, match_found, error_occurred, exit_code);
    }

    if (S_ISDIR(st.st_mode)) {
        char **entries;
        int count;
        if (collect_entries(operand, &entries, &count) < 0) {
            *error_occurred = 1;
            return 2;
        }

        size_t operand_len = strlen(operand);
        int has_trailing_slash = (operand_len > 0 && operand[operand_len - 1] == '/');

        for (int i = 0; i < count; i++) {
            char *name = entries[i];
            size_t name_len = strlen(name);

            size_t path_len = operand_len + 1 + name_len + 1;
            char *path = malloc(path_len);
            if (!path) {
                free_string_array(entries, count);
                fprintf(stderr, "memory allocation failed\n");
                *error_occurred = 1;
                return 2;
            }

            if (has_trailing_slash) {
                snprintf(path, path_len, "%s%s", operand, name);
            } else {
                snprintf(path, path_len, "%s/%s", operand, name);
            }

            struct stat entry_st;
            if (lstat(path, &entry_st) == -1) {
                fprintf(stderr, "%s: %s\n", path, strerror(errno));
                free(path);
                *error_occurred = 1;
                continue;
            }

            if (S_ISREG(entry_st.st_mode)) {
                int result = search_file(path, pattern, pattern_len, prefix_filename,
                                         ignore_case, match_found, error_occurred, exit_code);
                if (result == 2) {
                    *exit_code = 2;
                }
            } else if (S_ISDIR(entry_st.st_mode)) {
                int result = search_recursive(path, pattern, pattern_len, prefix_filename,
                                              ignore_case, match_found, error_occurred, exit_code);
                if (result == 2) {
                    *exit_code = 2;
                }
            }

            free(path);
        }

        free_string_array(entries, count);
        return 0;
    }

    return search_file(operand, pattern, pattern_len, prefix_filename,
                       ignore_case, match_found, error_occurred, exit_code);
}

static int
search_file(const char *filename, const char *pattern, size_t pattern_len,
            int prefix_filename, int ignore_case, int *match_found, int *error_occurred, int *exit_code)
{
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        *exit_code = 2;
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "%s: Is a directory\n", filename);
        fclose(fp);
        *error_occurred = 1;
        return 2;
    }

    LineBuffer buf;
    if (init_line_buffer(&buf) < 0) {
        fprintf(stderr, "memory allocation failed\n");
        fclose(fp);
        *error_occurred = 1;
        return 2;
    }

    int result = 0;

    while (1) {
        int status = read_line(&buf, fp);
        if (status == -3) {
            result = 2;
            break;
        }
        if (status == 0) {
            break;
        }

        if (match_pattern(buf.data, buf.len, pattern, pattern_len, ignore_case)) {
            *match_found = 1;
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    fprintf(stderr, "write error\n");
                    result = 2;
                    break;
                }
            }
            if (buf.len > 0) {
                if (fwrite(buf.data, 1, buf.len, stdout) != buf.len) {
                    fprintf(stderr, "write error\n");
                    result = 2;
                    break;
                }
            }
            if (putc('\n', stdout) == EOF) {
                fprintf(stderr, "write error\n");
                result = 2;
                break;
            }
        }
    }

    free_line_buffer(&buf);
    fclose(fp);

    return result;
}

static void
print_usage(void)
{
    fprintf(stderr, "usage: new_grep [-H|-h] [--with-filename|--no-filename] [-r] [-i] PATTERN [FILE...]\n");
}

int
main(int argc, char *argv[])
{
    if (argc < 2) {
        print_usage();
        return 2;
    }

    int i = 1;
    int saw_double_dash = 0;
    int filename_mode = 0;
    int recursive = 0;
    int ignore_case = 0;

    while (i < argc) {
        if (!saw_double_dash && strcmp(argv[i], "--") == 0) {
            saw_double_dash = 1;
            i++;
            continue;
        }
        if (!saw_double_dash && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                if (strcmp(argv[i], "--with-filename") == 0) {
                    filename_mode = 1;
                } else {
                    filename_mode = -1;
                }
                i++;
                continue;
            }
            if (strcmp(argv[i], "--recursive") == 0) {
                recursive = 1;
                i++;
                continue;
            }
            if (strcmp(argv[i], "--ignore-case") == 0) {
                ignore_case = 1;
                i++;
                continue;
            }
            if (argv[i][1] != '-') {
                int j = 1;
                while (argv[i][j] != '\0') {
                    if (argv[i][j] == 'H') {
                        filename_mode = 1;
                    } else if (argv[i][j] == 'h') {
                        filename_mode = -1;
                    } else if (argv[i][j] == 'r') {
                        recursive = 1;
                    } else if (argv[i][j] == 'i') {
                        ignore_case = 1;
                    } else {
                        print_usage();
                        return 2;
                    }
                    j++;
                }
                i++;
                continue;
            }
            print_usage();
            return 2;
        }
        break;
    }

    const char *pattern = argv[i];
    size_t pattern_len = strlen(pattern);
    i++;

    int num_files = argc - i;

    int has_directory = 0;
    if (recursive) {
        for (int j = i; j < argc; j++) {
            struct stat st;
            if (lstat(argv[j], &st) == 0 && S_ISDIR(st.st_mode)) {
                has_directory = 1;
                break;
            }
        }
    }

    int prefix_filename = (filename_mode == 1) ? 1 : ((filename_mode == -1) ? 0 :
                           ((num_files > 1) ? 1 : ((recursive && has_directory) ? 1 : 0)));

    int match_found = 0;
    int error_occurred = 0;
    int exit_code = 0;

    if (num_files == 0) {
        LineBuffer buf;
        if (init_line_buffer(&buf) < 0) {
            fprintf(stderr, "memory allocation failed\n");
            return 2;
        }

        while (1) {
            int status = read_line(&buf, stdin);
            if (status == -3) {
                exit_code = 2;
                break;
            }
            if (status == 0) {
                break;
            }
            if (match_pattern(buf.data, buf.len, pattern, pattern_len, ignore_case)) {
                match_found = 1;
                if (prefix_filename) {
                    if (fprintf(stdout, "(standard input):") < 0) {
                        fprintf(stderr, "write error\n");
                        exit_code = 2;
                        break;
                    }
                }
                if (buf.len > 0) {
                    if (fwrite(buf.data, 1, buf.len, stdout) != buf.len) {
                        fprintf(stderr, "write error\n");
                        exit_code = 2;
                        break;
                    }
                }
                if (putc('\n', stdout) == EOF) {
                    fprintf(stderr, "write error\n");
                    exit_code = 2;
                    break;
                }
            }
        }

        free_line_buffer(&buf);
    } else {
        for (; i < argc; i++) {
            int result;
            if (recursive) {
                result = search_recursive(argv[i], pattern, pattern_len,
                                          prefix_filename, ignore_case, &match_found, &error_occurred, &exit_code);
            } else {
                result = search_file(argv[i], pattern, pattern_len,
                                     prefix_filename, ignore_case, &match_found, &error_occurred, &exit_code);
            }
            if (result == 2) {
                exit_code = 2;
            }
        }
    }

    if (exit_code != 2 && match_found) {
        return 0;
    } else if (exit_code != 2) {
        return 1;
    } else {
        return 2;
    }
}
