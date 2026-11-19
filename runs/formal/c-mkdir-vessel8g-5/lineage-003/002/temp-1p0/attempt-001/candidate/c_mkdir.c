#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

/* ==================== Mode parsing ==================== */

#define WHO_U 1u
#define WHO_G 2u
#define WHO_O 4u
#define WHO_A 7u

typedef enum { OP_ADD, OP_REMOVE, OP_ASSIGN } Op;

typedef struct {
    unsigned who;
    int who_omitted;
    Op op;
    int perm_r, perm_w, perm_x;
    int perm_s, perm_t;
    int copy_src;   /* 0=none, 1=u, 2=g, 3=o */
    int empty;
} Clause;

static int is_numeric_str(const char *s, size_t len)
{
    if (len == 0) return 0;
    for (size_t i = 0; i < len; i++)
        if (s[i] < '0' || s[i] > '7') return 0;
    return 1;
}

static int try_parse_numeric(const char *s, size_t len, mode_t *out)
{
    unsigned long val = 0;
    for (size_t i = 0; i < len; i++) {
        val = val * 8 + (unsigned long)(s[i] - '0');
        if (val > 077777UL) return 0;
    }
    *out = (mode_t)val;
    return 1;
}

static long parse_one_clause(const char *s, size_t len, size_t pos, Clause *cl)
{
    memset(cl, 0, sizeof(*cl));

    /* who */
    size_t ws = pos;
    while (pos < len) {
        switch (s[pos]) {
        case 'u': cl->who |= WHO_U; pos++; break;
        case 'g': cl->who |= WHO_G; pos++; break;
        case 'o': cl->who |= WHO_O; pos++; break;
        case 'a': cl->who |= WHO_A; pos++; break;
        default:  goto who_done;
        }
    }
who_done:
    if (pos == ws) { cl->who_omitted = 1; cl->who = WHO_A; }

    /* operator */
    if (pos >= len) return -1;
    switch (s[pos]) {
    case '+': cl->op = OP_ADD;    break;
    case '-': cl->op = OP_REMOVE; break;
    case '=': cl->op = OP_ASSIGN; break;
    default:  return -1;
    }
    pos++;

    /* permissions (or empty) */
    if (pos >= len || s[pos] == ',') {
        if (cl->op != OP_ASSIGN) return -1;
        cl->empty = 1;
        return pos;
    }
    while (pos < len && s[pos] != ',') {
        switch (s[pos]) {
        case 'r': cl->perm_r = 1; break;
        case 'w': cl->perm_w = 1; break;
        case 'x': case 'X': cl->perm_x = 1; break;
        case 's': cl->perm_s = 1; break;
        case 't': cl->perm_t = 1; break;
        case 'u': if (cl->copy_src) return -1; cl->copy_src = 1; break;
        case 'g': if (cl->copy_src) return -1; cl->copy_src = 2; break;
        case 'o': if (cl->copy_src) return -1; cl->copy_src = 3; break;
        default:  return -1;
        }
        pos++;
    }
    if ((cl->perm_r || cl->perm_w || cl->perm_x || cl->perm_s || cl->perm_t)
        && cl->copy_src)
        return -1;
    return pos;
}

