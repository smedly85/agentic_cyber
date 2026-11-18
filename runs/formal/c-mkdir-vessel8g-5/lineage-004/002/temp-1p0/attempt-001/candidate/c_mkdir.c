#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#ifndef S_ISVTX
#define S_ISVTX 01000
#endif

typedef struct {
    int has_mode;
    int is_numeric;
    int num_digits;
    mode_t value;
    int uid_touched;
    int gid_touched;
    int sticky_touched;
} ParsedMode;

static int parse_mode_str(const char *s, mode_t umask, ParsedMode *out);
static int apply_explicit_mode(const char *path, const ParsedMode *pm);
static int ensure_dir(const char *path, mode_t um, int is_final, const ParsedMode *pm);
static int create_parents(const char *path, mode_t um, const ParsedMode *pm);

static int is_all_octal_digits(const char *s)
{
    if (*s == '\0')
        return 0;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '7')
            return 0;
    }
    return 1;
}

static int parse_numeric_mode(const char *s, ParsedMode *out)
{
    mode_t val = 0;
    int digits = 0;
    for (const char *p = s; *p; p++) {
        if (digits >= 5 || (digits == 4 && val > 0777)) {
            return -1;  /* out of range 0000..7777 */
        }
        val = (val << 3) | (mode_t)(*p - '0');
        digits++;
    }
    if (val > 07777)
        return -1;
    out->has_mode = 1;
    out->is_numeric = 1;
    out->num_digits = digits;
    out->value = val;
    out->uid_touched = 0;
    out->gid_touched = 0;
    out->sticky_touched = 0;
    return 0;
}

static int parse_symbolic_clause(const char **pp, mode_t umask, mode_t *result,
                                 int *uid_touched, int *gid_touched,
                                 int *sticky_touched)
{
    const char *p = *pp;

    /* --- who --- */
    int who_u = 0, who_g = 0, who_o = 0;
    int who_omitted = 1;
    while (*p && *p != '+' && *p != '-' && *p != '=') {
        if (*p == 'u')       { who_u = 1; who_omitted = 0; }
        else if (*p == 'g')  { who_g = 1; who_omitted = 0; }
        else if (*p == 'o')  { who_o = 1; who_omitted = 0; }
        else if (*p == 'a')  { who_u = who_g = who_o = 1; who_omitted = 0; }
        else return -1;
        p++;
    }

    /* --- operator --- */
    char op = *p;
    if (op != '+' && op != '-' && op != '=')
        return -1;
    p++;

    /* --- permissions --- */
    int p_r = 0, p_w = 0, p_x = 0, p_X = 0;
    int p_s = 0, p_t = 0;
    int cp_u = 0, cp_g = 0, cp_o = 0;
    int perm_omitted = 1;

    while (*p && *p != ',') {
        if (*p == 'r')       { p_r = 1; perm_omitted = 0; }
        else if (*p == 'w')  { p_w = 1; perm_omitted = 0; }
        else if (*p == 'x')  { p_x = 1; perm_omitted = 0; }
        else if (*p == 'X')  { p_X = 1; perm_omitted = 0; }
        else if (*p == 's')  { p_s = 1; perm_omitted = 0; }
        else if (*p == 't')  { p_t = 1; perm_omitted = 0; }
        else if (*p == 'u')  { cp_u = 1; perm_omitted = 0; }
        else if (*p == 'g')  { cp_g = 1; perm_omitted = 0; }
        else if (*p == 'o')  { cp_o = 1; perm_omitted = 0; }
        else return -1;
        p++;
    }
    *pp = p;

    /* + and - require at least one permission */
    if (perm_omitted && op != '=')
        return -1;

    int eff_u = who_omitted ? 1 : who_u;
    int eff_g = who_omitted ? 1 : who_g;
    int eff_o = who_omitted ? 1 : who_o;

    /* Build ordinary permission bits (X == x for directories) */
    mode_t perm_bits = 0;
    if (p_r) perm_bits |= 0444;
    if (p_w) perm_bits |= 0222;
    if (p_x || p_X) perm_bits |= 0111;

    /* Permission copy: source class's current rwx into the target */
    if (cp_u || cp_g || cp_o) {
        mode_t src = 0;
        if (cp_u) src |= (*result & 0700);
        if (cp_g) src |= (*result & 0070);
        if (cp_o) src |= (*result & 0007);
        perm_bits |= src;
    }

    /* Build special bits */
    mode_t special = 0;
    if (p_s) {
        if (eff_u) special |= S_ISUID;
        if (eff_g) special |= S_ISGID;
        if (eff_o) special |= S_ISVTX;
    }
    if (p_t) {
        special |= S_ISVTX;
    }

    mode_t umask_ordinary = umask & 0777;

    if (op == '+') {
        mode_t add = 0;
        if (eff_u) add |= perm_bits & 0700;
        if (eff_g) add |= perm_bits & 0070;
        if (eff_o) add |= perm_bits & 0007;
        add |= special;
        if (who_omitted)
            add = (add & ~umask_ordinary) | (add & (S_ISUID | S_ISGID | S_ISVTX));
        *result |= add;
    } else if (op == '-') {
        mode_t rem = 0;
        if (eff_u) rem |= perm_bits & 0700;
        if (eff_g) rem |= perm_bits & 0070;
        if (eff_o) rem |= perm_bits & 0007;
        rem |= special;
        if (who_omitted)
            rem = (rem & ~umask_ordinary) | (rem & (S_ISUID | S_ISGID | S_ISVTX));
        *result &= ~rem;
    } else { /* '=' */
        mode_t class_mask = 0;
        if (eff_u) class_mask |= 0700;
        if (eff_g) class_mask |= 0070;
        if (eff_o) class_mask |= 0007;

        mode_t new_ordinary = 0;
        if (eff_u) new_ordinary |= perm_bits & 0700;
        if (eff_g) new_ordinary |= perm_bits & 0070;
        if (eff_o) new_ordinary |= perm_bits & 0007;
        if (who_omitted)
            new_ordinary &= ~umask_ordinary;

        *result = (*result & ~class_mask) | new_ordinary;

        /* Special bits for '=': set if requested, cleared otherwise for addressed classes */
        if (eff_u) { *uid_touched = 1;
            if (p_s) *result |= S_ISUID; else *result &= ~S_ISUID; }
        if (eff_g) { *gid_touched = 1;
            if (p_s) *result |= S_ISGID; else *result &= ~S_ISGID; }
        if (eff_o) { *sticky_touched = 1;
            if (p_s || p_t) *result |= S_ISVTX; else *result &= ~S_ISVTX; }
        if (p_t && !eff_o) {
            /* t with who that doesn't include o (e.g. u+t) still sets sticky */
            *result |= S_ISVTX;
            *sticky_touched = 1;
        }
    }

    /* Track touched for + and - with special permissions */
    if (op == '+' || op == '-') {
        if (p_s) {
            if (eff_u) *uid_touched = 1;
            if (eff_g) *gid_touched = 1;
            if (eff_o) *sticky_touched = 1;
        }
        if (p_t) *sticky_touched = 1;
    }

    return 0;
}

