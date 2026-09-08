#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

static int create_parents(const char *path) {
    size_t len = strlen(path);
    if (len == 0) return 0;

    for (size_t i = 0; i <= len; i++) {
        if (path[i] == '/' || path[i] == '\0') {
            size_t prefix_len = i;
            if (prefix_len == 0) continue;

            int is_last = (i == len);

            char *prefix = malloc(prefix_len + 1);
            if (!prefix) { errno = ENOMEM; return -1; }
            memcpy(prefix, path, prefix_len);
            prefix[prefix_len] = '\0';

            struct stat st;
            int rc = stat(prefix, &st);
            if (rc == 0) {
                if (!S_ISDIR(st.st_mode)) {
                    errno = is_last ? EEXIST : ENOTDIR;
                    free(prefix);
                    return -1;
                }
            } else if (errno == ENOENT) {
                if (mkdir(prefix, 0777) != 0) {
                    free(prefix);
                    return -1;
                }
            } else {
                free(prefix);
                return -1;
            }
            free(prefix);
        }
    }
    return 0;
}

int main(int argc, char *argv[]) {
    int i;
    int end_of_options = 0;
    int parents = 0;
    int has_operand = 0;
    int ret = 0;

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                parents = 1;
                continue;
            }
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        has_operand = 1;
    }

    if (!has_operand) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    end_of_options = 0;
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && arg[1] != '\0') {
            continue;
        }
        if (parents) {
            if (create_parents(arg) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        arg, strerror(errno));
                ret = 1;
            }
        } else {
            if (mkdir(arg, 0777) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        arg, strerror(errno));
                ret = 1;
            }
        }
    }

    return ret;
}
