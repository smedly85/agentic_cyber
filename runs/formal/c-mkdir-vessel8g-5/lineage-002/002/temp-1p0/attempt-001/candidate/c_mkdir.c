#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <ctype.h>

#define MAX_PATH_LEN 4096

#ifndef S_ISVTX
#define S_ISVTX 01000
#endif

static int create_parents(const char *path, mode_t um, mode_t mode, int set_mode)
{
    char buf[MAX_PATH_LEN];
    size_t buflen = 0;
    size_t i = 0;
    size_t len = strlen(path);

    if (len == 0)
        return -1;

    if (path[0] == '/')
        buf[buflen++] = '/';

    int found = 0;

    while (i < len) {
        while (i < len && path[i] == '/')
            i++;
        if (i >= len)
            break;

        size_t start = i;
        while (i < len && path[i] != '/')
            i++;
        size_t clen = i - start;
        if (clen == 0)
            continue;

        /* Determine if this is the last non-empty component. */
        int is_last = 1;
        for (size_t j = i; j < len; j++) {
            if (path[j] != '/') {
                is_last = 0;
                break;
            }
        }

        if (buflen > 0 && buf[buflen - 1] != '/')
            buf[buflen++] = '/';
        if (buflen + clen >= sizeof(buf)) {
            errno = ENAMETOOLONG;
            return -1;
        }
        memcpy(buf + buflen, path + start, clen);
        buflen += clen;
        buf[buflen] = '\0';

        found = 1;

        struct stat st;
        if (lstat(buf, &st) == 0) {
            if (S_ISDIR(st.st_mode))
                continue;
            if (S_ISLNK(st.st_mode)) {
                if (stat(buf, &st) == 0 && S_ISDIR(st.st_mode))
                    continue;
                errno = ENOTDIR;
                return -1;
            }
            errno = ENOTDIR;
            return -1;
        }

        if (errno != ENOENT)
            return -1;

        mode_t create_mode = (0777 & ~um);
        if (is_last && set_mode) {
            create_mode = mode;
        } else if (!is_last) {
            create_mode = (0777 & ~um) | 0300;
        }
        
        if (mkdir(buf, create_mode) != 0)
            return -1;
        
        if (is_last && set_mode) {
            chmod(buf, mode);
        }
    }

    if (!found) {
        struct stat st;
        if (lstat(path, &st) == 0) {
            if (S_ISDIR(st.st_mode)) {
                if (set_mode) {
                    chmod(path, mode);
                }
                return 0;
            }
            if (S_ISLNK(st.st_mode)) {
                if (stat(path, &st) == 0 && S_ISDIR(st.st_mode)) {
                    if (set_mode) {
                        chmod(path, mode);
                    }
                    return 0;
                }
            }
            errno = ENOTDIR;
        }
        return -1;
    }

    return 0;
}

/* Parse symbolic mode string and return the resulting mode */
static int parse_symbolic_mode(const char *str, mode_t *result, mode_t umask)
{
    mode_t mode = 0777;

    int clauses = 0;
    while (*str) {
        while (*str == ',')
            str++;
        if (*str == '\0')
            break;

        int who_explicit = 0;
        mode_t who = 0;
        while (*str && strchr("ugoa", *str)) {
            who_explicit = 1;
            switch (*str) {
                case 'u': who |= 0700; break;
                case 'g': who |= 0070; break;
                case 'o': who |= 0007; break;
                case 'a': who |= 0777; break;
            }
            str++;
        }
        if (!who_explicit)
            who = 0777;

        int op;
        if (*str == '+') { op = '+'; str++; }
        else if (*str == '-') { op = '-'; str++; }
        else if (*str == '=') { op = '='; str++; }
        else
            return -1;

        mode_t perms = 0;
        int has_perm = 0;
        while (*str && strchr("rwxXstugo", *str)) {
            switch (*str) {
                case 'r':
                    perms |= (who & 0444);
                    has_perm = 1;
                    break;
                case 'w':
                    perms |= (who & 0222);
                    has_perm = 1;
                    break;
                case 'x':
                    perms |= (who & 0111);
                    has_perm = 1;
                    break;
                case 'X':
                    perms |= (who & 0111);
                    has_perm = 1;
                    break;
                case 's':
                    if (who & 0400) perms |= 04000;
                    if (who & 0040) perms |= 02000;
                    has_perm = 1;
                    break;
                case 't':
                    perms |= 01000;
                    has_perm = 1;
                    break;
                case 'u':
                    perms |= (mode & 0700);
                    has_perm = 1;
                    break;
                case 'g':
                    perms |= (mode & 0070);
                    has_perm = 1;
                    break;
                case 'o':
                    perms |= (mode & 0007);
                    has_perm = 1;
                    break;
            }
            str++;
        }

        if (op != '=' && !has_perm)
            return -1;

        clauses++;

        if (who_explicit) {
            switch (op) {
                case '+':
                    mode |= perms;
                    break;
                case '-':
                    mode &= ~perms;
                    break;
                case '=': {
                    mode_t domain = who & 0777;
                    if (who & 0700) domain |= 04000;
                    if (who & 0070) domain |= 02000;
                    if (who & 0007) domain |= 01000;
                    mode = (mode & ~domain) | (perms & domain);
                    break;
                }
            }
        } else {
            mode_t ordinary = perms & 0777;
            mode_t special = perms & ~0777;
            switch (op) {
                case '+':
                    mode |= (ordinary & ~umask) | special;
                    break;
                case '-':
                    mode &= ~((ordinary & ~umask) | special);
                    break;
                case '=':
                    mode = (mode & ~0777) | (ordinary & ~umask) | special;
                    break;
            }
        }
    }

    if (clauses == 0)
        return -1;

    *result = mode;
    return 0;
}

