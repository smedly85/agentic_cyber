#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <limits.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static const char *base_name(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static int copy_path(const char *src, const char *dst, int force)
{
    struct stat src_st;
    struct stat dst_st;
    int dst_exists = 0;

    if (stat(src, &src_st) != 0)
        return -1;
    if (!S_ISREG(src_st.st_mode))
        return -1;

    if (stat(dst, &dst_st) == 0) {
        dst_exists = 1;
        if (!S_ISREG(dst_st.st_mode))
            return -1;
    } else if (errno == ENOENT) {
        struct stat lstat_st;
        if (lstat(dst, &lstat_st) == 0 && S_ISLNK(lstat_st.st_mode))
            return -1;
    } else {
        return -1;
    }

    if (dst_exists && src_st.st_dev == dst_st.st_dev &&
        src_st.st_ino == dst_st.st_ino)
        return -1;

    int src_fd = open(src, O_RDONLY);
    if (src_fd < 0)
        return -1;

    int dst_fd;
    if (dst_exists) {
        dst_fd = open(dst, O_WRONLY | O_TRUNC);
        if (dst_fd < 0 && force) {
            if (unlink(dst) == 0) {
                mode_t mode = (mode_t)(src_st.st_mode & 0777);
                dst_fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, mode);
            }
        }
    } else {
        mode_t mode = (mode_t)(src_st.st_mode & 0777);
        dst_fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, mode);
    }
    if (dst_fd < 0) {
        close(src_fd);
        return -1;
    }

    char buf[65536];
    int rc = 0;
    for (;;) {
        ssize_t n = read(src_fd, buf, sizeof(buf));
        if (n < 0) {
            if (errno == EINTR)
                continue;
            rc = -1;
            break;
        }
        if (n == 0)
            break;
        ssize_t off = 0;
        while (off < n) {
            ssize_t w = write(dst_fd, buf + off, (size_t)(n - off));
            if (w < 0) {
                if (errno == EINTR)
                    continue;
                rc = -1;
                break;
            }
            off += w;
        }
        if (rc != 0)
            break;
    }

    close(src_fd);
    close(dst_fd);
    return rc;
}

int main(int argc, char *argv[])
{
    int separator_found = 0;
    int nops = 0;
    const char *ops[4096];
    int force = 0;

    for (int i = 1; i < argc; i++) {
        if (!separator_found && (strcmp(argv[i], "-f") == 0 ||
                                 strcmp(argv[i], "--force") == 0)) {
            force = 1;
            continue;
        }
        if (!separator_found && strcmp(argv[i], "--") == 0) {
            separator_found = 1;
            continue;
        }
        if (!separator_found && argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "cp: unknown option '%s'\n", argv[i]);
            return 1;
        }
        if (nops >= 4096) {
            fprintf(stderr, "cp: too many operands\n");
            return 1;
        }
        ops[nops++] = argv[i];
    }

    if (nops < 2) {
        fprintf(stderr, "cp: missing operand(s)\n");
        return 1;
    }

    int nsrc;
    const char *dest_dir = NULL;

    if (nops == 2) {
        nsrc = 1;
        struct stat st;
        if (stat(ops[1], &st) == 0 && S_ISDIR(st.st_mode))
            dest_dir = ops[1];
    } else {
        nsrc = nops - 1;
        dest_dir = ops[nops - 1];
        struct stat st;
        if (stat(dest_dir, &st) != 0 || !S_ISDIR(st.st_mode)) {
            fprintf(stderr, "cp: '%s' is not a directory\n", dest_dir);
            return 1;
        }
    }

    int any_failed = 0;

    for (int i = 0; i < nsrc; i++) {
        const char *src = ops[i];
        char dst[PATH_MAX];

        if (dest_dir) {
            const char *base = base_name(src);
            int n = snprintf(dst, sizeof(dst), "%s/%s", dest_dir, base);
            if (n < 0 || (size_t)n >= sizeof(dst)) {
                fprintf(stderr, "cp: cannot copy '%s': destination path too long\n", src);
                any_failed = 1;
                continue;
            }
        } else {
            size_t len = strlen(ops[1]);
            if (len >= PATH_MAX) {
                fprintf(stderr, "cp: cannot copy '%s': destination path too long\n", src);
                any_failed = 1;
                continue;
            }
            memcpy(dst, ops[1], len + 1);
        }

        struct stat st;
        if (stat(src, &st) == 0 && S_ISDIR(st.st_mode)) {
            fprintf(stderr, "cp: '%s' is a directory\n", src);
            any_failed = 1;
            continue;
        }

        if (copy_path(src, dst, force) != 0) {
            fprintf(stderr, "cp: cannot copy '%s' to '%s': %s\n",
                    src, dst, strerror(errno));
            any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}
