#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include <sys/stat.h>
#include <unistd.h>

static void report_error(const char *path, int err) {
    /* Print diagnostic in the required format */
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(err));
}

int main(int argc, char *argv[]) {
    int any_failed = 0;
    int end_of_options = 0;
    int operand_count = 0;

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) { /* stop option parsing */
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1; /* immediate failure before any directory creation */
        }
        /* treat as operand */
        ++operand_count;
        const char *path = arg;

        /* Duplicate path for manipulation */
        char *dup = strdup(path);
        if (!dup) {
            fprintf(stderr, "memory allocation failed\n");
            return 1;
        }

        /* Trim trailing slashes (except when the whole path is just "/") */
        size_t len = strlen(dup);
        while (len > 1 && dup[len - 1] == '/') {
            dup[--len] = '\0';
        }
        const char *proc_path = dup; // trimmed full operand

        /* Determine parent directory without destroying proc_path */
        char *slash = strrchr(dup, '/');
        const char *parent;
        if (slash) {
            *slash = '\0';               // temporarily terminate to get parent string
            parent = dup;                  // may be empty -> current directory
            *slash = '/';                 // restore slash for later use of proc_path
        } else {
            parent = ".";                // no slash means current directory is the parent
        }

        int err;
        if (parent[0] != '\0') {
            struct stat pst;
            if (lstat(parent, &pst) != 0) { // parent does not exist or other error
                err = errno; // ENOENT etc.
                report_error(proc_path, err);
                any_failed = 1;
                free(dup);
                continue;
            }
            if (S_ISLNK(pst.st_mode)) {
                /* Parent is a symlink – resolve its target and verify it is a directory */
                char link_target[PATH_MAX];
                ssize_t tlen = readlink(parent, link_target, sizeof(link_target) - 1);
                if (tlen == -1) {
                    err = errno;
                    report_error(proc_path, err);
                    any_failed = 1;
                    free(dup);
                    continue;
                }
                link_target[tlen] = '\0';
                char resolved[PATH_MAX];
                if (link_target[0] == '/') {
                    strncpy(resolved, link_target, sizeof(resolved));
                } else {
                    /* dirname of parent */
                    char *last_slash = strrchr(parent, '/');
                    if (last_slash) {
                        size_t dirlen = last_slash - parent;
                        snprintf(resolved, sizeof(resolved), "%.*s/%s", (int)dirlen, parent, link_target);
                    } else {
                        strncpy(resolved, link_target, sizeof(resolved));
                    }
                }
                struct stat targetst;
                if (stat(resolved, &targetst) != 0) {
                    err = errno; // ENOENT etc.
                    report_error(proc_path, err);
                    any_failed = 1;
                    free(dup);
                    continue;
                }
                if (!S_ISDIR(targetst.st_mode)) {
                    err = ENOTDIR;
                    report_error(proc_path, err);
                    any_failed = 1;
                    free(dup);
                    continue;
                }
            } else if (!S_ISDIR(pst.st_mode)) {
                err = ENOTDIR;
                report_error(proc_path, err);
                any_failed = 1;
                free(dup);
                continue;
            }
        }

        /* Check if final component already exists */
        struct stat dummy;
        if (stat(proc_path, &dummy) == 0) {
            err = EEXIST;
            report_error(proc_path, err);
            any_failed = 1;
            free(dup);
            continue;
        }

        /* Try to create directory */
        if (mkdir(proc_path, 0777) != 0) {
            err = errno;
            report_error(proc_path, err);
            any_failed = 1;
            free(dup);
            continue;
        }
        free(dup);
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failed ? 1 : 0;
}
