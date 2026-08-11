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

static unsigned char fold_byte(unsigned char c) {
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
        int found = 1;
        for (size_t j = 0; j < pat_len; j++) {
            unsigned char lc = fold_byte((unsigned char)line[i + j]);
            unsigned char pc = fold_byte((unsigned char)pattern[j]);
            if (lc != pc) {
                found = 0;
                break;
            }
        }
        if (found) return 1;
    }
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int ignore_case, int *match_found, int *error_occurred);

static void search_directory(const char *dirname, const char *pattern, size_t pat_len,
                              int prefix_filename, int ignore_case, int *match_found, int *error_occurred);

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int ignore_case, int *match_found, int *error_occurred) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        return 0;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fclose(fp);
        search_directory(filename, pattern, pat_len, prefix_filename, ignore_case, match_found, error_occurred);
        return 1;
    }

    size_t line_len;
    char *line;
    while ((line = read_line(fp, &line_len)) != NULL) {
        if (matches(line, line_len, pattern, pat_len, ignore_case)) {
            if (prefix_filename) {
                fprintf(stdout, "%s:", filename);
            }
            fwrite(line, 1, line_len, stdout);
            fputc('\n', stdout);
            *match_found = 1;
        }
        free(line);
    }

    fclose(fp);

    if (ferror(fp)) {
        fprintf(stderr, "%s: Input error\n", filename);
        *error_occurred = 1;
        return 0;
    }

    return 1;
}

static int compare_names(const void *a, const void *b) {
    const char *na = *(const char **)a;
    const char *nb = *(const char **)b;
    return strcmp(na, nb);
}

static void search_directory(const char *dirname, const char *pattern, size_t pat_len,
                              int prefix_filename, int ignore_case, int *match_found, int *error_occurred) {
    DIR *dir = opendir(dirname);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", dirname, strerror(errno));
        *error_occurred = 1;
        return;
    }

    size_t capacity = 64;
    size_t count = 0;
    char **entries = malloc(capacity * sizeof(char *));
    if (!entries) {
        closedir(dir);
        *error_occurred = 1;
        return;
    }

    struct dirent *de;
    while ((de = readdir(dir)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) continue;
        if (count >= capacity) {
            size_t new_cap = capacity * 2;
            char **new_entries = realloc(entries, new_cap * sizeof(char *));
            if (!new_entries) {
                for (size_t i = 0; i < count; i++) free(entries[i]);
                free(entries);
                closedir(dir);
                *error_occurred = 1;
                return;
            }
            entries = new_entries;
            capacity = new_cap;
        }
        size_t len = strlen(de->d_name);
        entries[count] = malloc(len + 1);
        if (!entries[count]) {
            for (size_t i = 0; i < count; i++) free(entries[i]);
            free(entries);
            closedir(dir);
            *error_occurred = 1;
            return;
        }
        strcpy(entries[count], de->d_name);
        count++;
    }
    closedir(dir);

    qsort(entries, count, sizeof(char *), compare_names);

    size_t dir_len = strlen(dirname);
    while (dir_len > 0 && dirname[dir_len - 1] == '/') dir_len--;

    for (size_t i = 0; i < count; i++) {
        size_t entry_len = strlen(entries[i]);
        char *path = malloc(dir_len + 1 + entry_len + 1);
        if (!path) {
            for (size_t j = i; j < count; j++) free(entries[j]);
            free(entries);
            *error_occurred = 1;
            return;
        }
        memcpy(path, dirname, dir_len);
        path[dir_len] = '/';
        strcpy(path + dir_len + 1, entries[i]);

        struct stat st;
        if (lstat(path, &st) == 0) {
            if (S_ISREG(st.st_mode)) {
                search_file(path, pattern, pat_len, prefix_filename, ignore_case, match_found, error_occurred);
            } else if (S_ISDIR(st.st_mode)) {
                search_directory(path, pattern, pat_len, prefix_filename, ignore_case, match_found, error_occurred);
            }
        } else {
            fprintf(stderr, "%s: %s\n", path, strerror(errno));
            *error_occurred = 1;
        }

        free(path);
        free(entries[i]);
    }
    free(entries);
}

