#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

static const char *basename_ptr(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static int interactive_prompt(const char *dst)
{
    fprintf(stderr, "overwrite '%s'? ", dst);
    fflush(stderr);
    int c = getchar();
    int affirm = (c == 'y' || c == 'Y');
    while ((c = getchar()) != EOF && c != '\n')
        ;
    return affirm ? 0 : 1;
}

static int copy_path(const char *src, const char *dst, int force, int interactive)
{
    struct stat src_st;
    int src_fd;
    int dst_fd;
    char buf[65536];

    src_fd = open(src, O_RDONLY);
    if (src_fd < 0) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        return -1;
    }

    if (fstat(src_fd, &src_st) < 0) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        close(src_fd);
        return -1;
    }

    if (!S_ISREG(src_st.st_mode)) {
        fprintf(stderr, "c_cp: '%s': cannot copy (not a regular file)\n", src);
        close(src_fd);
        return -1;
    }

    struct stat dst_st;
    if (stat(dst, &dst_st) == 0) {
        if (!S_ISREG(dst_st.st_mode)) {
            if (S_ISDIR(dst_st.st_mode)) {
                fprintf(stderr, "c_cp: '%s': cannot overwrite (directory)\n", dst);
                close(src_fd);
                return -1;
            }
            if (!force) {
                fprintf(stderr, "c_cp: '%s': cannot overwrite (not a regular file)\n", dst);
                close(src_fd);
                return -1;
            }
            if (unlink(dst) < 0) {
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                close(src_fd);
                return -1;
            }
            dst_fd = open(dst, O_WRONLY | O_CREAT | O_EXCL, src_st.st_mode & 0777);
            if (dst_fd < 0) {
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                close(src_fd);
                return -1;
            }
        } else {
            if (src_st.st_dev == dst_st.st_dev && src_st.st_ino == dst_st.st_ino) {
                fprintf(stderr, "c_cp: '%s' and '%s' are the same file\n", src, dst);
                close(src_fd);
                return -1;
            }

            if (interactive) {
                if (interactive_prompt(dst)) {
                    close(src_fd);
                    return -1;
                }
            }

            dst_fd = open(dst, O_WRONLY | O_TRUNC);
            if (dst_fd < 0) {
                if (!force) {
                    fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                    close(src_fd);
                    return -1;
                }
                if (unlink(dst) < 0) {
                    fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                    close(src_fd);
                    return -1;
                }
                dst_fd = open(dst, O_WRONLY | O_CREAT | O_EXCL, src_st.st_mode & 0777);
                if (dst_fd < 0) {
                    fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                    close(src_fd);
                    return -1;
                }
            }
        }
    } else {
        struct stat lst;
        if (lstat(dst, &lst) == 0) {
            if (S_ISDIR(lst.st_mode)) {
                fprintf(stderr, "c_cp: '%s': cannot create (destination is a directory)\n", dst);
                close(src_fd);
                return -1;
            }
            if (!force) {
                fprintf(stderr, "c_cp: '%s': cannot create (not a regular file or missing)\n", dst);
                close(src_fd);
                return -1;
            }
            if (unlink(dst) < 0) {
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                close(src_fd);
                return -1;
            }
            dst_fd = open(dst, O_WRONLY | O_CREAT | O_EXCL, src_st.st_mode & 0777);
            if (dst_fd < 0) {
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                close(src_fd);
                return -1;
            }
        } else {
            dst_fd = open(dst, O_WRONLY | O_CREAT | O_EXCL, src_st.st_mode & 0777);
            if (dst_fd < 0) {
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                close(src_fd);
                return -1;
            }
        }
    }

    for (;;) {
        ssize_t n = read(src_fd, buf, sizeof buf);
        if (n < 0) {
            fprintf(stderr, "c_cp: '%s': read: %s\n", src, strerror(errno));
            close(src_fd);
            close(dst_fd);
            return -1;
        }
        if (n == 0)
            break;
        size_t total = (size_t)n;
        size_t off = 0;
        while (off < total) {
            ssize_t w = write(dst_fd, buf + off, total - off);
            if (w < 0) {
                fprintf(stderr, "c_cp: '%s': write: %s\n", dst, strerror(errno));
                close(src_fd);
                close(dst_fd);
                return -1;
            }
            off += (size_t)w;
        }
    }

    close(src_fd);
    close(dst_fd);
    return 0;
}

