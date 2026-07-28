#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <limits.h>

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int i = 1;
    int end_of_options = 0;
    int have_operand = 0;
    int any_failure = 0;

    // Parse arguments for options (none exist) and '--'
    for (; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        have_operand = 1;
        // Normalize path: strip trailing slashes (except when path is "/")
        char norm_path[PATH_MAX];
        strncpy(norm_path, arg, PATH_MAX - 1);
        norm_path[PATH_MAX - 1] = '\0';
        size_t len = strlen(norm_path);
        while (len > 1 && norm_path[len - 1] == '/') {
            norm_path[--len] = '\0';
        }
        const char *path = norm_path;
        /* Determine parent directory */
        char *last_slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (last_slash) {
            size_t plen = last_slash - path;
            if (plen == 0) { // leading slash root
                strcpy(parent, "/");
            } else {
                memcpy(parent, path, plen);
                parent[plen] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }
        struct stat sb;
        if (stat(parent, &sb) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            print_error(path, "Not a directory");
            any_failure = 1;
            continue;
        }
        /* Check if final component already exists */
        struct stat sb2;
        if (stat(path, &sb2) == 0) {
            print_error(path, "File exists");
            any_failure = 1;
            continue;
        }
        /* Attempt to create directory */
        if (mkdir(path, 0777) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }
    }

    if (!have_operand) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
