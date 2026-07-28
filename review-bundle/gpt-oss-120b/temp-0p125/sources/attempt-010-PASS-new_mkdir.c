#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * new_mkdir – create directories given as operands.
 * Implements the minimal behavior required for checkpoint 1.
 */

static const char *prog_name = "mkdir";

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog_name, path, msg);
}

int main(int argc, char *argv[]) {
    int had_error = 0;
    int saw_double_dash = 0;

    if (argc < 2) {
        fprintf(stderr, "%s: missing operand\nTry '%s --help' for more information.\n", prog_name, prog_name);
        return 1;
    }

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!saw_double_dash && strcmp(arg, "--") == 0) { // end of options marker
            saw_double_dash = 1;
            continue;
        }
        if (!saw_double_dash && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "%s: unrecognized option '%s'\nTry '%s --help' for more information.\n", prog_name, arg, prog_name);
            return 1; // immediate failure before any directories are created
        }
        /* Strip trailing slashes */
        size_t orig_len = strlen(arg);
        while (orig_len > 0 && arg[orig_len - 1] == '/') {
            orig_len--;
        }
        char *path = NULL;
        if (orig_len != strlen(arg)) {
            path = malloc(orig_len + 1);
            if (!path) {
                fprintf(stderr, "%s: memory allocation failed\n", prog_name);
                return 1;
            }
            memcpy(path, arg, orig_len);
            path[orig_len] = '\0';
        } else {
            path = strdup(arg);
            if (!path) { fprintf(stderr, "%s: memory allocation failed\n", prog_name); return 1; }
        }
        size_t len = strlen(path);
        if (len == 0) {
            print_error(path, "invalid argument");
            had_error = 1;
            free(path);
            continue;
        }
        const char *sep = strrchr(path, '/');
        if (sep != NULL && sep != path) {
            size_t parent_len = sep - path;
            char *parent = malloc(parent_len + 1);
            if (!parent) { fprintf(stderr, "%s: memory allocation failed\n", prog_name); free(path); return 1; }
            memcpy(parent, path, parent_len);
            parent[parent_len] = '\0';
            struct stat st;
            if (stat(parent, &st) != 0) {
                print_error(path, strerror(errno));
                had_error = 1;
                free(parent);
                free(path);
                continue;
            }
            if (!S_ISDIR(st.st_mode)) {
                print_error(path, "Not a directory");
                had_error = 1;
                free(parent);
                free(path);
                continue;
            }
            free(parent);
        } else if (sep != NULL && sep == path) { /* path like "/foo" */ }

        if (mkdir(path, 0777) != 0) {
            print_error(path, strerror(errno));
            had_error = 1;
        }
        free(path);
    }

    return had_error ? 1 : 0;
}
