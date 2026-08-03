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

static int fold_char(int c) {
    if (c >= 'A' && c <= 'Z') {
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
            if (fold_char((unsigned char)line[i + j]) != fold_char((unsigned char)pattern[j])) {
                match = 0;
                break;
            }
        }
        if (match) return 1;
    }
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len, int prefix, int ignore_case);

struct queue_entry {
    char *path;
};

static void free_queue_entries(struct queue_entry *queue, size_t count) {
    for (size_t i = 0; i < count; i++) {
        free(queue[i].path);
    }
}

static int compare_strings(const void *a, const void *b) {
    const char *sa = *(const char **)a;
    const char *sb = *(const char **)b;
    return strcmp(sa, sb);
}

static int search_recursive(const char *operand, const char *pattern, size_t pat_len, 
                            int prefix, int ignore_case, int *status, int *matched_any) {
    DIR *dir = opendir(operand);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", operand, strerror(errno));
        return 2;
    }

    struct dirent *entry;
    size_t capacity = 64;
    char **names = malloc(capacity * sizeof(char *));
    size_t count = 0;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;
        
        if (count >= capacity) {
            capacity *= 2;
            names = realloc(names, capacity * sizeof(char *));
        }
        names[count] = strdup(entry->d_name);
        count++;
    }
    closedir(dir);

    qsort(names, count, sizeof(char *), compare_strings);

    dir = opendir(operand);
    if (!dir) {
        free_queue_entries((struct queue_entry *)names, count);
        free(names);
        return 2;
    }

    size_t op_len = strlen(operand);
    
    for (size_t i = 0; i < count; i++) {
        char *name = names[i];
        
        char *full_path;
        if (op_len > 0 && operand[op_len - 1] == '/') {
            full_path = malloc(op_len + strlen(name) + 1);
            strcpy(full_path, operand);
            strcat(full_path, name);
        } else {
            full_path = malloc(op_len + 1 + strlen(name) + 1);
            strcpy(full_path, operand);
            full_path[op_len] = '/';
            strcpy(full_path + op_len + 1, name);
        }

        struct stat st;
        if (lstat(full_path, &st) != 0) {
            fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
            free(full_path);
            (*status) = 2;
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int result = search_file(full_path, pattern, pat_len, prefix, ignore_case);
            if (result == 0) {
                *matched_any = 1;
            } else if (result == 2 && (*status) != 2) {
                (*status) = 2;
            }
        } else if (S_ISDIR(st.st_mode)) {
            int result = search_recursive(full_path, pattern, pat_len, prefix, ignore_case, status, matched_any);
            if (result == 2 && (*status) != 2) {
                (*status) = 2;
            }
        }

        free(full_path);
    }

    for (size_t i = 0; i < count; i++) {
        free(names[i]);
    }
    free(names);

    return (*matched_any) ? 0 : ((*status) == 2 ? 2 : 1);
}

static int search_file(const char *filename, const char *pattern, size_t pat_len, int prefix, int ignore_case) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "%s: Is a directory\n", filename);
        fclose(fp);
        return 2;
    }

    int matched = 0;
    size_t len;
    char *line;

    while ((line = read_line(fp, &len)) != NULL) {
        if (matches(line, len, pattern, pat_len, ignore_case)) {
            if (prefix) {
                fprintf(stdout, "%s:", filename);
            }
            fwrite(line, 1, len, stdout);
            fputc('\n', stdout);
            matched = 1;
        }
        free(line);
    }

    int result = matched ? 0 : 1;

    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        result = 2;
    }

    fclose(fp);
    return result;
}

