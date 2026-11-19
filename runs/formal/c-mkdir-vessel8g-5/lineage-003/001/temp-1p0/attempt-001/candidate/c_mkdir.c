#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int mkdir_parents(const char *path)
{
    size_t path_len = strlen(path);
    char *buf = malloc(path_len + 1);
    if (!buf) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                path, strerror(ENOMEM));
        return -1;
    }

    if (path[0] == '/') {
        buf[0] = '/';
        buf[1] = '\0';
    } else {
        buf[0] = '\0';
    }

    size_t i = 0;
    while (i < path_len && path[i] == '/') i++;

    for (; i < path_len; ) {
        size_t j = i;
        while (j < path_len && path[j] != '/') j++;
        size_t comp_len = j - i;

        if (comp_len == 1 && path[i] == '.') {
            i = j;
            while (i < path_len && path[i] == '/') i++;
            continue;
        }

        size_t blen = strlen(buf);
        if (blen > 0 && buf[blen - 1] != '/') {
            buf[blen] = '/';
            blen++;
        }
        memcpy(buf + blen, path + i, comp_len);
        buf[blen + comp_len] = '\0';

        size_t k = j;
        while (k < path_len && path[k] == '/') k++;
        int is_final = (k >= path_len);

        if (mkdir(buf, 0777) == 0) {
            if (!is_final) {
                mode_t mask = umask(0);
                umask(mask);
                chmod(buf, (0777 & ~mask) | 0300);
            }
        } else if (errno == EEXIST) {
            struct stat st;
            int rc = stat(buf, &st);
            if (rc == 0 && S_ISDIR(st.st_mode)) {
                /* exists as directory (or symlink to dir) — OK */
            } else {
                if (rc != 0) {
                    /* stat failed (e.g. broken symlink) — errno from stat */
                } else {
                    errno = ENOTDIR;
                }
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                free(buf);
                return -1;
            }
        } else {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            free(buf);
            return -1;
        }

        i = j;
        while (i < path_len && path[i] == '/') i++;
    }

    free(buf);
    return 0;
}

int main(int argc, char *argv[])
{
    const char *prog = "mkdir";

    int use_parents = 0;
    int terminated = 0;
    int n_operands = 0;
    const char *operands[512];

    for (int i = 1; i < argc; i++) {
        if (terminated) {
            operands[n_operands++] = argv[i];
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            terminated = 1;
            continue;
        }
        if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
            use_parents = 1;
            continue;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (argv[i][1] == '-')
                fprintf(stderr, "%s: unrecognized option '%s'\n", prog, argv[i]);
            else
                fprintf(stderr, "%s: invalid option -- '%c'\n", prog, argv[i][1]);
            fprintf(stderr, "Try '%s --help' for more information.\n", prog);
            return 1;
        }
        operands[n_operands++] = argv[i];
    }

    if (n_operands == 0) {
        fprintf(stderr, "%s: missing operand\n", prog);
        fprintf(stderr, "Try '%s --help' for more information.\n", prog);
        return 1;
    }

    int all_ok = 1;
    for (int i = 0; i < n_operands; i++) {
        const char *path = operands[i];
        if (use_parents) {
            if (mkdir_parents(path) != 0)
                all_ok = 0;
        } else {
            if (mkdir(path, 0777) != 0) {
                fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                        prog, path, strerror(errno));
                all_ok = 0;
            }
        }
    }

    return all_ok ? 0 : 1;
}
