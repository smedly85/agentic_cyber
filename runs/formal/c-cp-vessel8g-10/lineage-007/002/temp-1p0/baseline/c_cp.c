#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define COPY_BUF (256 * 1024)

static int copy_path(const char *src, const char *dst, int force)
{
    struct stat src_st;
    struct stat dst_st;
    int src_fd, dst_fd;
    char buf[COPY_BUF];
    ssize_t n;
    int dst_is_new;
    int rc = -1;

    if (stat(src, &src_st) != 0) {
        fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
        return -1;
    }
    if (!S_ISREG(src_st.st_mode)) {
        fprintf(stderr, "cp: %s: not a regular file\n", src);
        return -1;
    }

    int dst_exists = (stat(dst, &dst_st) == 0);
    if (dst_exists) {
        if (!S_ISREG(dst_st.st_mode)) {
            fprintf(stderr, "cp: %s: destination is not a regular file\n", dst);
            return -1;
        }
        if (src_st.st_dev == dst_st.st_dev &&
            src_st.st_ino == dst_st.st_ino) {
            fprintf(stderr, "cp: '%s' and '%s' are the same file\n", src, dst);
            return -1;
        }
        dst_is_new = 0;
    } else {
        struct stat link_st;
        if (lstat(dst, &link_st) == 0 && S_ISLNK(link_st.st_mode)) {
            if (force) {
                if (unlink(dst) != 0) {
                    fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
                    return -1;
                }
            } else {
                fprintf(stderr, "cp: %s: destination is a dangling symlink\n", dst);
                return -1;
            }
        }
        dst_is_new = 1;
    }

    src_fd = open(src, O_RDONLY);
    if (src_fd < 0) {
        fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
        return -1;
    }

    int flags = O_WRONLY | O_TRUNC;
    if (dst_is_new)
        flags |= O_CREAT;
    mode_t mode = dst_is_new ? (mode_t)(src_st.st_mode & 0777) : 0;
    dst_fd = open(dst, flags, mode);
    if (dst_fd < 0 && force && !dst_is_new) {
        struct stat dest_st;
        if (lstat(dst, &dest_st) == 0 && !S_ISDIR(dest_st.st_mode)) {
            if (unlink(dst) == 0) {
                dst_fd = open(dst, O_WRONLY | O_CREAT, (mode_t)(src_st.st_mode & 0777));
            }
        }
    }
    if (dst_fd < 0) {
        fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
        close(src_fd);
        return -1;
    }

    for (;;) {
        n = read(src_fd, buf, sizeof(buf));
        if (n < 0) {
            fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
            goto fail;
        }
        if (n == 0)
            break;
        ssize_t off = 0;
        while (off < n) {
            ssize_t w = write(dst_fd, buf + off, (size_t)(n - off));
            if (w < 0) {
                fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
                goto fail;
            }
            off += w;
        }
    }

    close(src_fd);
    close(dst_fd);
    return 0;

fail:
    close(src_fd);
    close(dst_fd);
    (void)rc;
    return -1;
}

static const char *path_basename(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static int build_path(char *buf, size_t size, const char *dir, const char *name)
{
    int n = snprintf(buf, size, "%s/%s", dir, name);
    return (n < 0 || (size_t)n >= size) ? -1 : 0;
}

int main(int argc, char *argv[])
{
    int saw_dd = 0;
    int force = 0;
    char **op = NULL;
    int n_op = 0, cap = 0;

    for (int i = 1; i < argc; i++) {
        if (!saw_dd) {
            if (strcmp(argv[i], "--") == 0) {
                saw_dd = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--force") == 0) {
                    force = 1;
                    continue;
                }
                fprintf(stderr, "cp: unknown option: %s\n", argv[i]);
                return 1;
            }
        }
        if (n_op == cap) {
            cap = cap ? cap * 2 : 8;
            char **tmp = realloc(op, (size_t)cap * sizeof(*tmp));
            if (!tmp) {
                fprintf(stderr, "cp: out of memory\n");
                free(op);
                return 1;
            }
            op = tmp;
        }
        op[n_op++] = argv[i];
    }

    if (n_op < 2) {
        fprintf(stderr, "cp: missing operand\n");
        free(op);
        return 1;
    }

    int multi = (n_op > 2);
    const char *last = op[n_op - 1];

    if (multi) {
        struct stat st;
        if (stat(last, &st) != 0 || !S_ISDIR(st.st_mode)) {
            fprintf(stderr, "cp: %s: target is not a directory\n", last);
            free(op);
            return 1;
        }
    }

    int n_src = multi ? (n_op - 1) : 1;
    int any_fail = 0;

    for (int i = 0; i < n_src; i++) {
        const char *src = op[i];
        char dst_buf[PATH_MAX];
        const char *dst;

        if (multi) {
            if (build_path(dst_buf, sizeof(dst_buf), last, path_basename(src)) != 0) {
                fprintf(stderr, "cp: %s: path too long\n", src);
                any_fail = 1;
                continue;
            }
            dst = dst_buf;
        } else {
            dst = op[1];
            struct stat st;
            if (stat(dst, &st) == 0 && S_ISDIR(st.st_mode)) {
                if (build_path(dst_buf, sizeof(dst_buf), dst, path_basename(src)) != 0) {
                    fprintf(stderr, "cp: %s: path too long\n", src);
                    any_fail = 1;
                    continue;
                }
                dst = dst_buf;
            }
        }

        if (copy_path(src, dst, force) != 0)
            any_fail = 1;
    }

    free(op);
    return any_fail ? 1 : 0;
}
