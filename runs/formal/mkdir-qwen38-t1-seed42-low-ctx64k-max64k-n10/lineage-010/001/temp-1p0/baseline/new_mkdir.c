#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    char **operands = NULL;
    int noperands = 0;
    int cap = 0;
    int end_of_opts = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_opts && strcmp(argv[i], "--") == 0) {
            end_of_opts = 1;
            continue;
        }
        if (!end_of_opts && argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                    "Try 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
        if (noperands == cap) {
            int newcap = cap ? cap * 2 : 4;
            char **tmp = realloc(operands, (size_t)newcap * sizeof(char *));
            if (!tmp) {
                fprintf(stderr, "mkdir: memory exhaustion\n");
                free(operands);
                return 1;
            }
            operands = tmp;
            cap = newcap;
        }
        operands[noperands++] = argv[i];
    }

    if (noperands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    int any_failed = 0;

    for (int i = 0; i < noperands; i++) {
        const char *path = operands[i];
        struct stat st;

        if (lstat(path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            any_failed = 1;
            continue;
        }

        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            any_failed = 1;
            continue;
        }
    }

    free(operands);
    return any_failed ? 1 : 0;
}
