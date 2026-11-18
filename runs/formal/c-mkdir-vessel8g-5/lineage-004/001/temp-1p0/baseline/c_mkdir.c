#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    int saw_ddash = 0;
    int n_operands = 0;

    /* Phase 1: validate arguments before any mutation.
       Detect unknown options and count operands. */
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!saw_ddash) {
            if (strcmp(arg, "--") == 0) {
                saw_ddash = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (arg[1] == '-' && arg[2] != '\0') {
                    fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
                } else {
                    fprintf(stderr, "mkdir: invalid option -- '%c'\n", arg[1]);
                }
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                return 1;
            }
        }
        n_operands++;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Phase 2: create each operand's directory in order;
       continue after per-operand errors. */
    int exit_code = 0;
    saw_ddash = 0;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!saw_ddash) {
            if (strcmp(arg, "--") == 0) {
                saw_ddash = 1;
                continue;
            }
        }
        if (mkdir(arg, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    arg, strerror(errno));
            exit_code = 1;
        }
    }

    return exit_code;
}
