#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <ctype.h>
#include <dirent.h>

#define MAX_CLAUSES 256
#define MAX_DEPTH 4096
#define PATH_BUF 8192

/* Permission encoding: x=1, w=2, r=4 (matches natural bit order per class) */
typedef struct {
    unsigned classes; /* bit0=u, bit1=g, bit2=o */
    char op;          /* '+', '-', '=' */
    unsigned perms;   /* bit0=x, bit1=w, bit2=r, bit3=X */
} clause_t;

typedef struct {
    int is_octal;
    mode_t octal_value;
    int nclauses;
    clause_t clauses[MAX_CLAUSES];
} mode_spec_t;

static int all_ascii_digits(const char *s) {
    if (*s == '\0') return 0;
    for (const char *p = s; *p; p++)
        if (*p < '0' || *p > '9') return 0;
    return 1;
}

static int parse_octal(const char *s, mode_t *out) {
    size_t len = strlen(s);
    if (len < 1 || len > 4) return -1;
    mode_t val = 0;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '7') return -1;
        val = (val << 3) | (mode_t)(s[i] - '0');
    }
    *out = val;
    return 0;
}

static int parse_symbolic(const char *s, mode_spec_t *spec) {
    spec->nclauses = 0;
    const char *p = s;

    while (*p) {
        clause_t c;
        c.classes = 0;
        c.op = 0;
        c.perms = 0;

        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            if (*p == 'u' || *p == 'a') c.classes |= 1;
            if (*p == 'g' || *p == 'a') c.classes |= 2;
            if (*p == 'o' || *p == 'a') c.classes |= 4;
            p++;
        }

        if (c.classes == 0) c.classes = 7;

        if (*p != '+' && *p != '-' && *p != '=') return -1;
        c.op = *p++;

        while (*p == 'r' || *p == 'w' || *p == 'x' || *p == 'X') {
            if (*p == 'r') c.perms |= 4;
            else if (*p == 'w') c.perms |= 2;
            else if (*p == 'x') c.perms |= 1;
            else if (*p == 'X') c.perms |= 8;
            p++;
        }

        spec->clauses[spec->nclauses++] = c;

        if (*p == ',') {
            p++;
            if (*p == '\0') return -1;
        } else if (*p != '\0') {
            return -1;
        }
    }

    return 0;
}

static int parse_mode(const char *s, mode_spec_t *spec) {
    spec->is_octal = 0;
    spec->octal_value = 0;
    spec->nclauses = 0;

    if (s[0] == '\0') return -1;

    if (all_ascii_digits(s)) {
        spec->is_octal = 1;
        return parse_octal(s, &spec->octal_value);
    }
    return parse_symbolic(s, spec);
}

static mode_t apply_spec(const mode_spec_t *spec, mode_t current, int is_dir) {
    if (spec->is_octal) return spec->octal_value;

    mode_t special = current & 07000;
    mode_t perm = current & 0777;

    for (int i = 0; i < spec->nclauses; i++) {
        const clause_t *c = &spec->clauses[i];

        unsigned eff = c->perms & 7;
        if (c->perms & 8) {
            if (is_dir || (perm & 0111))
                eff |= 1;
        }

        if (c->classes & 1) {
            mode_t m = (mode_t)eff << 6;
            if (c->op == '+')      perm |= m;
            else if (c->op == '-') perm &= ~m;
            else                   perm = (perm & ~0700) | m;
        }
        if (c->classes & 2) {
            mode_t m = (mode_t)eff << 3;
            if (c->op == '+')      perm |= m;
            else if (c->op == '-') perm &= ~m;
            else                   perm = (perm & ~0070) | m;
        }
        if (c->classes & 4) {
            mode_t m = (mode_t)eff;
            if (c->op == '+')      perm |= m;
            else if (c->op == '-') perm &= ~m;
            else                   perm = (perm & ~0007) | m;
        }
    }

    return special | perm;
}

