#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <limits.h>
#include <unistd.h>

static void report_error(const char *path) {
    // errno is set by the caller
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
}

int main(int argc, char *argv[]) {
    int have_operand = 0;
    int any_failure = 0;
    int parsing_options = 1; // still processing options until '--' encountered

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (parsing_options) {
            if (strcmp(arg, "--") == 0) {
                parsing_options = 0;
                continue;
            }
            // Unknown option detection: starts with '-' but is not exactly "-"
            if (arg[0] == '-' && strcmp(arg, "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
                return 1;
            }
        }
        // At this point arg is an operand
        have_operand = 1;
        const char *path = arg;
        /* Split path into parent and basename */
        char *last_slash = strrchr(path, '/');
        char parent_buf[PATH_MAX];
        const char *basename;
        if (last_slash == NULL) {
            strcpy(parent_buf, ".");
            basename = path;
        } else if (last_slash == path) { // leading slash only
            strcpy(parent_buf, "/");
            basename = last_slash + 1; // may be empty string -> treat as .?
        } else {
            size_t parent_len = last_slash - path;
            if (parent_len >= sizeof(parent_buf)) {
                errno = ENAMETOOLONG;
                report_error(path);
                any_failure = 1;
                continue;
            }
            memcpy(parent_buf, path, parent_len);
            parent_buf[parent_len] = '\0';
            basename = last_slash + 1;
        }

        // Empty basename means the argument ends with '/', treat as error like existing? We'll let mkdir handle it.
        if (basename[0] == '\0') {
            errno = ENOENT;
            report_error(path);
            any_failure = 1;
            continue;
        }

        struct stat st;
        // Check parent existence and that it's a directory
        if (stat(parent_buf, &st) != 0) {
            // parent does not exist or other error
            report_error(path);
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR;
            report_error(path);
            any_failure = 1;
            continue;
        }
        // Check whether final component already exists
        if (lstat(path, &st) == 0) {
            errno = EEXIST;
            report_error(path);
            any_failure = 1;
            continue;
        }
        // Attempt to create directory with default mode (0777 masked by umask)
        if (mkdir(path, 0777) != 0) {
            report_error(path);
            any_failure = 1;
            continue;
        }
        // success for this operand; nothing to output
    }

    if (!have_operand) {
        fprintf(stderr, "mkdir: missing operand\n");
        return 1;
    }
    return any_failure ? 1 : 0;
}