/* Parse mode string (symbolic or octal) */
static int parse_mode(const char *str, mode_t *result, mode_t umask)
{
    if (*str == '\0')
        return -1;

    /* Check if it's an octal number */
    if (str[0] >= '0' && str[0] <= '7') {
        char *endptr;
        long val = strtol(str, &endptr, 8);
        if (*endptr != '\0' || val < 0 || val > 07777)
            return -1;
        *result = (mode_t)val;
        return 0;
    }
    
    /* Otherwise parse as symbolic mode */
    return parse_symbolic_mode(str, result, umask);
}

int main(int argc, char *argv[])
{
    int parents = 0;
    int mode_specified = 0;
    mode_t mode = 0777;
    int n_operands = 0;
    int unknown_idx = -1;

    /* Pass 1: validate all arguments before any filesystem mutation. */
    int after_ddash = 0;
    for (int i = 1; i < argc; i++) {
        if (after_ddash) {
            n_operands++;
        } else if (argv[i][0] == '-' && argv[i][1] == '-' && argv[i][2] == '\0') {
            after_ddash = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
            } else if (strncmp(argv[i], "-m", 2) == 0) {
                mode_specified = 1;
                if (argv[i][2] != '\0') {
                    if (parse_mode(argv[i] + 2, &mode, 0) != 0) {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i] + 2);
                        return 1;
                    }
                } else {
                    i++;
                    if (i >= argc) {
                        fprintf(stderr, "mkdir: option requires an argument -- 'm'\n");
                        return 1;
                    }
                    if (parse_mode(argv[i], &mode, 0) != 0) {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                        return 1;
                    }
                }
            } else if (strncmp(argv[i], "--mode", 6) == 0) {
                mode_specified = 1;
                if (argv[i][6] == '=') {
                    if (parse_mode(argv[i] + 7, &mode, 0) != 0) {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i] + 7);
                        return 1;
                    }
                } else {
                    i++;
                    if (i >= argc) {
                        fprintf(stderr, "mkdir: option requires an argument -- 'mode'\n");
                        return 1;
                    }
                    if (parse_mode(argv[i], &mode, 0) != 0) {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                        return 1;
                    }
                }
            } else if (unknown_idx < 0) {
                unknown_idx = i;
            }
        } else {
            n_operands++;
        }
    }

    if (unknown_idx >= 0) {
        const char *a = argv[unknown_idx];
        if (a[1] == '-' && a[2] != '\0')
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", a);
        else
            fprintf(stderr, "mkdir: invalid option -- '%c'\n", a[1]);
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Determine umask for -p intermediate mode computation. */
    mode_t um = 0;
    if (parents) {
        um = umask(0);
        umask(um);
    }

    /* Pass 2: create directories; continue after per-operand errors. */
    after_ddash = 0;
    int rc = 0;
    for (int i = 1; i < argc; i++) {
        const char *path;

        if (after_ddash) {
            path = argv[i];
        } else if (argv[i][0] == '-' && argv[i][1] == '-' && argv[i][2] == '\0') {
            after_ddash = 1;
            continue;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if ((argv[i][0] == '-' && argv[i][1] == 'm' && argv[i][2] == '\0') ||
                (strncmp(argv[i], "--mode", 6) == 0 && argv[i][6] != '=')) {
                i++;
            }
            continue;
        } else {
            path = argv[i];
        }

        int err;
        if (parents) {
            err = (create_parents(path, um, mode, mode_specified) != 0);
        } else {
            /* Create with permissive mode, then chmod if needed */
            if (mkdir(path, 0777) != 0) {
                err = 1;
            } else {
                err = 0;
                if (mode_specified) {
                    chmod(path, mode);
                }
            }
        }
        if (err) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            rc = 1;
        }
    }

    return rc;
}
