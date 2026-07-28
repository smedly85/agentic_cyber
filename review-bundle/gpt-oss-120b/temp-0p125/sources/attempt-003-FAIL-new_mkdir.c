#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * new_mkdir – create directories specified on the command line.
 *
 * Behavior matches the specification for checkpoint 1:
 *   • Accepts one or more operands (paths) and "--" to end option parsing.
 *   • Unknown options cause an immediate error.
 *   • No operands → error with "missing operand".
 *   • For each operand, attempt to create the final component only if its
 *     parent exists and is a directory; otherwise report failure but continue.
 *   • Errors are printed to stderr in the format:
 *        mkdir: cannot create directory 'PATH': REASON
 *   • Exit status 0 on total success, 1 otherwise.
 */

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "missing operand\n");
        return 1;
    }

    int any_failure = 0;
    int i = 1;
    while (i < argc) {
        char *arg = argv[i];
        /* Handle end‑of‑options marker */
        if (strcmp(arg, "--") == 0) { i++; continue; }

        /* Unknown option detection (starts with '-' and is not a bare '-') */
        if (arg[0] == '-' && !(arg[1] == '\0')) {
            fprintf(stderr, "unknown option: %s\n", arg);
            return 1;
        }

        /* Determine parent directory */
        char *slash = strrchr(arg, '/');
        char *parent;
        if (slash) {
            size_t len = slash - arg; // length of parent part
            parent = malloc(len + 1);
            if (!parent) { perror("malloc"); return 1; }
            memcpy(parent, arg, len);
            parent[len] = '\0';
        } else {
            /* No '/' – use current directory as parent */
            parent = strdup(".");
            if (!parent) { perror("strdup"); return 1; }
        }

        /* Verify parent exists and is a directory */
        struct stat st;
        if (stat(parent, &st) != 0) {
            print_error(arg, strerror(errno));
            any_failure = 1;
            free(parent);
            i++;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error(arg, "Not a directory");
            any_failure = 1;
            free(parent);
            i++;
            continue;
        }

        /* Check that final component does not already exist */
        struct stat dst;
        if (stat(arg, &dst) == 0) {
            print_error(arg, "File exists");
            any_failure = 1;
            free(parent);
            i++;
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(arg, 0777) != 0) {
            print_error(arg, strerror(errno));
            any_failure = 1;
        }
        free(parent);
        i++;
    }

    return any_failure ? 1 : 0;
}