static void print_usage(const char *prog) {
    fprintf(stderr, "Usage: %s PATTERN [FILE...]\n", prog);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_usage(argv[0]);
        return 2;
    }

    int i = 1;
    int force_filename = -1;
    int recursive = 0;
    int ignore_case = 0;
    while (i < argc && argv[i][0] == '-' && strcmp(argv[i], "--") != 0) {
        if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
            force_filename = 1;
            i++;
            continue;
        }
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
            force_filename = 0;
            i++;
            continue;
        }
        if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
            recursive = 1;
            i++;
            continue;
        }
        if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--ignore-case") == 0) {
            ignore_case = 1;
            i++;
            continue;
        }
        if (argv[i][1] == 'H' && argv[i][2] == '\0') {
            force_filename = 1;
            i++;
            continue;
        }
        if (argv[i][1] == 'h' && argv[i][2] == '\0') {
            force_filename = 0;
            i++;
            continue;
        }
        if (argv[i][1] == 'r' && argv[i][2] == '\0') {
            recursive = 1;
            i++;
            continue;
        }
        if (argv[i][1] == 'i' && argv[i][2] == '\0') {
            ignore_case = 1;
            i++;
            continue;
        }
        if (argv[i][1] == 'H' || argv[i][1] == 'h' || argv[i][1] == 'r' || argv[i][1] == 'i') {
            int j = 1;
            while (argv[i][j] != '\0') {
                if (argv[i][j] == 'H') {
                    force_filename = 1;
                } else if (argv[i][j] == 'h') {
                    force_filename = 0;
                } else if (argv[i][j] == 'r') {
                    recursive = 1;
                } else if (argv[i][j] == 'i') {
                    ignore_case = 1;
                } else {
                    fprintf(stderr, "Unknown option: %s\n", argv[i]);
                    return 2;
                }
                j++;
            }
            i++;
            continue;
        }
        if (strcmp(argv[i], "-") == 0) {
            break;
        }
        fprintf(stderr, "Unknown option: %s\n", argv[i]);
        return 2;
    }

    if (i < argc && strcmp(argv[i], "--") == 0) {
        i++;
    }

    const char *pattern = argv[i++];
    size_t pat_len = strlen(pattern);

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

    int prefix_filename = (force_filename == 1) ? 1 : ((force_filename == 0) ? 0 : ((num_files > 1) ? 1 : 0));
    if (!prefix_filename && recursive && has_directory && force_filename != 0) {
        prefix_filename = 1;
    }

    int match_found = 0;
    int error_occurred = 0;

    if (num_files == 0) {
        size_t line_len;
        char *line;
        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (matches(line, line_len, pattern, pat_len, ignore_case)) {
                if (prefix_filename) {
                    fprintf(stdout, "(standard input):");
                }
                fwrite(line, 1, line_len, stdout);
                fputc('\n', stdout);
                match_found = 1;
            }
            free(line);
        }
        if (ferror(stdin)) {
            fprintf(stderr, "Input error\n");
            error_occurred = 1;
        }
    } else {
        for (; i < argc; i++) {
            const char *filename = argv[i];
            struct stat st;
            if (lstat(filename, &st) == 0 && S_ISDIR(st.st_mode)) {
                if (recursive) {
                    search_directory(filename, pattern, pat_len, prefix_filename,
                                     ignore_case, &match_found, &error_occurred);
                } else {
                    fprintf(stderr, "%s: Is a directory\n", filename);
                    error_occurred = 1;
                }
            } else {
                search_file(filename, pattern, pat_len, prefix_filename,
                            ignore_case, &match_found, &error_occurred);
            }
        }
    }

    if (error_occurred) return 2;
    return match_found ? 0 : 1;
}
