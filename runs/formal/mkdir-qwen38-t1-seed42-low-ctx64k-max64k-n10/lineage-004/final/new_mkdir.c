#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

/* Parse a mode string (octal or symbolic) into a mode_t value.
   Returns 0 on success, -1 on failure. */
static int parse_mode(const char *str, mode_t *result)
{
    if (!str || str[0] == '\0')
        return -1;

    /* Check if all characters are octal digits */
    int all_octal = 1;
    for (const char *p = str; *p; p++) {
        if (*p < '0' || *p > '7') {
            all_octal = 0;
            break;
        }
    }

    if (all_octal) {
        unsigned long val = 0;
        for (const char *p = str; *p; p++) {
            val = val * 8 + (unsigned long)(*p - '0');
            if (val > 07777)
                return -1;
        }
        *result = (mode_t)val;
        return 0;
    }

    /* Symbolic mode parsing: start from 0777, apply clauses left to right */
    mode_t base = 0777;
    const char *p = str;

    while (1) {
        int has_u = 0, has_g = 0, has_o = 0;
        int op = 0;
        int has_r = 0, has_w = 0, has_x = 0, has_s = 0, has_t = 0;

        /* Parse class letters */
        while (*p && (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a')) {
            if (*p == 'u' || *p == 'a') has_u = 1;
            if (*p == 'g' || *p == 'a') has_g = 1;
            if (*p == 'o' || *p == 'a') has_o = 1;
            p++;
        }
        if (!has_u && !has_g && !has_o) {
            has_u = has_g = has_o = 1;
        }

        /* Parse operator */
        if (*p == '+' || *p == '-' || *p == '=') {
            op = *p;
            p++;
        } else {
            return -1;
        }

        /* Parse permission letters (may be empty, e.g. "o=") */
        while (*p && *p != ',') {
            if (*p == 'r') has_r = 1;
            else if (*p == 'w') has_w = 1;
            else if (*p == 'x' || *p == 'X') has_x = 1;
            else if (*p == 's') has_s = 1;
            else if (*p == 't') has_t = 1;
            else return -1;
            p++;
        }

        /* Compute permission bits */
        mode_t perm = 0;
        if (has_r) {
            if (has_u) perm |= 0400;
            if (has_g) perm |= 0040;
            if (has_o) perm |= 0004;
        }
        if (has_w) {
            if (has_u) perm |= 0200;
            if (has_g) perm |= 0020;
            if (has_o) perm |= 0002;
        }
        if (has_x) {
            if (has_u) perm |= 0100;
            if (has_g) perm |= 0010;
            if (has_o) perm |= 0001;
        }
        if (has_s) {
            if (has_u) perm |= 04000;
            if (has_g) perm |= 02000;
        }
        if (has_t) perm |= 01000;

        /* Compute mask (bits affected by this clause) */
        mode_t mask = 0;
        if (has_u) mask |= 0700;
        if (has_g) mask |= 0070;
        if (has_o) mask |= 0007;
        if (op == '=') {
            /* '=' clears all bits for the class, including special bits */
            if (has_u) mask |= 04000;
            if (has_g) mask |= 02000;
            if (has_o) mask |= 01000;
        }

        /* Apply the clause */
        if (op == '=') {
            base = (base & ~mask) | perm;
        } else if (op == '+') {
            base |= perm;
        } else { /* '-' */
            base &= ~perm;
        }

        /* Check for comma (next clause) or end */
        if (*p == ',') {
            p++;
            continue;
        }
        break;
    }

    *result = base;
    return 0;
}

static int create_parents(const char *path, mode_t final_mode, int has_mode)
{
    size_t len = strlen(path);
    char *copy = malloc(len + 1);
    if (!copy) {
        errno = ENOMEM;
        return -1;
    }
    memcpy(copy, path, len + 1);

    size_t pos = 0;
    while (pos < len && copy[pos] == '/') pos++;

    while (pos < len) {
        size_t end = pos;
        while (end < len && copy[end] != '/') end++;

        char saved = copy[end];
        copy[end] = '\0';

        struct stat st;
        int is_final = (end >= len);
        int created = 0;

        if (stat(copy, &st) == 0) {
            if (!S_ISDIR(st.st_mode)) {
                errno = ENOTDIR;
                free(copy);
                return -1;
            }
        } else {
            if (mkdir(copy, 0777) != 0) {
                if (errno == EEXIST) {
                    if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                        errno = ENOTDIR;
                        free(copy);
                        return -1;
                    }
                } else {
                    free(copy);
                    return -1;
                }
            } else {
                created = 1;
            }
        }

        /* Apply -m mode only to the final directory, and only if newly created */
        if (is_final && has_mode && created) {
            if (chmod(copy, final_mode) != 0) {
                free(copy);
                return -1;
            }
        }

        copy[end] = saved;

        if (end >= len) break;
        pos = end + 1;
        while (pos < len && copy[pos] == '/') pos++;
    }

    free(copy);
    return 0;
}

int main(int argc, char *argv[])
{
    int i;
    int end_of_options = 0;
    int num_operands = 0;
    int parents = 0;
    const char *mode_str = NULL;
    mode_t computed_mode = 0;
    int has_mode = 0;

    /* First pass: parse options, collect mode (last wins), count operands */
    for (i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
                continue;
            }
            if (strcmp(argv[i], "-m") == 0) {
                if (i + 1 >= argc) {
                    mode_str = "";
                    has_mode = 1;
                    continue;
                }
                i++;
                mode_str = argv[i];
                has_mode = 1;
                continue;
            }
            if (strncmp(argv[i], "--mode=", 7) == 0) {
                mode_str = argv[i] + 7;
                has_mode = 1;
                continue;
            }
            if (strcmp(argv[i], "--mode") == 0) {
                if (i + 1 >= argc) {
                    mode_str = "";
                    has_mode = 1;
                    continue;
                }
                i++;
                mode_str = argv[i];
                has_mode = 1;
                continue;
            }
            if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                return 1;
            }
        }
        num_operands++;
    }

    if (num_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    if (has_mode) {
        if (parse_mode(mode_str, &computed_mode) != 0) {
            fprintf(stderr, "mkdir: invalid mode '%s'\n", mode_str);
            return 1;
        }
    }

    /* Second pass: create each directory */
    int any_failed = 0;
    end_of_options = 0;

    for (i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                continue;
            }
            if (strcmp(argv[i], "-m") == 0) {
                i++;
                continue;
            }
            if (strncmp(argv[i], "--mode=", 7) == 0) {
                continue;
            }
            if (strcmp(argv[i], "--mode") == 0) {
                i++;
                continue;
            }
        }
        const char *path = argv[i];
        int rc;
        if (parents) {
            rc = create_parents(path, computed_mode, has_mode);
        } else {
            if (mkdir(path, 0777) != 0) {
                rc = 1;
            } else if (has_mode) {
                rc = (chmod(path, computed_mode) != 0);
            } else {
                rc = 0;
            }
        }
        if (rc != 0) {
            any_failed = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
        }
    }

    return any_failed ? 1 : 0;
}
