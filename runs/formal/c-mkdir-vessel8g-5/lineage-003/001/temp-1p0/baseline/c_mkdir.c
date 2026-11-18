#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char *argv[])
{
    // Phase 1: Validate arguments (no filesystem mutation)
    int opt_done = 0;
    int has_operand = 0;

    for (int i = 1; i < argc; i++) {
        if (opt_done) {
            has_operand = 1;
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            opt_done = 1;
            continue;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        has_operand = 1;
    }

    if (!has_operand) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    // Phase 2: Create directories in order, continuing after per-operand errors
    int all_ok = 1;
    opt_done = 0;

    for (int i = 1; i < argc; i++) {
        if (!opt_done) {
            if (strcmp(argv[i], "--") == 0) {
                opt_done = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0')
                continue;
        }
        if (mkdir(argv[i], 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            all_ok = 0;
        }
    }

    return all_ok ? 0 : 1;
}