static int parse_symbolic_mode(const char *s, mode_t umask, ParsedMode *out)
{
    mode_t result = 0777;
    int uid_touched = 0, gid_touched = 0, sticky_touched = 0;
    const char *p = s;

    if (*p == '\0')
        return -1;

    while (*p) {
        if (parse_symbolic_clause(&p, umask, &result,
                                  &uid_touched, &gid_touched, &sticky_touched) != 0)
            return -1;
        if (*p == ',')
            p++;
        else if (*p != '\0')
            return -1;
    }

    out->has_mode = 1;
    out->is_numeric = 0;
    out->num_digits = 0;
    out->value = result & 07777;
    out->uid_touched = uid_touched;
    out->gid_touched = gid_touched;
    out->sticky_touched = sticky_touched;
    return 0;
}

static int parse_mode_str(const char *s, mode_t umask, ParsedMode *out)
{
    if (*s == '\0')
        return -1;
    if (is_all_octal_digits(s))
        return parse_numeric_mode(s, out);
    return parse_symbolic_mode(s, umask, out);
}

static int apply_explicit_mode(const char *path, const ParsedMode *pm)
{
    struct stat st;
    if (lstat(path, &st) != 0)
        return -1;

    mode_t inherited = st.st_mode & (S_ISUID | S_ISGID | S_ISVTX);
    mode_t final;

    if (pm->is_numeric) {
        if (pm->num_digits <= 4) {
            final = pm->value | (inherited & ~pm->value);
        } else {
            final = pm->value;
        }
    } else {
        final = pm->value;
        if (!pm->uid_touched)    final |= inherited & S_ISUID;
        if (!pm->gid_touched)    final |= inherited & S_ISGID;
        if (!pm->sticky_touched) final |= inherited & S_ISVTX;
    }

    return chmod(path, final) == 0 ? 0 : -1;
}

static int ensure_dir(const char *path, mode_t um, int is_final, const ParsedMode *pm)
{
    struct stat st;
    if (stat(path, &st) == 0) {
        if (S_ISDIR(st.st_mode))
            return 0;
        errno = ENOTDIR;
        return -1;
    }
    if (errno != ENOENT)
        return -1;

    if (mkdir(path, 0777) != 0) {
        if (errno == EEXIST) {
            if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
                return 0;
            errno = ENOTDIR;
        }
        return -1;
    }

    if (is_final) {
        if (pm && pm->has_mode) {
            if (apply_explicit_mode(path, pm) != 0)
                return -1;
        }
        /* No explicit mode: leave as mkdir gave it (0777 & ~um) */
    } else {
        if (chmod(path, (0777 & ~um) | 0300) != 0)
            return -1;
    }
    return 0;
}

