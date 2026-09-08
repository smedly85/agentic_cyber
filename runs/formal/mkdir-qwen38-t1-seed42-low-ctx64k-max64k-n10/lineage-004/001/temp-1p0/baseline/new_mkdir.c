#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    int i;
    int end_of_options = 0;
    int num_operands = 0;

    /* First pass: reject unknown options, count operands */
    for (i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
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

    /* Second pass: attempt to create each directory */
    int any_failed = 0;
    end_of_options = 0;

    for (i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
        }
        const char *path = argv[i];
        if (mkdir(path, 0777) != 0) {
            any_failed = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
        }
    }

    return any_failed ? 1 : 0;
}
