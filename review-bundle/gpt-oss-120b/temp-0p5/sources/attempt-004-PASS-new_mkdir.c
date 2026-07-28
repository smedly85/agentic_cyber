#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <libgen.h>

static void print_error(const char *msg) {
    // Deprecated: use specific error messages for consistency with GNU mkdir output.
    fprintf(stderr, "%s\n", msg);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        // No arguments at all
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int have_operand = 0;
    int any_failure = 0;
    int end_of_options = 0;

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
        // Unknown option
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
        return 1;
        }
        // Operand handling
        have_operand = 1;
        const char *path = arg;
        /* Determine parent directory */
        char *path_dup = strdup(path);
        if (!path_dup) {
            print_error("new_mkdir: memory allocation failed");
            return 1;
        }
    char *dir_name = NULL;
        // Use dirname and basename which may modify the string
        char *tmp = strdup(path_dup);
        if (!tmp) {
            free(path_dup);
            print_error("new_mkdir: memory allocation failed");
            return 1;
        }
        dir_name = dirname(tmp); // parent path, may be "." if no slash

        // Check parent exists and is directory
        struct stat st_parent;
        if (stat(dir_name, &st_parent) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            free(tmp);
            free(path_dup);
            continue;
        }
        if (!S_ISDIR(st_parent.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            any_failure = 1;
            free(tmp);
            free(path_dup);
            continue;
        }
        // Check final component does not already exist
        struct stat st_final;
        if (stat(path, &st_final) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            any_failure = 1;
            free(tmp);
            free(path_dup);
            continue;
        }
        // Attempt to create directory with default mode (0777 & ~umask)
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            free(tmp);
            free(path_dup);
            continue;
        }
        // Success
        free(tmp);
        free(path_dup);
    }

    if (!have_operand) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