static int create_parents(const char *path, mode_t um, const ParsedMode *pm)
{
    size_t len = strlen(path);
    if (len == 0) {
        errno = ENOENT;
        return -1;
    }

    char *buf = malloc(len + 1);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    memcpy(buf, path, len + 1);

    int result = 0;

    for (size_t i = 0; i < len; i++) {
        if (buf[i] != '/')
            continue;
        buf[i] = '\0';
        if (buf[0] == '\0' || strcmp(buf, ".") == 0) {
            buf[i] = '/';
            continue;
        }
        if (ensure_dir(buf, um, 0, pm) != 0) {
            result = -1;
            goto done;
        }
        buf[i] = '/';
    }

    if (buf[0] != '\0' && strcmp(buf, ".") != 0) {
        if (ensure_dir(buf, um, 1, pm) != 0)
            result = -1;
    }

done:
    free(buf);
    return result;
}

int main(int argc, char *argv[])
{
    int parents = 0;
    int saw_ddash = 0;
    int n_operands = 0;
    char *mode_str = NULL;
    int mode_arg_seen = 0;

    /* Pass 1: validate options, collect operands. No filesystem mutation. */
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!saw_ddash) {
            if (strcmp(arg, "--") == 0) {
                saw_ddash = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                    parents = 1;
                    continue;
                }
                /* -m MODE or -mMODE */
                if (arg[1] == 'm' && arg[2] != '\0') {
                    /* -mMODE (attached) */
                    const char *mval = arg + 2;
                    if (*mval == '\0') {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", mval);
                        return 1;
                    }
                    mode_str = strdup(mval);
                    if (!mode_str) {
                        fprintf(stderr, "mkdir: memory allocation failed\n");
                        return 1;
                    }
                    mode_arg_seen = 1;
                    continue;
                }
                if (strcmp(arg, "-m") == 0) {
                    /* -m MODE (separate) */
                    if (i + 1 >= argc) {
                        fprintf(stderr, "mkdir: option '-m' requires an argument\n");
                        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                        return 1;
                    }
                    i++;
                    const char *mval = argv[i];
                    if (*mval == '\0') {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", mval);
                        return 1;
                    }
                    mode_str = strdup(mval);
                    if (!mode_str) {
                        fprintf(stderr, "mkdir: memory allocation failed\n");
                        return 1;
                    }
                    mode_arg_seen = 1;
                    continue;
                }
                /* --mode=MODE */
                if (strncmp(arg, "--mode=", 7) == 0) {
                    const char *mval = arg + 7;
                    if (*mval == '\0') {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", mval);
                        return 1;
                    }
                    mode_str = strdup(mval);
                    if (!mode_str) {
                        fprintf(stderr, "mkdir: memory allocation failed\n");
                        return 1;
                    }
                    mode_arg_seen = 1;
                    continue;
                }
                /* --mode MODE */
                if (strcmp(arg, "--mode") == 0) {
                    if (i + 1 >= argc) {
                        fprintf(stderr, "mkdir: option '--mode' requires an argument\n");
                        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                        return 1;
                    }
                    i++;
                    const char *mval = argv[i];
                    if (*mval == '\0') {
                        fprintf(stderr, "mkdir: invalid mode '%s'\n", mval);
                        return 1;
                    }
                    mode_str = strdup(mval);
                    if (!mode_str) {
                        fprintf(stderr, "mkdir: memory allocation failed\n");
                        return 1;
                    }
                    mode_arg_seen = 1;
                    continue;
                }
                if (arg[1] == '-' && arg[2] != '\0') {
                    fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
                } else {
                    fprintf(stderr, "mkdir: invalid option -- '%c'\n", arg[1]);
                }
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                return 1;
            }
        }
        n_operands++;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Capture the process umask once. */
    mode_t um = umask(0);
    umask(um);

    ParsedMode mode = {0};
    if (mode_arg_seen) {
        if (parse_mode_str(mode_str, um, &mode) != 0) {
            fprintf(stderr, "mkdir: invalid mode '%s'\n", mode_str);
            free(mode_str);
            return 1;
        }
    }
    free(mode_str);

    /* Pass 2: create each operand in order; continue after errors. */
    int exit_code = 0;
    saw_ddash = 0;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!saw_ddash) {
            if (strcmp(arg, "--") == 0) {
                saw_ddash = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                /* Skip recognized options and their arguments */
                if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0)
                    continue;
                if (arg[1] == 'm' && arg[2] != '\0')
                    continue;
                if (strcmp(arg, "-m") == 0) { i++; continue; }
                if (strncmp(arg, "--mode=", 7) == 0)
                    continue;
                if (strcmp(arg, "--mode") == 0) { i++; continue; }
                continue;
            }
        }
        int rc;
        if (parents) {
            rc = create_parents(arg, um, &mode);
        } else {
            rc = mkdir(arg, 0777);
            if (rc == 0 && mode_arg_seen) {
                if (apply_explicit_mode(arg, &mode) != 0)
                    rc = -1;
            }
        }
        if (rc != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    arg, strerror(errno));
            exit_code = 1;
        }
    }

    return exit_code;
}
