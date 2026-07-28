#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <limits.h>

int main(int argc, char *argv[]) {
    int exit_status = 0;
    int any_operand = 0;
    int end_of_options = 0;

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        // Option handling (no options defined yet)
        if (!end_of_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }

        any_operand = 1;

        // Trim trailing slashes (except when the argument is just "/")
        size_t len = strlen(arg);
        while (len > 1 && arg[len - 1] == '/') {
            ((char *)arg)[--len] = '\0';
        }
        const char *path = arg;

        // Determine parent directory
        char parent[PATH_MAX];
        const char *slash = strrchr(path, '/');
        if (slash) {
            size_t plen = slash - path; // characters before the last slash
            if (plen == 0) { // path like "/foo"
                strcpy(parent, "/");
            } else {
                memcpy(parent, path, plen);
                parent[plen] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }

        struct stat st;
        if (stat(parent, &st) != 0) {
            // Parent does not exist or cannot be accessed
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            exit_status = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            exit_status = 1;
            continue;
        }

        // Check if final component already exists
        if (stat(path, &st) == 0) {
            errno = EEXIST;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            exit_status = 1;
            continue;
        }

        // Attempt to create the directory with mode 0777 (umask applied by OS)
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            exit_status = 1;
        }
    }

    if (!any_operand) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return exit_status;
}
