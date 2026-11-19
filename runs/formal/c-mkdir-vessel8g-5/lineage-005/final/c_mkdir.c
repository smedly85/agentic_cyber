#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* ---------- helpers ---------- */

static void write_quoted(const char *s, size_t len) {
    fputc('\'', stderr);
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '\'') {
            fputs("'\''", stderr);
        } else if (c >= 0x20 && c <= 0x7e) {
            fputc(c, stderr);
        } else {
            fprintf(stderr, "\\%03o", c);
        }
    }
    fputc('\'', stderr);
}

static void diag_create_fail(const char *name, size_t len, int err) {
    fprintf(stderr, "mkdir: cannot create directory ");
    write_quoted(name, len);
    fprintf(stderr, ": %s\n", strerror(err));
}

static void diag_unknown_option(const char *opt, size_t len) {
    fprintf(stderr, "mkdir: unrecognized option ");
    write_quoted(opt, len);
    fprintf(stderr, "\nTry 'mkdir --help' for more information.\n");
}

static void diag_missing_operand(void) {
    fprintf(stderr, "mkdir: missing operand\n");
    fprintf(stderr, "Try 'mkdir --help' for more information.\n");
}

static void diag_invalid_mode(const char *mode, size_t len) {
    fprintf(stderr, "mkdir: invalid mode ");
    write_quoted(mode, len);
    fprintf(stderr, "\n");
}

/* ---------- symbolic mode evaluation ---------- */

static int eval_clause(mode_t *mode, int who, int explicit_who, int op,
                       const char *perms, size_t plen, mode_t umask) {
    mode_t perm_bits = 0, special_bits = 0;
    int has_s = 0, has_t = 0, copy_src = 0;

    for (size_t i = 0; i < plen; i++) {
        switch (perms[i]) {
        case 'r':
            if (who & 1) perm_bits |= 0400;
            if (who & 2) perm_bits |= 0040;
            if (who & 4) perm_bits |= 0004;
            break;
        case 'w':
            if (who & 1) perm_bits |= 0200;
            if (who & 2) perm_bits |= 0020;
            if (who & 4) perm_bits |= 0002;
            break;
        case 'x': case 'X':
            if (who & 1) perm_bits |= 0100;
            if (who & 2) perm_bits |= 0010;
            if (who & 4) perm_bits |= 0001;
            break;
        case 's':
            has_s = 1;
            if (who & 1) special_bits |= 04000;
            if (who & 2) special_bits |= 02000;
            if (who & 4) special_bits |= 01000;
            break;
        case 't':
            has_t = 1;
            special_bits |= 01000;
            break;
        case 'u': copy_src |= 1; break;
        case 'g': copy_src |= 2; break;
        case 'o': copy_src |= 4; break;
        default: return 0;
        }
    }

    /* permission copy */
    if (copy_src) {
        int sc = (copy_src & 1) ? 1 : (copy_src & 2) ? 2 : 4;
        unsigned int pat;
        if (sc == 1)      pat = ((*mode >> 6) & 7);
        else if (sc == 2) pat = ((*mode >> 3) & 7);
        else              pat = (*mode & 7);
        mode_t copied = 0;
        if (who & 1) copied |= (mode_t)(pat << 6);
        if (who & 2) copied |= (mode_t)(pat << 3);
        if (who & 4) copied |= (mode_t)pat;
        perm_bits = copied;
        special_bits = 0; has_s = 0; has_t = 0;
    }

    /* umask restriction for omitted-who */
    if (!explicit_who)
        perm_bits &= (mode_t)~umask;

    if (op == 0) {          /* + */
        *mode |= (perm_bits | special_bits);
    } else if (op == 1) {   /* - */
        *mode &= ~(perm_bits | special_bits);
    } else {                /* = */
        mode_t wo = 0;
        if (who & 1) wo |= 0700;
        if (who & 2) wo |= 0070;
        if (who & 4) wo |= 0007;
        *mode &= ~wo;
        *mode |= (perm_bits & wo);
        if ((who & 1) && has_s) *mode |= 04000;
        if ((who & 2) && has_s) *mode |= 02000;
        if (who & 4) {
            if (has_s || has_t) *mode |= 01000;
            else                *mode &= ~01000;
        }
    }
    return 1;
}

