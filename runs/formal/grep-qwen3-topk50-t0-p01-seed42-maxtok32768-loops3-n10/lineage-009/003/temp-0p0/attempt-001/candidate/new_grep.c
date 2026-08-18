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

    if (len >= capacity - 1) {
        char *new_buf = realloc(buf, len + 1);
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

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int *match_found, int *error_occurred);

static int is_symlink(const char *path) {
    struct stat st;
    if (lstat(path, &st) != 0) return 0;
    return S_ISLNK(st.st_mode);
}

static int is_directory(const char *path) {
    struct stat st;
    if (stat(path, &st) != 0) return 0;
    return S_ISDIR(st.st_mode);
}

static int search_file_recursive(const char *operand, const char *rel_path,
                                 const char *pattern, size_t pat_len,
                                 int prefix_filename, int *match_found, int *error_occurred);

static int process_entry(const char *operand, const char *dir_path, const char *entry_name,
                         const char *pattern, size_t pat_len,
                         int prefix_filename, int *match_found, int *error_occurred) {
    size_t dir_len = strlen(dir_path);
    size_t entry_len = strlen(entry_name);
    char *full_path = malloc(dir_len + 1 + entry_len + 1);
    if (!full_path) return 0;
    
    memcpy(full_path, dir_path, dir_len);
    full_path[dir_len] = '/';
    memcpy(full_path + dir_len + 1, entry_name, entry_len);
    full_path[dir_len + 1 + entry_len] = '\0';
    
    int result = search_file_recursive(operand, full_path, pattern, pat_len,
                                       prefix_filename, match_found, error_occurred);
    
    free(full_path);
    return result;
}

