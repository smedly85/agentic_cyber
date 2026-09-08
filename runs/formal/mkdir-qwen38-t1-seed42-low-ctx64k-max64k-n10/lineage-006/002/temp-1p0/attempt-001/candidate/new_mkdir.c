#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int parse_mode(const char *str, mode_t *result)
{
    if (str == NULL || str[0] == '\0')
        return -1;

    /* Try octal: 1–4 octal digits only. */
    size_t len = strlen(str);
    if (len >= 1 && len <= 4) {
        int all_octal = 1;
        for (size_t i = 0; i < len; i++) {
            if (str[i] < '0' || str[i] > '7') {
                all_octal = 0;
                break;
            }
        }
        if (all_octal) {
            *result = (mode_t)strtol(str, NULL, 8);
            return 0;
        }
    }

    /* Symbolic mode: base is 0777, apply clauses left to right. */
    mode_t mode = 0777;
    const char *p = str;

    while (1) {
        /* Parse class letters (may be multiple, e.g. "ug"). */
        int has_u = 0, has_g = 0, has_o = 0, has_class = 0;
        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            has_class = 1;
            if (*p == 'u') has_u = 1;
            else if (*p == 'g') has_g = 1;
            else if (*p == 'o') has_o = 1;
            else if (*p == 'a') has_u = has_g = has_o = 1;
            p++;
        }
        if (!has_class)
            has_u = has_g = has_o = 1;  /* default: all */

        /* Parse operator. */
        char op;
        if (*p != '+' && *p != '-' && *p != '=')
            return -1;
        op = *p++;

        /* Parse permission letters (may be empty for '='). */
        int has_r = 0, has_w = 0, has_x = 0, has_s = 0, has_t = 0;
        while (*p == 'r' || *p == 'w' || *p == 'x' ||
               *p == 'X' || *p == 's' || *p == 't') {
            if (*p == 'r') has_r = 1;
            else if (*p == 'w') has_w = 1;
            else if (*p == 'x' || *p == 'X') has_x = 1;
            else if (*p == 's') has_s = 1;
            else if (*p == 't') has_t = 1;
            p++;
        }

        /* Compute permission bits for affected classes only. */
        mode_t perm = 0;
        if (has_r) { if (has_u) perm |= 0400; if (has_g) perm |= 0040; if (has_o) perm |= 0004; }
        if (has_w) { if (has_u) perm |= 0200; if (has_g) perm |= 0020; if (has_o) perm |= 0002; }
        if (has_x) { if (has_u) perm |= 0100; if (has_g) perm |= 0010; if (has_o) perm |= 0001; }
        if (has_s) { if (has_u) perm |= 04000; if (has_g) perm |= 02000; }
        if (has_t) perm |= 01000;

        /* Full class mask: all bits belonging to affected classes. */
        mode_t class_mask = 0;
        if (has_u) class_mask |= 04700;
        if (has_g) class_mask |= 02070;
        if (has_o) class_mask |= 01007;

        /* Apply operator. */
        if (op == '+')
            mode |= perm;
        else if (op == '-')
            mode &= ~perm;
        else /* '=' */
            mode = (mode & ~class_mask) | perm;

        /* Advance past comma or expect end. */
        if (*p == ',') { p++; continue; }
        if (*p == '\0') break;
        return -1;  /* unexpected character */
    }

    *result = mode;
    return 0;
}

static int make_parents(const char *path, mode_t final_mode, int do_chmod)
{
    size_t len = strlen(path);
    char *copy = malloc(len + 1);
    if (!copy)
        return -1;
    memcpy(copy, path, len + 1);

    int failed = 0;

    /* Create each missing intermediate component in order. */
    for (size_t i = 1; i < len; i++) {
        if (copy[i] == '/') {
            copy[i] = '\0';
            if (copy[0] != '\0') {
                int rc = mkdir(copy, 0777);
                if (rc != 0 && errno != EEXIST) {
                    failed = 1;
                    break;
                }
                if (rc != 0) {
                    /* EEXIST: must be a directory to continue through it. */
                    struct stat st;
                    if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                        errno = ENOTDIR;
                        failed = 1;
                        break;
                    }
                }
            }
            copy[i] = '/';
        }
    }

    /* Create the final component, or accept it if it is already a directory. */
    if (!failed) {
        if (mkdir(copy, final_mode) != 0) {
            if (errno == EEXIST) {
                struct stat st;
                if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                    /* exists but is not a directory: failure (EEXIST) */
                    failed = 1;
                }
                /* exists and is a directory: success, do not change mode */
            } else {
                failed = 1;
            }
        } else if (do_chmod) {
            if (chmod(copy, final_mode) != 0)
                failed = 1;
        }
    }

    free(copy);
    return failed;
}

int main(int argc, char *argv[])
{
    int parents = 0;
    int have_mode = 0;
    mode_t mode = 0777;
    int end_of_options = 0;

    /* First pass: parse options, collect operand indices, validate mode. */
    int *operand_idx = malloc((size_t)(argc - 1) * sizeof(int));
    if (!operand_idx && argc > 1)
        return 1;
    int n_operands = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options && strcmp(argv[i], "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
                continue;
            }
            if (strcmp(argv[i], "-m") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'm'\n");
                    free(operand_idx);
                    return 1;
                }
                i++;
                if (parse_mode(argv[i], &mode) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                    free(operand_idx);
                    return 1;
                }
                have_mode = 1;
                continue;
            }
            if (strncmp(argv[i], "--mode=", 7) == 0) {
                const char *m = argv[i] + 7;
                if (parse_mode(m, &mode) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", m);
                    free(operand_idx);
                    return 1;
                }
                have_mode = 1;
                continue;
            }
            if (strcmp(argv[i], "--mode") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'mode'\n");
                    free(operand_idx);
                    return 1;
                }
                i++;
                if (parse_mode(argv[i], &mode) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                    free(operand_idx);
                    return 1;
                }
                have_mode = 1;
                continue;
            }
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            free(operand_idx);
            return 1;
        }
        operand_idx[n_operands++] = i;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        free(operand_idx);
        return 1;
    }

    /* Second pass: execute mkdir for each operand. */
    int any_failure = 0;
    mode_t m = have_mode ? mode : 0777;
    for (int i = 0; i < n_operands; i++) {
        const char *path = argv[operand_idx[i]];
        int rc;
        if (parents)
            rc = make_parents(path, m, have_mode);
        else {
            rc = (mkdir(path, m) != 0) ? -1 : 0;
            if (rc == 0 && have_mode && chmod(path, m) != 0)
                rc = -1;
        }
        if (rc != 0) {
            any_failure = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
        }
    }

    free(operand_idx);
    return any_failure ? 1 : 0;
}
