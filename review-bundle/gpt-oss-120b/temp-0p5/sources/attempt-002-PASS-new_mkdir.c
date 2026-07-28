#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>

static void print_error(const char *prog, const char *path, const char *msg) {
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog, path, msg);
}

int main(int argc, char *argv[]) {
    const char *prog_name = "mkdir"; // program name for messages matching GNU mkdir
    int had_error = 0;
    int end_of_options = 0;
    int operand_count = 0;

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // unknown option
            fprintf(stderr, "%s: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", prog_name, arg);
            return 1;
        }
        // treat as operand
        ++operand_count;
        const char *path = arg; // keep original for later error messages
        const char *orig_path = path;
        /* Strip trailing slashes (except when path is root "/") */
        while (path[0] != '\0' && path[strlen(path) - 1] == '/' && !(strlen(path) == 1)) {
            size_t len = strlen(path);
            char *tmp = malloc(len); // len bytes, will hold len-1 chars + '\0'
            if (!tmp) { print_error(prog_name, orig_path, "Memory allocation failed"); had_error = 1; break; }
            memcpy(tmp, path, len - 1);
            tmp[len - 1] = '\0';
            path = tmp;
        }

        /* Determine parent directory */
        char parent[PATH_MAX];
        const char *name;
        const char *slash = strrchr(path, '/');
        if (slash) {
            size_t plen = slash - path;
            if (plen == 0) {
                strcpy(parent, "/");
            } else {
            if (plen >= sizeof(parent)) {
                print_error(prog_name, orig_path, "Path too long");
                had_error = 1;
                continue;
            }
                memcpy(parent, path, plen);
                parent[plen] = '\0';
            }
            name = slash + 1; // may be empty string (e.g., trailing slash) – treat as error later
        } else {
            strcpy(parent, ".");
            name = path;
        }

        /* Reject empty final component */
            if (name[0] == '\0') {
                print_error(prog_name, orig_path, "Invalid argument");
                had_error = 1;
                continue;
            }

        struct stat sb;
            if (stat(parent, &sb) != 0) {
                // parent does not exist or cannot be accessed
                print_error(prog_name, orig_path, strerror(errno));
                had_error = 1;
                continue;
            }
            if (!S_ISDIR(sb.st_mode)) {
                // parent exists but is not a directory
                print_error(prog_name, orig_path, "Not a directory");
                had_error = 1;
                continue;
            }

        /* Check if target already exists */
            if (lstat(path, &sb) == 0) {
                // something with that name exists
                print_error(prog_name, orig_path, "File exists");
                had_error = 1;
                continue;
            }

        /* Attempt to create the directory */
            if (mkdir(path, 0777) != 0) {
                // failure – report based on errno
                print_error(prog_name, orig_path, strerror(errno));
                had_error = 1;
                continue;
            }
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\nTry 'mkdir --help' for more information.\n", prog_name);
        return 1;
    }

    return had_error ? 1 : 0;
}