static void apply_clause(mode_t *mode, const Clause *cl, mode_t umask_val,
                         int *had_ordinary)
{
    mode_t m = *mode;
    unsigned who = cl->who;
    int use_umask = cl->who_omitted;
    int shifts[3] = {6, 3, 0};

    /* permission copy */
    if (cl->copy_src) {
        unsigned int src;
        switch (cl->copy_src) {
        case 1: src = (m >> 6) & 7; break;
        case 2: src = (m >> 3) & 7; break;
        default: src = m & 7; break;
        }
        for (int c = 0; c < 3; c++) {
            unsigned cb = 1u << c;
            if (!(who & cb)) continue;
            int sh = shifts[c];
            mode_t cmask = (mode_t)7 << sh;
            mode_t val = (mode_t)src << sh;
            switch (cl->op) {
            case OP_ADD:    m |= val;              break;
            case OP_REMOVE: m &= ~val;             break;
            case OP_ASSIGN: m = (m & ~cmask) | val; break;
            }
        }
        *had_ordinary = 1;
        *mode = m;
        return;
    }

    /* explicit permissions */
    mode_t perms = 0;
    if (cl->perm_r) perms |= 0444;
    if (cl->perm_w) perms |= 0222;
    if (cl->perm_x) perms |= 0111;

    mode_t special = 0;
    if (cl->perm_s) {
        if (who & WHO_U) special |= 04000;
        if (who & WHO_G) special |= 02000;
    }
    if (cl->perm_t) special |= 01000;

    for (int c = 0; c < 3; c++) {
        unsigned cb = 1u << c;
        if (!(who & cb)) continue;
        int sh = shifts[c];
        mode_t cmask = (mode_t)7 << sh;
        mode_t cperms = perms & cmask;
        if (use_umask) {
            mode_t uc = umask_val & cmask;
            switch (cl->op) {
            case OP_ADD:    m |= (cperms & ~uc);                break;
            case OP_REMOVE: m &= ~(cperms & ~uc);              break;
            case OP_ASSIGN: m = (m & ~cmask) | (cperms & ~uc); break;
            }
        } else {
            switch (cl->op) {
            case OP_ADD:    m |= cperms;              break;
            case OP_REMOVE: m &= ~cperms;             break;
            case OP_ASSIGN: m = (m & ~cmask) | cperms; break;
            }
        }
    }

    /* special bits */
    switch (cl->op) {
    case OP_ADD:    m |= special; break;
    case OP_REMOVE: m &= ~special; break;
    case OP_ASSIGN:
        if (cl->perm_s) {
            if (who & WHO_U) {
                if (special & 04000) m |= 04000; else m &= ~04000;
            }
            if (who & WHO_G) {
                if (special & 02000) m |= 02000; else m &= ~02000;
            }
        }
        if (cl->perm_t) {
            if (special & 01000) m |= 01000; else m &= ~01000;
        } else {
            if (who & WHO_O) m &= ~01000;
        }
        break;
    }

    if (cl->perm_r || cl->perm_w || cl->perm_x || cl->empty)
        *had_ordinary = 1;
    *mode = m;
}

static int parse_symbolic(const char *s, size_t len, mode_t umask_val,
                          mode_t *out)
{
    if (len == 0) return 0;
    mode_t mode = 0777;
    int had_ordinary = 0;
    int had_setid = 0;
    size_t pos = 0;
    for (;;) {
        Clause cl;
        long nxt = parse_one_clause(s, len, pos, &cl);
        if (nxt < 0) return 0;
        if (cl.perm_s) had_setid = 1;
        apply_clause(&mode, &cl, umask_val, &had_ordinary);
        pos = (size_t)nxt;
        if (pos >= len) break;
        if (s[pos] != ',') return 0;
        pos++;
    }
    if (!had_ordinary && !had_setid)
        mode = (mode & ~0777) | 0755;
    *out = mode;
    return 1;
}

static int parse_mode_string(const char *s, mode_t umask_val, mode_t *out)
{
    size_t len = strlen(s);
    if (len == 0) return 0;
    if (is_numeric_str(s, len))
        return try_parse_numeric(s, len, out);
    return parse_symbolic(s, len, umask_val, out);
}

static int mkdir_parents(const char *path, mode_t final_mode, int has_explicit)
{
    size_t path_len = strlen(path);
    char *buf = malloc(path_len + 1);
    if (!buf) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                path, strerror(ENOMEM));
        return -1;
    }

    if (path[0] == '/') {
        buf[0] = '/';
        buf[1] = '\0';
    } else {
        buf[0] = '\0';
    }

    size_t i = 0;
    while (i < path_len && path[i] == '/') i++;

    for (; i < path_len; ) {
        size_t j = i;
        while (j < path_len && path[j] != '/') j++;
        size_t comp_len = j - i;

        if (comp_len == 1 && path[i] == '.') {
            i = j;
            while (i < path_len && path[i] == '/') i++;
            continue;
        }

        size_t blen = strlen(buf);
        if (blen > 0 && buf[blen - 1] != '/') {
            buf[blen] = '/';
            blen++;
        }
        memcpy(buf + blen, path + i, comp_len);
        buf[blen + comp_len] = '\0';

        size_t k = j;
        while (k < path_len && path[k] == '/') k++;
        int is_final = (k >= path_len);

        if (mkdir(buf, 0777) == 0) {
            if (!is_final) {
                mode_t mask = umask(0);
                umask(mask);
                chmod(buf, (0777 & ~mask) | 0300);
            } else if (has_explicit) {
                chmod(buf, final_mode);
            }
        } else if (errno == EEXIST) {
            struct stat st;
            int rc = stat(buf, &st);
            if (rc == 0 && S_ISDIR(st.st_mode)) {
                /* exists as directory (or symlink to dir) — OK */
            } else {
                if (rc != 0) {
                    /* stat failed (e.g. broken symlink) — errno from stat */
                } else {
                    errno = ENOTDIR;
                }
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                free(buf);
                return -1;
            }
        } else {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            free(buf);
            return -1;
        }

        i = j;
        while (i < path_len && path[i] == '/') i++;
    }

    free(buf);
    return 0;
}

