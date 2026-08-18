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
                buf[len] = '\0';
                *len_out = len;
                return buf;
            }
            free(buf);
            *len_out = 0;
            return NULL;
        }
        if (c == '\n') {
            buf[len] = '\0';
            *len_out = len;
            return buf;
        }
        buf[len++] = (char)c;
        if (len >= capacity) {
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
    }
}

static unsigned char fold_byte(unsigned char c) {
    if (c >= 'A' && c <= 'Z') {
        return c | 0x20;
    }
    return c;
}

static int contains_pattern(const char *line, size_t line_len,
                            const char *pattern, size_t pattern_len,
                            int ignore_case) {
    if (pattern_len == 0) return 1;
    if (pattern_len > line_len) return 0;

    if (!ignore_case) {
        for (size_t i = 0; i <= line_len - pattern_len; i++) {
            if (memcmp(line + i, pattern, pattern_len) == 0) {
                return 1;
            }
        }
        return 0;
    }

    const unsigned char *uline = (const unsigned char *)line;
    const unsigned char *upattern = (const unsigned char *)pattern;

    for (size_t i = 0; i <= line_len - pattern_len; i++) {
        int match = 1;
        for (size_t j = 0; j < pattern_len; j++) {
            if (fold_byte(uline[i + j]) != fold_byte(upattern[j])) {
                match = 0;
                break;
            }
        }
        if (match) return 1;
    }
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pattern_len,
                        int prefix_filename, int recursive, int ignore_case);

static void free_strings(char **strings, int count) {
    for (int i = 0; i < count; i++) {
        free(strings[i]);
    }
    free(strings);
}

static int compare_strings(const void *a, const void *b) {
    const char *sa = *(const char **)a;
    const char *sb = *(const char **)b;
    return strcmp(sa, sb);
}

static int search_directory(const char *dirname, const char *pattern, size_t pattern_len,
                            int prefix_filename, int ignore_case);

static int search_file(const char *filename, const char *pattern, size_t pattern_len,
                        int prefix_filename, int recursive, int ignore_case) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fclose(fp);
        if (recursive) {
            return search_directory(filename, pattern, pattern_len, prefix_filename, ignore_case);
        } else {
            fprintf(stderr, "%s: Is a directory\n", filename);
            return 2;
        }
    }

    int matched = 0;
    int error_occurred = 0;
    size_t line_len;
    char *line;

    while ((line = read_line(fp, &line_len)) != NULL) {
        if (contains_pattern(line, line_len, pattern, pattern_len, ignore_case)) {
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    error_occurred = 1;
                    break;
                }
            }
            if (line_len > 0) {
                if (fwrite(line, 1, line_len, stdout) != line_len) {
                    error_occurred = 1;
                    break;
                }
            }
            if (putc('\n', stdout) == EOF) {
                error_occurred = 1;
                break;
            }
            matched = 1;
        }
        free(line);
    }

    fclose(fp);

    if (error_occurred) {
        fprintf(stderr, "write error\n");
        return 2;
    }

    return matched ? 0 : 1;
}

static int search_directory(const char *dirname, const char *pattern, size_t pattern_len,
                            int prefix_filename, int ignore_case) {
    DIR *dir = opendir(dirname);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirname, strerror(errno));
        return 2;
    }

    struct dirent *entry;
    char **names = NULL;
    int name_count = 0;
    int capacity = 0;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (name_count >= capacity) {
            capacity = (capacity == 0) ? 64 : capacity * 2;
            char **new_names = realloc(names, capacity * sizeof(char *));
            if (!new_names) {
                free_strings(names, name_count);
                closedir(dir);
                return 2;
            }
            names = new_names;
        }
        names[name_count] = strdup(entry->d_name);
        if (!names[name_count]) {
            free_strings(names, name_count);
            closedir(dir);
            return 2;
        }
        name_count++;
    }
    closedir(dir);

    qsort(names, name_count, sizeof(char *), compare_strings);

    int status = 0;
    int matched_any = 0;

    for (int i = 0; i < name_count; i++) {
        struct stat st;
        char *full_path;
        size_t dir_len = strlen(dirname);
        if (dir_len > 0 && dirname[dir_len - 1] == '/') {
            if (asprintf(&full_path, "%s%s", dirname, names[i]) < 0) {
                status = 2;
                break;
            }
        } else {
            if (asprintf(&full_path, "%s/%s", dirname, names[i]) < 0) {
                status = 2;
                break;
            }
        }

        int link_result = lstat(full_path, &st);
        if (link_result != 0) {
            fprintf(stderr, "%s: %s\n", full_path, strerror(errno));
            free(full_path);
            status = 2;
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(full_path);
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int result = search_file(full_path, pattern, pattern_len, prefix_filename, 0, ignore_case);
            free(full_path);
            if (result == 2) status = 2;
            else if (result == 0) matched_any = 1;
        } else if (S_ISDIR(st.st_mode)) {
            int result = search_directory(full_path, pattern, pattern_len, prefix_filename, ignore_case);
            free(full_path);
            if (result == 2) status = 2;
            else if (result == 0) matched_any = 1;
        }
    }

    free_strings(names, name_count);

    return status != 0 ? 2 : (matched_any ? 0 : 1);
}