static void render_symbolic(mode_t mode, char *out) {
    int suid   = (mode & 04000) != 0;
    int sgid   = (mode & 02000) != 0;
    int sticky = (mode & 01000) != 0;

    const char *letters = "rwxrwxrwx";
    int bits[9] = {
        (mode & 0400) != 0, (mode & 0200) != 0, (mode & 0100) != 0,
        (mode & 0040) != 0, (mode & 0020) != 0, (mode & 0010) != 0,
        (mode & 0004) != 0, (mode & 0002) != 0, (mode & 0001) != 0
    };

    for (int i = 0; i < 9; i++) {
        if (i == 2 && suid)       out[i] = bits[i] ? 's' : 'S';
        else if (i == 5 && sgid)  out[i] = bits[i] ? 's' : 'S';
        else if (i == 8 && sticky) out[i] = bits[i] ? 't' : 'T';
        else                       out[i] = bits[i] ? letters[i] : '-';
    }
    out[9] = '\0';
}

static void report_change(const char *path, mode_t old_mode, mode_t new_mode) {
    char old_sym[10], new_sym[10];
    render_symbolic(old_mode & 07777, old_sym);
    render_symbolic(new_mode & 07777, new_sym);
    printf("mode of '%s' changed from %04o (%s) to %04o (%s)\n",
           path, old_mode & 07777, old_sym, new_mode & 07777, new_sym);
}

static void report_retained(const char *path, mode_t mode) {
    char sym[10];
    render_symbolic(mode & 07777, sym);
    printf("mode of '%s' retained as %04o (%s)\n", path, mode & 07777, sym);
}

static int compare_dirent(const void *a, const void *b) {
    const struct dirent *da = (const struct dirent *)a;
    const struct dirent *db = (const struct dirent *)b;
    return strcmp(da->d_name, db->d_name);
}

