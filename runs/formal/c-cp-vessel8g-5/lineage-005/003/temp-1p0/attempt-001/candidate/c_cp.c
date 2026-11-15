#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <dirent.h>
#include <limits.h>

static int prompt_interactive(const char *dst) {
    fprintf(stderr, "override '%s'? ", dst);
    fflush(stderr);
    int c = getchar();
    int affirm = (c == 'y' || c == 'Y');
    int ch;
    while ((ch = getchar()) != EOF && ch != '\n') {}
    return affirm;
}

static int copy_path(const char *src, const char *dst, int force, int interactive) {
    int srcfd = open(src, O_RDONLY);
    if (srcfd == -1) {
        fprintf(stderr, "cannot open '%s': %s\n", src, strerror(errno));
        return -1;
    }

    struct stat src_st;
    if (fstat(srcfd, &src_st) == -1) {
        fprintf(stderr, "cannot stat '%s': %s\n", src, strerror(errno));
        close(srcfd);
        return -1;
    }

    if (!S_ISREG(src_st.st_mode)) {
        fprintf(stderr, "'%s' is not a regular file\n", src);
        close(srcfd);
        return -1;
    }

    struct stat dst_st;
    int dst_existed = (stat(dst, &dst_st) == 0);

    if (dst_existed) {
        if (!S_ISREG(dst_st.st_mode)) {
            fprintf(stderr, "'%s' is not a regular file\n", dst);
            close(srcfd);
            return -1;
        }
        if (src_st.st_dev == dst_st.st_dev && src_st.st_ino == dst_st.st_ino) {
            fprintf(stderr, "'%s' and '%s' are the same file\n", src, dst);
            close(srcfd);
            return -1;
        }

        if (interactive) {
            if (!prompt_interactive(dst)) {
                close(srcfd);
                return 1;
            }
        }
    } else {
        struct stat lstat_st;
        if (lstat(dst, &lstat_st) == 0 && S_ISLNK(lstat_st.st_mode)) {
            fprintf(stderr, "'%s' is a dangling symlink\n", dst);
            close(srcfd);
            return -1;
        }
    }

    int dstfd;
    if (dst_existed) {
        dstfd = open(dst, O_WRONLY | O_TRUNC);
        if (dstfd == -1 && force) {
            if (unlink(dst) == 0) {
                dstfd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, src_st.st_mode & 0777);
            }
        }
    } else {
        dstfd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, src_st.st_mode & 0777);
    }
    if (dstfd == -1) {
        fprintf(stderr, "cannot open '%s': %s\n", dst, strerror(errno));
        close(srcfd);
        return -1;
    }

    char buf[65536];
    for (;;) {
        ssize_t nread = read(srcfd, buf, sizeof(buf));
        if (nread == 0) {
            break;
        }
        if (nread == -1) {
            fprintf(stderr, "cannot read from '%s': %s\n", src, strerror(errno));
            close(srcfd);
            close(dstfd);
            return -1;
        }

        ssize_t nwritten = 0;
        while (nwritten < nread) {
            ssize_t w = write(dstfd, buf + nwritten, nread - nwritten);
            if (w == -1) {
                fprintf(stderr, "cannot write to '%s': %s\n", dst, strerror(errno));
                close(srcfd);
                close(dstfd);
                return -1;
            }
            nwritten += w;
        }
    }

    close(srcfd);
    close(dstfd);
    return 0;
}

static int is_self_or_descendant(const char *src, const char *dst) {
    struct stat src_st, dst_st;
    if (stat(src, &src_st) != 0 || !S_ISDIR(src_st.st_mode))
        return 0;
    if (stat(dst, &dst_st) != 0)
        return 0;
    if (src_st.st_dev == dst_st.st_dev && src_st.st_ino == dst_st.st_ino)
        return 1;

    char cwd[PATH_MAX];
    if (getcwd(cwd, sizeof(cwd)) == NULL)
        return 0;

    char src_abs[PATH_MAX], dst_abs[PATH_MAX];
    if (src[0] == '/') {
        if (snprintf(src_abs, sizeof(src_abs), "%s", src) >= (int)sizeof(src_abs))
            return 0;
    } else {
        if (snprintf(src_abs, sizeof(src_abs), "%s/%s", cwd, src) >= (int)sizeof(src_abs))
            return 0;
    }
    if (dst[0] == '/') {
        if (snprintf(dst_abs, sizeof(dst_abs), "%s", dst) >= (int)sizeof(dst_abs))
            return 0;
    } else {
        if (snprintf(dst_abs, sizeof(dst_abs), "%s/%s", cwd, dst) >= (int)sizeof(dst_abs))
            return 0;
    }

    size_t slen = strlen(src_abs);
    if (slen > 0 && strncmp(dst_abs, src_abs, slen) == 0 && dst_abs[slen] == '/')
        return 1;
    return 0;
}

