#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/* Helper to print error messages with the standard "mkdir" prefix */
static void mkdir_error(const char *fmt, ...) {
    va_list ap;
    fprintf(stderr, "mkdir: ");
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
}

int main(int argc, char *argv[]) {
    int exit_status = 0;
    int have_operand = 0;
    int i = 1; // start after program name

    /* Parse options (none are supported yet) */
    for (; i < argc; ++i) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) { /* end of options */
            ++i;
            break;
        }
        if (arg[0] == '-' && strcmp(arg, "-") != 0) {
            mkdir_error("unrecognized option '%s'", arg);
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        break; /* first non‑option operand */
    }

    /* Process remaining arguments as operands */
    for (; i < argc; ++i) {
        const char *orig_path = argv[i];
        if (strcmp(orig_path, "--") == 0)
            continue; // ignore stray '--'
        have_operand = 1;

        /* Trim trailing slashes (except when the path is exactly "/") */
        char *path = strdup(orig_path);
        if (!path) {
            mkdir_error("memory allocation failed");
            return 1;
        }
        size_t len = strlen(path);
        while (len > 1 && path[len - 1] == '/') {
            path[--len] = '\0';
        }

        /* Split path into parent and leaf */
        const char *slash = strrchr(path, '/');
        char *parent;
        const char *leaf;
        if (slash) {
            size_t plen = slash - path;
            parent = malloc(plen + 1);
            if (!parent) {
                free(path);
                mkdir_error("memory allocation failed");
                return 1;
            }
            memcpy(parent, path, plen);
            parent[plen] = '\0';
            leaf = slash + 1; // may be empty for "foo/"
        } else {
            parent = strdup(".");
            if (!parent) {
                free(path);
                mkdir_error("memory allocation failed");
                return 1;
            }
            leaf = path;
        }

        /* If leaf is empty after trimming, treat as error (should not happen) */
        if (*leaf == '\0') {
            mkdir_error("cannot create directory '%s': No such file or directory", orig_path);
            free(parent);
            free(path);
            exit_status = 1;
            continue;
        }

        /* Verify parent exists and is a directory */
        struct stat st_parent;
        if (stat(parent, &st_parent) != 0) {
            mkdir_error("cannot create directory '%s': %s", orig_path, strerror(errno));
            free(parent);
            free(path);
            exit_status = 1;
            continue;
        }
        if (!S_ISDIR(st_parent.st_mode)) {
            mkdir_error("cannot create directory '%s': Not a directory", orig_path);
            free(parent);
            free(path);
            exit_status = 1;
            continue;
        }

        /* Check if target already exists */
        struct stat st_target;
        if (stat(path, &st_target) == 0) {
            mkdir_error("cannot create directory '%s': File exists", orig_path);
            free(parent);
            free(path);
            exit_status = 1;
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            mkdir_error("cannot create directory '%s': %s", orig_path, strerror(errno));
            free(parent);
            free(path);
            exit_status = 1;
            continue;
        }

        free(parent);
        free(path);
    }

    if (!have_operand) {
        mkdir_error("missing operand");
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    return exit_status;
}

