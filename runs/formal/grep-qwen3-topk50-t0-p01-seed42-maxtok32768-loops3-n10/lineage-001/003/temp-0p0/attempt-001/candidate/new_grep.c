#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>

#define CHUNK_SIZE 4096

struct entry_list {
    char **names;
    size_t count;
    size_t capacity;
};

static void init_entry_list(struct entry_list *list) {
    list->names = NULL;
    list->count = 0;
    list->capacity = 0;
}

static void free_entry_list(struct entry_list *list) {
    for (size_t i = 0; i < list->count; i++) {
        free(list->names[i]);
    }
    free(list->names);
    list->names = NULL;
    list->count = 0;
    list->capacity = 0;
}

static int add_entry(struct entry_list *list, const char *name) {
    if (list->count >= list->capacity) {
        size_t new_cap = list->capacity == 0 ? 16 : list->capacity * 2;
        char **new_names = realloc(list->names, new_cap * sizeof(char *));
        if (!new_names) return -1;
        list->names = new_names;
        list->capacity = new_cap;
    }
    list->names[list->count] = strdup(name);
    if (!list->names[list->count]) return -1;
    list->count++;
    return 0;
}

static int compare_strings(const void *a, const void *b) {
    const char *sa = *(const char **)a;
    const char *sb = *(const char **)b;
    return strcmp(sa, sb);
}

static void sort_entry_list(struct entry_list *list) {
    qsort(list->names, list->count, sizeof(char *), compare_strings);
}

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

static int search_recursive(const char *operand, const char *rel_path, const char *pattern,
                            size_t pat_len, int prefix_filename, int *match_found,
                            int *error_occurred);

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                        int prefix_filename, int *match_found, int *error_occurred) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        return 0;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fclose(fp);
        fprintf(stderr, "%s: Is a directory\n", filename);
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

    fclose(fp);

    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        return 0;
    }

    return 1;
}

static int search_recursive(const char *operand, const char *rel_path, const char *pattern,
                            size_t pat_len, int prefix_filename, int *match_found,
                            int *error_occurred) {
    DIR *dir = opendir(rel_path);
    if (!dir) {
        fprintf(stderr, "%s: %s\n", rel_path, strerror(errno));
        *error_occurred = 1;
        return 0;
    }

    struct entry_list entries;
    init_entry_list(&entries);

    struct dirent *de;
    while ((de = readdir(dir)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) continue;
        if (add_entry(&entries, de->d_name) < 0) {
            fprintf(stderr, "%s: %s\n", rel_path, strerror(ENOMEM));
            free_entry_list(&entries);
            closedir(dir);
            *error_occurred = 1;
            return 0;
        }
    }

    sort_entry_list(&entries);

    size_t operand_len = strlen(operand);
    int need_slash = operand_len > 0 && operand[operand_len - 1] != '/';

    for (size_t j = 0; j < entries.count; j++) {
        const char *name = entries.names[j];
        size_t rel_len = strlen(rel_path);
        size_t name_len = strlen(name);
        char *child_path = malloc(rel_len + 1 + name_len + 1);
        if (!child_path) {
            fprintf(stderr, "%s: %s\n", rel_path, strerror(ENOMEM));
            free_entry_list(&entries);
            closedir(dir);
            *error_occurred = 1;
            return 0;
        }
        memcpy(child_path, rel_path, rel_len);
        child_path[rel_len] = '/';
        memcpy(child_path + rel_len + 1, name, name_len + 1);

        struct stat st;
        if (lstat(child_path, &st) < 0) {
            fprintf(stderr, "%s: %s\n", child_path, strerror(errno));
            free(child_path);
            *error_occurred = 1;
            continue;
        }

        size_t display_len = operand_len + (need_slash ? 1 : 0) + name_len + 1;
        char *display_path = malloc(display_len);
        if (!display_path) {
            fprintf(stderr, "%s: %s\n", rel_path, strerror(ENOMEM));
            free(child_path);
            free_entry_list(&entries);
            closedir(dir);
            *error_occurred = 1;
            return 0;
        }
        memcpy(display_path, operand, operand_len);
        if (need_slash) {
            display_path[operand_len] = '/';
        }
        memcpy(display_path + operand_len + (need_slash ? 1 : 0), name, name_len + 1);

        if (S_ISREG(st.st_mode)) {
            search_file(display_path, pattern, pat_len, prefix_filename,
                        match_found, error_occurred);
        } else if (S_ISDIR(st.st_mode)) {
            search_recursive(display_path, child_path, pattern, pat_len,
                             prefix_filename, match_found, error_occurred);
        }

        free(child_path);
        free(display_path);
    }

    free_entry_list(&entries);
    closedir(dir);

    return 1;
}

