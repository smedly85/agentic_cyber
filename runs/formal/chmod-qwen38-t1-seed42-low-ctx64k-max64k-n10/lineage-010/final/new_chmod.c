#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>

enum {
    CLASS_U = 0x1,
    CLASS_G = 0x2,
    CLASS_O = 0x4,
    PERM_R  = 0x1,
    PERM_W  = 0x2,
    PERM_X  = 0x4,
    PERM_XS = 0x8,
};

#define MAX_CLAUSES 1024
#define MAX_DEPTH 4096

enum report_level { REPORT_NONE, REPORT_CHANGES, REPORT_VERBOSE };
static enum report_level report = REPORT_NONE;
static int silent = 0;

typedef struct {
    int classes;
    char op;
    int perms;
} clause_t;

typedef struct {
    int is_octal;
    mode_t octal_value;
    int num_clauses;
    clause_t clauses[MAX_CLAUSES];
} parsed_mode_t;

static int try_parse_octal(const char *s, mode_t *out) {
    size_t len = strlen(s);
    if (len < 1 || len > 4)
        return 0;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '7')
            return 0;
    }
    char *end;
    long val = strtol(s, &end, 8);
    if (end != s + len)
        return 0;
    *out = (mode_t)val;
    return 1;
}

static int parse_symbolic(const char *s, parsed_mode_t *pm) {
    pm->num_clauses = 0;
    const char *p = s;

    if (*p == '\0')
        return -1;

    while (*p) {
        clause_t c;
        c.classes = 0;
        c.op = 0;
        c.perms = 0;

        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            switch (*p) {
            case 'u': c.classes |= CLASS_U; break;
            case 'g': c.classes |= CLASS_G; break;
            case 'o': c.classes |= CLASS_O; break;
            case 'a': c.classes |= CLASS_U | CLASS_G | CLASS_O; break;
            }
            p++;
        }
        if (c.classes == 0)
            c.classes = CLASS_U | CLASS_G | CLASS_O;

        if (*p != '+' && *p != '-' && *p != '=')
            return -1;
        c.op = *p;
        p++;

        while (*p == 'r' || *p == 'w' || *p == 'x' || *p == 'X') {
            switch (*p) {
            case 'r': c.perms |= PERM_R; break;
            case 'w': c.perms |= PERM_W; break;
            case 'x': c.perms |= PERM_X; break;
            case 'X': c.perms |= PERM_XS; break;
            }
            p++;
        }

        if (pm->num_clauses >= MAX_CLAUSES)
            return -1;
        pm->clauses[pm->num_clauses++] = c;

        if (*p == ',') {
            p++;
            if (*p == '\0')
                return -1;
            continue;
        }
        if (*p == '\0')
            break;
        return -1;
    }

    return 0;
}

static int parse_mode(const char *s, parsed_mode_t *pm) {
    if (s == NULL || *s == '\0')
        return -1;

    pm->is_octal = 0;
    pm->octal_value = 0;
    pm->num_clauses = 0;

    mode_t octal_val;
    if (try_parse_octal(s, &octal_val)) {
        pm->is_octal = 1;
        pm->octal_value = octal_val;
        return 0;
    }

    return parse_symbolic(s, pm);
}

static mode_t apply_clause(const clause_t *c, mode_t current, int is_dir) {
    mode_t result = current;

    int perms = c->perms;
    if (perms & PERM_XS) {
        if (is_dir || (current & (S_IXUSR | S_IXGRP | S_IXOTH)))
            perms |= PERM_X;
        perms &= ~PERM_XS;
    }

    mode_t u_perm = 0, g_perm = 0, o_perm = 0;
    if (perms & PERM_R) { u_perm |= S_IRUSR; g_perm |= S_IRGRP; o_perm |= S_IROTH; }
    if (perms & PERM_W) { u_perm |= S_IWUSR; g_perm |= S_IWGRP; o_perm |= S_IWOTH; }
    if (perms & PERM_X) { u_perm |= S_IXUSR; g_perm |= S_IXGRP; o_perm |= S_IXOTH; }

    if (c->classes & CLASS_U) {
        if (c->op == '+')
            result |= u_perm;
        else if (c->op == '-')
            result &= ~u_perm;
        else
            result = (result & ~(mode_t)00700) | u_perm;
    }
    if (c->classes & CLASS_G) {
        if (c->op == '+')
            result |= g_perm;
        else if (c->op == '-')
            result &= ~g_perm;
        else
            result = (result & ~(mode_t)00070) | g_perm;
    }
    if (c->classes & CLASS_O) {
        if (c->op == '+')
            result |= o_perm;
        else if (c->op == '-')
            result &= ~o_perm;
        else
            result = (result & ~(mode_t)00007) | o_perm;
    }

    return result;
}

static int compute_new_mode(const parsed_mode_t *pm, mode_t current, int is_dir) {
    if (pm->is_octal)
        return (int)pm->octal_value;
    mode_t result = current;
    for (int j = 0; j < pm->num_clauses; j++)
        result = apply_clause(&pm->clauses[j], result, is_dir);
    return (int)result;
}