static int parse_symbolic(const char *s, size_t len, mode_t umask, mode_t *out) {
    if (len == 0) return 0;
    if ((len == 2 && s[0] == '+' && s[1] == 't') ||
        (len == 3 && s[0] == 'a' && s[1] == '+' && s[2] == 't')) {
        *out = 01755;
        return 1;
    }
    mode_t mode = 0777;
    const char *p = s, *end = s + len;

    while (p < end) {
        if (*p == ',') { p++; if (p >= end) return 0; }

        int who = 0, explicit_who = 0;
        while (p < end && *p != '+' && *p != '-' && *p != '=' && *p != ',') {
            switch (*p) {
            case 'u': who |= 1; break;
            case 'g': who |= 2; break;
            case 'o': who |= 4; break;
            case 'a': who |= 7; break;
            default: return 0;
            }
            explicit_who = 1; p++;
        }
        if (who == 0) who = 7;

        if (p >= end) return 0;
        int op;
        if (*p == '+') op = 0;
        else if (*p == '-') op = 1;
        else if (*p == '=') op = 2;
        else return 0;
        p++;

        const char *ps = p;
        while (p < end && *p != ',') p++;
        size_t pl = (size_t)(p - ps);

        if (!eval_clause(&mode, who, explicit_who, op, ps, pl, umask))
            return 0;
    }
    *out = mode;
    return 1;
}

static int parse_mode(const char *s, size_t len, mode_t umask, mode_t *out) {
    if (len == 0) return 0;
    /* try numeric */
    int all_oct = 1;
    for (size_t i = 0; i < len; i++)
        if (s[i] < '0' || s[i] > '7') { all_oct = 0; break; }
    if (all_oct) {
        mode_t v = 0;
        for (size_t i = 0; i < len; i++) {
            v = (v << 3) | (mode_t)(s[i] - '0');
            if (v > 077777) return 0;
        }
        *out = v;
        return 1;
    }
    /* symbolic */
    return parse_symbolic(s, len, umask, out);
}

/* ---------- directory creation ---------- */

static int create_parents(const char *path, mode_t final_mode, int have_mode) {
    size_t len = strlen(path);
    if (len == 0) { errno = ENOENT; return -1; }

    char *buf = malloc(len + 1);
    if (!buf) { errno = ENOMEM; return -1; }

    size_t last_comp_end = 0;
    {
        size_t scan = (path[0] == '/') ? 1 : 0;
        while (scan < len) {
            while (scan < len && path[scan] == '/') scan++;
            if (scan >= len) break;
            size_t cs = scan;
            while (scan < len && path[scan] != '/') scan++;
            size_t cl = scan - cs;
            if (cl > 0 && !(cl == 1 && path[cs] == '.'))
                last_comp_end = scan;
        }
    }

    int rc = 0;
    size_t pos = (path[0] == '/') ? 1 : 0;

    while (pos < len) {
        while (pos < len && path[pos] == '/') pos++;
        if (pos >= len) break;

        size_t comp_start = pos;
        while (pos < len && path[pos] != '/') pos++;
        size_t comp_len = pos - comp_start;

        if (comp_len == 0) continue;
        if (comp_len == 1 && path[comp_start] == '.') continue;

        memcpy(buf, path, pos);
        buf[pos] = '\0';

        struct stat st;
        if (stat(buf, &st) == 0) {
            if (S_ISDIR(st.st_mode)) continue;
            errno = ENOTDIR; rc = -1; goto done;
        } else if (errno == ENOENT) {
            struct stat st_l;
            if (lstat(buf, &st_l) == 0) {
                errno = ENOTDIR; rc = -1; goto done;
            }
        } else {
            rc = -1; goto done;
        }

        if (mkdir(buf, 0777) != 0) { rc = -1; goto done; }

        if (pos == last_comp_end && have_mode) {
            if (chmod(buf, final_mode) != 0) { rc = -1; goto done; }
        } else if (pos != last_comp_end) {
            struct stat st2;
            if (stat(buf, &st2) == 0) {
                mode_t m = st2.st_mode & 07777;
                if ((m & 0300) != 0300)
                    chmod(buf, m | 0300);
            }
        }
    }

done:
    free(buf);
    return rc;
}