static void walk_recursive(const char *path, const mode_spec_t *spec,
                           int *any_failed, int depth, int report_level) {
    if (depth > MAX_DEPTH) {
        fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(ELOOP));
        *any_failed = 1;
        return;
    }

    struct stat st;
    if (stat(path, &st) != 0) {
        fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
        *any_failed = 1;
        return;
    }

    int is_dir = S_ISDIR(st.st_mode);
    mode_t old_mode = st.st_mode & 07777;
    mode_t new_mode = apply_spec(spec, st.st_mode, is_dir);

    if (chmod(path, new_mode) != 0) {
        fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
        *any_failed = 1;
    } else {
        if (report_level >= 2 || (report_level >= 1 && new_mode != old_mode)) {
            if (new_mode != old_mode) {
                report_change(path, old_mode, new_mode);
            } else {
                report_retained(path, new_mode);
            }
        }
    }

    if (!is_dir) return;

    DIR *dp = opendir(path);
    if (!dp) {
        fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
        *any_failed = 1;
        return;
    }

    struct dirent *entries = NULL;
    size_t count = 0;
    size_t capacity = 0;
    struct dirent *entry;
    while ((entry = readdir(dp)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (count == capacity) {
            size_t newcap = capacity ? capacity * 2 : 16;
            struct dirent *tmp = realloc(entries, newcap * sizeof(struct dirent));
            if (!tmp) {
                free(entries);
                closedir(dp);
                fprintf(stderr, "new_chmod: out of memory\n");
                *any_failed = 1;
                return;
            }
            entries = tmp;
            capacity = newcap;
        }
        memcpy(&entries[count++], entry, sizeof(struct dirent));
    }
    closedir(dp);

    if (count > 1)
        qsort(entries, count, sizeof(struct dirent), compare_dirent);

    for (size_t i = 0; i < count; i++) {
        char child[PATH_BUF];
        size_t dlen = strlen(path);
        if (dlen + 1 + strlen(entries[i].d_name) >= PATH_BUF) {
            fprintf(stderr, "new_chmod: %s/%s: %s\n", path, entries[i].d_name,
                    strerror(ENAMETOOLONG));
            *any_failed = 1;
            continue;
        }
        if (dlen > 0 && path[dlen - 1] == '/')
            snprintf(child, PATH_BUF, "%s%s", path, entries[i].d_name);
        else
            snprintf(child, PATH_BUF, "%s/%s", path, entries[i].d_name);

        struct stat cst;
        if (lstat(child, &cst) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", child, strerror(errno));
            *any_failed = 1;
            continue;
        }

        if (S_ISLNK(cst.st_mode))
            continue;

        if (S_ISDIR(cst.st_mode)) {
            walk_recursive(child, spec, any_failed, depth + 1, report_level);
        } else {
            mode_t child_old = cst.st_mode & 07777;
            mode_t child_new = apply_spec(spec, cst.st_mode, 0);

            if (chmod(child, child_new) != 0) {
                fprintf(stderr, "new_chmod: %s: %s\n", child, strerror(errno));
                *any_failed = 1;
                continue;
            }

            if (report_level >= 2 || (report_level >= 1 && child_new != child_old)) {
                if (child_new != child_old) {
                    report_change(child, child_old, child_new);
                } else {
                    report_retained(child, child_new);
                }
            }
        }
    }

    free(entries);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "new_chmod: missing arguments\n");
        fprintf(stderr, "usage: new_chmod [-R] [-c] [-v] MODE FILE...\n");
        return 1;
    }

    int recursive = 0;
    int report_level = 0;
    int idx = 1;

    while (idx < argc) {
        if (strcmp(argv[idx], "--") == 0) {
            idx++;
            break;
        }
        if (strcmp(argv[idx], "--recursive") == 0) {
            recursive = 1;
            idx++;
            continue;
        }
        if (strcmp(argv[idx], "--changes") == 0) {
            report_level = 1;
            idx++;
            continue;
        }
        if (strcmp(argv[idx], "--verbose") == 0) {
            report_level = 2;
            idx++;
            continue;
        }
        if (argv[idx][0] == '-' && argv[idx][1] != '\0') {
            int ok = 1;
            for (const char *p = argv[idx] + 1; *p; p++) {
                if (*p == 'R') recursive = 1;
                else if (*p == 'c') report_level = 1;
                else if (*p == 'v') report_level = 2;
                else { ok = 0; break; }
            }
            if (!ok) {
                fprintf(stderr, "new_chmod: unknown option: %s\n", argv[idx]);
                fprintf(stderr, "usage: new_chmod [-R] [-c] [-v] MODE FILE...\n");
                return 1;
            }
            idx++;
            continue;
        }
        break;
    }

    if (idx >= argc) {
        fprintf(stderr, "new_chmod: missing mode or operand\n");
        fprintf(stderr, "usage: new_chmod [-R] [-c] [-v] MODE FILE...\n");
        return 1;
    }

    const char *mode_str = argv[idx];
    int operand_start = idx + 1;

    if (operand_start >= argc) {
        fprintf(stderr, "new_chmod: missing operand\n");
        fprintf(stderr, "usage: new_chmod [-R] [-c] [-v] MODE FILE...\n");
        return 1;
    }

    mode_spec_t spec;
    if (parse_mode(mode_str, &spec) != 0) {
        fprintf(stderr, "new_chmod: invalid mode: %s\n", mode_str);
        return 1;
    }

    int any_failed = 0;

    for (int i = operand_start; i < argc; i++) {
        const char *path = argv[i];
        struct stat st;

        if (stat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
            continue;
        }

        if (recursive && S_ISDIR(st.st_mode)) {
            walk_recursive(path, &spec, &any_failed, 0, report_level);
        } else {
            int is_dir = S_ISDIR(st.st_mode);
            mode_t old_mode = st.st_mode & 07777;
            mode_t new_mode = apply_spec(&spec, st.st_mode, is_dir);
            if (chmod(path, new_mode) != 0) {
                fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
                any_failed = 1;
            } else {
                if (report_level >= 2 || (report_level >= 1 && new_mode != old_mode)) {
                    if (new_mode != old_mode) {
                        report_change(path, old_mode, new_mode);
                    } else {
                        report_retained(path, new_mode);
                    }
                }
            }
        }
    }

    return any_failed ? 1 : 0;
}
