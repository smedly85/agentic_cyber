#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#include <limits.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

/* ───────────────────────── helpers ───────────────────────── */

static const char *base_name(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static int interactive_prompt(const char *dest)
{
    fprintf(stderr, "cp: overwrite '%s'? ", dest);
    fflush(stderr);

    char line[256];
    if (fgets(line, sizeof(line), stdin) == NULL)
        return 0;

    return (line[0] == 'y' || line[0] == 'Y') ? 1 : 0;
}

/* ───────────────── core file copy (semantic anchor) ───────────────── */

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

/* ───────────────── recursive support ───────────────── */

/* Returns 1 if 'path' is the same as 'dir' or a descendant of 'dir'. */
static int path_is_self_or_descendant(const char *dir, const char *path)
{
    struct stat dir_st, path_st;
    if (stat(dir, &dir_st) == 0 && stat(path, &path_st) == 0) {
        if (dir_st.st_dev == path_st.st_dev && dir_st.st_ino == path_st.st_ino)
            return 1;
    }

    size_t dlen = strlen(dir);
    if (dlen > strlen(path))
        return 0;
    if (strncmp(dir, path, dlen) != 0)
        return 0;
    if (dlen == strlen(path))
        return 1;
    return path[dlen] == '/';
}

/* Recreate a symlink at 'dst' with the same target as 'src'. */
static int copy_symlink_at(const char *src, const char *dst)
{
    char target[PATH_MAX];
    ssize_t len = readlink(src, target, sizeof(target) - 1);
    if (len < 0)
        return -1;
    target[len] = '\0';

    /* Remove existing entry at dst (file or symlink; not a directory) */
    struct stat st;
    if (lstat(dst, &st) == 0) {
        if (S_ISDIR(st.st_mode))
            return -1;
        if (unlink(dst) != 0)
            return -1;
    }

    if (symlink(target, dst) != 0)
        return -1;
    return 0;
}

/* Copy the contents of source directory 'src' into destination directory 'dst'.
   Assumes 'dst' already exists or has just been created. */
static int copy_tree_children(const char *src, const char *dst,
                              int force, int interactive, int *any_failed)
{
    DIR *d = opendir(src);
    if (d == NULL) {
        fprintf(stderr, "cp: cannot open directory '%s': %s\n", src, strerror(errno));
        *any_failed = 1;
        return -1;
    }

    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0)
            continue;

        char src_path[PATH_MAX], dst_path[PATH_MAX];
        int n1 = snprintf(src_path, sizeof(src_path), "%s/%s", src, ent->d_name);
        if (n1 < 0 || (size_t)n1 >= sizeof(src_path)) {
            fprintf(stderr, "cp: path too long: '%s'\n", ent->d_name);
            *any_failed = 1;
            continue;
        }
        int n2 = snprintf(dst_path, sizeof(dst_path), "%s/%s", dst, ent->d_name);
        if (n2 < 0 || (size_t)n2 >= sizeof(dst_path)) {
            fprintf(stderr, "cp: path too long: '%s'\n", ent->d_name);
            *any_failed = 1;
            continue;
        }

        struct stat lst;
        if (lstat(src_path, &lst) != 0) {
            fprintf(stderr, "cp: cannot stat '%s': %s\n", src_path, strerror(errno));
            *any_failed = 1;
            continue;
        }

        if (S_ISLNK(lst.st_mode)) {
            if (copy_symlink_at(src_path, dst_path) != 0) {
                fprintf(stderr, "cp: cannot copy '%s': %s\n", src_path, strerror(errno));
                *any_failed = 1;
            }
        } else if (S_ISDIR(lst.st_mode)) {
            /* Create destination subdirectory */
            if (mkdir(dst_path, lst.st_mode & 0777) != 0) {
                if (errno != EEXIST) {
                    fprintf(stderr, "cp: cannot create directory '%s': %s\n",
                            dst_path, strerror(errno));
                    *any_failed = 1;
                }
            }
            copy_tree_children(src_path, dst_path, force, interactive, any_failed);
        } else if (S_ISREG(lst.st_mode)) {
            /* Interactive prompt before overwriting existing dest */
            if (interactive) {
                struct stat dst_st;
                if (lstat(dst_path, &dst_st) == 0) {
                    if (!interactive_prompt(dst_path)) {
                        *any_failed = 1;
                        continue;
                    }
                }
            }
            if (copy_path(src_path, dst_path, force) != 0) {
                fprintf(stderr, "cp: cannot copy '%s' to '%s': %s\n",
                        src_path, dst_path, strerror(errno));
                *any_failed = 1;
            }
        } else {
            fprintf(stderr, "cp: '%s' is a special file, not copied\n", src_path);
            *any_failed = 1;
        }
    }

    closedir(d);
    return 0;
}

