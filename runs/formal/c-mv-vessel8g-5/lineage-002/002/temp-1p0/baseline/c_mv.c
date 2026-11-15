#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <dirent.h>

/* POSIX realpath may be hidden by glibc under -std=c11 strict mode. */
extern char *realpath(const char *restrict path, char *restrict resolved);

/* move_path: core filesystem operation — moves src to dest via rename() */
static int move_path(const char *src, const char *dest, int force)
{
    if (rename(src, dest) != 0) {
        if (force && (errno == EACCES || errno == EPERM)) {
            if (unlink(dest) == 0) {
                if (rename(src, dest) == 0)
                    return 0;
            }
        }
        fprintf(stderr, "mv: cannot move '%s' to '%s': %s\n",
                src, dest, strerror(errno));
        return -1;
    }
    return 0;
}

/* Returns 1 if directory is empty, 0 if not, -1 on error */
static int dir_is_empty(const char *path)
{
    DIR *d = opendir(path);
    if (!d)
        return -1;
    struct dirent *entry;
    while ((entry = readdir(d)) != NULL) {
        if (strcmp(entry->d_name, ".") != 0 &&
            strcmp(entry->d_name, "..") != 0) {
            closedir(d);
            return 0;
        }
    }
    closedir(d);
    return 1;
}

