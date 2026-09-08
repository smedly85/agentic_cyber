#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int parse_mode_str(const char *s)
{
    if (s[0] == '\0')
        return -1;

    /* Try octal: all characters must be 0-7 */
    int all_octal = 1;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '7') { all_octal = 0; break; }
    }
    if (all_octal) {
        unsigned int mode = 0;
        for (const char *p = s; *p; p++) {
            mode = mode * 8u + (unsigned int)(*p - '0');
            if (mode > 07777u)
                return -1;
        }
        return (int)mode;
    }

    /* Symbolic mode: comma-separated clauses [ugoa...][+-=][rwxXst...] */
    int mode = 0777;
    const char *p = s;

    while (*p) {
        int classes = 0;
        int has_class = 0;

        while (*p == 'u' || *p == 'g' || *p == 'a' || *p == 'o') {
            has_class = 1;
            if (*p == 'u') classes |= 1;
            else if (*p == 'g') classes |= 2;
            else if (*p == 'a') classes = 7;
            else classes |= 4;
            p++;
        }
        if (!has_class)
            classes = 7;

        if (*p != '+' && *p != '-' && *p != '=')
            return -1;
        char op = *p++;

        int named = 0;

        while (*p && *p != ',') {
            switch (*p) {
            case 'r':
                if (classes & 1) named |= 256;
                if (classes & 2) named |= 32;
                if (classes & 4) named |= 4;
                break;
            case 'w':
                if (classes & 1) named |= 128;
                if (classes & 2) named |= 16;
                if (classes & 4) named |= 2;
                break;
            case 'x':
            case 'X':
                if (classes & 1) named |= 64;
                if (classes & 2) named |= 8;
                if (classes & 4) named |= 1;
                break;
            case 's':
                if (classes & 1) named |= 2048;
                if (classes & 2) named |= 1024;
                break;
            case 't':
                named |= 512;
                break;
            default:
                return -1;
            }
            p++;
        }

        int affected = 0;
        if (classes & 1) affected |= 448 | 2048;
        if (classes & 2) affected |= 56 | 1024;
        if (classes & 4) affected |= 7 | 512;

        if (op == '=') {
            mode = (mode & ~affected) | named;
        } else if (op == '+') {
            mode |= named;
        } else {
            mode &= ~named;
        }

        if (*p == ',')
            p++;
        else if (*p == '\0')
            break;
        else
            return -1;
    }

    return mode;
}

static int create_parents(const char *path, int final_mode, int has_mode)
{
    size_t len = strlen(path);
    char *buf = malloc(len + 1);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    memcpy(buf, path, len + 1);

    for (size_t i = 1; i < len; i++) {
        if (buf[i] == '/') {
            buf[i] = '\0';
            struct stat st;
            if (stat(buf, &st) == 0) {
                if (!S_ISDIR(st.st_mode)) {
                    free(buf);
                    errno = ENOTDIR;
                    return -1;
                }
            } else if (errno == ENOENT) {
                if (mkdir(buf, 0777) != 0) {
                    free(buf);
                    return -1;
                }
            } else {
                free(buf);
                return -1;
            }
            buf[i] = '/';
        }
    }

    struct stat st;
    if (stat(buf, &st) == 0) {
        if (!S_ISDIR(st.st_mode)) {
            free(buf);
            errno = ENOTDIR;
            return -1;
        }
    } else if (errno == ENOENT) {
        if (mkdir(buf, 0777) != 0) {
            free(buf);
            return -1;
        }
        if (has_mode && chmod(buf, (mode_t)final_mode) != 0) {
            free(buf);
            return -1;
        }
    } else {
        free(buf);
        return -1;
    }

    free(buf);
    return 0;
}

int main(int argc, char *argv[])
{
    int end_of_options = 0;
    int operand_count = 0;
    int operand_cap = 0;
    int any_failed = 0;
    int parents = 0;
    const char *mode_str = NULL;
    int *operands = NULL;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
                if (strcmp(argv[i], "-p") == 0 ||
                    strcmp(argv[i], "--parents") == 0) {
                    parents = 1;
                    continue;
                }
                if (strcmp(argv[i], "-m") == 0) {
                    if (i + 1 >= argc) {
                        fprintf(stderr,
                                "mkdir: option requires an argument -- 'm'\n");
                        free(operands);
                        return 1;
                    }
                    i++;
                    mode_str = argv[i];
                    continue;
                }
                if (strncmp(argv[i], "--mode=", 7) == 0) {
                    mode_str = argv[i] + 7;
                    continue;
                }
                if (strcmp(argv[i], "--mode") == 0) {
                    if (i + 1 >= argc) {
                        fprintf(stderr,
                                "mkdir: option requires an argument -- 'mode'\n");
                        free(operands);
                        return 1;
                    }
                    i++;
                    mode_str = argv[i];
                    continue;
                }
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                free(operands);
                return 1;
            }
        }
        if (operand_count == operand_cap) {
            int new_cap = operand_cap ? operand_cap * 2 : 8;
            int *tmp = realloc(operands, (size_t)new_cap * sizeof(int));
            if (!tmp) {
                fprintf(stderr, "mkdir: memory allocation failed\n");
                free(operands);
                return 1;
            }
            operands = tmp;
            operand_cap = new_cap;
        }
        operands[operand_count++] = i;
    }

    int mkdir_mode = 0777;
    if (mode_str) {
        mkdir_mode = parse_mode_str(mode_str);
        if (mkdir_mode < 0) {
            fprintf(stderr, "mkdir: invalid mode '%s'\n", mode_str);
            free(operands);
            return 1;
        }
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    for (int i = 0; i < operand_count; i++) {
        const char *path = argv[operands[i]];
        int rc;
        if (parents) {
            rc = create_parents(path, mkdir_mode, mode_str != NULL);
        } else {
            rc = (mkdir(path, 0777) != 0);
            if (rc == 0 && mode_str) {
                rc = (chmod(path, (mode_t)mkdir_mode) != 0);
            }
        }
        if (rc != 0) {
            any_failed = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
        }
    }

    free(operands);
    return any_failed ? 1 : 0;
}
