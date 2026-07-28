#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * new_mkdir - create directories without creating intermediate components.
 * Implements behavior described in the task prompt.
 */

static void print_error(const char *prog, const char *path, const char *msg) {
    // Format: prog: cannot create directory 'PATH': REASON\n to stderr
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog, path, msg);
}

int main(int argc, char *argv[]) {
    const char *prog = "mkdir";
    int any_failure = 0;
    int i = 1;

    // No operands check (will also be after option processing)
    if (i >= argc) {
        fprintf(stderr, "%s: missing operand\nTry 'mkdir --help' for more information.\n", prog);
        return 1;
    }

    // Option parsing – only '--' and unknown options handling
    while (i < argc) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) { i++; break; }
        if (arg[0] == '-' && strcmp(arg, "-") != 0) {
            // unknown option
            fprintf(stderr, "%s: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", prog, arg);
            return 1;
        }
        break; // first non‑option operand found
    }

    if (i >= argc) {
        fprintf(stderr, "%s: missing operand\nTry 'mkdir --help' for more information.\n", prog);
        return 1;
    }

    for (; i < argc; ++i) {
        const char *orig_path = argv[i];
        // Duplicate and normalize path (strip trailing slashes except root)
        char *norm_path = strdup(orig_path);
        if (!norm_path) {
            fprintf(stderr, "%s: memory allocation failed\n", prog);
            return 1;
        }
        size_t len = strlen(norm_path);
        while (len > 1 && norm_path[len - 1] == '/') {
            norm_path[--len] = '\0';
        }

        // Determine parent directory string
        char *parent_path = NULL;
        const char *slash = strrchr(norm_path, '/');
        if (slash) {
            if (slash == norm_path) {
                /* Path like "/foo" – parent is root "/" */
                parent_path = strdup("/");
            } else {
                size_t plen = slash - norm_path;
                parent_path = malloc(plen + 1);
                if (!parent_path) {
                    fprintf(stderr, "%s: memory allocation failed\n", prog);
                    free(norm_path);
                    return 1;
                }
                memcpy(parent_path, norm_path, plen);
                parent_path[plen] = '\0';
            }
        } else {
            /* No slash – parent is current directory "." */
            parent_path = strdup(".");
        }

        struct stat sb;
        if (stat(parent_path, &sb) != 0) {
            print_error(prog, orig_path, strerror(errno));
            any_failure = 1;
            free(parent_path);
            free(norm_path);
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            print_error(prog, orig_path, "Not a directory");
            any_failure = 1;
            free(parent_path);
            free(norm_path);
            continue;
        }
        free(parent_path);

        // Check if final component already exists (any type)
        struct stat sb2;
        if (lstat(norm_path, &sb2) == 0) {
            print_error(prog, orig_path, "File exists");
            any_failure = 1;
            free(norm_path);
            continue;
        }

        // Attempt to create the directory with default mode (umask applied)
        if (mkdir(norm_path, 0777) != 0) {
            print_error(prog, orig_path, strerror(errno));
            any_failure = 1;
            free(norm_path);
            continue;
        }

        free(norm_path);
    }

    return any_failure ? 1 : 0;
}
