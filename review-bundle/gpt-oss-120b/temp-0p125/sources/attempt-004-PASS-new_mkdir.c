#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <libgen.h>

static void print_error_missing_operand(void) {
    fprintf(stderr, "mkdir: missing operand\n");
    fprintf(stderr, "Try 'mkdir --help' for more information.\n");
}

static void print_error_unknown_option(const char *opt) {
    fprintf(stderr, "mkdir: unrecognized option '%s'\n", opt);
    fprintf(stderr, "Try 'mkdir --help' for more information.\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_error_missing_operand();
        return 1;
    }

    int any_failure = 0;
    int operands_start = 1; // first operand index after handling '--'
    int parsing_options = 1;
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (parsing_options && strcmp(arg, "--") == 0) {
            parsing_options = 0;
            operands_start = i + 1;
            continue;
        }
        if (parsing_options && arg[0] == '-') {
            // '-' alone is allowed as operand; otherwise unknown option
            if (strcmp(arg, "-") != 0) {
            print_error_unknown_option(arg);
            return 1;
        }
        }
    }

        if (operands_start >= argc) { // no operands after '--'
            print_error_missing_operand();
            return 1;
        }

    for (int i = operands_start; i < argc; ++i) {
        const char *path = argv[i];
        struct stat sb;
        if (stat(path, &sb) == 0) {
            // something already exists at path
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(EEXIST));
            any_failure = 1;
            continue;
        }

        // Determine parent directory
        char *path_copy = strdup(path);
        if (!path_copy) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(ENOMEM));
            any_failure = 1;
            continue;
        }
        char *parent = dirname(path_copy);

        struct stat pstat;
        if (stat(parent, &pstat) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(ENOENT));
            any_failure = 1;
            free(path_copy);
            continue;
        }
        if (!S_ISDIR(pstat.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(ENOTDIR));
            any_failure = 1;
            free(path_copy);
            continue;
        }
        free(path_copy);

        // Attempt to create the directory with default mode (umask applied)
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        }
    }

    return any_failure ? 1 : 0;
}
