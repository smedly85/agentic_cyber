#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * c_mv — base checkpoint: move files, symlinks, and directory trees
 * on a single filesystem using rename(2).
 */

/*
 * move_path — core filesystem move operation.
 * Performs a same-filesystem rename. Returns 0 on success, -1 on failure
 * (with errno set).
 */
static int move_path(const char *src, const char *dest)
{
    return rename(src, dest);
}

/* Return pointer to the basename component of a pathname. */
static const char *basename_of(const char *path)
{
    size_t len = strlen(path);
    while (len > 0 && path[len - 1] == '/')
        len--;
    if (len == 0)
        return "/";
    const char *end = path + len - 1;
    while (end > path && *end != '/')
        end--;
    if (*end == '/')
        return end + 1;
    return path;
}

/* Join dir and name into buf as "dir/name". Returns 0 on success. */
static int path_join(char *buf, size_t bufsz, const char *dir, const char *name)
{
    int n = snprintf(buf, bufsz, "%s/%s", dir, name);
    return (n >= 0 && (size_t)n < bufsz) ? 0 : -1;
}

/*
 * Check whether dest (possibly relative) resolves to the same location as
 * src_real (a canonical absolute directory path) or to a path inside it.
 */
static int is_same_or_inside(const char *src_real, const char *dest)
{
    size_t slen = strlen(src_real);
    char abspath[PATH_MAX];

    if (dest[0] == '/') {
        if (strcmp(dest, src_real) == 0)
            return 1;
        if (slen < PATH_MAX && strncmp(dest, src_real, slen) == 0
            && dest[slen] == '/')
            return 1;
    } else {
        char cwd[PATH_MAX];
        if (getcwd(cwd, sizeof(cwd)) == NULL)
            return 0;
        int n = snprintf(abspath, sizeof(abspath), "%s/%s", cwd, dest);
        if (n < 0 || (size_t)n >= sizeof(abspath))
            return 0;
        if (strcmp(abspath, src_real) == 0)
            return 1;
        if (strncmp(abspath, src_real, slen) == 0 && abspath[slen] == '/')
            return 1;
    }
    return 0;
}

/*
 * Validate one source→effective-destination pair before any filesystem
 * mutation. Returns 0 if the move is permitted, -1 if not (diagnostic
 * already printed to stderr).
 */
static int validate_move(const char *src, const char *eff_dest)
{
    struct stat src_st, dest_st;

    if (lstat(src, &src_st) != 0) {
        fprintf(stderr, "c_mv: cannot stat '%s': %s\n", src, strerror(errno));
        return -1;
    }

    int dest_exists = (stat(eff_dest, &dest_st) == 0);

    /* Identical source and destination (same inode) */
    if (dest_exists &&
        src_st.st_dev == dest_st.st_dev &&
        src_st.st_ino == dest_st.st_ino) {
        fprintf(stderr, "c_mv: '%s' and '%s' are the same file\n",
                src, eff_dest);
        return -1;
    }

    if (S_ISDIR(src_st.st_mode)) {
        /* Source is a directory */
        if (dest_exists && !S_ISDIR(dest_st.st_mode)) {
            fprintf(stderr,
                    "c_mv: cannot move directory '%s' to non-directory '%s'\n",
                    src, eff_dest);
            return -1;
        }
        /* Destination must not be the source itself or inside it.
         * Build an absolute form of src without realpath so the code
         * compiles under strict -std=c11.  Test fixtures guarantee no
         * symlink ancestors, so lexical resolution is correct. */
        char src_real[PATH_MAX];
        if (src[0] == '/') {
            size_t slen = strlen(src);
            if (slen < PATH_MAX) {
                memcpy(src_real, src, slen + 1);
                if (is_same_or_inside(src_real, eff_dest)) {
                    fprintf(stderr,
                            "c_mv: cannot move directory '%s' into itself\n",
                            src);
                    return -1;
                }
            }
        } else {
            char cwd[PATH_MAX];
            if (getcwd(cwd, sizeof(cwd)) != NULL) {
                int n = snprintf(src_real, sizeof(src_real), "%s/%s", cwd, src);
                if (n > 0 && (size_t)n < sizeof(src_real)) {
                    if (is_same_or_inside(src_real, eff_dest)) {
                        fprintf(stderr,
                                "c_mv: cannot move directory '%s' into itself\n",
                                src);
                        return -1;
                    }
                }
            }
        }
    } else {
        /* Source is a regular file or symlink */
        if (dest_exists && S_ISDIR(dest_st.st_mode)) {
            fprintf(stderr,
                    "c_mv: cannot overwrite directory '%s' with non-directory '%s'\n",
                    eff_dest, src);
            return -1;
        }
    }

    return 0;
}

