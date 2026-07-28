#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

int main(int argc, char *argv[]) {
    const char **operands = NULL;
    int op_cnt = 0;
    int i;
    int status_failed = 0; // track if any operand failed
    int end_of_options = 0;

        if (argc < 2) {
            fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
            return 1;
        }

    operands = malloc(sizeof(char *) * (size_t)(argc - 1));
    if (!operands) {
        fprintf(stderr, "new_mkdir: memory allocation failed\n");
        return 1;
    }

    for (i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue; // do not treat '--' as operand
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            /* Unknown option */
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            free((void *)operands);
            return 1;
        }
        operands[op_cnt++] = arg; // treat as operand
    }

        if (op_cnt == 0) {
            fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
            free((void *)operands);
            return 1;
        }

    for (i = 0; i < op_cnt; ++i) {
        const char *path = operands[i];
        /* Attempt to create the directory with default mode (0777 & ~umask). */
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            status_failed = 1;
        }
    }

    free((void *)operands);
    return status_failed ? 1 : 0;
}
