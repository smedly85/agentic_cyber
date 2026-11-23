#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <limits.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

#define XPROG "c_mv"
#define MAX_OPERANDS 256

static const char *path_basename(const char *path)
{
    size_t len = strlen(path);
    while (len > 1 && path[len - 1] == '/')
        len--;
    const char *last_slash = NULL;
    for (const char *p = path + len; p > path; ) {
        p--;
        if (*p == '/') {
            last_slash = p;
            break;
        }
    }
    return last_slash ? last_slash + 1 : path;
}

static int paths_identical(const char *a, const char *b)
{
    struct stat sa, sb;
    if (stat(a, &sa) != 0 || stat(b, &sb) != 0)
        return 0;
    return sa.st_dev == sb.st_dev && sa.st_ino == sb.st_ino;
}

static int dir_is_ancestor_or_self(const char *dir, const char *path)
{
    size_t dlen = strlen(dir);
    while (dlen > 1 && dir[dlen - 1] == '/')
        dlen--;
    if (strlen(path) == dlen && strncmp(dir, path, dlen) == 0)
        return 1;
    if (strncmp(dir, path, dlen) == 0 && path[dlen] == '/')
        return 1;
    return 0;
}

static int read_prompt_response(void)
{
    int c = getchar();
    int affirm = (c == 'y' || c == 'Y');
    while ((c = getchar()) != EOF && c != '\n')
        ;
    return affirm;
}

static int move_path(const char *src, const char *dst, int policy)
{
    struct stat src_sb;
    if (lstat(src, &src_sb) != 0) {
        fprintf(stderr, XPROG ": cannot stat '%s': %s\n", src, strerror(errno));
        return 1;
    }

    struct stat dst_sb;
    int dst_exists = (lstat(dst, &dst_sb) == 0);

    if (dst_exists) {
        if (paths_identical(src, dst)) {
            fprintf(stderr, XPROG ": '%s' and '%s' are the same file\n", src, dst);
            return 1;
        }
        int src_is_dir = S_ISDIR(src_sb.st_mode);
        int dst_is_dir = S_ISDIR(dst_sb.st_mode);
        if (src_is_dir && !dst_is_dir) {
            fprintf(stderr, XPROG
                ": cannot overwrite non-directory '%s' with directory '%s'\n",
                dst, src);
            return 1;
        }
        if (!src_is_dir && dst_is_dir) {
            fprintf(stderr, XPROG
                ": cannot overwrite directory '%s' with non-directory '%s'\n",
                dst, src);
            return 1;
        }
    } else {
        if (paths_identical(src, dst)) {
            fprintf(stderr, XPROG ": '%s' and '%s' are the same file\n", src, dst);
            return 1;
        }
    }

    if (S_ISDIR(src_sb.st_mode) && dir_is_ancestor_or_self(src, dst)) {
        fprintf(stderr, XPROG ": cannot move directory '%s' into itself\n", src);
        return 1;
    }

    if (dst_exists && policy == 2) {
        fprintf(stderr, XPROG ": overwrite '%s'? ", dst);
        fflush(stderr);
        if (!read_prompt_response())
            return 1;
    }

    if (rename(src, dst) != 0) {
        fprintf(stderr, XPROG ": cannot move '%s' to '%s': %s\n",
            src, dst, strerror(errno));
        return 1;
    }
    return 0;
}

static int construct_dest(const char *dir, const char *base, char *out, size_t outsz)
{
    size_t dlen = strlen(dir);
    while (dlen > 1 && dir[dlen - 1] == '/')
        dlen--;
    size_t blen = strlen(base);
    if (dlen + 1 + blen + 1 > outsz)
        return -1;
    memcpy(out, dir, dlen);
    out[dlen] = '/';
    memcpy(out + dlen + 1, base, blen + 1);
    return 0;
}

int main(int argc, char *argv[])
{
    const char *operands[MAX_OPERANDS];
    int n = 0;
    int after_ddash = 0;
    int policy = 0;  /* 0=none/force, 2=interactive; last occurrence wins */

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (after_ddash) {
            if (n >= MAX_OPERANDS) {
                fprintf(stderr, XPROG ": too many operands\n");
                return 1;
            }
            operands[n++] = arg;
        } else if (strcmp(arg, "--") == 0) {
            after_ddash = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-f") == 0 || strcmp(arg, "--force") == 0) {
                policy = 0;
            } else if (strcmp(arg, "-i") == 0 || strcmp(arg, "--interactive") == 0) {
                policy = 2;
            } else {
                fprintf(stderr, XPROG ": unknown option '%s'\n", arg);
                return 1;
            }
        } else {
            if (n >= MAX_OPERANDS) {
                fprintf(stderr, XPROG ": too many operands\n");
                return 1;
            }
            operands[n++] = arg;
        }
    }

    if (n < 2) {
        if (n == 0)
            fprintf(stderr, XPROG ": missing source and destination operands\n");
        else
            fprintf(stderr, XPROG ": missing destination operand\n");
        return 1;
    }

    int multi = (n > 2);
    int rc = 0;

    if (multi) {
        const char *dest_dir = operands[n - 1];
        struct stat sb;
        if (stat(dest_dir, &sb) != 0 || !S_ISDIR(sb.st_mode)) {
            fprintf(stderr, XPROG ": target '%s' is not a directory\n", dest_dir);
            return 1;
        }

        for (int i = 0; i < n - 1; i++) {
            const char *src = operands[i];
            const char *base = path_basename(src);
            char dst[PATH_MAX];
            if (construct_dest(dest_dir, base, dst, sizeof(dst)) != 0) {
                fprintf(stderr, XPROG ": path too long\n");
                rc = 1;
                continue;
            }
            if (move_path(src, dst, policy) != 0)
                rc = 1;
        }
    } else {
        const char *src = operands[0];
        const char *dst = operands[1];

        struct stat sb;
        if (lstat(dst, &sb) == 0 && S_ISDIR(sb.st_mode)) {
            const char *base = path_basename(src);
            char eff_dst[PATH_MAX];
            if (construct_dest(dst, base, eff_dst, sizeof(eff_dst)) != 0) {
                fprintf(stderr, XPROG ": path too long\n");
                return 1;
            }
            if (move_path(src, eff_dst, policy) != 0)
                rc = 1;
        } else {
            if (move_path(src, dst, policy) != 0)
                rc = 1;
        }
    }

    return rc;
}
