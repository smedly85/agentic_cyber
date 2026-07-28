#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdarg.h>

/*
 * new_mkdir – create directories according to the specification.
 * Implements only the behavior described in the task prompt.
 */

static void print_error(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
}

int main(int argc, char *argv[]) {
    int exit_status = 0; // 0 if all succeed, 1 otherwise
    int have_operand = 0;
    int end_of_options = 0;
    /* Collect operands after option parsing */
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options) {
            if (strcmp(arg, "--") == 0) {   // end of options marker
                end_of_options = 1;
                continue;
            }
            if (arg[0] == '-' && !(arg[0] == '-' && arg[1] == '\0')) {
                /* unknown option */
                print_error("mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
                return 1;
            }
        }
        // treat everything after "--" or non‑option arguments as operands
        have_operand = 1;
        char *path = arg; // operand to process

        /* Split path into parent and final component */
        char *slash = strrchr(path, '/');
        char *parent_dir = NULL;
        if (slash == NULL) {
            parent_dir = strdup(".");
            if (!parent_dir) {
                print_error("new_mkdir: memory allocation failed\n");
                return 1;
            }
        } else {
            /* If the slash is the first character, parent is "/" */
            size_t plen = (size_t)(slash - path);
            if (plen == 0) {
                parent_dir = strdup("/");
            } else {
                parent_dir = malloc(plen + 1);
                if (!parent_dir) {
                    print_error("new_mkdir: memory allocation failed\n");
                    return 1;
                }
                memcpy(parent_dir, path, plen);
                parent_dir[plen] = '\0';
            }
        }

        /* Validate parent directory */
        struct stat sb;
        if (stat(parent_dir, &sb) != 0) {
            print_error("mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            exit_status = 1;
            free(parent_dir);
            continue; // move to next operand
        }
        if (!S_ISDIR(sb.st_mode)) {
            print_error("mkdir: cannot create directory '%s': %s\n", path, "Not a directory");
            exit_status = 1;
            free(parent_dir);
            continue;
        }

        /* Check if final component already exists */
        struct stat sb2;
        if (lstat(path, &sb2) == 0) {
            print_error("mkdir: cannot create directory '%s': %s\n", path, "File exists");
            exit_status = 1;
            free(parent_dir);
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            print_error("mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            exit_status = 1;
            free(parent_dir);
            continue;
        }

        free(parent_dir);
    }

    if (!have_operand) {
        print_error("mkdir: missing operand\nTry ""?"???"?","
        return 1;
    }

    return exit_status;
}
