#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#include <sys/stat.h>

#define INITIAL_LINE_CAPACITY 256

typedef struct {
    char *data;
    size_t len;
    size_t capacity;
} LineBuffer;

static bool line_buffer_init(LineBuffer *buf) {
    buf->data = malloc(INITIAL_LINE_CAPACITY);
    if (!buf->data) return false;
    buf->len = 0;
    buf->capacity = INITIAL_LINE_CAPACITY;
    return true;
}

static void line_buffer_free(LineBuffer *buf) {
    free(buf->data);
}

static bool line_buffer_grow(LineBuffer *buf, size_t needed) {
    size_t new_cap = buf->capacity;
    while (new_cap - buf->len < needed) {
        if (new_cap > SIZE_MAX / 2) return false;
        new_cap *= 2;
    }
    char *new_data = realloc(buf->data, new_cap);
    if (!new_data) return false;
    buf->data = new_data;
    buf->capacity = new_cap;
    return true;
}

static int read_line(LineBuffer *buf, FILE *fp) {
    buf->len = 0;
    
    for (;;) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (ferror(fp)) return -1;
            if (buf->len == 0) return 0;
            break;
        }
        
        if (c == '\n') break;
        
        if (buf->len + 1 >= buf->capacity) {
            if (!line_buffer_grow(buf, 1)) return -2;
        }
        buf->data[buf->len++] = (char)c;
    }
    
    if (buf->len + 1 >= buf->capacity) {
        if (!line_buffer_grow(buf, 1)) return -2;
    }
    buf->data[buf->len] = '\0';
    return 1;
}

static bool pattern_matches(const char *pattern, size_t pat_len,
                            const char *line, size_t line_len) {
    if (pat_len == 0) return true;
    if (pat_len > line_len) return false;
    
    for (size_t i = 0; i <= line_len - pat_len; i++) {
        bool match = true;
        for (size_t j = 0; j < pat_len; j++) {
            if (line[i + j] != pattern[j]) {
                match = false;
                break;
            }
        }
        if (match) return true;
    }
    return false;
}

static void write_line_with_prefix(const char *filename, const char *line, size_t len) {
    fwrite(filename, 1, strlen(filename), stdout);
    fputc(':', stdout);
    fwrite(line, 1, len, stdout);
    fputc('\n', stdout);
}

static void write_line(const char *line, size_t len) {
    fwrite(line, 1, len, stdout);
    fputc('\n', stdout);
}

static bool is_directory(const char *path) {
    struct stat st;
    if (stat(path, &st) != 0) return false;
    return S_ISDIR(st.st_mode);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }
    
    int option_end = 1;
    while (option_end < argc && strcmp(argv[option_end], "--") != 0) {
        if (argv[option_end][0] == '-' && argv[option_end][1] != '\0') {
            fprintf(stderr, "Unknown option: %s\n", argv[option_end]);
            return 2;
        }
        option_end++;
    }
    
    const char *pattern = argv[1];
    size_t pat_len = strlen(pattern);
    
    int file_arg_start;
    if (strcmp(argv[option_end], "--") == 0) {
        file_arg_start = option_end + 1;
    } else {
        file_arg_start = option_end;
    }
    
    int num_files = argc - file_arg_start;
    bool multi_file = num_files > 1;
    
    LineBuffer line_buf;
    if (!line_buffer_init(&line_buf)) {
        fprintf(stderr, "Memory allocation failed\n");
        return 2;
    }
    
    int exit_code = 0;
    bool matched_at_least_once = false;
    bool error_occurred = false;
    
    if (num_files == 0) {
        for (;;) {
            int result = read_line(&line_buf, stdin);
            if (result < 0) {
                fprintf(stderr, "Error reading input\n");
                exit_code = 2;
                error_occurred = true;
                break;
            }
            if (result == 0) break;
            
            if (pattern_matches(pattern, pat_len, line_buf.data, line_buf.len)) {
                matched_at_least_once = true;
                write_line(line_buf.data, line_buf.len);
                if (ferror(stdout)) {
                    fprintf(stderr, "Write error\n");
                    exit_code = 2;
                    error_occurred = true;
                    break;
                }
            }
        }
    } else {
        for (int i = file_arg_start; i < argc; i++) {
            const char *filename = argv[i];
            
            if (is_directory(filename)) {
                fprintf(stderr, "Error: %s is a directory\n", filename);
                exit_code = 2;
                error_occurred = true;
                continue;
            }
            
            FILE *fp = fopen(filename, "r");
            if (!fp) {
                fprintf(stderr, "Error: cannot open %s: %s\n", filename, strerror(errno));
                exit_code = 2;
                error_occurred = true;
                continue;
            }
            
            for (;;) {
                int result = read_line(&line_buf, fp);
                if (result < 0) {
                    fprintf(stderr, "Error reading %s\n", filename);
                    exit_code = 2;
                    error_occurred = true;
                    break;
                }
                if (result == 0) break;
                
                if (pattern_matches(pattern, pat_len, line_buf.data, line_buf.len)) {
                    matched_at_least_once = true;
                    if (multi_file) {
                        write_line_with_prefix(filename, line_buf.data, line_buf.len);
                    } else {
                        write_line(line_buf.data, line_buf.len);
                    }
                    if (ferror(stdout)) {
                        fprintf(stderr, "Write error\n");
                        exit_code = 2;
                        error_occurred = true;
                        break;
                    }
                }
            }
            
            fclose(fp);
        }
    }
    
    line_buffer_free(&line_buf);
    
    if (!error_occurred) {
        exit_code = matched_at_least_once ? 0 : 1;
    }
    
    return exit_code;
}
