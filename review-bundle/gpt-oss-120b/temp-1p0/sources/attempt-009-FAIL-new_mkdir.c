#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int i;
    int end_of_options = 0;
    int any_operand = 0;
    int overall_failed = 0;

    /* First pass: detect early errors (unknown options, missing operand) */
    for (i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {   // end of options marker
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", arg);
            return 1;
        }
        /* Anything else is treated as an operand */
        any_operand = 1;
    }

    if (!any_operand) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    /* Second pass: process operands in order */
    end_of_options = 0;
    for (i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {   // skip marker
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            /* already handled in first pass */
            continue;
        }

        const char *path = arg;                 // full path to create
        char *parent_path = NULL;               // will point to allocated string or literal
        struct stat st;
        int need_free_parent = 0;

        /* Determine parent directory */
        char *dup = strdup(path);
        if (!dup) {
            fprintf(stderr, "new_mkdir: memory allocation failure\n");
            return 1;
        }
        char *last_slash = strrchr(dup, '/');
        if (last_slash == NULL) {
            parent_path = ".";                 // current directory
        } else if (last_slash == dup) {
            /* Path like "/foo" – parent is root */
            *(last_slash + 1) = '\0';           // keep the leading '/'
            parent_path = dup;
            need_free_parent = 1;               // we will free dup later
        } else {
            *last_slash = '\0';                // truncate to parent part
            parent_path = dup;
            need_free_parent = 1;
        }

        /* Check that the parent exists and is a directory */
        if (stat(parent_path, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_failed = 1;
            if (need_free_parent) free(dup);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR; /* mimic GNU mkdir error */
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_failed = 1;
            if (need_free_parent) free(dup);
            continue;
        }

        /* Check whether the final component already exists */
        if (lstat(path, &st) == 0) {
            errno = EEXIST;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_failed = 1;
            if (need_free_parent) free(dup);
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_failed = 1;
            if (need_free_parent) free(dup);
            continue;
        }

        if (need_free_parent) free(dup);
    }

    return overall_failed ? 1 : 0;
}
