#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

static void report_error(const char *prog, const char *path)
{
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog, path,
            strerror(errno));
}

int main(int argc, char *argv[])
{
    const char *prog = "new_mkdir";
    int i;
    int end_of_options = 0;
    int operand_count = 0;
    int any_failure = 0;

    if (argc <= 1) {
        fprintf(stderr, "%s: missing operand\n", prog);
        return 1;
    }

    /* First pass: validate options and count operands */
    for (i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "%s: unrecognized option '%s'\n", prog, arg);
            return 1;
        }
        /* Treat everything else as an operand */
        operand_count++;
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", prog);
        return 1;
    }

    end_of_options = 0; /* reset for second pass */
    for (i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            /* already handled in first pass */
            continue;
        }
        const char *path = arg; // operand
        /* Determine parent directory */
        char *slash = strrchr(path, '/');
        const char *parent_path;
        if (slash) {
            size_t plen = slash - path;
            if (plen == 0) {
                parent_path = "/"; // root
            } else {
                char *tmp = strndup(path, plen);
                if (!tmp) {
                    fprintf(stderr, "%s: memory allocation failed\n", prog);
                    return 1;
                }
                parent_path = tmp; // will free later
                struct stat sb;
                if (stat(parent_path, &sb) != 0) {
                    report_error(prog, path);
                    any_failure = 1;
                    free((void *)parent_path);
                    continue;
                }
                if (!S_ISDIR(sb.st_mode)) {
                    report_error(prog, path);
                    any_failure = 1;
                    free((void *)parent_path);
                    continue;
                }
                /* parent is ok */
                free((void *)parent_path);
            }
        } else {
            parent_path = "."; // current directory
            struct stat sb;
            if (stat(parent_path, &sb) != 0) {
                report_error(prog, path);
                any_failure = 1;
                continue;
            }
            if (!S_ISDIR(sb.st_mode)) {
                report_error(prog, path);
                any_failure = 1;
                continue;
            }
        }

        /* Check if the final component already exists */
        struct stat sb2;
        if (stat(path, &sb2) == 0) {
            report_error(prog, path);
            any_failure = 1;
            continue;
        } else if (errno != ENOENT) { // some other error when checking existence
            report_error(prog, path);
            any_failure = 1;
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            report_error(prog, path);
            any_failure = 1;
            continue;
        }
    }

    return any_failure ? 1 : 0;
}
