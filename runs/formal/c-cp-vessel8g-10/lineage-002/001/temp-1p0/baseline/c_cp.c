#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>

int copy_path(const char *src, const char *dst)
{
    struct stat src_stat;
    if (stat(src, &src_stat) != 0)
        return -1;
    if (S_ISDIR(src_stat.st_mode)) {
        errno = EISDIR;
        return -1;
    }
    if (!S_ISREG(src_stat.st_mode)) {
        errno = EPERM;
        return -1;
    }

    struct stat dst_stat;
    int dst_exists = (lstat(dst, &dst_stat) == 0);
    if (dst_exists) {
        if (S_ISDIR(dst_stat.st_mode)) {
            errno = EISDIR;
            return -1;
        }
        if (S_ISLNK(dst_stat.st_mode)) {
            if (stat(dst, &dst_stat) != 0)
                return -1;
            if (!S_ISREG(dst_stat.st_mode)) {
                errno = EPERM;
                return -1;
            }
        } else if (!S_ISREG(dst_stat.st_mode)) {
            errno = EPERM;
            return -1;
        }
        if (src_stat.st_dev == dst_stat.st_dev &&
            src_stat.st_ino == dst_stat.st_ino) {
            errno = ELOOP;
            return -1;
        }
    }

    int src_fd = open(src, O_RDONLY);
    if (src_fd < 0)
        return -1;

    int flags = O_WRONLY;
    if (dst_exists)
        flags |= O_TRUNC;
    else
        flags |= O_CREAT | O_TRUNC;

    int dst_fd = open(dst, flags, src_stat.st_mode & 0777);
    if (dst_fd < 0) {
        close(src_fd);
        return -1;
    }

    char buf[65536];
    for (;;) {
        ssize_t n = read(src_fd, buf, sizeof buf);
        if (n < 0) {
            close(src_fd);
            close(dst_fd);
            return -1;
        }
        if (n == 0)
            break;
        ssize_t off = 0;
        while (off < n) {
            ssize_t w = write(dst_fd, buf + off, (size_t)(n - off));
            if (w < 0) {
                close(src_fd);
                close(dst_fd);
                return -1;
            }
            off += w;
        }
    }

    close(src_fd);
    close(dst_fd);
    return 0;
}

int main(int argc, char *argv[])
{
    int seen_ddash = 0;
    const char *operands[8192];
    int n = 0;

    for (int i = 1; i < argc; i++) {
        if (!seen_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                seen_ddash = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "c_cp: unknown option: %s\n", argv[i]);
                return 1;
            }
        }
        if (n >= 8192) {
            fprintf(stderr, "c_cp: too many operands\n");
            return 1;
        }
        operands[n++] = argv[i];
    }

    if (n < 2) {
        fprintf(stderr, "c_cp: missing file operand\n");
        return 1;
    }

    int multi = (n > 2);

    if (multi) {
        const char *dir = operands[n - 1];
        struct stat st;
        if (stat(dir, &st) != 0 || !S_ISDIR(st.st_mode)) {
            fprintf(stderr, "c_cp: %s: not a directory\n", dir);
            return 1;
        }
    }

    int rc = 0;

    for (int i = 0; i < n - 1; i++) {
        const char *src = operands[i];
        char *dst_alloc = NULL;
        const char *dst;

        if (multi) {
            const char *dir = operands[n - 1];
            const char *slash = strrchr(src, '/');
            const char *base = (slash != NULL) ? slash + 1 : src;
            size_t dlen = strlen(dir);
            size_t blen = strlen(base);
            size_t len = dlen + 1 + blen + 1;
            dst_alloc = malloc(len);
            if (dst_alloc == NULL) {
                fprintf(stderr, "c_cp: out of memory\n");
                return 1;
            }
            memcpy(dst_alloc, dir, dlen);
            dst_alloc[dlen] = '/';
            memcpy(dst_alloc + dlen + 1, base, blen + 1);
            dst = dst_alloc;
        } else {
            const char *dest = operands[1];
            struct stat st;
            if (stat(dest, &st) == 0 && S_ISDIR(st.st_mode)) {
                const char *slash = strrchr(src, '/');
                const char *base = (slash != NULL) ? slash + 1 : src;
                size_t dlen = strlen(dest);
                size_t blen = strlen(base);
                size_t len = dlen + 1 + blen + 1;
                dst_alloc = malloc(len);
                if (dst_alloc == NULL) {
                    fprintf(stderr, "c_cp: out of memory\n");
                    return 1;
                }
                memcpy(dst_alloc, dest, dlen);
                dst_alloc[dlen] = '/';
                memcpy(dst_alloc + dlen + 1, base, blen + 1);
                dst = dst_alloc;
            } else {
                dst = dest;
            }
        }

        if (copy_path(src, dst) != 0) {
            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
            rc = 1;
        }

        if (dst_alloc != NULL)
            free(dst_alloc);
    }

    return rc;
}
