#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>

#define INITIAL_LINE_CAPACITY 256

typedef struct {
    char *data;
    size_t len;
    size_t capacity;
} LineBuffer;

static int
alloc_line_buffer(LineBuffer *buf)
{
    buf->capacity = INITIAL_LINE_CAPACITY;
    buf->data = malloc(buf->capacity);
    if (!buf->data) {
        return -1;
    }
    buf->len = 0;
    return 0;
}

static void
free_line_buffer(LineBuffer *buf)
{
    free(buf->data);
    buf->data = NULL;
    buf->len = 0;
    buf->capacity = 0;
}

static int
grow_line_buffer(LineBuffer *buf, size_t needed)
{
    size_t new_cap = buf->capacity;
    while (new_cap < buf->len + needed) {
        if (new_cap > SIZE_MAX / 2) {
            return -1;
        }
        new_cap *= 2;
    }
    char *new_data = realloc(buf->data, new_cap);
    if (!new_data) {
        return -1;
    }
    buf->data = new_data;
    buf->capacity = new_cap;
    return 0;
}

static int
read_line(FILE *fp, LineBuffer *buf)
{
    buf->len = 0;

    for (;;) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (ferror(fp)) {
                return -1;
            }
            if (buf->len == 0) {
                return 0;
            }
            return 1;
        }
        if (c == '\n') {
            return 1;
        }
        if (grow_line_buffer(buf, 1) < 0) {
            return -1;
        }
        buf->data[buf->len] = (char)c;
        buf->len++;
    }
}

static int
match_pattern(const char *line, size_t line_len, const char *pattern, size_t pattern_len)
{
    if (pattern_len == 0) {
        return 1;
    }
    if (pattern_len > line_len) {
        return 0;
    }

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

static int
is_directory(const char *path)
{
    struct stat st;
    if (lstat(path, &st) < 0) {
        return 0;
    }
    if (S_ISLNK(st.st_mode)) {
        if (stat(path, &st) < 0) {
            return 0;
        }
    }
    return S_ISDIR(st.st_mode);
}

static int
is_symlink(const char *path)
{
    struct stat st;
    if (lstat(path, &st) < 0) {
        return 0;
    }
    return S_ISLNK(st.st_mode);
}

static int
search_file(const char *filename, const char *pattern, size_t pattern_len,
            int prefix_filename, LineBuffer *buf)
{
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    int matched_at_least_once = 0;

    while (1) {
        int result = read_line(fp, buf);
        if (result < 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            fclose(fp);
            return 2;
        }
        if (result == 0) {
            break;
        }

        if (match_pattern(buf->data, buf->len, pattern, pattern_len)) {
            if (prefix_filename) {
                fprintf(stdout, "%s:", filename);
            }
            fwrite(buf->data, 1, buf->len, stdout);
            fputc('\n', stdout);
            matched_at_least_once = 1;
        }
    }

    fclose(fp);

    if (matched_at_least_once) {
        return 0;
    }
    return 1;
}

static int
search_directory(const char *dirname, const char *pattern, size_t pattern_len,
                 int prefix_filename, LineBuffer *buf, int *has_error_ptr, int *exit_status_ptr)
{
    DIR *dir = opendir(dirname);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirname, strerror(errno));
        (*has_error_ptr) = 1;
        return 2;
    }

    struct dirent *entry;
    char **names = NULL;
    size_t name_count = 0;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        names = realloc(names, (name_count + 1) * sizeof(char *));
        if (!names) {
            closedir(dir);
            fprintf(stderr, "%s: memory allocation failed\n", dirname);
            (*has_error_ptr) = 1;
            return 2;
        }
        names[name_count] = strdup(entry->d_name);
        if (!names[name_count]) {
            for (size_t i = 0; i < name_count; i++) {
                free(names[i]);
            }
            free(names);
            closedir(dir);
            fprintf(stderr, "%s: memory allocation failed\n", dirname);
            (*has_error_ptr) = 1;
            return 2;
        }
        name_count++;
    }
    closedir(dir);

    for (size_t i = 0; i < name_count; i++) {
        for (size_t j = i + 1; j < name_count; j++) {
            if (strcmp(names[i], names[j]) > 0) {
                char *tmp = names[i];
                names[i] = names[j];
                names[j] = tmp;
            }
        }
    }

    int local_has_error = *has_error_ptr;
    int local_exit_status = *exit_status_ptr;

    for (size_t i = 0; i < name_count; i++) {
        char *full_path = NULL;
        size_t dir_len = strlen(dirname);
        size_t name_len = strlen(names[i]);
        
        if (dirname[dir_len - 1] == '/') {
            full_path = malloc(dir_len + name_len + 1);
            snprintf(full_path, dir_len + name_len + 1, "%s%s", dirname, names[i]);
        } else {
            full_path = malloc(dir_len + name_len + 2);
            snprintf(full_path, dir_len + name_len + 2, "%s/%s", dirname, names[i]);
        }
        
        free(names[i]);

        struct stat st;
        if (lstat(full_path, &st) < 0) {
            fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
            local_has_error = 1;
            free(full_path);
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int status = search_file(full_path, pattern, pattern_len,
                                     prefix_filename, buf);
            if (status == 2) {
                local_has_error = 1;
            } else if (status == 0 && local_exit_status == 1) {
                local_exit_status = 0;
            }
        } else if (S_ISDIR(st.st_mode)) {
            int status = search_directory(full_path, pattern, pattern_len,
                                          prefix_filename, buf, &local_has_error, &local_exit_status);
            if (status == 2) {
                local_has_error = 1;
            } else if (status == 0 && local_exit_status == 1) {
                local_exit_status = 0;
            }
        }

        free(full_path);
    }

    free(names);

    *has_error_ptr = local_has_error;
    *exit_status_ptr = local_exit_status;

    return local_exit_status;
}

