#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

static void emit_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int exit_status = 0; // 0 if all succeed, 1 otherwise
    int i;
    int operands_start = 0;
    int have_operand = 0;

    // Parse arguments: detect '--' and unknown options before it
    for (i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!operands_start && strcmp(arg, "--") == 0) {
            operands_start = i + 1;
            continue;
        }
        if (!operands_start) { // still in option processing
            if (arg[0] == '-' && strcmp(arg, "-") != 0) {
                // unknown option ("--" already handled above)
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
                return 1;
            } else {
                operands_start = i; // first non-option operand
            }
        }
    }

    if (!operands_start) {
        // No '--' and no operands found (e.g., only program name)
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    // Process remaining arguments as operands
    for (i = operands_start; i < argc; ++i) {
        const char *path = argv[i];
        if (strcmp(path, "--") == 0) {
            continue; // skip stray '--' after operands start
        }
        have_operand = 1;

    // Trim trailing slashes (except when path is just "/")
    char *path_copy = strdup(path);
    if (!path_copy) {
        fprintf(stderr, "mkdir: memory allocation failed\n");
        exit_status = 1;
        /* no parent path allocated here */
        continue;
    }
    size_t len = strlen(path_copy);
    while (len > 1 && path_copy[len-1] == '/') {
        path_copy[--len] = '\0';
    }

    // Determine parent directory and final component using trimmed path
    const char *proc_path = path_copy;
    const char *slash = strrchr(proc_path, '/');
    char *parent_path2 = NULL;
    if (slash == NULL) {
        parent_path2 = strdup(".");
    } else if (slash == proc_path) { // root '/' as parent
        parent_path2 = strdup("/");
    } else {
        size_t plen = slash - proc_path;
        parent_path2 = malloc(plen + 1);
        if (!parent_path2) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            exit_status = 1;
            free(path_copy);
        // No parent_path allocated yet, nothing to free

            continue;
        }
        memcpy(parent_path2, proc_path, plen);
        parent_path2[plen] = '\0';
    }
    if (!parent_path2) {
        fprintf(stderr, "mkdir: memory allocation failed\n");
        exit_status = 1;
        free(path_copy);
        /* no parent path allocated here */
        continue;
    }

        // Check parent exists and is a directory
        struct stat st;
        if (stat(parent_path2, &st) != 0) {
            emit_error(proc_path, strerror(errno));
            exit_status = 1;
            free(parent_path2);
            free(path_copy);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            emit_error(proc_path, "Not a directory");
            exit_status = 1;
            free(parent_path2);
            free(path_copy);
            continue;
        }

        // Check final component does not already exist
        struct stat dummy;
        if (lstat(proc_path, &dummy) == 0) {
            emit_error(proc_path, "File exists");
            exit_status = 1;
            free(parent_path2);
            free(path_copy);
            continue;
        }

        // Attempt to create directory with default mode (0777 masked by umask)
        if (mkdir(proc_path, 0777) != 0) {
            emit_error(proc_path, strerror(errno));
            exit_status = 1;
            free(parent_path2);
            free(path_copy);
            continue;
        }

        free(parent_path2);
        free(path_copy);
    }

    if (!have_operand) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return exit_status;
}