/* Top-level recursive copy: src is a directory.
   dst is the effective destination directory (may not exist yet). */
static void copy_tree(const char *src, const char *dst,
                      int force, int interactive, int *any_failed)
{
    struct stat dst_st;
    if (lstat(dst, &dst_st) == 0) {
        if (!S_ISDIR(dst_st.st_mode)) {
            fprintf(stderr, "cp: cannot copy '%s' to '%s': not a directory\n", src, dst);
            *any_failed = 1;
            return;
        }
    } else if (errno == ENOENT) {
        struct stat src_st;
        if (stat(src, &src_st) != 0) {
            *any_failed = 1;
            return;
        }
        if (mkdir(dst, src_st.st_mode & 0777) != 0) {
            fprintf(stderr, "cp: cannot create directory '%s': %s\n", dst, strerror(errno));
            *any_failed = 1;
            return;
        }
    } else {
        fprintf(stderr, "cp: cannot access '%s': %s\n", dst, strerror(errno));
        *any_failed = 1;
        return;
    }

    copy_tree_children(src, dst, force, interactive, any_failed);
}

/* ───────────────── main ───────────────── */

int main(int argc, char *argv[])
{
    int separator_found = 0;
    int nops = 0;
    const char *ops[4096];
    int force = 0;
    int interactive = 0;
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        if (!separator_found) {
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
            if (strcmp(argv[i], "--") == 0) {
                separator_found = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "cp: unknown option '%s'\n", argv[i]);
                return 1;
            }
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

        struct stat lst;
        if (lstat(src, &lst) != 0) {
            fprintf(stderr, "cp: cannot stat '%s': %s\n", src, strerror(errno));
            any_failed = 1;
            continue;
        }

        if (S_ISLNK(lst.st_mode)) {
            if (recursive) {
                if (copy_symlink_at(src, dst) != 0) {
                    fprintf(stderr, "cp: cannot copy '%s' to '%s': %s\n",
                            src, dst, strerror(errno));
                    any_failed = 1;
                }
            } else {
                struct stat fst;
                if (stat(src, &fst) != 0 || !S_ISREG(fst.st_mode)) {
                    fprintf(stderr, "cp: '%s' is not a regular file\n", src);
                    any_failed = 1;
                    continue;
                }
                if (interactive) {
                    struct stat dst_st;
                    if (lstat(dst, &dst_st) == 0) {
                        if (!interactive_prompt(dst)) {
                            any_failed = 1;
                            continue;
                        }
                    }
                }
                if (copy_path(src, dst, force) != 0) {
                    fprintf(stderr, "cp: cannot copy '%s' to '%s': %s\n",
                            src, dst, strerror(errno));
                    any_failed = 1;
                }
            }
        } else if (S_ISDIR(lst.st_mode)) {
            if (recursive) {
                if (path_is_self_or_descendant(src, dst)) {
                    fprintf(stderr, "cp: '%s' is a subdirectory of '%s'\n", dst, src);
                    any_failed = 1;
                    continue;
                }
                copy_tree(src, dst, force, interactive, &any_failed);
            } else {
                fprintf(stderr, "cp: '%s' is a directory\n", src);
                any_failed = 1;
                continue;
            }
        } else if (S_ISREG(lst.st_mode)) {
            if (interactive) {
                struct stat dst_st;
                if (lstat(dst, &dst_st) == 0) {
                    if (!interactive_prompt(dst)) {
                        any_failed = 1;
                        continue;
                    }
                }
            }
            if (copy_path(src, dst, force) != 0) {
                fprintf(stderr, "cp: cannot copy '%s' to '%s': %s\n",
                        src, dst, strerror(errno));
                any_failed = 1;
            }
        } else {
            fprintf(stderr, "cp: '%s' is a special file, not copied\n", src);
            any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}