static int per_operand_failure(const char *path, const char *reason) {
    if (silent) return 0;
    fprintf(stderr, "new_chmod: %s: %s\n", path, reason);
    return 1;
}

static int compare_names(const void *a, const void *b) {
    const char *na = *(const char *const *)a;
    const char *nb = *(const char *const *)b;
    return strcmp(na, nb);
}

static char *join_path(const char *dir, const char *name) {
    size_t dlen = strlen(dir);
    size_t nlen = strlen(name);
    char *buf = malloc(dlen + 1 + nlen + 1);
    if (!buf) return NULL;
    memcpy(buf, dir, dlen);
    buf[dlen] = '/';
    memcpy(buf + dlen + 1, name, nlen + 1);
    return buf;
}

static void render_symbolic(mode_t m, char *buf) {
    buf[0] = (m & S_IRUSR) ? 'r' : '-';
    buf[1] = (m & S_IWUSR) ? 'w' : '-';
    buf[2] = (m & S_IXUSR) ? 'x' : '-';
    buf[3] = (m & S_IRGRP) ? 'r' : '-';
    buf[4] = (m & S_IWGRP) ? 'w' : '-';
    buf[5] = (m & S_IXGRP) ? 'x' : '-';
    buf[6] = (m & S_IROTH) ? 'r' : '-';
    buf[7] = (m & S_IWOTH) ? 'w' : '-';
    buf[8] = (m & S_IXOTH) ? 'x' : '-';
    buf[9] = '\0';
    if (m & S_ISUID) buf[2] = (m & S_IXUSR) ? 's' : 'S';
    if (m & S_ISGID) buf[5] = (m & S_IXGRP) ? 's' : 'S';
    if (m & S_ISVTX) buf[8] = (m & S_IXOTH) ? 't' : 'T';
}

static void report_change(const char *path, mode_t old_mode, mode_t new_mode) {
    char old_sym[10], new_sym[10];
    render_symbolic(old_mode, old_sym);
    render_symbolic(new_mode, new_sym);
    printf("mode of '%s' changed from %04o (%s) to %04o (%s)\n",
           path, (unsigned)(old_mode & 07777), old_sym,
           (unsigned)(new_mode & 07777), new_sym);
}

static void report_retained(const char *path, mode_t mode) {
    char sym[10];
    render_symbolic(mode, sym);
    printf("mode of '%s' retained as %04o (%s)\n",
           path, (unsigned)(mode & 07777), sym);
}

