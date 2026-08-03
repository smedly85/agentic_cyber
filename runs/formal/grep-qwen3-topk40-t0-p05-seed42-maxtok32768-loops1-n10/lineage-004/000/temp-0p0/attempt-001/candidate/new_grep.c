#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>

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

static bool read_line(LineBuffer *buf, FILE *fp) {
    buf->len = 0;
    int c;
    
    while ((c = fgetc(fp)) != EOF) {
        if (c == '\n') break;
        if (buf->len + 1 >= buf->capacity && !line_buffer_grow(buf, 1)) return false;
        buf->data[buf->len++] = (char)c;
    }
    
    if (buf->len == 0 && c == EOF) {
        return false;
    }
    
    if (buf->len + 1 >= buf->capacity && !line_buffer_grow(buf, 1)) return false;
    buf->data[buf->len] = '\0';
    return true;
}

static bool match_pattern(const char *pattern, size_t pattern_len,
                          const char *line, size_t line_len) {
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

static void write_line_with_prefix(const char *filename, const char *line) {
    fprintf(stdout, "%s:%s\n", filename, line);
}

static void write_line(const char *line, size_t len) {
    fwrite(line, 1, len, stdout);
    fputc('\n', stdout);
}

static bool is_regular_file(const char *path) {
    struct stat st;
    if (lstat(path, &st) != 0) return false;
    if (S_ISLNK(st.st_mode)) {
        if (stat(path, &st) != 0) return false;
    }
    return S_ISREG(st.st_mode);
}

static bool is_directory(const char *path) {
    struct stat st;
    if (lstat(path, &st) != 0) return false;
    if (S_ISLNK(st.st_mode)) {
        if (stat(path, &st) != 0) return false;
    }
    return S_ISDIR(st.st_mode);
}

static int search_file(const char *filename, const char *pattern, size_t pattern_len,
                       bool prefix, bool *matched) {
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
    
    int status = 1;
    
    while (read_line(&buf, fp)) {
        if (match_pattern(pattern, pattern_len, buf.data, buf.len)) {
            *matched = true;
            status = 0;
            if (prefix) {
                write_line_with_prefix(filename, buf.data);
            } else {
                write_line(buf.data, buf.len);
            }
        }
    }
    
    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        status = 2;
    }
    
    line_buffer_free(&buf);
    fclose(fp);
    return status;
}

static int search_stdin(const char *pattern, size_t pattern_len) {
    LineBuffer buf;
    if (!line_buffer_init(&buf)) {
        fprintf(stderr, "memory allocation failed\n");
        return 2;
    }
    
    int status = 1;
    
    while (read_line(&buf, stdin)) {
        if (match_pattern(pattern, pattern_len, buf.data, buf.len)) {
            status = 0;
            write_line(buf.data, buf.len);
        }
    }
    
    line_buffer_free(&buf);
    return status;
}

static void print_usage(void) {
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_usage();
        return 2;
    }
    
    int pattern_arg = 1;
    bool has_stdin_search = true;
    
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            pattern_arg = i + 1;
            break;
        }
        if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            print_usage();
            return 2;
        }
    }
    
    const char *pattern = argv[pattern_arg];
    size_t pattern_len = strlen(pattern);
    
    int file_arg_start = pattern_arg + 1;
    
    for (int i = file_arg_start; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            file_arg_start = i + 1;
            has_stdin_search = false;
            break;
        }
        if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            print_usage();
            return 2;
        }
    }
    
    int num_files = argc - file_arg_start;
    bool prefix = (num_files >= 2);
    
    if (num_files == 0) {
        has_stdin_search = true;
    } else {
        has_stdin_search = false;
    }
    
    int final_status = 1;
    bool matched = false;
    bool error_occurred = false;
    
    if (has_stdin_search) {
        int status = search_stdin(pattern, pattern_len);
        if (status == 0) matched = true;
        if (status == 2) error_occurred = true;
        final_status = status;
    }
    
    for (int i = file_arg_start; i < argc; i++) {
        const char *filename = argv[i];
        
        if (is_directory(filename)) {
            fprintf(stderr, "%s: is a directory\n", filename);
            error_occurred = true;
            continue;
        }
        
        if (!is_regular_file(filename)) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            error_occurred = true;
            continue;
        }
        
        int status = search_file(filename, pattern, pattern_len, prefix, &matched);
        if (status == 0) matched = true;
        if (status == 2) error_occurred = true;
        
        if (final_status != 2 && status == 2) {
            final_status = 2;
        }
    }
    
    if (error_occurred) return 2;
    if (matched) return 0;
    return 1;
}