int main(int argc, char *argv[])
{
    size_t max_ops = (size_t)(argc - 1);
    const char **operands;
    size_t n_op = 0;
    size_t i;
    int no_more_options = 0;
    int force = 0;
    int interactive = 0;

    if (max_ops == 0) {
        fprintf(stderr, "c_cp: missing operand\n");
        return 1;
    }

    operands = malloc(max_ops * sizeof *operands);
    if (!operands) {
        fprintf(stderr, "c_cp: out of memory\n");
        return 1;
    }

    for (i = 1; i < (size_t)argc; i++) {
        if (!no_more_options && strcmp(argv[i], "--") == 0) {
            no_more_options = 1;
            continue;
        }
        if (!no_more_options && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--force") == 0) {
                force = 1;
                continue;
            }
            if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--interactive") == 0) {
                interactive = 1;
                continue;
            }
            fprintf(stderr, "c_cp: invalid option -- '%s'\n", argv[i]);
            free(operands);
            return 1;
        }
        operands[n_op++] = argv[i];
    }

    if (n_op < 2) {
        fprintf(stderr, "c_cp: missing operand\n");
        free(operands);
        return 1;
    }

    /* Determine number of copy operations and build destination paths */
    size_t n_copies;
    const char **srcs;
    char **dsts;
    int any_failure = 0;

    if (n_op == 2) {
        struct stat st;
        n_copies = 1;
        srcs = malloc(sizeof *srcs);
        dsts = malloc(sizeof *dsts);
        if (!srcs || !dsts) {
            fprintf(stderr, "c_cp: out of memory\n");
            free(srcs); free(dsts); free(operands);
            return 1;
        }
        srcs[0] = operands[0];
        if (stat(operands[1], &st) == 0 && S_ISDIR(st.st_mode)) {
            const char *bn = basename_ptr(operands[0]);
            size_t len = strlen(operands[1]) + 1 + strlen(bn) + 1;
            dsts[0] = malloc(len);
            if (!dsts[0]) {
                fprintf(stderr, "c_cp: out of memory\n");
                free(srcs); free(dsts); free(operands);
                return 1;
            }
            snprintf(dsts[0], len, "%s/%s", operands[1], bn);
        } else {
            dsts[0] = malloc(strlen(operands[1]) + 1);
            if (!dsts[0]) {
                fprintf(stderr, "c_cp: out of memory\n");
                free(srcs); free(dsts); free(operands);
                return 1;
            }
            strcpy(dsts[0], operands[1]);
        }
    } else {
        struct stat st;
        if (stat(operands[n_op - 1], &st) != 0 || !S_ISDIR(st.st_mode)) {
            fprintf(stderr, "c_cp: '%s' is not a directory\n", operands[n_op - 1]);
            free(operands);
            return 1;
        }
        n_copies = n_op - 1;
        srcs = malloc(n_copies * sizeof *srcs);
        dsts = malloc(n_copies * sizeof *dsts);
        if (!srcs || !dsts) {
            fprintf(stderr, "c_cp: out of memory\n");
            free(srcs); free(dsts); free(operands);
            return 1;
        }
        const char *dir = operands[n_op - 1];
        for (i = 0; i < n_copies; i++) {
            const char *bn = basename_ptr(operands[i]);
            size_t len = strlen(dir) + 1 + strlen(bn) + 1;
            srcs[i] = operands[i];
            dsts[i] = malloc(len);
            if (!dsts[i]) {
                fprintf(stderr, "c_cp: out of memory\n");
                size_t j;
                for (j = 0; j <= i; j++) free(dsts[j]);
                free(srcs); free(dsts); free(operands);
                return 1;
            }
            snprintf(dsts[i], len, "%s/%s", dir, bn);
        }
    }

    for (i = 0; i < n_copies; i++) {
        if (copy_path(srcs[i], dsts[i], force, interactive) != 0)
            any_failure = 1;
    }

    for (i = 0; i < n_copies; i++)
        free(dsts[i]);
    free(srcs);
    free(dsts);
    free(operands);
    return any_failure ? 1 : 0;
}