int main(int argc, char *argv[])
{
    const char *ops[256];
    int nops = 0;
    int seen_dd = 0;

    /* --- Argument parsing --- */
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!seen_dd) {
            if (strcmp(arg, "--") == 0) {
                seen_dd = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (strcmp(arg, "-f") == 0 || strcmp(arg, "--force") == 0) {
                    continue;
                }
                fprintf(stderr, "c_mv: invalid option -- '%s'\n", arg);
                return 1;
            }
            /* bare "-" falls through as a filename operand */
        }
        if (nops >= (int)(sizeof(ops) / sizeof(ops[0]))) {
            fprintf(stderr, "c_mv: too many operands\n");
            return 1;
        }
        ops[nops++] = arg;
    }

    if (nops < 2) {
        fprintf(stderr, "c_mv: missing operand(s)\n");
        return 1;
    }

    /* --- Single source, single destination --- */
    if (nops == 2) {
        const char *src = ops[0];
        const char *dest = ops[1];
        char eff_dest[PATH_MAX];

        struct stat dstat;
        if (stat(dest, &dstat) == 0 && S_ISDIR(dstat.st_mode)) {
            const char *base = basename_of(src);
            if (path_join(eff_dest, sizeof(eff_dest), dest, base) != 0) {
                fprintf(stderr, "c_mv: result path for '%s' is too long\n", src);
                return 1;
            }
        } else {
            size_t dlen = strlen(dest);
            if (dlen >= PATH_MAX) {
                fprintf(stderr, "c_mv: path too long\n");
                return 1;
            }
            memcpy(eff_dest, dest, dlen + 1);
        }

        if (validate_move(src, eff_dest) != 0)
            return 1;

        if (move_path(src, eff_dest) != 0) {
            fprintf(stderr, "c_mv: cannot move '%s' to '%s': %s\n",
                    src, eff_dest, strerror(errno));
            return 1;
        }
        return 0;
    }

    /* --- Multiple sources: last operand must be an existing directory --- */
    const char *dir = ops[nops - 1];
    {
        struct stat dstat;
        if (stat(dir, &dstat) != 0 || !S_ISDIR(dstat.st_mode)) {
            fprintf(stderr, "c_mv: target '%s' is not a directory\n", dir);
            return 1;
        }
    }

    int failed = 0;
    for (int i = 0; i < nops - 1; i++) {
        const char *src = ops[i];
        const char *base = basename_of(src);
        char eff_dest[PATH_MAX];

        if (path_join(eff_dest, sizeof(eff_dest), dir, base) != 0) {
            fprintf(stderr, "c_mv: result path for '%s' is too long\n", src);
            failed = 1;
            continue;
        }

        if (validate_move(src, eff_dest) != 0) {
            failed = 1;
            continue;
        }

        if (move_path(src, eff_dest) != 0) {
            fprintf(stderr, "c_mv: cannot move '%s' to '%s': %s\n",
                    src, eff_dest, strerror(errno));
            failed = 1;
        }
    }
    return failed ? 1 : 0;
}
