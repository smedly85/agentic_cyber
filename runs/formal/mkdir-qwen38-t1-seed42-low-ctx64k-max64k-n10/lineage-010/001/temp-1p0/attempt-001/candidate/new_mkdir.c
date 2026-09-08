#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int mkdir_p(const char *path)
{
    size_t len = strlen(path);
    char *buf = malloc(len + 1);
    if (!buf) return -1;
    memcpy(buf, path, len + 1);

    int rc = 0;

    for (size_t i = 0; i <= len; i++) {
        if (i < len && buf[i] != '/') continue;

        size_t prefix_len = i;
        if (i < len) buf[i] = '\0';

        if (prefix_len == 0 || (prefix_len == 1 && buf[0] == '/')) {
            if (i < len) buf[i] = '/';
            continue;
        }

        int is_final = (i == len);

        struct stat st;
        if (stat(buf, &st) == 0) {
            if (!S_ISDIR(st.st_mode)) {
                errno = is_final ? EEXIST : ENOTDIR;
                rc = -1;
                break;
            }
        } else if (mkdir(buf, 0777) != 0) {
            rc = -1;
            break;
        }

        if (i < len) buf[i] = '/';
    }

    free(buf);
    return rc;
}

int main(int argc, char *argv[])
{
    char **operands = NULL;
    int noperands = 0;
    int cap = 0;
    int end_of_opts = 0;
    int parents = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_opts && strcmp(argv[i], "--") == 0) {
            end_of_opts = 1;
            continue;
        }
        if (!end_of_opts && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
                continue;
            }
            fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                    "Try 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
        if (noperands == cap) {
            int newcap = cap ? cap * 2 : 4;
            char **tmp = realloc(operands, (size_t)newcap * sizeof(char *));
            if (!tmp) {
                fprintf(stderr, "mkdir: memory exhaustion\n");
                free(operands);
                return 1;
            }
            operands = tmp;
            cap = newcap;
        }
        operands[noperands++] = argv[i];
    }

    if (noperands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    int any_failed = 0;

    for (int i = 0; i < noperands; i++) {
        const char *path = operands[i];

        if (parents) {
            if (mkdir_p(path) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
            }
        } else {
            struct stat st;
            if (lstat(path, &st) == 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
                any_failed = 1;
                continue;
            }
            if (mkdir(path, 0777) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
                continue;
            }
        }
    }

    free(operands);
    return any_failed ? 1 : 0;
}