static int search_file_recursive(const char *operand, const char *rel_path,
                                 const char *pattern, size_t pat_len,
                                 int prefix_filename, int *match_found, int *error_occurred) {
    if (is_symlink(rel_path)) {
        return 1;
    }
    
    struct stat st;
    if (stat(rel_path, &st) != 0) {
        fprintf(stderr, "%s: %s\n", rel_path, strerror(errno));
        *error_occurred = 1;
        return 0;
    }
    
    if (S_ISDIR(st.st_mode)) {
        DIR *dir = opendir(rel_path);
        if (!dir) {
            fprintf(stderr, "%s: %s\n", rel_path, strerror(errno));
            *error_occurred = 1;
            return 0;
        }
        
        size_t entry_count = 0;
        size_t capacity = 64;
        char **entries = malloc(capacity * sizeof(char *));
        if (!entries) {
            closedir(dir);
            return 0;
        }
        
        struct dirent *de;
        while ((de = readdir(dir)) != NULL) {
            if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) continue;
            
            if (entry_count >= capacity) {
                size_t new_cap = capacity * 2;
                char **new_entries = realloc(entries, new_cap * sizeof(char *));
                if (!new_entries) {
                    for (size_t i = 0; i < entry_count; i++) free(entries[i]);
                    free(entries);
                    closedir(dir);
                    return 0;
                }
                entries = new_entries;
                capacity = new_cap;
            }
            
            entries[entry_count] = strdup(de->d_name);
            if (!entries[entry_count]) {
                for (size_t i = 0; i < entry_count; i++) free(entries[i]);
                free(entries);
                closedir(dir);
                return 0;
            }
            entry_count++;
        }
        
        closedir(dir);
        
        for (size_t i = 0; i < entry_count; i++) {
            for (size_t j = i + 1; j < entry_count; j++) {
                if (strcmp(entries[i], entries[j]) > 0) {
                    char *tmp = entries[i];
                    entries[i] = entries[j];
                    entries[j] = tmp;
                }
            }
        }
        
        for (size_t i = 0; i < entry_count; i++) {
            process_entry(operand, rel_path, entries[i], pattern, pat_len,
                          prefix_filename, match_found, error_occurred);
            free(entries[i]);
        }
        free(entries);
    } else if (S_ISREG(st.st_mode)) {
        search_file(rel_path, pattern, pat_len, prefix_filename, match_found, error_occurred);
    }
    
    return 1;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int *match_found, int *error_occurred) {
    FILE *fp = fopen(filename, "r");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        return 0;
    }

    size_t line_len;
    char *line;
    while ((line = read_line(fp, &line_len)) != NULL) {
        if (matches(line, line_len, pattern, pat_len)) {
            if (prefix_filename) {
                fprintf(stdout, "%s:", filename);
            }
            fwrite(line, 1, line_len, stdout);
            fputc('\n', stdout);
            *match_found = 1;
        }
        free(line);
    }

    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        fclose(fp);
        *error_occurred = 1;
        return 0;
    }

    fclose(fp);
    return 1;
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s PATTERN [FILE...]\n", prog);
    fprintf(stderr, "Options:\n");
    fprintf(stderr, "  -H, --with-filename  prefix each line with filename\n");
    fprintf(stderr, "  -h, --no-filename    do not prefix lines with filename\n");
    fprintf(stderr, "  -r, --recursive      search directories recursively\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage(argv[0]);
        return 2;
    }

    int force_filename = 0;
    int no_filename = 0;
    int recursive = 0;
    int i = 1;
    while (i < argc && argv[i][0] == '-' && strcmp(argv[i], "--") != 0) {
        if (strcmp(argv[i], "-") == 0) {
            break;
        }
        if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
            force_filename = 1;
            no_filename = 0;
            i++;
            continue;
        }
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
            no_filename = 1;
            force_filename = 0;
            i++;
            continue;
        }
        if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
            recursive = 1;
            i++;
            continue;
        }
        if (argv[i][1] != '\0' && argv[i][2] == '\0') {
            char c = argv[i][1];
            if (c == 'H') {
                force_filename = 1;
                no_filename = 0;
                i++;
                continue;
            }
            if (c == 'h') {
                no_filename = 1;
                force_filename = 0;
                i++;
                continue;
            }
            if (c == 'r') {
                recursive = 1;
                i++;
                continue;
            }
        }
        if (argv[i][1] != '\0' && argv[i][2] != '\0' && argv[i][3] == '\0') {
            char c1 = argv[i][1];
            char c2 = argv[i][2];
            int processed = 0;
            while (1) {
                if (c1 == 'H') {
                    force_filename = 1;
                    no_filename = 0;
                    processed = 1;
                } else if (c1 == 'h') {
                    no_filename = 1;
                    force_filename = 0;
                    processed = 1;
                } else if (c1 == 'r') {
                    recursive = 1;
                    processed = 1;
                } else {
                    break;
                }
                if (processed && c2 != '\0') {
                    if (c2 == 'H') {
                        force_filename = 1;
                        no_filename = 0;
                        processed = 1;
                    } else if (c2 == 'h') {
                        no_filename = 1;
                        force_filename = 0;
                        processed = 1;
                    } else if (c2 == 'r') {
                        recursive = 1;
                        processed = 1;
                    } else {
                        processed = 0;
                    }
                }
                break;
            }
            if (processed) {
                i++;
                continue;
            }
        }
        fprintf(stderr, "%s: unrecognized option '%s'\n", argv[0], argv[i]);
        return 2;
    }

    if (i < argc && strcmp(argv[i], "--") == 0) {
        i++;
    }

    const char *pattern = argv[i++];
    size_t pat_len = strlen(pattern);

    int file_count = argc - i;
    
    int has_directory = 0;
    for (int j = i; j < argc; j++) {
        if (is_directory(argv[j])) {
            has_directory = 1;
            break;
        }
    }
    
    int prefix_filename = no_filename ? 0 : 
                          (force_filename || 
                           (file_count > 1) ||
                           (recursive && has_directory));

    int match_found = 0;
    int error_occurred = 0;

    if (file_count == 0) {
        size_t line_len;
        char *line;
        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (matches(line, line_len, pattern, pat_len)) {
                if (force_filename) {
                    fprintf(stdout, "(standard input):");
                }
                fwrite(line, 1, line_len, stdout);
                fputc('\n', stdout);
                match_found = 1;
            }
            free(line);
        }
        if (ferror(stdin)) {
            fprintf(stderr, "stdin: %s\n", strerror(errno));
            error_occurred = 1;
        }
    } else {
        for (; i < argc; i++) {
            const char *filename = argv[i];
            if (recursive && is_directory(filename)) {
                size_t op_len = strlen(filename);
                while (op_len > 0 && filename[op_len - 1] == '/') op_len--;
                char *operand = malloc(op_len + 1);
                if (operand) {
                    memcpy(operand, filename, op_len);
                    operand[op_len] = '\0';
                    search_file_recursive(operand, operand, pattern, pat_len,
                                          prefix_filename, &match_found, &error_occurred);
                    free(operand);
                }
            } else {
                search_file(filename, pattern, pat_len, prefix_filename,
                            &match_found, &error_occurred);
            }
        }
    }

    if (error_occurred) return 2;
    return match_found ? 0 : 1;
}
