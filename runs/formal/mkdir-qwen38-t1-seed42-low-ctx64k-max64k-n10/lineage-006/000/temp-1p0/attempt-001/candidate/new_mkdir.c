#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    (void)argc;
    int have_operands = 0;
    int any_failure = 0;
    int end_of_options = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options && strcmp(argv[i], "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        have_operands = 1;
        if (mkdir(argv[i], 0777) != 0) {
            any_failure = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
        }
    }

    if (!have_operands) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
