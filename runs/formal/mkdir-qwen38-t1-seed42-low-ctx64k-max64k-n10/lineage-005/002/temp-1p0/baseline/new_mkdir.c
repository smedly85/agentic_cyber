#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int create_parents(const char *path)
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
    int *operands = NULL;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
                if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                    parents = 1;
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
            rc = create_parents(path);
        } else {
            rc = (mkdir(path, 0777) != 0);
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