static int has_filename_prefix(int num_files, int force_filename, int no_force_filename,
                                int recursive, int has_dir_operand) {
    if (no_force_filename) return 0;
    if (force_filename) return 1;
    if (num_files > 1) return 1;
    if (recursive && has_dir_operand) return 1;
    return 0;
}

static void print_usage(const char *prog) {
    fprintf(stderr, "Usage: %s PATTERN [FILE...]\n", prog);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_usage(argv[0]);
        return 2;
    }

    int force_filename = 0;
    int no_force_filename = 0;
    int recursive = 0;
    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            if (strcmp(argv[i], "--with-filename") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                if (strcmp(argv[i], "--with-filename") == 0) {
                    force_filename = 1;
                    no_force_filename = 0;
                } else {
                    no_force_filename = 1;
                    force_filename = 0;
                }
                i++;
                continue;
            }
            if (strcmp(argv[i], "--recursive") == 0) {
                recursive = 1;
                i++;
                continue;
            }
            char *p = &argv[i][1];
            while (*p != '\0') {
                if (*p == 'H') {
                    force_filename = 1;
                    no_force_filename = 0;
                } else if (*p == 'h') {
                    no_force_filename = 1;
                    force_filename = 0;
                } else if (*p == 'r') {
                    recursive = 1;
                } else {
                    fprintf(stderr, "%s: unrecognized option '%s'\n", argv[0], argv[i]);
                    return 2;
                }
                p++;
            }
            i++;
            continue;
        }
        break;
    }

    const char *pattern = argv[i++];
    size_t pat_len = strlen(pattern);

    int num_files = argc - i;

    int has_dir_operand = 0;
    for (int j = i; j < argc; j++) {
        struct stat st;
        if (stat(argv[j], &st) == 0 && S_ISDIR(st.st_mode)) {
            has_dir_operand = 1;
            break;
        }
    }

    int prefix_filename = has_filename_prefix(num_files, force_filename, no_force_filename,
                                               recursive, has_dir_operand);

    int match_found = 0;
    int error_occurred = 0;

    if (num_files == 0) {
        size_t line_len;
        char *line;
        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (matches(line, line_len, pattern, pat_len)) {
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
            fprintf(stderr, "%s: %s\n", argv[0], strerror(errno));
            error_occurred = 1;
        }
    } else {
        for (; i < argc; i++) {
            const char *filename = argv[i];
            struct stat st;
            if (lstat(filename, &st) == 0 && S_ISLNK(st.st_mode)) {
                search_file(filename, pattern, pat_len, prefix_filename,
                            &match_found, &error_occurred);
            } else if (stat(filename, &st) == 0 && S_ISDIR(st.st_mode)) {
                if (!recursive) {
                    fprintf(stderr, "%s: Is a directory\n", filename);
                    error_occurred = 1;
                } else {
                    size_t len = strlen(filename);
                    char *operand_copy = NULL;
                    const char *operand_display = filename;
                    if (len > 0 && filename[len - 1] == '/') {
                        operand_copy = strdup(filename);
                        if (operand_copy) {
                            operand_copy[len - 1] = '\0';
                            operand_display = operand_copy;
                        }
                    }
                    search_recursive(operand_display, filename, pattern, pat_len,
                                     prefix_filename, &match_found, &error_occurred);
                    free(operand_copy);
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
