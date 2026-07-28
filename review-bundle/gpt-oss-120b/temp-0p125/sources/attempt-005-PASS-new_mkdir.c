#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include <sys/stat.h>
#include <unistd.h>
 
int main(int argc, char *argv[]) {
    int exit_status = 0; // 0 if all succeed, 1 otherwise
    int end_of_options = 0;
    int operand_count = 0;
 
    // Process arguments
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options) {
            if (strcmp(arg, "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
                // Unknown option
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                return 1;
            }
        }
        // Treat as operand
        ++operand_count;
        const char *orig_path = arg; // keep original for messages
        // Normalize path: remove trailing slashes (except root "/")
        char norm_path[PATH_MAX];
        strncpy(norm_path, orig_path, PATH_MAX - 1);
        norm_path[PATH_MAX - 1] = '\0';
        size_t nlen = strlen(norm_path);
        while (nlen > 1 && norm_path[nlen - 1] == '/') {
            norm_path[--nlen] = '\0';
        }
        const char *path = norm_path;
 
        // Split into parent and final component
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t len = slash - path;
            if (len == 0) { // path like "/foo"
                strcpy(parent, "/");
            } else {
                if (len >= PATH_MAX) {
                    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", orig_path, strerror(ENAMETOOLONG));
                    exit_status = 1;
                    continue;
                }
                memcpy(parent, path, len);
                parent[len] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }
 
        // Verify parent exists and is a directory
        struct stat pst;
        if (stat(parent, &pst) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", orig_path, strerror(errno));
            exit_status = 1;
            continue;
        }
        if (!S_ISDIR(pst.st_mode)) {
            errno = ENOTDIR;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", orig_path, strerror(errno));
            exit_status = 1;
            continue;
        }
 
        // Check if final component already exists
        struct stat tst;
        if (stat(orig_path, &tst) == 0) {
            errno = EEXIST; // Already exists
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", orig_path, strerror(errno));
            exit_status = 1;
            continue;
        }
 
        // Attempt to create the directory
        if (mkdir(orig_path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", orig_path, strerror(errno));
            exit_status = 1;
            continue;
        }
    }
 
    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }
    return exit_status;
}

