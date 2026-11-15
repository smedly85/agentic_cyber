#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>
#include <dirent.h>
#include <limits.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

char *realpath(const char *path, char *resolved);

static int prompt_overwrite(const char *dst)
{
    fprintf(stderr, "c_cp: overwrite '%s'? ", dst);
    fflush(stderr);

    int c = getchar();
    int affirm = (c == 'y' || c == 'Y');
    /* Consume remainder of the line */
    while ((c = getchar()) != EOF && c != '\n')
        ;
    return affirm;
}

int copy_path(const char *src, const char *dst, int force, int interactive)
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
        if (interactive) {
            if (!prompt_overwrite(dst))
                return 1;
        }
    }

    int src_fd = open(src, O_RDONLY);
    if (src_fd < 0)
        return -1;

    int dst_fd = -1;
    if (dst_exists) {
        dst_fd = open(dst, O_WRONLY | O_TRUNC, 0);
        if (dst_fd < 0 && force) {
            if (unlink(dst) == 0)
                dst_fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC,
                              src_stat.st_mode & 0777);
        }
    } else {
        dst_fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC,
                      src_stat.st_mode & 0777);
    }
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

static int is_path_under(const char *ancestor, const char *path)
{
    size_t alen = strlen(ancestor);
    if (strncmp(path, ancestor, alen) != 0)
        return 0;
    return (path[alen] == '/' || path[alen] == '\0');
}

static int recreate_symlink(const char *src, const char *dst,
                            int force, int interactive)
{
    (void)force;
    char target[PATH_MAX];
    ssize_t tlen = readlink(src, target, sizeof target - 1);
    if (tlen < 0)
        return -1;
    target[tlen] = '\0';

    struct stat dst_stat;
    if (lstat(dst, &dst_stat) == 0) {
        if (interactive) {
            if (!prompt_overwrite(dst))
                return 1;
        }
        if (S_ISDIR(dst_stat.st_mode)) {
            errno = EISDIR;
            return -1;
        }
        if (unlink(dst) != 0)
            return -1;
    }

    if (symlink(target, dst) != 0)
        return -1;
    return 0;
}

