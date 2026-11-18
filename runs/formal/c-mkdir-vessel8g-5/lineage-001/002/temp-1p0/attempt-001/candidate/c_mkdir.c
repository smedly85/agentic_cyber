#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <stdlib.h>

#define PROGNAM "mkdir"

/* Returns 1 if the expression is sticky-bit-only: contains 't' as a
   special bit, no ordinary bits (r/w/x/X), and no 's' (setuid/setgid).
   Per spec: "Do not generalize this sticky-only behavior into a masked
   starting mode for other symbolic expressions." */
static int is_sticky_only(const char *str)
{
    int has_ordinary = 0, has_t = 0, has_s = 0;
    for (const char *p = str; *p; p++) {
        switch (*p) {
        case 'r': case 'w': case 'x': case 'X':
            has_ordinary = 1;
            break;
        case 't':
            has_t = 1;
            break;
        case 's':
            has_s = 1;
            break;
        default:
            break;
        }
    }
    return has_t && !has_ordinary && !has_s;
}

static mode_t parse_mode_str(const char *str, mode_t umask)
{
    if (!str || !*str)
        return (mode_t)-1;

    /* Numeric octal */
    int all_octal = 1;
    for (const char *c = str; *c; c++) {
        if (*c < '0' || *c > '7') { all_octal = 0; break; }
    }
    if (all_octal) {
        mode_t val = 0;
        for (const char *c = str; *c; c++) {
            val = (val << 3) | (*c - '0');
            if (val > 07777) return (mode_t)-1;
        }
        return val;
    }

    /* Symbolic */
    mode_t mode = is_sticky_only(str) ? 0755 : 0777;
    const char *p = str;

    while (*p) {
        int who_u = 0, who_g = 0, who_o = 0, has_who = 0;

        if (*p == 'a') {
            who_u = who_g = who_o = 1; has_who = 1; p++;
        } else {
            while (*p == 'u' || *p == 'g' || *p == 'o') {
                if (*p == 'u') who_u = 1;
                else if (*p == 'g') who_g = 1;
                else who_o = 1;
                has_who = 1; p++;
            }
        }

        if (*p != '+' && *p != '-' && *p != '=')
            return (mode_t)-1;
        char op = *p++;

        int p_r=0, p_w=0, p_x=0, p_s=0, p_t=0;
        int copy_u=0, copy_g=0, copy_o=0;

        while (*p && *p != ',') {
            switch (*p) {
            case 'r': p_r=1; break;
            case 'w': p_w=1; break;
            case 'x': p_x=1; break;
            case 'X': p_x=1; break;
            case 's': p_s=1; break;
            case 't': p_t=1; break;
            case 'u': copy_u=1; break;
            case 'g': copy_g=1; break;
            case 'o': copy_o=1; break;
            default: return (mode_t)-1;
            }
            p++;
        }

        mode_t perm = 0;

        if (p_r || p_w || p_x) {
            if (who_u || !has_who) {
                if (p_r) perm |= 0400;
                if (p_w) perm |= 0200;
                if (p_x) perm |= 0100;
            }
            if (who_g || !has_who) {
                if (p_r) perm |= 040;
                if (p_w) perm |= 020;
                if (p_x) perm |= 010;
            }
            if (who_o || !has_who) {
                if (p_r) perm |= 004;
                if (p_w) perm |= 002;
                if (p_x) perm |= 001;
            }
        }
        if (p_s) {
            if (who_u || !has_who) perm |= 04000;
            if (who_g || !has_who) perm |= 02000;
            if (who_o || !has_who) perm |= 01000;
        }
        if (p_t) perm |= 01000;

        if (copy_u) {
            mode_t src = mode & 0700;
            if (who_u || !has_who) perm |= src;
            if (who_g || !has_who) perm |= (src >> 3);
            if (who_o || !has_who) perm |= (src >> 6);
        }
        if (copy_g) {
            mode_t src = mode & 0070;
            if (who_u || !has_who) perm |= (src << 3);
            if (who_g || !has_who) perm |= src;
            if (who_o || !has_who) perm |= (src << 6);
        }
        if (copy_o) {
            mode_t src = mode & 0007;
            if (who_u || !has_who) perm |= (src << 6);
            if (who_g || !has_who) perm |= (src << 3);
            if (who_o || !has_who) perm |= src;
        }

        if (has_who) {
            mode_t wm = 0;
            if (who_u) wm |= 07000;
            if (who_g) wm |= 02070;
            if (who_o) wm |= 01007;

            if (op == '+') {
                mode |= (perm & wm);
            } else if (op == '-') {
                mode &= ~(perm & wm);
            } else {
                mode_t om = wm & 0777;
                mode = (mode & ~om) | (perm & om);
                if (p_s || p_t) {
                    mode_t sm = wm & 07000;
                    mode = (mode & ~sm) | (perm & sm);
                } else {
                    if (wm & 01000) mode &= ~01000;
                }
            }
        } else {
            if (op == '+') {
                mode |= ((perm & 0777) & ~umask) | (perm & 07000);
            } else if (op == '-') {
                mode &= ~(((perm & 0777) & ~umask) | (perm & 07000));
            } else {
                mode = (mode & 07000) | ((perm & 0777) & ~umask);
                if (p_s || p_t) {
                    mode = (mode & 0777) | (perm & 07000);
                } else {
                    mode &= ~01000;
                }
            }
        }

        if (*p == ',') { p++; continue; }
        break;
    }
    return mode;
}