static void usage(void) {
    fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep -H PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep --with-filename PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep -h PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep --no-filename PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep -r PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep --recursive PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep -i PATTERN [FILE...]\n");
    fprintf(stderr, "       new_grep --ignore-case PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int seen_dashdash = 0;
    int prefix_mode = -1;
    int recursive = 0;
    int ignore_case = 0;

    for (int i = 1; i < argc; i++) {
        if (!seen_dashdash && argv[i][0] == '-' && strcmp(argv[i], "-") != 0 && strcmp(argv[i], "--") != 0) {
            if (strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "-H") == 0) {
                prefix_mode = 1;
            } else if (strcmp(argv[i], "--no-filename") == 0 || strcmp(argv[i], "-h") == 0) {
                prefix_mode = 0;
            } else if (strcmp(argv[i], "--recursive") == 0 || strcmp(argv[i], "-r") == 0) {
                recursive = 1;
            } else if (strcmp(argv[i], "--ignore-case") == 0 || strcmp(argv[i], "-i") == 0) {
                ignore_case = 1;
            } else if (argv[i][1] == 'H' && argv[i][2] == '\0') {
                prefix_mode = 1;
            } else if (argv[i][1] == 'h' && argv[i][2] == '\0') {
                prefix_mode = 0;
            } else if (argv[i][1] == 'r' && argv[i][2] == '\0') {
                recursive = 1;
            } else if (argv[i][1] == 'i' && argv[i][2] == '\0') {
                ignore_case = 1;
            } else if (argv[i][1] == 'H' || argv[i][1] == 'h' || argv[i][1] == 'r' || argv[i][1] == 'i') {
                for (int j = 1; argv[i][j]; j++) {
                    if (argv[i][j] == 'H') {
                        prefix_mode = 1;
                    } else if (argv[i][j] == 'h') {
                        prefix_mode = 0;
                    } else if (argv[i][j] == 'r') {
                        recursive = 1;
                    } else if (argv[i][j] == 'i') {
                        ignore_case = 1;
                    } else {
                        usage();
                        return 2;
                    }
                }
            } else {
                usage();
                return 2;
            }
        }
        if (strcmp(argv[i], "--") == 0) {
            seen_dashdash = 1;
        }
    }

    int pattern_idx = -1;

    for (int i = 1; i < argc; i++) {
        if (!seen_dashdash && argv[i][0] == '-' && strcmp(argv[i], "-") != 0 && strcmp(argv[i], "--") != 0) {
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            seen_dashdash = 1;
            continue;
        }
        pattern_idx = i;
        break;
    }

    if (pattern_idx < 0) {
        usage();
        return 2;
    }

    const char *pattern = argv[pattern_idx];
    size_t pat_len = strlen(pattern);

    int file_count = 0;
    int has_dir_operand = 0;
    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) continue;
        file_count++;
        
        struct stat st;
        if (stat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
            has_dir_operand = 1;
        }
    }
    
    int prefix = (prefix_mode == 1) ? 1 : ((prefix_mode == 0) ? 0 : 
                (file_count > 1 || (recursive && has_dir_operand)));

    if (file_count == 0) {
        int matched = 0;
        size_t len;
        char *line;

        while ((line = read_line(stdin, &len)) != NULL) {
            if (matches(line, len, pattern, pat_len, ignore_case)) {
                if (prefix) {
                    fprintf(stdout, "(standard input):");
                }
                fwrite(line, 1, len, stdout);
                fputc('\n', stdout);
                matched = 1;
            }
            free(line);
        }

        return matched ? 0 : 1;
    }

    int status = 0;
    int matched_any = 0;

    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) continue;
        const char *filename = argv[i];
        
        struct stat st;
        if (stat(filename, &st) != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            status = 2;
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int result = search_file(filename, pattern, pat_len, prefix, ignore_case);
            if (result == 0) matched_any = 1;
            else if (result == 2 && status != 2) status = 2;
        } else if (S_ISDIR(st.st_mode)) {
            if (recursive) {
                int result = search_recursive(filename, pattern, pat_len, prefix, ignore_case, &status, &matched_any);
                if (result == 2 && status != 2) status = 2;
            } else {
                fprintf(stderr, "%s: Is a directory\n", filename);
                status = 2;
            }
        }
    }

    return (matched_any || status == 2) ? status : 1;
}
