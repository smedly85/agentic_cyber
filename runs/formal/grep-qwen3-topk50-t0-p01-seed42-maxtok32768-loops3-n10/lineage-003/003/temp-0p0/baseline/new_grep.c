#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

#define INITIAL_LINE_CAPACITY 256

typedef struct {
    char *data;
    size_t len;
    size_t capacity;
} LineBuffer;

static bool line_buffer_init(LineBuffer *buf) {
    buf->capacity = INITIAL_LINE_CAPACITY;
    buf->data = malloc(buf->capacity);
    if (!buf->data) return false;
    buf->len = 0;
    return true;
}

static void line_buffer_free(LineBuffer *buf) {
    free(buf->data);
}

static bool line_buffer_grow(LineBuffer *buf, size_t needed) {
    size_t new_cap = buf->capacity;
    while (new_cap < buf->len + needed) {
        if (new_cap > SIZE_MAX / 2) return false;
        new_cap *= 2;
    }
    char *new_data = realloc(buf->data, new_cap);
    if (!new_data) return false;
    buf->data = new_data;
    buf->capacity = new_cap;
    return true;
}

static bool read_line(LineBuffer *buf, FILE *fp) {
    size_t saved_len = buf->len;
    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (c == '\n') break;
        if ((size_t)(buf->len + 1) > buf->capacity) {
            if (!line_buffer_grow(buf, 1)) return false;
        }
        buf->data[buf->len++] = (char)c;
    }
    if (ferror(fp)) return false;
    if (buf->len == saved_len && c == EOF) return false;
    return true;
}

static bool match_pattern(const char *line, size_t line_len,
                          const char *pattern, size_t pattern_len) {
    if (pattern_len == 0) return true;
    if (pattern_len > line_len) return false;
    
    for (size_t i = 0; i <= line_len - pattern_len; i++) {
        bool found = true;
        for (size_t j = 0; j < pattern_len; j++) {
            if (line[i + j] != pattern[j]) {
                found = false;
                break;
            }
        }
        if (found) return true;
    }
    return false;
}

static void write_line_with_prefix(const char *filename, const char *data,
                                   size_t len) {
    fwrite(filename, 1, strlen(filename), stdout);
    fputc(':', stdout);
    fwrite(data, 1, len, stdout);
    fputc('\n', stdout);
}

static void write_line(const char *data, size_t len) {
    fwrite(data, 1, len, stdout);
    fputc('\n', stdout);
}

static bool is_directory(const char *path) {
    struct stat st;
    if (stat(path, &st) != 0) return false;
    return S_ISDIR(st.st_mode);
}

static int search_file(const char *filename, const char *pattern,
                       size_t pattern_len, bool prefix_filenames) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }
    
    LineBuffer buf;
    if (!line_buffer_init(&buf)) {
        fprintf(stderr, "memory allocation failed\n");
        fclose(fp);
        return 2;
    }
    
    int exit_code = 1;
    
    while (read_line(&buf, fp)) {
        if (match_pattern(buf.data, buf.len, pattern, pattern_len)) {
            exit_code = 0;
            if (prefix_filenames) {
                write_line_with_prefix(filename, buf.data, buf.len);
            } else {
                write_line(buf.data, buf.len);
            }
        }
        buf.len = 0;
    }
    
    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        exit_code = 2;
    }
    
    line_buffer_free(&buf);
    fclose(fp);
    return exit_code;
}

static void print_usage(void) {
    fprintf(stderr, "usage: new_grep [-H|-h] [--with-filename|--no-filename] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_usage();
        return 2;
    }
    
    int first_file_pos = 1;
    bool has_stdin = true;
    bool options_done = false;
    int filename_flag = 0;
    
    for (int i = 1; i < argc; i++) {
        if (!options_done && strcmp(argv[i], "--") == 0) {
            options_done = true;
            first_file_pos = i + 1;
            continue;
        }
        if (!options_done && argv[i][0] == '-' && strlen(argv[i]) > 1) {
            if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
                filename_flag = 1;
                first_file_pos++;
                continue;
            }
            if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                filename_flag = -1;
                first_file_pos++;
                continue;
            }
            if (strlen(argv[i]) > 2 && argv[i][0] == '-' && argv[i][1] != '-') {
                bool processed = false;
                for (size_t j = 1; argv[i][j] != '\0'; j++) {
                    if (argv[i][j] == 'H') {
                        filename_flag = 1;
                        processed = true;
                    } else if (argv[i][j] == 'h') {
                        filename_flag = -1;
                        processed = true;
                    } else {
                        print_usage();
                        return 2;
                    }
                }
                if (processed) {
                    first_file_pos++;
                    continue;
                }
            }
            print_usage();
            return 2;
        }
    }
    
    const char *pattern = argv[first_file_pos];
    size_t pattern_len = strlen(pattern);
    int file_arg_end = first_file_pos + 1;
    
    int num_files = argc - file_arg_end;
    bool prefix_filenames = false;
    if (filename_flag == 1) {
        prefix_filenames = true;
    } else if (filename_flag == -1) {
        prefix_filenames = false;
    } else {
        prefix_filenames = (num_files >= 2);
    }
    
    if (num_files == 0) {
        has_stdin = true;
    } else {
        has_stdin = false;
    }
    
    int exit_code = 1;
    bool error_occurred = false;
    
    if (has_stdin) {
        LineBuffer buf;
        if (!line_buffer_init(&buf)) {
            fprintf(stderr, "memory allocation failed\n");
            return 2;
        }
        
        while (read_line(&buf, stdin)) {
            if (match_pattern(buf.data, buf.len, pattern, pattern_len)) {
                exit_code = 0;
                if (prefix_filenames) {
                    write_line_with_prefix("(standard input)", buf.data, buf.len);
                } else {
                    write_line(buf.data, buf.len);
                }
            }
            buf.len = 0;
        }
        
        if (ferror(stdin)) {
            fprintf(stderr, "stdin: %s\n", strerror(errno));
            exit_code = 2;
            error_occurred = true;
        }
        
        line_buffer_free(&buf);
    } else {
        for (int i = first_file_pos + 1; i < argc; i++) {
            const char *filename = argv[i];
            
            if (is_directory(filename)) {
                fprintf(stderr, "%s: is a directory\n", filename);
                exit_code = 2;
                error_occurred = true;
                continue;
            }
            
            int result = search_file(filename, pattern, pattern_len,
                                     prefix_filenames);
            if (result == 2) {
                error_occurred = true;
            }
            if (result == 0) {
                exit_code = 0;
            }
        }
    }
    
    return error_occurred ? 2 : exit_code;
}