static int create_one(const char *path, int use_parents,
                      int mode_specified, mode_t parsed_mode)
{
    if (use_parents) {
        size_t len = strlen(path);
        char *copy = malloc(len + 1);
        if (!copy) { errno = ENOMEM; return -1; }
        memcpy(copy, path, len + 1);

        int rc = 0;
        int final_created = 0;

        for (size_t i = 1; i < len; i++) {
            if (copy[i] != '/') continue;
            copy[i] = '\0';
            if (copy[0] == '\0' || strcmp(copy, "/") == 0) {
                copy[i] = '/';
                continue;
            }
            if (mkdir(copy, 0777) != 0) {
                if (errno == EEXIST) {
                    struct stat st;
                    if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                        errno = ENOTDIR;
                        rc = -1;
                        break;
                    }
                } else { rc = -1; break; }
            }
            copy[i] = '/';
        }

        if (rc == 0) {
            mode_t final_mk_mode = mode_specified ? (parsed_mode | 07777) : 0777;
            if (mkdir(copy, final_mk_mode) == 0) {
                final_created = 1;
            } else if (errno == EEXIST) {
                struct stat st;
                if (stat(copy, &st) != 0) {
                    rc = -1;
                } else if (!S_ISDIR(st.st_mode)) {
                    errno = ENOTDIR;
                    rc = -1;
                }
            } else { rc = -1; }
        }

        if (rc == 0 && final_created && mode_specified) {
            if (chmod(copy, parsed_mode) != 0)
                rc = -1;
        }

        free(copy);
        return rc;
    } else {
        mode_t mk_mode = mode_specified ? (parsed_mode | 07777) : 0777;
        if (mkdir(path, mk_mode) == 0) {
            if (mode_specified && chmod(path, parsed_mode) != 0)
                return -1;
            return 0;
        }
        return -1;
    }
}

int main(int argc, char *argv[])
{
    int in_positional = 0;
    int operand_count = 0;
    int any_failed = 0;
    int use_parents = 0;
    int mode_specified = 0;
    mode_t parsed_mode = 0;
    int i;

    /* Phase 1: validate all arguments before any filesystem mutation */
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (in_positional) {
            operand_count++;
        } else if (strcmp(arg, "--") == 0) {
            in_positional = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                use_parents = 1;
            } else if (strcmp(arg, "-m") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "%s: option requires an argument -- 'm'\n", PROGNAM);
                    return 1;
                }
                i++;
                mode_t m = parse_mode_str(argv[i], 0);
                if (m == (mode_t)-1) {
                    fprintf(stderr, "%s: invalid mode '%s'\n", PROGNAM, argv[i]);
                    return 1;
                }
                parsed_mode = m; mode_specified = 1;
            } else if (arg[1] == 'm' && arg[2] != '\0') {
                mode_t m = parse_mode_str(arg + 2, 0);
                if (m == (mode_t)-1) {
                    fprintf(stderr, "%s: invalid mode '%s'\n", PROGNAM, arg + 2);
                    return 1;
                }
                parsed_mode = m; mode_specified = 1;
            } else if (strcmp(arg, "--mode") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "%s: option requires an argument -- 'mode'\n", PROGNAM);
                    return 1;
                }
                i++;
                mode_t m = parse_mode_str(argv[i], 0);
                if (m == (mode_t)-1) {
                    fprintf(stderr, "%s: invalid mode '%s'\n", PROGNAM, argv[i]);
                    return 1;
                }
                parsed_mode = m; mode_specified = 1;
            } else if (strncmp(arg, "--mode=", 7) == 0) {
                mode_t m = parse_mode_str(arg + 7, 0);
                if (m == (mode_t)-1) {
                    fprintf(stderr, "%s: invalid mode '%s'\n", PROGNAM, arg + 7);
                    return 1;
                }
                parsed_mode = m; mode_specified = 1;
            } else {
                if (arg[1] == '-')
                    fprintf(stderr, "%s: unrecognized option '%s'\n", PROGNAM, arg);
                else
                    fprintf(stderr, "%s: invalid option -- '%c'\n", PROGNAM, arg[1]);
                fprintf(stderr, "Try '%s --help' for more information.\n", PROGNAM);
                return 1;
            }
        } else {
            operand_count++;
        }
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", PROGNAM);
        fprintf(stderr, "Try '%s --help' for more information.\n", PROGNAM);
        return 1;
    }

    /* Phase 2: create each operand in order */
    in_positional = 0;
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (in_positional) {
            if (create_one(arg, use_parents, mode_specified, parsed_mode) != 0) {
                any_failed = 1;
                fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                        PROGNAM, arg, strerror(errno));
            }
        } else if (strcmp(arg, "--") == 0) {
            in_positional = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-m") == 0) {
                i++;
            } else if (strcmp(arg, "--mode") == 0) {
                i++;
            }
            /* -p, --parents, -mMODE, --mode=VALUE: no separate arg to skip */
        } else {
            if (create_one(arg, use_parents, mode_specified, parsed_mode) != 0) {
                any_failed = 1;
                fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                        PROGNAM, arg, strerror(errno));
            }
        }
    }

    return any_failed;
}
