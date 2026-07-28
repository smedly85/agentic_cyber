#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>

static void print_error(const char *path) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
}

int main(int argc, char *argv[]) {
    if (argc == 1) {
        // No arguments at all.
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    int any_failure = 0;
    int end_of_options = 0;
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue; // '--' is not an operand.
        }

        // Option handling: any argument beginning with '-' (except "-" and before '--') is unknown.
        if (!end_of_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", arg);
            return 1;
        }

        // At this point, 'arg' is an operand.
        const char *path = arg;
        // Determine parent directory.
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash == NULL) {
            strcpy(parent, ".");
        } else if (slash == path) { // leading '/' means root is parent
            // parent is "/"
            strncpy(parent, "/", sizeof(parent)-1);
            parent[sizeof(parent)-1] = '\0';
        } else {
            size_t len = slash - path;
            if (len >= sizeof(parent)) {
                // Truncate safely; this shouldn't happen on normal paths.
                len = sizeof(parent) - 1;
            }
            memcpy(parent, path, len);
            parent[len] = '\0';
        }

        struct stat sb;
        if (stat(parent, &sb) != 0) {
            // Parent does not exist or cannot be accessed.
            print_error(path);
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            // Parent exists but is not a directory.
            errno = ENOTDIR; // set appropriate errno for message
            print_error(path);
            any_failure = 1;
            continue;
        }

        struct stat sb2;
        if (stat(path, &sb2) == 0) {
            // Path already exists.
            errno = EEXIST;
            print_error(path);
            any_failure = 1;
            continue;
        }

        // Try to create the directory with default mode (0777 masked by umask).
        if (mkdir(path, 0777) != 0) {
            // mkdir failed; errno already set.
            print_error(path);
            any_failure = 1;
            continue;
        }
        // Success – nothing to output.
    }

    return any_failure ? 1 : 0;
}
