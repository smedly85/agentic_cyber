#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

static int copy_path(const char *src, const char *dst, int force) {
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

    int status = 0;

    if (noperands == 2) {
        const char *src = operands[0];
        const char *dst = operands[1];

        struct stat dst_st;
        if (stat(dst, &dst_st) == 0 && S_ISDIR(dst_st.st_mode)) {
            const char *name = strrchr(src, '/');
            char *effective_dst;
            if (name && name[1] != '\0') {
                effective_dst = malloc(strlen(dst) + 1 + strlen(name + 1) + 1);
                if (!effective_dst) {
                    fprintf(stderr, "memory allocation failed\n");
                    free(operands);
                    return 1;
                }
                sprintf(effective_dst, "%s/%s", dst, name + 1);
            } else {
                effective_dst = malloc(strlen(dst) + 1 + strlen(src) + 1);
                if (!effective_dst) {
                    fprintf(stderr, "memory allocation failed\n");
                    free(operands);
                    return 1;
                }
                sprintf(effective_dst, "%s/%s", dst, src);
            }
            if (copy_path(src, effective_dst, force) == -1) {
                status = 1;
            }
            free(effective_dst);
        } else {
            if (copy_path(src, dst, force) == -1) {
                status = 1;
            }
        }
    } else {
        const char *dest_dir = operands[noperands - 1];
        struct stat dest_st;
        if (stat(dest_dir, &dest_st) != 0 || !S_ISDIR(dest_st.st_mode)) {
            fprintf(stderr, "target directory '%s' does not exist or is not a directory\n", dest_dir);
            free(operands);
            return 1;
        }

        int nsrc = noperands - 1;
        for (int i = 0; i < nsrc; i++) {
            const char *src = operands[i];
            const char *name = strrchr(src, '/');
            char *effective_dst;
            if (name && name[1] != '\0') {
                effective_dst = malloc(strlen(dest_dir) + 1 + strlen(name + 1) + 1);
                if (!effective_dst) {
                    fprintf(stderr, "memory allocation failed\n");
                    free(operands);
                    return 1;
                }
                sprintf(effective_dst, "%s/%s", dest_dir, name + 1);
            } else {
                effective_dst = malloc(strlen(dest_dir) + 1 + strlen(src) + 1);
                if (!effective_dst) {
                    fprintf(stderr, "memory allocation failed\n");
                    free(operands);
                    return 1;
                }
                sprintf(effective_dst, "%s/%s", dest_dir, src);
            }
            if (copy_path(src, effective_dst, force) == -1) {
                status = 1;
            }
            free(effective_dst);
        }
    }

    free(operands);
    return status;
}