static int copy_tree(const char *src, const char *dst, int force, int interactive) {
    struct stat src_st;
    if (lstat(src, &src_st) != 0) {
        fprintf(stderr, "cannot stat '%s': %s\n", src, strerror(errno));
        return 1;
    }

    struct stat dst_st;
    int dst_existed = (stat(dst, &dst_st) == 0);
    if (dst_existed) {
        if (!S_ISDIR(dst_st.st_mode)) {
            fprintf(stderr, "'%s' is not a directory\n", dst);
            return 1;
        }
    } else {
        if (mkdir(dst, src_st.st_mode & 0777) != 0) {
            fprintf(stderr, "cannot create directory '%s': %s\n", dst, strerror(errno));
            return 1;
        }
    }

    DIR *dir = opendir(src);
    if (!dir) {
        fprintf(stderr, "cannot open directory '%s': %s\n", src, strerror(errno));
        return 1;
    }

    int status = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;

        char src_path[PATH_MAX], dst_path[PATH_MAX];
        if (snprintf(src_path, sizeof(src_path), "%s/%s", src, entry->d_name) >= (int)sizeof(src_path)) {
            fprintf(stderr, "path too long: '%s/%s'\n", src, entry->d_name);
            status = 1;
            continue;
        }
        if (snprintf(dst_path, sizeof(dst_path), "%s/%s", dst, entry->d_name) >= (int)sizeof(dst_path)) {
            fprintf(stderr, "path too long: '%s/%s'\n", dst, entry->d_name);
            status = 1;
            continue;
        }

        struct stat st;
        if (lstat(src_path, &st) != 0) {
            fprintf(stderr, "cannot stat '%s': %s\n", src_path, strerror(errno));
            status = 1;
            continue;
        }

        if (S_ISREG(st.st_mode)) {
            int rc = copy_path(src_path, dst_path, force, interactive);
            if (rc != 0) status = 1;
        } else if (S_ISLNK(st.st_mode)) {
            char target[PATH_MAX];
            ssize_t tlen = readlink(src_path, target, sizeof(target) - 1);
            if (tlen == -1) {
                fprintf(stderr, "cannot read symlink '%s': %s\n", src_path, strerror(errno));
                status = 1;
                continue;
            }
            target[tlen] = '\0';

            struct stat dst_check;
            if (lstat(dst_path, &dst_check) == 0) {
                if (S_ISLNK(dst_check.st_mode)) {
                    if (unlink(dst_path) != 0) {
                        fprintf(stderr, "cannot remove '%s': %s\n", dst_path, strerror(errno));
                        status = 1;
                        continue;
                    }
                } else {
                    fprintf(stderr, "'%s' is not a symlink\n", dst_path);
                    status = 1;
                    continue;
                }
            }
            if (symlink(target, dst_path) != 0) {
                fprintf(stderr, "cannot create symlink '%s': %s\n", dst_path, strerror(errno));
                status = 1;
            }
        } else if (S_ISDIR(st.st_mode)) {
            int rc = copy_tree(src_path, dst_path, force, interactive);
            if (rc != 0) status = 1;
        } else {
            fprintf(stderr, "'%s' is a special file\n", src_path);
            status = 1;
        }
    }
    closedir(dir);
    return status;
}

static const char *basename_of(const char *path) {
    const char *slash = strrchr(path, '/');
    if (slash && slash[1] != '\0') return slash + 1;
    return path;
}

