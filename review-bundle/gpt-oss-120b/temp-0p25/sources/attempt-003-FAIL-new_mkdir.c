#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

static void report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int end_of_options = 0;
    int have_operand = 0;
    int any_failure = 0;

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", arg);
            return 1;
        }
        // Operand
        have_operand = 1;
        const char *path = arg;
        /* Determine parent directory */
        const char *slash = strrchr(path, '/');
        char *parent;
        if (slash == NULL) {
            parent = strdup(".");
        } else if (slash == path) { // starts with '/' and no other slash
            parent = strdup("/");
        } else {
            size_t len = (size_t)(slash - path);
            parent = malloc(len + 1);
            if (!parent) {
                fprintf(stderr, "new_mkdir: memory allocation failed\n");
                return 1;
            }
            memcpy(parent, path, len);
            parent[len] = '\0';
        }
        /* Verify parent exists and is a directory */
        struct stat sb;
        if (stat(parent, &sb) != 0) {
            report_error(path, strerror(errno));
            any_failure = 1;
            free(parent);
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            report_error(path, "Not a directory");
            any_failure = 1;
            free(parent);
            continue;
        }
        /* Check target does not already exist */
        if (stat(path, &sb) == 0) {
            report_error(path, "File exists");
            any_failure = 1;
            free(parent);
            continue;
        }
        /* Attempt creation */
        if (mkdir(path, 0777) != 0) {
            report_error(path, strerror(errno));
            any_failure = 1;
            free(parent);
            continue;
        }
        free(parent);
    }

    if (!have_operand) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
