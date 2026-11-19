#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    /* Pass 1: validate arguments -- detect unknown options, count operands.
       No filesystem mutation happens until pass 2. */
    int after_ddash = 0;
    int n_operands = 0;
    int unknown_idx = -1;

    for (int i = 1; i < argc; i++) {
        if (after_ddash) {
            n_operands++;
        } else if (argv[i][0] == '-' && argv[i][1] == '-' && argv[i][2] == '\0') {
            after_ddash = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            /* Unknown option (single-char or long) */
            if (unknown_idx < 0)
                unknown_idx = i;
        } else {
            /* bare '-' or a regular operand */
            n_operands++;
        }
    }

    if (unknown_idx >= 0) {
        const char *a = argv[unknown_idx];
        if (a[1] == '-' && a[2] != '\0')
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", a);
        else
            fprintf(stderr, "mkdir: invalid option -- '%c'\n", a[1]);
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Pass 2: create each operand in order; continue after errors. */
    after_ddash = 0;
    int rc = 0;
    for (int i = 1; i < argc; i++) {
        if (!after_ddash &&
            argv[i][0] == '-' && argv[i][1] == '-' && argv[i][2] == '\0') {
            after_ddash = 1;
            continue;
        }
        if (mkdir(argv[i], 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            rc = 1;
        }
    }

    return rc;
}