/* Returns pointer to the last path component (after final '/') */
static const char *path_basename(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

/* Returns 1 if desc is a proper sub-path of anc (both absolute, no trailing /) */
static int is_proper_descendant(const char *anc, const char *desc)
{
    size_t len = strlen(anc);
    if (strncmp(desc, anc, len) != 0)
        return 0;
    if (len == strlen(desc))
        return 0;
    return desc[len] == '/';
}

int main(int argc, char **argv)
{
    /* --- Parse arguments --- */
    int force = 0;
    int seen_ddash = 0;

    /* Pass 1: validate and count operands */
    int n_ops = 0;
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
                fprintf(stderr, "mv: invalid option -- '%c'\n", argv[i][1]);
                return 1;
            }
        }
        n_ops++;
    }

    if (n_ops < 2) {
        fprintf(stderr, "mv: missing destination operand\n");
        return 1;
    }

    /* Pass 2: collect operand pointers */
    const char **ops = malloc((size_t)n_ops * sizeof(*ops));
    if (!ops) {
        fprintf(stderr, "mv: out of memory\n");
        return 1;
    }
    n_ops = 0;
    seen_ddash = 0;
    for (int i = 1; i < argc; i++) {
        if (!seen_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                seen_ddash = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0' &&
                (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--force") == 0)) {
                continue;
            }
        }
        ops[n_ops++] = argv[i];
    }

    int n_sources = n_ops - 1;
    const char *dest = ops[n_ops - 1];

    /* --- Determine destination type --- */
    struct stat st_dest;
    int dest_exists = (lstat(dest, &st_dest) == 0);
    int dest_is_dir = 0;

    if (n_sources > 1) {
        if (!dest_exists || !S_ISDIR(st_dest.st_mode)) {
            fprintf(stderr, "mv: target '%s' is not a directory\n", dest);
            free(ops);
            return 1;
        }
        dest_is_dir = 1;
    } else if (dest_exists) {
        dest_is_dir = S_ISDIR(st_dest.st_mode);
    }

    /* --- Process each source in order --- */
    int any_failed = 0;

    for (int i = 0; i < n_sources; i++) {
        const char *src = ops[i];

        /* Source must exist */
        struct stat st_src;
        if (lstat(src, &st_src) != 0) {
            fprintf(stderr, "mv: cannot stat '%s': %s\n", src, strerror(errno));
            any_failed = 1;
            continue;
        }
        int src_is_dir = S_ISDIR(st_src.st_mode);

        /* Compute effective destination */
        char *eff_dest;
        if (dest_is_dir) {
            const char *base = path_basename(src);
            size_t dlen = strlen(dest);
            size_t blen = strlen(base);
            eff_dest = malloc(dlen + 1 + blen + 1);
            if (!eff_dest) {
                fprintf(stderr, "mv: out of memory\n");
                free(ops);
                return 1;
            }
            memcpy(eff_dest, dest, dlen);
            eff_dest[dlen] = '/';
            memcpy(eff_dest + dlen + 1, base, blen + 1);
        } else {
            eff_dest = strdup(dest);
            if (!eff_dest) {
                fprintf(stderr, "mv: out of memory\n");
                free(ops);
                return 1;
            }
        }

        /* Validate effective destination before any change */
        struct stat st_eff;
        int eff_exists = (lstat(eff_dest, &st_eff) == 0);
        int eff_is_dir = eff_exists && S_ISDIR(st_eff.st_mode);
        int skip = 0;

        if (eff_exists) {
            /* Type compatibility: nondir must not replace dir */
            if (!src_is_dir && eff_is_dir) {
                fprintf(stderr,
                        "mv: cannot overwrite directory '%s' with non-directory '%s'\n",
                        eff_dest, src);
                skip = 1;
            }
            /* Type compatibility: dir must not replace nondir */
            else if (src_is_dir && !eff_is_dir) {
                fprintf(stderr,
                        "mv: cannot move directory '%s' to non-directory '%s'\n",
                        src, eff_dest);
                skip = 1;
            }

            /* Resolve real paths for identity / descendant checks */
            char *real_src = NULL;
            char *real_eff = NULL;
            if (!skip) {
                real_src = realpath(src, NULL);
                real_eff = realpath(eff_dest, NULL);
                if (real_src && real_eff) {
                    /* Identical source and destination */
                    if (strcmp(real_src, real_eff) == 0) {
                        fprintf(stderr,
                                "mv: '%s' and '%s' are the same file\n",
                                src, eff_dest);
                        skip = 1;
                    }
                    /* Directory moved into itself or a descendant */
                    else if (src_is_dir &&
                             is_proper_descendant(real_src, real_eff)) {
                        fprintf(stderr,
                                "mv: cannot move '%s' into a subdirectory of itself, '%s'\n",
                                src, eff_dest);
                        skip = 1;
                    }
                }
            }

            /* If both are directories, destination must be empty */
            if (!skip && src_is_dir && eff_is_dir) {
                if (dir_is_empty(eff_dest) != 1) {
                    fprintf(stderr,
                            "mv: cannot overwrite non-empty directory '%s' with directory '%s'\n",
                            eff_dest, src);
                    skip = 1;
                }
            }

            free(real_src);
            free(real_eff);
        } else {
            /* Effective dest does not exist — check dir-into-itself textually */
            if (src_is_dir) {
                char *real_src = realpath(src, NULL);
                if (real_src) {
                    /* Resolve the parent of eff_dest to build a real path */
                    char *parent_copy = strdup(eff_dest);
                    if (parent_copy) {
                        char *last_slash = strrchr(parent_copy, '/');
                        if (last_slash) {
                            *last_slash = '\0';
                        }
                        char *real_parent = realpath(parent_copy, NULL);
                        if (real_parent) {
                            size_t plen = strlen(real_parent);
                            size_t src_len = strlen(real_src);
                            if (strncmp(real_parent, real_src, src_len) == 0 &&
                                (real_parent[src_len] == '/' ||
                                 (last_slash == NULL && plen == src_len))) {
                                fprintf(stderr,
                                        "mv: cannot move '%s' into a subdirectory of itself, '%s'\n",
                                        src, eff_dest);
                                skip = 1;
                            }
                            free(real_parent);
                        }
                        free(parent_copy);
                    }
                    free(real_src);
                }
            }
        }

        if (skip) {
            free(eff_dest);
            any_failed = 1;
            continue;
        }

        /* Perform the move */
        if (move_path(src, eff_dest, force) != 0)
            any_failed = 1;

        free(eff_dest);
    }

    free(ops);
    return any_failed ? 1 : 0;
}
