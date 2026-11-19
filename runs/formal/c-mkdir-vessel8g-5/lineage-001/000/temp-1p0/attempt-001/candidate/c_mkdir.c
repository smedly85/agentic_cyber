#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    /* Phase 1: Validate all arguments before any mutation.
       Reject unknown options immediately. */
    int after_ddash = 0;
    for (int i = 1; i < argc; i++) {
        if (after_ddash)
            continue;
        const char *a = argv[i];
        if (strcmp(a, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (a[0] == '-' && a[1] != '\0') {
            /* Unknown option (neither bare '-' nor '--') */
            if (a[1] == '-') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", a);
            } else {
                fprintf(stderr, "mkdir: invalid option -- '%c'\n", a[1]);
            }
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
    }

    /* Check we have at least one operand */
    if (argc == 1) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Phase 2: Create each directory in order; continue after failures. */
    int exit_status = 0;
    after_ddash = 0;
    for (int i = 1; i < argc; i++) {
        if (after_ddash) {
            if (mkdir(argv[i], 0777) != 0) {
                int e = errno;
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        argv[i], strerror(e));
                exit_status = 1;
            }
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            /* Already validated in phase 1, but guard against logic errors */
            continue;
        }
        if (mkdir(argv[i], 0777) != 0) {
            int e = errno;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(e));
            exit_status = 1;
        }
    }

    return exit_status;
}