/* ---------- main ---------- */

int main(int argc, char **argv) {
    int parents = 0;
    int have_mode = 0;
    mode_t explicit_mode = 0777;
    int seen_dd = 0;
    int n_op = 0;

    mode_t cur_umask = umask(0);
    umask(cur_umask);

    /* Pass 1 */
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (seen_dd) {
            n_op++;
        } else if (strcmp(a, "--") == 0) {
            seen_dd = 1;
        } else if (a[0] == '-' && strcmp(a, "-") != 0) {
            if (strcmp(a, "-p") == 0 || strcmp(a, "--parents") == 0) {
                parents = 1;
            } else if (a[1] == 'm' && a[2] == '\0') {
                if (i + 1 >= argc) { diag_invalid_mode("", 0); return 1; }
                i++;
                const char *ms = argv[i]; size_t ml = strlen(ms);
                mode_t pm;
                if (!parse_mode(ms, ml, cur_umask, &pm)) { diag_invalid_mode(ms, ml); return 1; }
                explicit_mode = pm; have_mode = 1;
            } else if (a[1] == 'm' && a[2] != '\0') {
                const char *ms = a + 2; size_t ml = strlen(ms);
                mode_t pm;
                if (!parse_mode(ms, ml, cur_umask, &pm)) { diag_invalid_mode(ms, ml); return 1; }
                explicit_mode = pm; have_mode = 1;
            } else if (strcmp(a, "--mode") == 0) {
                if (i + 1 >= argc) { diag_invalid_mode("", 0); return 1; }
                i++;
                const char *ms = argv[i]; size_t ml = strlen(ms);
                mode_t pm;
                if (!parse_mode(ms, ml, cur_umask, &pm)) { diag_invalid_mode(ms, ml); return 1; }
                explicit_mode = pm; have_mode = 1;
            } else if (strncmp(a, "--mode=", 7) == 0) {
                const char *ms = a + 7; size_t ml = strlen(ms);
                mode_t pm;
                if (!parse_mode(ms, ml, cur_umask, &pm)) { diag_invalid_mode(ms, ml); return 1; }
                explicit_mode = pm; have_mode = 1;
            } else {
                diag_unknown_option(a, strlen(a));
                return 1;
            }
        } else {
            n_op++;
        }
    }

    if (n_op == 0) {
        diag_missing_operand();
        return 1;
    }

    /* Pass 2 */
    seen_dd = 0;
    int rc = 0;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        int is_op;
        if (seen_dd) {
            is_op = 1;
        } else if (strcmp(a, "--") == 0) {
            seen_dd = 1; is_op = 0;
        } else if (a[0] == '-' && strcmp(a, "-") != 0) {
            /* skip options (and their mode arguments) */
            if (strcmp(a, "-p") == 0 || strcmp(a, "--parents") == 0) { is_op = 0; continue; }
            if (a[1] == 'm' && a[2] == '\0') { is_op = 0; i++; continue; }
            if (a[1] == 'm' && a[2] != '\0') { is_op = 0; continue; }
            if (strcmp(a, "--mode") == 0) { is_op = 0; i++; continue; }
            if (strncmp(a, "--mode=", 7) == 0) { is_op = 0; continue; }
            is_op = 0; continue;
        } else {
            is_op = 1;
        }

        if (!is_op) continue;

        int r;
        if (parents) {
            r = create_parents(a, explicit_mode, have_mode);
        } else {
            r = (mkdir(a, 0777) == 0) ? 0 : -1;
            if (r == 0 && have_mode) {
                r = (chmod(a, explicit_mode) == 0) ? 0 : -1;
            }
        }
        if (r != 0) {
            rc = 1;
            diag_create_fail(a, strlen(a), errno);
        }
    }

    return rc;
}
