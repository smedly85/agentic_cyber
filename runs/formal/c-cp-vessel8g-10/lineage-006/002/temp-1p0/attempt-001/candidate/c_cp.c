#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <limits.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static int opt_force = 0;
static int opt_interactive = 0;

static int interactive_confirm(const char *dst)
{
    fprintf(stderr, "c_cp: overwrite '%s'? ", dst);
    fflush(stderr);

    int first = getchar();
    if (first == EOF)
        return 0;
    int c;
    while ((c = getchar()) != EOF && c != '\n')
        ;
    return (first == 'y' || first == 'Y') ? 1 : 0;
}

static int copy_path(const char *src, const char *dst)
{
    struct stat st_src;
    struct stat st_dst;
    int dst_exists = 0;

    if (stat(src, &st_src) != 0) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        return -1;
    }
    if (!S_ISREG(st_src.st_mode)) {
        fprintf(stderr, "c_cp: '%s': not a regular file\n", src);
        return -1;
    }

    if (lstat(dst, &st_dst) == 0) {
        dst_exists = 1;
        if (S_ISLNK(st_dst.st_mode)) {
            char resolved[PATH_MAX];
            if (realpath(dst, resolved) == NULL) {
                fprintf(stderr, "c_cp: '%s': dangling symlink\n", dst);
                return -1;
            }
            if (stat(resolved, &st_dst) != 0) {
                fprintf(stderr, "c_cp: '%s': dangling symlink\n", dst);
                return -1;
            }
        }
        if (!S_ISREG(st_dst.st_mode)) {
            fprintf(stderr, "c_cp: '%s': not a regular file\n", dst);
            return -1;
        }
    }

    if (dst_exists && st_src.st_dev == st_dst.st_dev && st_src.st_ino == st_dst.st_ino) {
        fprintf(stderr, "c_cp: '%s' and '%s': are the same file\n", src, dst);
        return -1;
    }

    if (opt_interactive && dst_exists) {
        if (!interactive_confirm(dst)) {
            fprintf(stderr, "c_cp: not overwriting '%s'\n", dst);
            return -1;
        }
    }

    int fd_src = open(src, O_RDONLY);
    if (fd_src < 0) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        return -1;
    }

    mode_t new_mode = st_src.st_mode & 0777;
    int fd_dst = open(dst, O_WRONLY | O_CREAT | O_TRUNC, new_mode);
    if (fd_dst < 0) {
        if (opt_force && dst_exists) {
            if (unlink(dst) != 0) {
                fprintf(stderr, "c_cp: cannot remove '%s': %s\n", dst, strerror(errno));
                close(fd_src);
                return -1;
            }
            fd_dst = open(dst, O_WRONLY | O_CREAT, new_mode);
            if (fd_dst < 0) {
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                close(fd_src);
                return -1;
            }
        } else {
            fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
            close(fd_src);
            return -1;
        }
    }

    char buf[65536];
    ssize_t n;
    while ((n = read(fd_src, buf, sizeof buf)) > 0) {
        ssize_t off = 0;
        while (off < n) {
            ssize_t w = write(fd_dst, buf + off, (size_t)(n - off));
            if (w < 0) {
                if (errno == EINTR)
                    continue;
                fprintf(stderr, "c_cp: '%s': %s\n", dst, strerror(errno));
                close(fd_src);
                close(fd_dst);
                return -1;
            }
            off += w;
        }
    }
    if (n < 0) {
        fprintf(stderr, "c_cp: '%s': %s\n", src, strerror(errno));
        close(fd_src);
        close(fd_dst);
        return -1;
    }

    close(fd_src);
    close(fd_dst);
    return 0;
}

int main(int argc, char *argv[])
{
    const char *operands[256];
    int n_op = 0;
    int after_ddash = 0;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = 1;
                continue;
            }
            if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--force") == 0) {
                opt_force = 1;
                continue;
            }
            if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--interactive") == 0) {
                opt_interactive = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "c_cp: unknown option '%s'\n", argv[i]);
                return 1;
            }
        }
        if (n_op >= 256) {
            fprintf(stderr, "c_cp: too many operands\n");
            return 1;
        }
        operands[n_op++] = argv[i];
    }

    if (n_op < 2) {
        fprintf(stderr, "c_cp: missing operand\n");
        return 1;
    }

    int multi = (n_op > 2);
    if (multi) {
        const char *dir = operands[n_op - 1];
        struct stat st;
        if (stat(dir, &st) != 0 || !S_ISDIR(st.st_mode)) {
            fprintf(stderr, "c_cp: '%s': not a directory\n", dir);
            return 1;
        }
    }

    int rc = 0;
    for (int i = 0; i < n_op - 1; i++) {
        const char *src = operands[i];
        char dst_buf[PATH_MAX];
        const char *dst;

        if (multi) {
            const char *base = strrchr(src, '/');
            base = base ? base + 1 : src;
            int len = snprintf(dst_buf, sizeof dst_buf, "%s/%s", operands[n_op - 1], base);
            if (len < 0 || (size_t)len >= sizeof dst_buf) {
                fprintf(stderr, "c_cp: path too long\n");
                rc = 1;
                continue;
            }
            dst = dst_buf;
        } else {
            dst = operands[1];
        }

        if (copy_path(src, dst) != 0)
            rc = 1;
    }

    return rc;
}