static char *join_path(const char *dir, const char *name) {
    size_t dlen = strlen(dir);
    size_t nlen = strlen(name);
    int need_slash = (dlen == 0 || dir[dlen - 1] != '/') ? 1 : 0;
    char *result = malloc(dlen + nlen + need_slash + 1);
    if (!result) return NULL;
    memcpy(result, dir, dlen);
    if (need_slash)
        result[dlen++] = '/';
    memcpy(result + dlen, name, nlen + 1);
    return result;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "missing operand\n");
        return 1;
    }

    const char **operands = malloc(argc * sizeof(char *));
    if (!operands) {
        fprintf(stderr, "memory allocation failed\n");
        return 1;
    }

    int after_ddash = 0;
    int noperands = 0;
    int force = 0;
    int interactive = 0;
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash && strcmp(argv[i], "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (!after_ddash && argv[i][0] == '-' && argv[i][1] != '\0') {
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
            fprintf(stderr, "unknown option: '%s'\n", argv[i]);
            free(operands);
            return 1;
        }
        operands[noperands++] = argv[i];
    }

    if (noperands < 2) {
        fprintf(stderr, "missing operand\n");
        free(operands);
        return 1;
    }

    // Validate multi-source destination before any filesystem changes
    if (noperands > 2) {
        const char *dest_dir = operands[noperands - 1];
        struct stat dest_st;
        if (stat(dest_dir, &dest_st) != 0 || !S_ISDIR(dest_st.st_mode)) {
            fprintf(stderr, "target directory '%s' does not exist or is not a directory\n", dest_dir);
            free(operands);
            return 1;
        }
    }

    int status = 0;

    for (int idx = 0; idx < noperands - 1; idx++) {
        const char *src = operands[idx];
        const char *dst_operand = operands[noperands - 1];

        struct stat lstat_st;
        if (lstat(src, &lstat_st) != 0) {
            fprintf(stderr, "cannot stat '%s': %s\n", src, strerror(errno));
            status = 1;
            continue;
        }

        if (recursive && S_ISDIR(lstat_st.st_mode)) {
            // Determine effective destination for the tree root
            char *effective_dst = NULL;
            struct stat dst_check;
            int dst_is_dir = (stat(dst_operand, &dst_check) == 0 && S_ISDIR(dst_check.st_mode));

            if (dst_is_dir) {
                // Existing directory: append source basename
                effective_dst = join_path(dst_operand, basename_of(src));
                if (!effective_dst) {
                    fprintf(stderr, "memory allocation failed\n");
                    free(operands);
                    return 1;
                }
            } else {
                effective_dst = strdup(dst_operand);
                if (!effective_dst) {
                    fprintf(stderr, "memory allocation failed\n");
                    free(operands);
                    return 1;
                }
            }

            // Check self-copy
            if (is_self_or_descendant(src, effective_dst)) {
                fprintf(stderr, "'%s' and '%s' are the same directory\n", src, effective_dst);
                free(effective_dst);
                status = 1;
                continue;
            }

            int rc = copy_tree(src, effective_dst, force, interactive);
            if (rc != 0) status = 1;
            free(effective_dst);
        } else if (recursive && S_ISLNK(lstat_st.st_mode)) {
            // Recreate symlink (not traversed)
            char *effective_dst = NULL;
            struct stat dst_check;
            int dst_is_dir = (stat(dst_operand, &dst_check) == 0 && S_ISDIR(dst_check.st_mode));
            if (dst_is_dir) {
                effective_dst = join_path(dst_operand, basename_of(src));
            } else {
                effective_dst = strdup(dst_operand);
            }
            if (!effective_dst) {
                fprintf(stderr, "memory allocation failed\n");
                free(operands);
                return 1;
            }

            char target[PATH_MAX];
            ssize_t tlen = readlink(src, target, sizeof(target) - 1);
            if (tlen == -1) {
                fprintf(stderr, "cannot read symlink '%s': %s\n", src, strerror(errno));
                free(effective_dst);
                status = 1;
                continue;
            }
            target[tlen] = '\0';

            struct stat dst_check2;
            if (lstat(effective_dst, &dst_check2) == 0) {
                if (!S_ISLNK(dst_check2.st_mode)) {
                    fprintf(stderr, "'%s' is not a symlink\n", effective_dst);
                    free(effective_dst);
                    status = 1;
                    continue;
                }
                unlink(effective_dst);
            }
            if (symlink(target, effective_dst) != 0) {
                fprintf(stderr, "cannot create symlink '%s': %s\n", effective_dst, strerror(errno));
                free(effective_dst);
                status = 1;
                continue;
            }
            free(effective_dst);
        } else {
            // Regular file copy (or non-recursive path: follow symlinks via open)
            char *effective_dst = NULL;
            struct stat dst_check;
            if (stat(dst_operand, &dst_check) == 0 && S_ISDIR(dst_check.st_mode)) {
                effective_dst = join_path(dst_operand, basename_of(src));
            } else {
                effective_dst = strdup(dst_operand);
            }
            if (!effective_dst) {
                fprintf(stderr, "memory allocation failed\n");
                free(operands);
                return 1;
            }

            int rc = copy_path(src, effective_dst, force, interactive);
            if (rc != 0) status = 1;
            free(effective_dst);
        }
    }

    free(operands);
    return status;
}
