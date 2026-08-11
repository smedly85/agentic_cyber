#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
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
                           const char *line, size_t line_len, bool ignore_case) {
    if (pattern_len == 0) return true;
    if (pattern_len > line_len) return false;
    
    for (size_t i = 0; i <= line_len - pattern_len; i++) {
        bool found = true;
        for (size_t j = 0; j < pattern_len; j++) {
            char c_line = line[i + j];
            char c_pattern = pattern[j];
            if (ignore_case) {
                if ((unsigned char)c_line >= 0x41 && (unsigned char)c_line <= 0x5A) {
                    c_line = (char)((unsigned char)c_line | 0x20);
                }
                if ((unsigned char)c_pattern >= 0x41 && (unsigned char)c_pattern <= 0x5A) {
                    c_pattern = (char)((unsigned char)c_pattern | 0x20);
                }
            }
            if (c_line != c_pattern) {
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

static int search_file(const char *filename, const char *pattern, size_t pattern_len,
                        bool prefix, bool *matched, bool ignore_case) {
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
        if (match_pattern(pattern, pattern_len, buf.data, buf.len, ignore_case)) {
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

static int search_stdin(const char *pattern, size_t pattern_len, bool force_filename, bool ignore_case) {
    LineBuffer buf;
    if (!line_buffer_init(&buf)) {
        fprintf(stderr, "memory allocation failed\n");
        return 2;
    }
    
    int status = 1;
    
    while (read_line(&buf, stdin)) {
        if (match_pattern(pattern, pattern_len, buf.data, buf.len, ignore_case)) {
            status = 0;
            if (force_filename) {
                fprintf(stdout, "(standard input):%s\n", buf.data);
            } else {
                write_line(buf.data, buf.len);
            }
        }
    }
    
    line_buffer_free(&buf);
    return status;
}

static void print_usage(void) {
    fprintf(stderr, "usage: new_grep [-H|-h] [-r] [-i] PATTERN [FILE...]\n");
}

typedef struct {
    char **entries;
    size_t count;
    size_t capacity;
} EntryList;

static bool entry_list_init(EntryList *list) {
    list->capacity = 16;
    list->entries = malloc(list->capacity * sizeof(char *));
    if (!list->entries) return false;
    list->count = 0;
    return true;
}

static void entry_list_free(EntryList *list) {
    for (size_t i = 0; i < list->count; i++) {
        free(list->entries[i]);
    }
    free(list->entries);
}

static bool entry_list_add(EntryList *list, const char *name) {
    if (list->count >= list->capacity) {
        size_t new_cap = list->capacity * 2;
        if (new_cap > SIZE_MAX / sizeof(char *)) return false;
        char **new_entries = realloc(list->entries, new_cap * sizeof(char *));
        if (!new_entries) return false;
        list->entries = new_entries;
        list->capacity = new_cap;
    }
    list->entries[list->count] = strdup(name);
    if (!list->entries[list->count]) return false;
    list->count++;
    return true;
}

static int compare_names(const void *a, const void *b) {
    const char *na = *(const char **)a;
    const char *nb = *(const char **)b;
    return strcmp(na, nb);
}

static void sort_entries(EntryList *list) {
    qsort(list->entries, list->count, sizeof(char *), compare_names);
}

static int main_recursive_search(const char *dirname, const char *pattern, size_t pattern_len,
                                  bool prefix, bool *matched, bool *error_occurred, bool ignore_case) {
    DIR *dir = opendir(dirname);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirname, strerror(errno));
        return 2;
    }

    EntryList entries;
    if (!entry_list_init(&entries)) {
        fprintf(stderr, "memory allocation failed\n");
        closedir(dir);
        return 2;
    }

    struct dirent *de;
    while ((de = readdir(dir)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) continue;
        if (!entry_list_add(&entries, de->d_name)) {
            fprintf(stderr, "memory allocation failed\n");
            entry_list_free(&entries);
            closedir(dir);
            return 2;
        }
    }
    closedir(dir);

    sort_entries(&entries);

    char *dirpath = malloc(strlen(dirname) + 1);
    if (!dirpath) {
        fprintf(stderr, "memory allocation failed\n");
        entry_list_free(&entries);
        return 2;
    }
    strcpy(dirpath, dirname);

    size_t dir_len = strlen(dirpath);
    while (dir_len > 0 && dirpath[dir_len - 1] == '/') {
        dirpath[--dir_len] = '\0';
    }

    int final_status = 1;

    for (size_t i = 0; i < entries.count; i++) {
        char *full_path = malloc(strlen(dirpath) + 1 + strlen(entries.entries[i]) + 1);
        if (!full_path) {
            fprintf(stderr, "memory allocation failed\n");
            entry_list_free(&entries);
            free(dirpath);
            return 2;
        }
        sprintf(full_path, "%s/%s", dirpath, entries.entries[i]);

        struct stat st_entry;
        if (lstat(full_path, &st_entry) != 0) {
            fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
            free(full_path);
            *error_occurred = true;
            final_status = 2;
            continue;
        }

        if (S_ISLNK(st_entry.st_mode)) {
            free(full_path);
            continue;
        }

        if (S_ISREG(st_entry.st_mode)) {
            int file_status = search_file(full_path, pattern, pattern_len, prefix, matched, ignore_case);
            free(full_path);
            if (file_status == 0) final_status = 0;
            if (file_status == 2) {
                *error_occurred = true;
                final_status = 2;
            }
        } else if (S_ISDIR(st_entry.st_mode)) {
            entry_list_free(&entries);
            free(dirpath);

            int dir_status = main_recursive_search(full_path, pattern, pattern_len, prefix, matched, error_occurred, ignore_case);
            free(full_path);
            if (dir_status == 0) final_status = 0;
            if (dir_status == 2) {
                *error_occurred = true;
                final_status = 2;
            }

            goto next_entry_loop;
        } else {
            free(full_path);
        }
    }

    entry_list_free(&entries);
    free(dirpath);

next_entry_loop:
    return final_status;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_usage();
        return 2;
    }
    
    int pattern_arg = 1;
    bool has_stdin_search = true;
    int filename_flag = 0;
    bool recursive = false;
    bool ignore_case = false;
    
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            pattern_arg = i + 1;
            break;
        }
        if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
                filename_flag = 1;
                continue;
            }
            if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                filename_flag = -1;
                continue;
            }
            if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
                recursive = true;
                continue;
            }
            if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--ignore-case") == 0) {
                ignore_case = true;
                continue;
            }
            bool combined_short = false;
            for (size_t j = 1; j < strlen(argv[i]); j++) {
                if (argv[i][j] == 'H') {
                    filename_flag = 1;
                    combined_short = true;
                } else if (argv[i][j] == 'h') {
                    filename_flag = -1;
                    combined_short = true;
                } else if (argv[i][j] == 'r') {
                    recursive = true;
                    combined_short = true;
                } else if (argv[i][j] == 'i') {
                    ignore_case = true;
                    combined_short = true;
                } else {
                    print_usage();
                    return 2;
                }
            }
            if (combined_short) continue;
            print_usage();
            return 2;
        }
        pattern_arg = i;
        break;
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
    bool prefix = false;
    if (filename_flag == 1) {
        prefix = true;
    } else if (filename_flag == -1) {
        prefix = false;
    } else {
        bool has_dir = false;
        for (int i = file_arg_start; i < argc; i++) {
            struct stat st;
            if (lstat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
                has_dir = true;
                break;
            }
        }
        prefix = (num_files >= 2 || (recursive && has_dir));
    }
    
    if (num_files == 0) {
        has_stdin_search = true;
    } else {
        has_stdin_search = false;
    }
    
    int final_status = 1;
    bool matched = false;
    bool error_occurred = false;
    
    if (has_stdin_search) {
        int status = search_stdin(pattern, pattern_len, prefix, ignore_case);
        if (status == 0) matched = true;
        if (status == 2) error_occurred = true;
        final_status = status;
    }
    
    for (int i = file_arg_start; i < argc; i++) {
        const char *filename = argv[i];
        
        struct stat st;
        if (lstat(filename, &st) != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            error_occurred = true;
            continue;
        }
        
        if (S_ISLNK(st.st_mode)) {
            int status = search_file(filename, pattern, pattern_len, prefix, &matched, ignore_case);
            if (status == 0) matched = true;
            if (status == 2) error_occurred = true;
            if (final_status != 2 && status == 2) final_status = 2;
            continue;
        }
        
        if (S_ISDIR(st.st_mode)) {
            if (!recursive) {
                fprintf(stderr, "%s: is a directory\n", filename);
                error_occurred = true;
                continue;
            }
            
            DIR *dir = opendir(filename);
            if (!dir) {
                fprintf(stderr, "%s: %s\n", filename, strerror(errno));
                error_occurred = true;
                final_status = 2;
                continue;
            }
            
            EntryList entries;
            if (!entry_list_init(&entries)) {
                fprintf(stderr, "memory allocation failed\n");
                closedir(dir);
                error_occurred = true;
                final_status = 2;
                continue;
            }
            
            struct dirent *de;
            while ((de = readdir(dir)) != NULL) {
                if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) continue;
                if (!entry_list_add(&entries, de->d_name)) {
                    fprintf(stderr, "memory allocation failed\n");
                    entry_list_free(&entries);
                    closedir(dir);
                    error_occurred = true;
                    final_status = 2;
                    goto next_file;
                }
            }
            closedir(dir);
            
            sort_entries(&entries);
            
            char *dirpath = malloc(strlen(filename) + 1);
            if (!dirpath) {
                fprintf(stderr, "memory allocation failed\n");
                entry_list_free(&entries);
                error_occurred = true;
                final_status = 2;
                goto next_file;
            }
            strcpy(dirpath, filename);
            
            size_t dir_len = strlen(dirpath);
            while (dir_len > 0 && dirpath[dir_len - 1] == '/') {
                dirpath[--dir_len] = '\0';
            }
            
            for (size_t j = 0; j < entries.count; j++) {
                char *full_path = malloc(strlen(dirpath) + 1 + strlen(entries.entries[j]) + 1);
                if (!full_path) {
                    fprintf(stderr, "memory allocation failed\n");
                    entry_list_free(&entries);
                    free(dirpath);
                    error_occurred = true;
                    final_status = 2;
                    goto next_file;
                }
                sprintf(full_path, "%s/%s", dirpath, entries.entries[j]);
                
                struct stat st_entry;
                if (lstat(full_path, &st_entry) != 0) {
                    fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
                    free(full_path);
                    error_occurred = true;
                    final_status = 2;
                    continue;
                }
                
                if (S_ISLNK(st_entry.st_mode)) {
                    free(full_path);
                    continue;
                }
                
                if (S_ISREG(st_entry.st_mode)) {
                    int file_status = search_file(full_path, pattern, pattern_len, prefix, &matched, ignore_case);
                    free(full_path);
                    if (file_status == 0) final_status = 0;
                    if (file_status == 2) {
                        error_occurred = true;
                        final_status = 2;
                    }
                } else if (S_ISDIR(st_entry.st_mode)) {
                    entry_list_free(&entries);
                    free(dirpath);
                    
                    int dir_status = main_recursive_search(full_path, pattern, pattern_len, prefix, &matched, &error_occurred, ignore_case);
                    free(full_path);
                    if (dir_status == 0) final_status = 0;
                    if (dir_status == 2) {
                        error_occurred = true;
                        final_status = 2;
                    }
                    
                    goto next_file_entry_loop;
                } else {
                    free(full_path);
                }
            }
            
            entry_list_free(&entries);
            free(dirpath);
            
        next_file_entry_loop:
            continue;
            
        next_file:
            continue;
        }
        
        int status = search_file(filename, pattern, pattern_len, prefix, &matched, ignore_case);
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
