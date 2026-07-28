#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <libgen.h>
#include <unistd.h>

static void report_error(const char *path, const char *reason) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, reason);
}

int main(int argc, char *argv[]) {
    int operands_start = 1;
    int saw_double_dash = 0;

    for (int i = 1; i < argc; i++) {
        char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            saw_double_dash = 1;
            operands_start = i + 1;
            break;
        }
        if (arg[0] == '-' && arg[1] != '\0' && strcmp(arg, "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
    }

    if (!saw_double_dash) {
        operands_start = 1;
    }

    if (operands_start >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int success = 1;
    for (int i = operands_start; i < argc; i++) {
        char *path = argv[i];
        char *dup_path = strdup(path);
        if (!dup_path) {
            report_error(path, "memory allocation failed");
            success = 0;
            continue;
        }

        char *dir = dirname(dup_path);
        struct stat sb;
        if (stat(dir, &sb) != 0) {
            report_error(path, strerror(errno));
            free(dup_path);
            success = 0;
            continue;
        }

        if (!S_ISDIR(sb.st_mode)) {
            report_error(path, "Not a directory");
            free(dup_path);
            success = 0;
            continue;
        }

        if (stat(path, &sb) == 0) {
            report_error(path, "File exists");
            free(dup_path);
            success = 0;
            continue;
        }

        if (mkdir(path, 0777) != 0) {
            report_error(path, strerror(errno));
            free(dup_path);
            success = 0;
            continue;
        }

        free(dup_path);
    }

    return success ? 0 : 1;
}