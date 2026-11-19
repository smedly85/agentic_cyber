#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    const char *prog = "mkdir";

    /* Phase 1: validate options before any mutation.
       Only "--" is recognized (option terminator).
       "-" is an operand. Other dash-prefixed tokens are errors. */
    int terminated = 0;
    for (int i = 1; i < argc; i++) {
        if (terminated)
            break;
        if (strcmp(argv[i], "--") == 0) {
            terminated = 1;
            continue;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (argv[i][1] == '-')
                fprintf(stderr, "%s: unrecognized option '%s'\n", prog, argv[i]);
            else
                fprintf(stderr, "%s: invalid option -- '%c'\n", prog, argv[i][1]);
            fprintf(stderr, "Try '%s --help' for more information.\n", prog);
            return 1;
        }
    }

    /* Count operands (all args except the "--" terminator). */
    int operand_count = 0;
    terminated = 0;
    for (int i = 1; i < argc; i++) {
        if (!terminated && strcmp(argv[i], "--") == 0) {
            terminated = 1;
            continue;
        }
        operand_count++;
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", prog);
        fprintf(stderr, "Try '%s --help' for more information.\n", prog);
        return 1;
    }

    /* Phase 2: create each operand directory in order, continuing after errors. */
    int all_ok = 1;
    terminated = 0;
    for (int i = 1; i < argc; i++) {
        if (!terminated && strcmp(argv[i], "--") == 0) {
            terminated = 1;
            continue;
        }
        if (mkdir(argv[i], 0777) != 0) {
            fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                    prog, argv[i], strerror(errno));
            all_ok = 0;
        }
    }

    return all_ok ? 0 : 1;
}
