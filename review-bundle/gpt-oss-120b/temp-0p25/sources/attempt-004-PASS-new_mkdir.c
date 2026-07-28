#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * new_mkdir – create directories specified as operands.
 * Implements the minimal behavior required for checkpoint 1.
 */

static const char *prog_name = "mkdir";

static int is_option(const char *arg) {
    return arg[0] == '-' && !(strcmp(arg, "-") == 0);
}

static void print_error_operand(const char *msg) {
    fprintf(stderr, "%s: %s\nTry 'mkdir --help' for more information.\n", prog_name, msg);
}

static void print_error_dir(const char *path, const char *msg) {
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog_name, path, msg);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_error_operand("missing operand");
        return 1;
    }

    int any_fail = 0;
    int end_of_options = 0;
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && is_option(arg)) {
            fprintf(stderr, "%s: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", prog_name, arg);
            return 1; // immediate failure before any creation
        }
        /* process operand */
        char *orig_path = arg;
        // make a mutable copy to strip trailing slashes (unless path is "/")
        char *path = strdup(orig_path);
        if (!path) {
            print_error_operand("memory allocation failed");
            return 1;
        }
        size_t len = strlen(path);
        while (len > 1 && path[len - 1] == '/') {
            path[--len] = '\0';
        }
        if (len == 0) { // became empty, treat as "."
            free(path);
            path = strdup(".");
            len = 1;
        }

        char *sep = strrchr(path, '/');
        char *parent = NULL;
        if (sep) {
            size_t p_len = sep - path;
            if (p_len == 0) { // leading slash -> root is parent
                parent = "/";
            } else {
                parent = strndup(path, p_len);
                if (!parent) {
                    print_error_operand("memory allocation failed");
                    free(path);
                    return 1;
                }
            }
        } else {
            parent = strdup(".");
            if (!parent) { print_error_operand("memory allocation failed"); free(path); return 1; }
        }

        struct stat st;
        if (stat(parent, &st) != 0) {
            print_error_dir(orig_path, strerror(errno)); // use original arg for message
            any_fail = 1;
            free(path);
            if (parent && strcmp(parent, "/") != 0 && strcmp(parent, ".") != 0) free(parent);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error_dir(orig_path, "Not a directory");
            any_fail = 1;
            free(path);
            if (parent && strcmp(parent, "/") != 0 && strcmp(parent, ".") != 0) free(parent);
            continue;
        }
        /* Check if final component already exists */
        if (stat(orig_path, &st) == 0) {
            print_error_dir(orig_path, "File exists");
            any_fail = 1;
            free(path);
            if (parent && strcmp(parent, "/") != 0 && strcmp(parent, ".") != 0) free(parent);
            continue;
        }
        /* Attempt to create directory */
        if (mkdir(orig_path, 0777) != 0) {
            print_error_dir(orig_path, strerror(errno));
            any_fail = 1;
            free(path);
            if (parent && strcmp(parent, "/") != 0 && strcmp(parent, ".") != 0) free(parent);
            continue;
        }
        free(path);
        if (parent && strcmp(parent, "/") != 0 && strcmp(parent, ".") != 0) free(parent);
    }

    return any_fail ? 1 : 0;
}
