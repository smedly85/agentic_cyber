#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

static int process_operand(const char *path) {
    /* Determine parent directory */
    const char *sep = strrchr(path, '/');
    const char *parent;
    char *parent_buf = NULL;
    if (!sep) {
        parent = ".";                 // no slash -> current directory is parent
    } else if (sep == path) {
        parent = "/";                // leading '/' like "/foo"
    } else {
        size_t plen = sep - path;
        parent_buf = malloc(plen + 1);
        if (!parent_buf) {
            fprintf(stderr, "mkdir: memory allocation failure\n");
            return -1;                  // treat as fatal for this operand
        }
        memcpy(parent_buf, path, plen);
        parent_buf[plen] = '\0';
        parent = parent_buf;
    }

    /* Verify parent exists and is a directory */
    struct stat sb;
    if (stat(parent, &sb) != 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(parent_buf);
        return 1;
    }
    if (!S_ISDIR(sb.st_mode)) {
        fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
        free(parent_buf);
        return 1;
    }

    /* Check if target already exists */
    struct stat sb2;
    if (stat(path, &sb2) == 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
        free(parent_buf);
        return 1;
    }

    /* Attempt to create the directory */
    if (mkdir(path, 0777) != 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(parent_buf);
        return 1;
    }

    free(parent_buf);
    return 0; // success
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failure = 0;
    int parsing_options = 1; // true until '--' encountered

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];

        if (parsing_options && strcmp(arg, "--") == 0) {
            parsing_options = 0;
            continue; // '--' is not an operand
        }

        if (parsing_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
        // Unknown option
        fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
        }

        // Operand processing
        // Strip trailing slashes (except when the operand is exactly "/")
        char *norm = strdup(arg);
        if (!norm) {
            fprintf(stderr, "mkdir: memory allocation failure\n");
            any_failure = 1;
            break;
        }
        size_t len = strlen(norm);
        while (len > 1 && norm[len-1] == '/') {
            norm[--len] = '\0';
        }
        int res = process_operand(norm);
        free(norm);

        if (res == -1) { // memory allocation failure – treat as overall failure
            any_failure = 1;
            break;
        } else if (res != 0) {
            any_failure = 1;
        }
    }

    return any_failure ? 1 : 0;
}