static void
usage(void)
{
    fprintf(stderr, "Usage: new_grep [-H|-h] [-r] [--with-filename|--no-filename|--recursive] PATTERN [FILE...]\n");
}

int
main(int argc, char *argv[])
{
    if (argc < 2) {
        usage();
        return 2;
    }

    const char *pattern;
    size_t pattern_len;
    int num_files;
    int filename_mode = 0;
    int recursive_mode = 0;

    int arg_idx = 1;
    while (arg_idx < argc && argv[arg_idx][0] == '-' && argv[arg_idx][1] != '\0') {
        if (strcmp(argv[arg_idx], "--with-filename") == 0) {
            filename_mode = 1;
            arg_idx++;
        } else if (strcmp(argv[arg_idx], "--no-filename") == 0) {
            filename_mode = -1;
            arg_idx++;
        } else if (strcmp(argv[arg_idx], "--recursive") == 0) {
            recursive_mode = 1;
            arg_idx++;
        } else if (strcmp(argv[arg_idx], "--") == 0) {
            arg_idx++;
            break;
        } else if (argv[arg_idx][1] == 'r') {
            for (int j = 1; argv[arg_idx][j] != '\0'; j++) {
                if (argv[arg_idx][j] == 'r') {
                    recursive_mode = 1;
                } else if (argv[arg_idx][j] == 'H') {
                    filename_mode = 1;
                } else if (argv[arg_idx][j] == 'h') {
                    filename_mode = -1;
                } else {
                    usage();
                    return 2;
                }
            }
            arg_idx++;
        } else if (argv[arg_idx][1] == 'H' || argv[arg_idx][1] == 'h') {
            for (int j = 1; argv[arg_idx][j] != '\0'; j++) {
                if (argv[arg_idx][j] == 'H') {
                    filename_mode = 1;
                } else if (argv[arg_idx][j] == 'h') {
                    filename_mode = -1;
                } else {
                    usage();
                    return 2;
                }
            }
            arg_idx++;
        } else {
            usage();
            return 2;
        }
    }

    if (arg_idx >= argc) {
        usage();
        return 2;
    }

    pattern = argv[arg_idx];
    pattern_len = strlen(pattern);
    
    int file_start = arg_idx + 1;
    num_files = 0;
    for (int i = file_start; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            continue;
        }
        num_files++;
    }

    LineBuffer buf;
    if (alloc_line_buffer(&buf) < 0) {
        fprintf(stderr, "memory allocation failed\n");
        return 2;
    }

    int exit_status = 1;
    int has_error = 0;

    int prefix_filename;
    if (filename_mode == -1) {
        prefix_filename = 0;
    } else if (filename_mode == 1) {
        prefix_filename = 1;
    } else {
        int dir_count = 0;
        for (int i = file_start; i < argc; i++) {
            if (strcmp(argv[i], "--") == 0) {
                continue;
            }
            if (is_directory(argv[i])) {
                dir_count++;
            }
        }
        prefix_filename = ((num_files > 1) || (recursive_mode && dir_count > 0)) ? 1 : 0;
    }

    if (num_files == 0) {
        while (1) {
            int result = read_line(stdin, &buf);
            if (result < 0) {
                fprintf(stderr, "(standard input): %s\n", strerror(errno));
                has_error = 1;
                break;
            }
            if (result == 0) {
                break;
            }
            if (match_pattern(buf.data, buf.len, pattern, pattern_len)) {
                if (prefix_filename) {
                    fprintf(stdout, "(standard input):");
                }
                fwrite(buf.data, 1, buf.len, stdout);
                fputc('\n', stdout);
                exit_status = 0;
            }
        }
    } else {
        for (int i = file_start; i < argc; i++) {
            if (strcmp(argv[i], "--") == 0) {
                continue;
            }
            const char *filename = argv[i];

            if (is_symlink(filename)) {
                int status = search_file(filename, pattern, pattern_len,
                                         prefix_filename, &buf);
                if (status == 2) {
                    has_error = 1;
                } else if (status == 0 && exit_status == 1) {
                    exit_status = 0;
                }
            } else if (is_directory(filename)) {
                if (recursive_mode) {
                    int status = search_directory(filename, pattern, pattern_len,
                                                  prefix_filename, &buf, &has_error, &exit_status);
                    if (status == 2) {
                        has_error = 1;
                    }
                } else {
                    fprintf(stderr, "%s: is a directory\n", filename);
                    has_error = 1;
                    continue;
                }
            } else {
                int status = search_file(filename, pattern, pattern_len,
                                         prefix_filename, &buf);
                if (status == 2) {
                    has_error = 1;
                } else if (status == 0 && exit_status == 1) {
                    exit_status = 0;
                }
            }
        }
    }

    free_line_buffer(&buf);

    return has_error ? 2 : exit_status;
}
