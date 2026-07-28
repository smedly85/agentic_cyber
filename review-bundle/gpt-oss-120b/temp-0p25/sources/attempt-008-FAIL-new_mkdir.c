#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <stdbool.h>

/*
 * new_mkdir – minimal mkdir utility for the checkpoint.
 * Implements behavior described in the task prompt.
 */

static void print_error(const char *msg) {
    fprintf(stderr, "%s\n", msg);
}

int main(int argc, char *argv[]) {
    int i = 1;                  // start after program name
    int have_operand = 0;
    /* Option parsing – only '--' is recognized. Any other leading '-'
     * (except a lone '-') is an unknown option.
     */
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) { // end of options
            i++;
            break; // remaining args are operands
        }
        if (argv[i][0] == '-') {
            /* '-' alone is a valid operand, otherwise unknown option */
            if (strcmp(argv[i], "-") != 0) {
                print_error("new_mkdir: unrecognized option");
                return 1;
            }
        }
        break; // first non‑option argument
    }

    /* Process remaining arguments as operands */
    for (; i < argc; ++i) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            continue; // stray '--' after parsing – ignore as operand delimiter
        }
        have_operand = 1;
        /* Make a mutable copy so we can strip trailing slashes */
        char *path = strdup(arg);
        if (!path) {
            print_error("new_mkdir: memory allocation failed");
            return 1;
        }
        size_t len = strlen(path);
        while (len > 1 && path[len - 1] == '/') {
            path[--len] = '\0';
        }

        /* Determine parent directory */
        char *slash = strrchr(path, '/');
        char *parent = NULL;
        if (slash) {
            size_t plen = (size_t)(slash - path);
            if (plen == 0) {

            } else {

            }
        } else {
            /* No '/' – use current directory as parent */

        }

        /* Check that the parent exists and is a directory */
        struct stat pst;
        if (stat(parent, &pst) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", arg, strerror(errno));
            free(path);
            free(parent);
            continue; // operand failure, move to next
        }
        if (!S_ISDIR(pst.st_mode)) {
            errno = ENOTDIR;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", arg, strerror(errno));
            free(path);
            free(parent);
            continue;
        }

        /* Verify final component does not already exist */
        struct stat fst;
        if (stat(arg, &fst) == 0) {
            errno = EEXIST; // mimic mkdir behaviour for existing entry
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", arg, strerror(errno));
            free(path);
            free(parent);
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(arg, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", arg, strerror(errno));
            // do not abort – continue with remaining operands
        }

        free(path);
        free(parent);
    }

    if (!have_operand) {
        print_error("new_mkdir: missing operand");
        return 1;
    }
    /* If we reached here, all processing done. The program exits with
     * status 0 when every operand succeeded; otherwise the per‑operand
     * failures already printed cause a non‑zero exit.
     */
    return 0;
}