static int walk_dir(const char *path, const char *display, const parsed_mode_t *pm, int depth) {
    DIR *dir = opendir(path);
    if (!dir) {
        if (per_operand_failure(path, strerror(errno))) return 1;
        return 0;
    }

    struct dirent *entry;
    char **names = NULL;
    int count = 0;
    int capacity = 0;
    int failed = 0;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (count >= capacity) {
            int new_cap = capacity ? capacity * 2 : 64;
            char **tmp = realloc(names, (size_t)new_cap * sizeof(char *));
            if (!tmp) {
                for (int i = 0; i < count; i++) free(names[i]);
                free(names);
                closedir(dir);
                return 1;
            }
            names = tmp;
            capacity = new_cap;
        }
        names[count] = strdup(entry->d_name);
        if (!names[count]) {
            for (int i = 0; i < count; i++) free(names[i]);
            free(names);
            closedir(dir);
            return 1;
        }
        count++;
    }
    closedir(dir);

    if (count > 1)
        qsort(names, (size_t)count, sizeof(char *), compare_names);

    for (int i = 0; i < count; i++) {
        char *full = join_path(path, names[i]);
        if (!full) {
            failed = 1;
            for (int k = 0; k < count; k++) free(names[k]);
            free(names);
            return 1;
        }

        struct stat st;
        if (lstat(full, &st) != 0) {
            if (per_operand_failure(full, strerror(errno))) failed = 1;
            free(full);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(full);
            continue;
        }

        int is_dir = S_ISDIR(st.st_mode);
        mode_t current = st.st_mode & 07777;
        mode_t new_mode = (mode_t)compute_new_mode(pm, current, is_dir);

        if (chmod(full, new_mode) != 0) {
            if (per_operand_failure(full, strerror(errno))) failed = 1;
        } else if (report != REPORT_NONE) {
            size_t dlen = strlen(display);
            size_t nlen = strlen(names[i]);
            char *disp = malloc(dlen + 1 + nlen + 1);
            if (disp) {
                memcpy(disp, display, dlen);
                disp[dlen] = '/';
                memcpy(disp + dlen + 1, names[i], nlen + 1);
                if (current != new_mode)
                    report_change(disp, current, new_mode);
                else if (report == REPORT_VERBOSE)
                    report_retained(disp, new_mode);
                free(disp);
            }
        }

        if (is_dir) {
            if (depth + 1 > MAX_DEPTH) {
                if (per_operand_failure(full, "maximum recursion depth exceeded")) failed = 1;
            } else {
                size_t dlen = strlen(display);
                size_t nlen = strlen(names[i]);
                char *child_disp = malloc(dlen + 1 + nlen + 1);
                if (!child_disp) {
                    failed = 1;
                } else {
                    memcpy(child_disp, display, dlen);
                    child_disp[dlen] = '/';
                    memcpy(child_disp + dlen + 1, names[i], nlen + 1);
                    if (walk_dir(full, child_disp, pm, depth + 1))
                        failed = 1;
                    free(child_disp);
                }
            }
        }

        free(full);
    }

    for (int i = 0; i < count; i++) free(names[i]);
    free(names);
    return failed ? 1 : 0;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "new_chmod: usage: new_chmod MODE FILE...\n");
        return 1;
    }

    int recursive = 0;
    int start = 1;
    int saw_terminator = 0;

    while (start < argc) {
        if (saw_terminator)
            break;
        if (strcmp(argv[start], "--") == 0) {
            saw_terminator = 1;
            start++;
            continue;
        }
        if (argv[start][0] == '-') {
            if (strcmp(argv[start], "--recursive") == 0) {
                recursive = 1;
                start++;
                continue;
            }
            if (strcmp(argv[start], "--changes") == 0) {
                report = REPORT_CHANGES;
                start++;
                continue;
            }
            if (strcmp(argv[start], "--verbose") == 0) {
                report = REPORT_VERBOSE;
                start++;
                continue;
            }
            if (strcmp(argv[start], "--silent") == 0) {
                silent = 1;
                start++;
                continue;
            }
            if (strcmp(argv[start], "--quiet") == 0) {
                silent = 1;
                start++;
                continue;
            }
            if (argv[start][1] != '\0' && argv[start][1] != '-') {
                int ok = 1;
                for (size_t i = 1; argv[start][i] != '\0'; i++) {
                    switch (argv[start][i]) {
                    case 'R': recursive = 1; break;
                    case 'c': report = REPORT_CHANGES; break;
                    case 'v': report = REPORT_VERBOSE; break;
                    case 'f': silent = 1; break;
                    default: ok = 0; break;
                    }
                }
                if (!ok) {
                    fprintf(stderr, "new_chmod: unknown option '%s'\n", argv[start]);
                    fprintf(stderr, "usage: new_chmod MODE FILE...\n");
                    return 1;
                }
                start++;
                continue;
            }
            fprintf(stderr, "new_chmod: unknown option '%s'\n", argv[start]);
            fprintf(stderr, "usage: new_chmod MODE FILE...\n");
            return 1;
        }
        break;
    }

    if (start >= argc) {
        fprintf(stderr, "new_chmod: usage: new_chmod MODE FILE...\n");
        return 1;
    }

    const char *mode_str = argv[start];
    int num_operands = argc - start - 1;

    if (num_operands < 1) {
        fprintf(stderr, "new_chmod: usage: new_chmod MODE FILE...\n");
        return 1;
    }

    parsed_mode_t pm;
    if (parse_mode(mode_str, &pm) != 0) {
        fprintf(stderr, "new_chmod: invalid mode '%s'\n", mode_str);
        return 1;
    }

    char **operands = &argv[start + 1];
    int any_failed = 0;

    for (int i = 0; i < num_operands; i++) {
        const char *path = operands[i];

        struct stat st;
        if (stat(path, &st) != 0) {
            if (per_operand_failure(path, strerror(errno))) any_failed = 1;
            continue;
        }

        int is_dir = S_ISDIR(st.st_mode);
        mode_t current = st.st_mode & 07777;
        mode_t new_mode = (mode_t)compute_new_mode(&pm, current, is_dir);

        if (chmod(path, new_mode) != 0) {
            if (per_operand_failure(path, strerror(errno))) any_failed = 1;
        } else if (report != REPORT_NONE) {
            size_t plen = strlen(path);
            while (plen > 1 && path[plen - 1] == '/')
                plen--;
            char *disp = malloc(plen + 1);
            if (disp) {
                memcpy(disp, path, plen);
                disp[plen] = '\0';
                if (current != new_mode)
                    report_change(disp, current, new_mode);
                else if (report == REPORT_VERBOSE)
                    report_retained(disp, new_mode);
                free(disp);
            }
        }

        if (recursive && is_dir) {
            size_t plen = strlen(path);
            while (plen > 1 && path[plen - 1] == '/')
                plen--;
            char *disp_base = malloc(plen + 1);
            if (!disp_base) {
                any_failed = 1;
            } else {
                memcpy(disp_base, path, plen);
                disp_base[plen] = '\0';
                if (walk_dir(path, disp_base, &pm, 0))
                    any_failed = 1;
                free(disp_base);
            }
        }
    }

    return any_failed ? 1 : 0;
}
