#define _XOPEN_SOURCE 700
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <ftw.h>
#include <limits.h>

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
            if (interactive) {
                if (interactive_prompt(dst)) {
                    close(src_fd);
                    return -1;
                }
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

static int recreate_symlink(const char *src, const char *dst)
{
    char target[PATH_MAX];
    ssize_t len = readlink(src, target, sizeof target - 1);
    if (len < 0) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        return -1;
    }
    target[len] = '\0';

    struct stat st;
    if (lstat(dst, &st) == 0) {
        if (unlink(dst) < 0) {
            fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
            return -1;
        }
    }

    if (symlink(target, dst) < 0) {
        fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
        return -1;
    }
    return 0;
}

static struct {
    const char *src_abs;
    const char *dst_root;
    int force;
    int interactive;
    int any_error;
} rc_state;

static int rc_callback(const char *path, const struct stat *sb,
                       int typeflag, struct FTW *ftw)
{
    (void)ftw;

    const char *rel = path + strlen(rc_state.src_abs);
    if (*rel == '\0') return 0;

    size_t dlen = strlen(rc_state.dst_root) + strlen(rel) + 1;
    char *dst = malloc(dlen);
    if (!dst) {
        rc_state.any_error = 1;
        return 0;
    }
    snprintf(dst, dlen, "%s%s", rc_state.dst_root, rel);

    if (typeflag == FTW_D) {
        struct stat st;
        if (stat(dst, &st) != 0) {
            if (mkdir(dst, sb->st_mode & 0777) < 0) {
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                rc_state.any_error = 1;
            }
        } else if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "c_cp: '%s': destination is not a directory\n", dst);
            rc_state.any_error = 1;
        }
    } else if (typeflag == FTW_F) {
        if (copy_path(path, dst, rc_state.force, rc_state.interactive) != 0)
            rc_state.any_error = 1;
    } else if (typeflag == FTW_SL) {
        if (recreate_symlink(path, dst) != 0)
            rc_state.any_error = 1;
    } else {
        fprintf(stderr, "c_cp: '%s': unsupported file type\n", path);
        rc_state.any_error = 1;
    }

    free(dst);
    return 0;
}

static int recursive_copy(const char *src, const char *dst,
                          int force, int interactive)
{
    char *src_abs = realpath(src, NULL);
    if (!src_abs) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        return -1;
    }

    struct stat dst_st;
    if (lstat(dst, &dst_st) == 0) {
        if (S_ISLNK(dst_st.st_mode)) {
            fprintf(stderr, "c_cp: '%s': destination is a dangling symlink\n", dst);
            free(src_abs);
            return -1;
        }
        if (!S_ISDIR(dst_st.st_mode)) {
            fprintf(stderr, "c_cp: '%s': destination is not a directory\n", dst);
            free(src_abs);
            return -1;
        }
    } else {
        struct stat src_st;
        int mode = 0777;
        if (lstat(src_abs, &src_st) == 0)
            mode = src_st.st_mode & 0777;
        if (mkdir(dst, mode) < 0) {
            fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
            free(src_abs);
            return -1;
        }
    }

    char *dst_abs = realpath(dst, NULL);
    if (dst_abs) {
        size_t sl = strlen(src_abs);
        if (strcmp(src_abs, dst_abs) == 0 ||
            (sl < strlen(dst_abs) &&
             strncmp(src_abs, dst_abs, sl) == 0 &&
             dst_abs[sl] == '/')) {
            fprintf(stderr, "c_cp: '%s': cannot copy a directory into itself or a descendant\n", src);
            free(src_abs);
            free(dst_abs);
            return -1;
        }
        free(dst_abs);
    }

    rc_state.src_abs = src_abs;
    rc_state.dst_root = dst;
    rc_state.force = force;
    rc_state.interactive = interactive;
    rc_state.any_error = 0;

    int rc = nftw(src_abs, rc_callback, 32, FTW_PHYS);

    free(src_abs);

    if (rc < 0 && !rc_state.any_error) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        rc_state.any_error = 1;
    }
    return rc_state.any_error ? -1 : 0;
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
    int recursive = 0;

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
            if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
                recursive = 1;
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
        struct stat lst;
        int rc = -1;
        if (lstat(srcs[i], &lst) == 0 && S_ISLNK(lst.st_mode) && recursive) {
            rc = recreate_symlink(srcs[i], dsts[i]);
        } else if (lstat(srcs[i], &lst) == 0 && S_ISDIR(lst.st_mode) && recursive) {
            rc = recursive_copy(srcs[i], dsts[i], force, interactive);
        } else {
            rc = copy_path(srcs[i], dsts[i], force, interactive);
        }
        if (rc != 0)
            any_failure = 1;
    }

    for (i = 0; i < n_copies; i++)
        free(dsts[i]);
    free(srcs);
    free(dsts);
    free(operands);
    return any_failure ? 1 : 0;
}
