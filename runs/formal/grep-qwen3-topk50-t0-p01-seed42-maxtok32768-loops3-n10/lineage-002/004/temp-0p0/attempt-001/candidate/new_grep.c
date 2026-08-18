#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <limits.h>
#include <dirent.h>

#define CHUNK_SIZE 4096

static char *read_line(FILE *fp, size_t *len_out) {
    size_t capacity = CHUNK_SIZE;
    size_t len = 0;
    char *buf = malloc(capacity);
    if (!buf) return NULL;

    while (1) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (ferror(fp)) {
                free(buf);
                return NULL;
            }
            if (len == 0) {
                free(buf);
                return NULL;
            }
            break;
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
            if (fold_char((unsigned char)line[i + j]) != fold_char((unsigned char)pattern[j])) {
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

static int compare_strings(const void *a, const void *b) {
    return strcmp(*(const char **)a, *(const char **)b);
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int recursive, int top_level, int ignore_case);

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

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int recursive, int top_level, int ignore_case) {
    struct stat st;
    int (*stat_fn)(const char *, struct stat *) = top_level ? stat : lstat;
    if (stat_fn(filename, &st) != 0) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    if (S_ISLNK(st.st_mode)) {
        if (!top_level) {
            return 0;
        }
        if (lstat(filename, &st) != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            return 2;
        }
    }

    if (S_ISDIR(st.st_mode)) {
        if (!recursive) {
            fprintf(stderr, "%s: Is a directory\n", filename);
            return 2;
        }
        DIR *dir = opendir(filename);
        if (!dir) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            return 2;
        }

        size_t entry_count = 0;
        size_t capacity = 64;
        char **entries = malloc(capacity * sizeof(char *));
        if (!entries) {
            closedir(dir);
            return 2;
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
                    return 2;
                }
                entries = new_entries;
                capacity = new_cap;
            }
            entries[entry_count] = strdup(de->d_name);
            if (!entries[entry_count]) {
                for (size_t i = 0; i < entry_count; i++) free(entries[i]);
                free(entries);
                closedir(dir);
                return 2;
            }
            entry_count++;
        }

        qsort(entries, entry_count, sizeof(char *), compare_strings);

        int result = 0;
        for (size_t i = 0; i < entry_count; i++) {
            char *entry_name = entries[i];
            size_t base_len = strlen(filename);
            while (base_len > 0 && filename[base_len - 1] == '/') base_len--;
            
            size_t entry_len = strlen(entry_name);
            size_t full_len = base_len + 1 + entry_len;
            char *full_path = malloc(full_len + 1);
            if (!full_path) {
                result = 2;
                for (size_t j = i; j < entry_count; j++) free(entries[j]);
                free(entries);
                closedir(dir);
                return 2;
            }
            memcpy(full_path, filename, base_len);
            full_path[base_len] = '/';
            memcpy(full_path + base_len + 1, entry_name, entry_len);
            full_path[full_len] = '\0';

            struct stat est;
            if (lstat(full_path, &est) == 0 && S_ISLNK(est.st_mode)) {
                free(full_path);
                continue;
            }

            int res = search_file(full_path, pattern, pat_len, prefix_filename, recursive, 0, ignore_case);
            if (res > result) result = res;

            free(full_path);
        }

        for (size_t i = 0; i < entry_count; i++) free(entries[i]);
        free(entries);
        closedir(dir);
        return result;
    }

    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    int matched = 0;
    int error_occurred = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && ferror(fp)) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            error_occurred = 2;
            break;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len, ignore_case)) {
            matched = 1;
            if (prefix_filename) {
                if (write_line_with_prefix(filename, line, line_len) < 0) {
                    error_occurred = 2;
                    free(line);
                    break;
                }
            } else {
                if (write_line(line, line_len) < 0) {
                    error_occurred = 2;
                    free(line);
                    break;
                }
            }
        }
        free(line);
    }

    fclose(fp);
    return matched ? 1 : error_occurred;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int terminator_found = 0;
    int force_filename = -1;
    int recursive = 0;
    int ignore_case = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            terminator_found = 1;
            continue;
        }
        if (!terminator_found && argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            if (strcmp(argv[i], "--with-filename") == 0) {
                force_filename = 1;
                continue;
            }
            if (strcmp(argv[i], "--no-filename") == 0) {
                force_filename = 0;
                continue;
            }
            if (strcmp(argv[i], "--recursive") == 0) {
                recursive = 1;
                continue;
            }
            if (strcmp(argv[i], "--ignore-case") == 0) {
                ignore_case = 1;
                continue;
            }
            for (int j = 1; argv[i][j]; j++) {
                if (argv[i][j] == 'H') {
                    force_filename = 1;
                } else if (argv[i][j] == 'h') {
                    force_filename = 0;
                } else if (argv[i][j] == 'r') {
                    recursive = 1;
                } else if (argv[i][j] == 'i') {
                    ignore_case = 1;
                } else {
                    usage();
                    return 2;
                }
            }
            continue;
            usage();
            return 2;
        }
    }

    int pattern_idx = terminator_found ? 2 : 1;
    while (pattern_idx < argc && argv[pattern_idx][0] == '-' && strcmp(argv[pattern_idx], "-") != 0) {
        if (strcmp(argv[pattern_idx], "--with-filename") == 0 || strcmp(argv[pattern_idx], "--no-filename") == 0 ||
            strcmp(argv[pattern_idx], "--recursive") == 0 || strcmp(argv[pattern_idx], "--ignore-case") == 0) {
            pattern_idx++;
            continue;
        }
        int all_opts = 1;
        for (int j = 1; argv[pattern_idx][j]; j++) {
            if (argv[pattern_idx][j] != 'H' && argv[pattern_idx][j] != 'h' && argv[pattern_idx][j] != 'r' &&
                argv[pattern_idx][j] != 'i') {
                all_opts = 0;
                break;
            }
        }
        if (all_opts) {
            pattern_idx++;
            continue;
        }
        break;
    }
    const char *pattern = argv[pattern_idx];
    size_t pat_len = strlen(pattern);

    int num_files = 0;
    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) continue;
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            if (strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0 ||
                strcmp(argv[i], "--recursive") == 0 || strcmp(argv[i], "--ignore-case") == 0) continue;
            int all_opts = 1;
            for (int j = 1; argv[i][j]; j++) {
                if (argv[i][j] != 'H' && argv[i][j] != 'h' && argv[i][j] != 'r' && argv[i][j] != 'i') {
                    all_opts = 0;
                    break;
                }
            }
            if (all_opts) continue;
        }
        num_files++;
    }

    int has_directory = 0;
    for (int i = pattern_idx + 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) continue;
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            if (strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0 ||
                strcmp(argv[i], "--recursive") == 0 || strcmp(argv[i], "--ignore-case") == 0) continue;
            int all_opts = 1;
            for (int j = 1; argv[i][j]; j++) {
                if (argv[i][j] != 'H' && argv[i][j] != 'h' && argv[i][j] != 'r' && argv[i][j] != 'i') {
                    all_opts = 0;
                    break;
                }
            }
            if (all_opts) continue;
        }
        struct stat st;
        if (lstat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
            has_directory = 1;
            break;
        }
    }

    int prefix_filename = (force_filename == 1) || ((force_filename != 0) && (num_files >= 2));
    if (!prefix_filename && force_filename != 0 && recursive && has_directory) {
        prefix_filename = 1;
    }

    int matched_at_least_once = 0;
    int error_occurred = 0;

    if (num_files == 0) {
        while (1) {
            size_t line_len;
            char *line = read_line(stdin, &line_len);
            if (!line && ferror(stdin)) {
                fprintf(stderr, "(standard input): %s\n", strerror(errno));
                error_occurred = 2;
                break;
            }
            if (!line) break;

            if (matches(line, line_len, pattern, pat_len, ignore_case)) {
                matched_at_least_once = 1;
                if (prefix_filename) {
                    if (write_line_with_prefix("(standard input)", line, line_len) < 0) {
                        error_occurred = 2;
                        free(line);
                        break;
                    }
                } else {
                    if (write_line(line, line_len) < 0) {
                        error_occurred = 2;
                        free(line);
                        break;
                    }
                }
            }
            free(line);
        }
    } else {
        for (int i = pattern_idx + 1; i < argc; i++) {
            if (strcmp(argv[i], "--") == 0) {
                continue;
            }
            if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
                if (strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0 ||
                    strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "-h") == 0 ||
                    strcmp(argv[i], "--recursive") == 0 || strcmp(argv[i], "--ignore-case") == 0) {
                    continue;
                }
                if (argv[i][1] == 'r' || argv[i][1] == 'H' || argv[i][1] == 'h' || argv[i][1] == 'i') {
                    int skip = 1;
                    for (int j = 1; argv[i][j]; j++) {
                        if (argv[i][j] != 'r' && argv[i][j] != 'H' && argv[i][j] != 'h' && argv[i][j] != 'i') {
                            skip = 0;
                            break;
                        }
                    }
                    if (skip) continue;
                }
            }
            int result = search_file(argv[i], pattern, pat_len, prefix_filename, recursive, 1, ignore_case);
            if (result == 2) {
                error_occurred = 2;
            } else if (result == 1) {
                matched_at_least_once = 1;
            }
        }
    }

    if (error_occurred) return 2;
    return matched_at_least_once ? 0 : 1;
}
