#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int ensure_dir(const char *path, int ensure_owner_wx) {
    struct stat lst;
    if (lstat(path, &lst) == 0) {
        if (S_ISDIR(lst.st_mode))
            return 0;
        if (S_ISLNK(lst.st_mode)) {
            struct stat st;
            if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
                return 0;
            errno = ENOTDIR;
            return -1;
        }
        errno = ENOTDIR;
        return -1;
    }
    if (errno != ENOENT)
        return -1;

    if (mkdir(path, 0777) == -1)
        return -1;

    if (ensure_owner_wx) {
        struct stat st;
        if (stat(path, &st) == 0 && !(st.st_mode & 0300))
            chmod(path, (st.st_mode & 07777) | 0300);
    }
    return 0;
}

static int create_parents(const char *path) {
    size_t len = strlen(path);
    if (len == 0) {
        errno = ENOENT;
        return -1;
    }

    char *buf = malloc(len + 1);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    memcpy(buf, path, len + 1);

    int result = 0;
    size_t i = 0;

    while (i < len && buf[i] == '/')
        i++;
    if (i >= len) {
        free(buf);
        return 0;
    }

    while (i < len) {
        size_t comp_start = i;
        while (i < len && buf[i] != '/')
            i++;
        size_t comp_end = i;
        size_t comp_len = comp_end - comp_start;

        if (comp_len == 1 && buf[comp_start] == '.') {
            while (i < len && buf[i] == '/')
                i++;
            continue;
        }

        int is_last = 1;
        {
            size_t j = i;
            while (j < len && buf[j] == '/')
                j++;
            while (j < len) {
                size_t k = j;
                while (k < len && buf[k] != '/')
                    k++;
                size_t next_len = k - j;
                if (!(next_len == 1 && buf[j] == '.')) {
                    is_last = 0;
                    break;
                }
                j = k;
            }
        }

        char saved = buf[comp_end];
        buf[comp_end] = '\0';
        int rc = ensure_dir(buf, !is_last);
        buf[comp_end] = saved;
        if (rc != 0) {
            result = -1;
            break;
        }

        // Advance past the slash (which is at comp_end in the original string)
        // before the next iteration
        i = comp_end + 1;
    }

    free(buf);
    return result;
}

int main(int argc, char *argv[]) {
    int parents = 0;
    int n_operands = 0;
    int after_ddash = 0;
    int i;

    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (after_ddash == 0 && strcmp(arg, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (after_ddash == 0 && arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                parents = 1;
                continue;
            }
            if (arg[1] == '-') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                                "Try 'mkdir --help' for more information.\n",
                        arg);
            } else {
                fprintf(stderr, "mkdir: invalid option -- '%c'\n"
                                "Try 'mkdir --help' for more information.\n",
                        arg[1]);
            }
            return 1;
        }
        n_operands++;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    after_ddash = 0;
    int all_ok = 1;

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (after_ddash == 0 && strcmp(arg, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (after_ddash == 0 && arg[0] == '-' && arg[1] != '\0')
            continue;

        errno = 0;
        int rc;
        if (parents)
            rc = create_parents(arg);
        else
            rc = (mkdir(arg, 0777) == -1) ? -1 : 0;

        if (rc != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    arg, strerror(errno));
            all_ok = 0;
        }
    }

    return all_ok ? 0 : 1;
}
