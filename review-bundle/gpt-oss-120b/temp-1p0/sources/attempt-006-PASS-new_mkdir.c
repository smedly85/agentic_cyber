#define PROG_NAME "mkdir"

#define PROG_NAME "mkdir"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>

static void report_error(const char *path, const char *msg) {
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", PROG_NAME, path, msg);
}

int main(int argc, char *argv[]) {
        if (argc < 2) {
            fprintf(stderr, "%s: missing operand\nTry '%s --help' for more information.\n", PROG_NAME, PROG_NAME);
            return 1;
        }

    int any_failure = 0;
    int end_of_options = 0;
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
        fprintf(stderr, "%s: unrecognized option '%s'\nTry '%s --help' for more information.\n", PROG_NAME, arg, PROG_NAME);
        return 1;
    }
        // Trim trailing slashes from operand (except root "/")
        char *trimmed = strdup(arg);
        if (!trimmed) {
            fprintf(stderr, "%s: memory allocation failed\n", PROG_NAME);
            return 1;
        }
        size_t tlen = strlen(trimmed);
        while (tlen > 1 && trimmed[tlen - 1] == '/') {
            trimmed[--tlen] = '\0';
        }
        const char *path = trimmed; // use trimmed for processing
        // Determine parent directory
        const char *slash = strrchr(path, '/');
        char *parent = NULL;
        if (slash) {
            size_t plen = slash - path;
            if (plen == 0) { // root '/' as parent
                parent = strdup("/");
            } else {
                parent = malloc(plen + 1);
                if (!parent) {
                    fprintf(stderr, "%s: memory allocation failed\n", PROG_NAME);
                    free(trimmed);
                    return 1;
                }
                memcpy(parent, path, plen);
                parent[plen] = '\0';
            }
        } else {
            // No slash; current directory is parent
            parent = strdup(".");
        }
        if (!parent) {
            fprintf(stderr, "%s: memory allocation failed\n", PROG_NAME);
            free(trimmed);
            return 1;
        }

        struct stat st;
        // Check parent existence and that it is a directory
        if (stat(parent, &st) != 0) {
            report_error(path, strerror(errno));
            any_failure = 1;
            free(parent);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            report_error(path, "Not a directory");
            any_failure = 1;
            free(parent);
            continue;
        }

        // Check if final component already exists
        struct stat st2;
        if (stat(path, &st2) == 0) {
            report_error(path, "File exists");
            any_failure = 1;
            free(parent);
            continue;
        }

        // Attempt to create directory with default mode (0777 masked by umask)
        if (mkdir(path, 0777) != 0) {
            report_error(path, strerror(errno));
            any_failure = 1;
            free(parent);
            continue;
        }

        free(parent);
    }
    return any_failure ? 1 : 0;
}