static void usage(void) {
    fprintf(stderr, "usage: new_grep [-H|-h] [-r] [-i] [--with-filename|--no-filename|--recursive|--ignore-case] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int found_double_dash_at = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            found_double_dash_at = i;
            break;
        }
    }

    int force_filename = -1;
    int recursive = 0;
    int ignore_case = 0;
    int options_end = (found_double_dash_at >= 0 ? found_double_dash_at : argc);

    for (int i = 1; i < options_end; i++) {
        if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
            force_filename = 1;
        } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
            force_filename = 0;
        } else if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
            recursive = 1;
        } else if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--ignore-case") == 0) {
            ignore_case = 1;
        } else if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            const char *p = argv[i] + 1;
            while (*p) {
                if (*p == 'H') {
                    force_filename = 1;
                } else if (*p == 'h') {
                    force_filename = 0;
                } else if (*p == 'r') {
                    recursive = 1;
                } else if (*p == 'i') {
                    ignore_case = 1;
                } else {
                    usage();
                    return 2;
                }
                p++;
            }
        } else {
            break;
        }
    }

    int pattern_index;
    if (found_double_dash_at >= 0 && found_double_dash_at + 1 < argc) {
        pattern_index = found_double_dash_at + 1;
    } else {
        for (pattern_index = 1; pattern_index < options_end; pattern_index++) {
            if (strcmp(argv[pattern_index], "-H") == 0 ||
                strcmp(argv[pattern_index], "--with-filename") == 0 ||
                strcmp(argv[pattern_index], "-h") == 0 ||
                strcmp(argv[pattern_index], "--no-filename") == 0 ||
                strcmp(argv[pattern_index], "-r") == 0 ||
                strcmp(argv[pattern_index], "--recursive") == 0 ||
                strcmp(argv[pattern_index], "-i") == 0 ||
                strcmp(argv[pattern_index], "--ignore-case") == 0) {
                continue;
            }
            if (argv[pattern_index][0] == '-' && strlen(argv[pattern_index]) > 1) {
                const char *p = argv[pattern_index] + 1;
                int all_opts = 1;
                while (*p) {
                    if (*p != 'H' && *p != 'h' && *p != 'r' && *p != 'i') {
                        all_opts = 0;
                        break;
                    }
                    p++;
                }
                if (all_opts) continue;
            }
            break;
        }
    }

    const char *pattern = argv[pattern_index];
    size_t pattern_len = strlen(pattern);

    int file_offset;
    if (found_double_dash_at >= 0) {
        file_offset = found_double_dash_at + 2;
    } else {
        file_offset = pattern_index + 1;
    }

    int file_count = argc - file_offset;

    int has_directory_operand = 0;
    for (int i = file_offset; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) continue;
        struct stat st;
        char *path_to_stat = argv[i];
        size_t path_len = strlen(argv[i]);
        if (path_len > 0 && argv[i][path_len - 1] == '/') {
            path_to_stat = strdup(argv[i]);
            path_to_stat[path_len - 1] = '\0';
        }
        if (stat(path_to_stat, &st) == 0 && S_ISDIR(st.st_mode)) {
            has_directory_operand = 1;
        }
        if (path_to_stat != argv[i]) {
            free(path_to_stat);
        }
    }

    if (force_filename == -1) {
        if (file_count >= 2) {
            force_filename = 1;
        } else if (recursive && has_directory_operand) {
            force_filename = 1;
        } else {
            force_filename = 0;
        }
    }
    int prefix_filename = force_filename;

    if (file_count == 0) {
        size_t line_len;
        char *line;
        int matched = 0;

        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (contains_pattern(line, line_len, pattern, pattern_len, ignore_case)) {
                if (prefix_filename) {
                    if (fprintf(stdout, "(standard input):") < 0) {
                        fprintf(stderr, "write error\n");
                        return 2;
                    }
                }
                if (line_len > 0) {
                    if (fwrite(line, 1, line_len, stdout) != line_len) {
                        fprintf(stderr, "write error\n");
                        return 2;
                    }
                }
                if (putc('\n', stdout) == EOF) {
                    fprintf(stderr, "write error\n");
                    return 2;
                }
                matched = 1;
            }
            free(line);
        }

        return matched ? 0 : 1;
    } else {
        int status = 0;
        int matched_any = 0;

        for (int i = file_offset; i < argc; i++) {
            if (strcmp(argv[i], "--") == 0) continue;
            if (argv[i][0] == '-' && strlen(argv[i]) > 1) continue;
            int result = search_file(argv[i], pattern, pattern_len, prefix_filename, recursive, ignore_case);
            if (result == 2) status = 2;
            else if (result == 0) matched_any = 1;
        }

        return status != 0 ? 2 : (matched_any ? 0 : 1);
    }
}