static int copy_tree(const char *src, const char *dst,
                     int force, int interactive)
{
    struct stat src_stat;
    if (lstat(src, &src_stat) != 0)
        return -1;
    if (!S_ISDIR(src_stat.st_mode)) {
        errno = ENOTDIR;
        return -1;
    }

    /* Self-copy detection (same inode, or dst is a descendant of src) */
    char src_real[PATH_MAX];
    if (realpath(src, src_real) == NULL)
        return -1;

    struct stat dst_stat;
    int dst_exists = (lstat(dst, &dst_stat) == 0);

    if (dst_exists) {
        if (dst_stat.st_dev == src_stat.st_dev &&
            dst_stat.st_ino == src_stat.st_ino) {
            errno = ELOOP;
            return -1;
        }
        char dst_real[PATH_MAX];
        if (realpath(dst, dst_real) != NULL) {
            if (strcmp(dst_real, src_real) == 0 ||
                is_path_under(src_real, dst_real)) {
                errno = ELOOP;
                return -1;
            }
        }
    } else {
        char dst_abs[PATH_MAX];
        if (dst[0] == '/') {
            int r = snprintf(dst_abs, sizeof dst_abs, "%s", dst);
            if (r < 0 || (size_t)r >= sizeof dst_abs)
                return -1;
        } else {
            char cwd[PATH_MAX];
            if (getcwd(cwd, sizeof cwd) == NULL)
                return -1;
            int r = snprintf(dst_abs, sizeof dst_abs, "%s/%s", cwd, dst);
            if (r < 0 || (size_t)r >= sizeof dst_abs)
                return -1;
        }
        if (strcmp(dst_abs, src_real) == 0 ||
            is_path_under(src_real, dst_abs)) {
            errno = ELOOP;
            return -1;
        }
    }

    /* Create destination or validate existing type */
    if (!dst_exists) {
        if (mkdir(dst, src_stat.st_mode & 0777) != 0)
            return -1;
    } else {
        if (S_ISDIR(dst_stat.st_mode)) {
            /* usable as tree root */
        } else if (S_ISLNK(dst_stat.st_mode)) {
            if (stat(dst, &dst_stat) != 0) {
                errno = ENOENT;
                return -1;
            }
            if (!S_ISDIR(dst_stat.st_mode)) {
                errno = ENOTDIR;
                return -1;
            }
        } else {
            errno = ENOTDIR;
            return -1;
        }
    }

    /* Iterate directory entries */
    DIR *dp = opendir(src);
    if (dp == NULL)
        return -1;

    int rc = 0;
    struct dirent *entry;
    while ((entry = readdir(dp)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 ||
            strcmp(entry->d_name, "..") == 0)
            continue;

        char src_child[PATH_MAX];
        int r1 = snprintf(src_child, sizeof src_child, "%s/%s",
                          src, entry->d_name);
        if (r1 < 0 || (size_t)r1 >= sizeof src_child) {
            rc = 1;
            continue;
        }

        struct stat child_stat;
        if (lstat(src_child, &child_stat) != 0) {
            rc = 1;
            continue;
        }

        if (S_ISLNK(child_stat.st_mode)) {
            char dst_child[PATH_MAX];
            int r2 = snprintf(dst_child, sizeof dst_child, "%s/%s",
                              dst, entry->d_name);
            if (r2 < 0 || (size_t)r2 >= sizeof dst_child) {
                rc = 1;
                continue;
            }
            int r3 = recreate_symlink(src_child, dst_child,
                                      force, interactive);
            if (r3 != 0) {
                if (r3 == -1)
                    fprintf(stderr, "c_cp: %s: %s\n",
                            src_child, strerror(errno));
                rc = 1;
            }
        } else if (S_ISDIR(child_stat.st_mode)) {
            char dst_child[PATH_MAX];
            int r2 = snprintf(dst_child, sizeof dst_child, "%s/%s",
                              dst, entry->d_name);
            if (r2 < 0 || (size_t)r2 >= sizeof dst_child) {
                rc = 1;
                continue;
            }
            int r3 = copy_tree(src_child, dst_child, force, interactive);
            if (r3 != 0) {
                if (r3 == -1)
                    fprintf(stderr, "c_cp: %s: %s\n",
                            src_child, strerror(errno));
                rc = 1;
            }
        } else if (S_ISREG(child_stat.st_mode)) {
            char dst_child[PATH_MAX];
            int r2 = snprintf(dst_child, sizeof dst_child, "%s/%s",
                              dst, entry->d_name);
            if (r2 < 0 || (size_t)r2 >= sizeof dst_child) {
                rc = 1;
                continue;
            }
            int r3 = copy_path(src_child, dst_child, force, interactive);
            if (r3 != 0) {
                if (r3 == -1)
                    fprintf(stderr, "c_cp: %s: %s\n",
                            src_child, strerror(errno));
                rc = 1;
            }
        }
        /* Skip non-regular, non-dir, non-symlink entries (fifo, socket, etc.) */
    }

    closedir(dp);
    return rc;
}

int main(int argc, char *argv[])
{
    int force = 0;
    int interactive = 0;
    int recursive = 0;
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

        int result;
        {
            struct stat src_ls;
            if (lstat(src, &src_ls) != 0) {
                fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                rc = 1;
                if (dst_alloc != NULL)
                    free(dst_alloc);
                continue;
            }
            if (recursive && S_ISDIR(src_ls.st_mode)) {
                result = copy_tree(src, dst, force, interactive);
            } else if (recursive && S_ISLNK(src_ls.st_mode)) {
                result = recreate_symlink(src, dst, force, interactive);
            } else {
                result = copy_path(src, dst, force, interactive);
            }
        }

        if (result != 0) {
            if (result == -1)
                fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
            rc = 1;
        }

        if (dst_alloc != NULL)
            free(dst_alloc);
    }

    return rc;
}