int main(int argc, char *argv[])
{
    const char *prog = "mkdir";

    int use_parents = 0;
    int terminated = 0;
    int n_operands = 0;
    const char *operands[512];
    int has_mode = 0;
    mode_t explicit_mode = 0;

    mode_t umask_val = umask(0);
    umask(umask_val);

    for (int i = 1; i < argc; i++) {
        if (terminated) {
            operands[n_operands++] = argv[i];
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            terminated = 1;
            continue;
        }
        if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
            use_parents = 1;
            continue;
        }
        if (strcmp(argv[i], "-m") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "%s: option requires an argument -- 'm'\n", prog);
                return 1;
            }
            if (!parse_mode_string(argv[i+1], umask_val, &explicit_mode)) {
                fprintf(stderr, "%s: invalid mode '%s'\n", prog, argv[i+1]);
                return 1;
            }
            has_mode = 1;
            i++;
            continue;
        }
        if (strncmp(argv[i], "-m", 2) == 0 && argv[i][2] != '\0') {
            const char *val = argv[i] + 2;
            if (!parse_mode_string(val, umask_val, &explicit_mode)) {
                fprintf(stderr, "%s: invalid mode '%s'\n", prog, val);
                return 1;
            }
            has_mode = 1;
            continue;
        }
        if (strcmp(argv[i], "--mode") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "%s: option '--mode' requires an argument\n", prog);
                return 1;
            }
            if (!parse_mode_string(argv[i+1], umask_val, &explicit_mode)) {
                fprintf(stderr, "%s: invalid mode '%s'\n", prog, argv[i+1]);
                return 1;
            }
            has_mode = 1;
            i++;
            continue;
        }
        if (strncmp(argv[i], "--mode=", 7) == 0) {
            const char *val = argv[i] + 7;
            if (!parse_mode_string(val, umask_val, &explicit_mode)) {
                fprintf(stderr, "%s: invalid mode '%s'\n", prog, val);
                return 1;
            }
            has_mode = 1;
            continue;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (argv[i][1] == '-')
                fprintf(stderr, "%s: unrecognized option '%s'\n", prog, argv[i]);
            else
                fprintf(stderr, "%s: invalid option -- '%c'\n", prog, argv[i][1]);
            fprintf(stderr, "Try '%s --help' for more information.\n", prog);
            return 1;
        }
        operands[n_operands++] = argv[i];
    }

    if (n_operands == 0) {
        fprintf(stderr, "%s: missing operand\n", prog);
        fprintf(stderr, "Try '%s --help' for more information.\n", prog);
        return 1;
    }

    mode_t default_mode = 0777 & ~umask_val;

    int all_ok = 1;
    for (int i = 0; i < n_operands; i++) {
        const char *path = operands[i];
        if (use_parents) {
            if (mkdir_parents(path, explicit_mode, has_mode) != 0)
                all_ok = 0;
        } else {
            mode_t m = has_mode ? explicit_mode : default_mode;
            mode_t saved = umask(0);
            int rc = mkdir(path, m);
            umask(saved);
            if (rc != 0) {
                fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                        prog, path, strerror(errno));
                all_ok = 0;
            } else if (has_mode && (explicit_mode & 06000)) {
                if (chmod(path, explicit_mode) != 0) {
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                            prog, path, strerror(errno));
                    all_ok = 0;
                }
            }
        }
    }

    return all_ok ? 0 : 1;
}
