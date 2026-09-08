#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <dirent.h>

#define CL_U 0x1
#define CL_G 0x2
#define CL_O 0x4
#define CL_A (CL_U | CL_G | CL_O)

#define OP_ADD 0
#define OP_SUB 1
#define OP_EQ  2

#define PERM_R 0x1
#define PERM_W 0x2
#define PERM_X 0x4
#define PERM_XCOND 0x8

#define REPORT_NONE    0
#define REPORT_CHANGES 1
#define REPORT_VERBOSE 2

typedef struct {
    int classes;
    int op;
    int perms;
} clause_t;

#define MAX_CLAUSES 512

typedef struct {
    clause_t clauses[MAX_CLAUSES];
    int count;
} symbolic_mode_t;

static int parse_octal(const char *s, mode_t *out) {
    size_t len = strlen(s);
    if (len < 1 || len > 4) return -1;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '7') return -1;
    }
    mode_t val = 0;
    for (size_t i = 0; i < len; i++) {
        val = (val << 3) | (mode_t)(s[i] - '0');
    }
    *out = val;
    return 0;
}

static int is_valid_octal(const char *s) {
    mode_t tmp;
    return parse_octal(s, &tmp) == 0;
}

static int parse_clause(const char *s, size_t len, clause_t *clause) {
    size_t i = 0;
    int classes = 0;

    while (i < len) {
        char c = s[i];
        if (c == 'u') { classes |= CL_U; i++; }
        else if (c == 'g') { classes |= CL_G; i++; }
        else if (c == 'o') { classes |= CL_O; i++; }
        else if (c == 'a') { classes |= CL_A; i++; }
        else break;
    }
    if (classes == 0) classes = CL_A;

    if (i >= len) return -1;
    char op_char = s[i];
    int op;
    if (op_char == '+') op = OP_ADD;
    else if (op_char == '-') op = OP_SUB;
    else if (op_char == '=') op = OP_EQ;
    else return -1;
    i++;

    int perms = 0;
    while (i < len) {
        char c = s[i];
        if (c == 'r') { perms |= PERM_R; i++; }
        else if (c == 'w') { perms |= PERM_W; i++; }
        else if (c == 'x') { perms |= PERM_X; i++; }
        else if (c == 'X') { perms |= PERM_XCOND; i++; }
        else return -1;
    }

    clause->classes = classes;
    clause->op = op;
    clause->perms = perms;
    return 0;
}

static int parse_symbolic(const char *s, symbolic_mode_t *sm) {
    sm->count = 0;
    if (*s == '\0') return -1;

    const char *start = s;
    while (1) {
        const char *comma = strchr(start, ',');
        size_t len = comma ? (size_t)(comma - start) : strlen(start);

        if (len == 0) return -1;

        clause_t clause;
        if (parse_clause(start, len, &clause) != 0) return -1;
        if (sm->count >= MAX_CLAUSES) return -1;
        sm->clauses[sm->count++] = clause;

        if (comma) start = comma + 1;
        else break;
    }
    return 0;
}

static void apply_clause(const clause_t *cl, mode_t *mode, int is_dir) {
    int classes = cl->classes;
    int op = cl->op;
    int perms = cl->perms;

    int any_exec = ((*mode >> 6) & 1) || ((*mode >> 3) & 1) || ((*mode >> 0) & 1);

    for (int cl_idx = 0; cl_idx < 3; cl_idx++) {
        if (!(classes & (1 << cl_idx))) continue;

        int shift = (2 - cl_idx) * 3;
        mode_t mask = (mode_t)7 << shift;
        mode_t p = 0;
        if (perms & PERM_R) p |= (mode_t)4 << shift;
        if (perms & PERM_W) p |= (mode_t)2 << shift;
        if (perms & PERM_X) p |= (mode_t)1 << shift;
        if (perms & PERM_XCOND) {
            if (is_dir || any_exec) p |= (mode_t)1 << shift;
        }

        switch (op) {
            case OP_ADD: *mode |= p; break;
            case OP_SUB: *mode &= ~p; break;
            case OP_EQ:  *mode = (*mode & ~mask) | p; break;
        }
    }
}

static mode_t apply_symbolic(const symbolic_mode_t *sm, mode_t current, int is_dir) {
    mode_t m = current;
    for (int i = 0; i < sm->count; i++) {
        apply_clause(&sm->clauses[i], &m, is_dir);
    }
    return m;
}

static void render_symbolic(mode_t mode, char *out) {
    int setuid = (mode & 04000) != 0;
    int setgid = (mode & 02000) != 0;
    int sticky = (mode & 01000) != 0;

    const char *letters = "rwxrwxrwx";
    for (int i = 0; i < 9; i++) {
        int bit = (mode >> (8 - i)) & 1;
        out[i] = bit ? letters[i] : '-';
    }
    if (setuid) out[2] = ((mode >> 6) & 1) ? 's' : 'S';
    if (setgid) out[5] = ((mode >> 3) & 1) ? 's' : 'S';
    if (sticky) out[8] = (mode & 1) ? 't' : 'T';
    out[9] = '\0';
}

static void report_change(const char *path, mode_t old_mode, mode_t new_mode) {
    char old_sym[10], new_sym[10];
    render_symbolic(old_mode & 07777, old_sym);
    render_symbolic(new_mode & 07777, new_sym);
    printf("mode of '%s' changed from %04o (%s) to %04o (%s)\n",
           path, (unsigned)(old_mode & 07777), old_sym,
           (unsigned)(new_mode & 07777), new_sym);
}

static void report_retained(const char *path, mode_t mode) {
    char sym[10];
    render_symbolic(mode & 07777, sym);
    printf("mode of '%s' retained as %04o (%s)\n",
           path, (unsigned)(mode & 07777), sym);
}

static int name_cmp(const void *a, const void *b) {
    const unsigned char *na = (const unsigned char *)a;
    const unsigned char *nb = (const unsigned char *)b;
    while (*na && *na == *nb) { na++; nb++; }
    return (int)*na - (int)*nb;
}

static void fail_operand(const char *path, const char *msg, int force, int *any_failed) {
    if (force) return;
    fprintf(stderr, "new_chmod: %s: %s\n", path, msg);
    *any_failed = 1;
}

static void apply_to_path(const char *path, const char *display_path,
                          int is_octal, mode_t octal_val,
                          const symbolic_mode_t *sym,
                          int report_level, int force, int *any_failed) {
    struct stat st;
    if (lstat(path, &st) != 0) {
        fail_operand(display_path, strerror(errno), force, any_failed);
        return;
    }
    int is_dir = S_ISDIR(st.st_mode);
    mode_t old_mode = st.st_mode & 07777;
    mode_t new_mode;
    if (is_octal) {
        new_mode = octal_val;
    } else {
        new_mode = apply_symbolic(sym, old_mode, is_dir);
    }
    if (chmod(path, new_mode) != 0) {
        fail_operand(display_path, strerror(errno), force, any_failed);
        return;
    }
    if (report_level >= REPORT_CHANGES) {
        if (new_mode != old_mode) {
            report_change(display_path, old_mode, new_mode);
        } else if (report_level == REPORT_VERBOSE) {
            report_retained(display_path, new_mode);
        }
    }
}

static void walk_recursive(const char *path, const char *display_path,
                           int is_octal, mode_t octal_val,
                           const symbolic_mode_t *sym,
                           int report_level, int force, int *any_failed) {
    apply_to_path(path, display_path, is_octal, octal_val, sym, report_level, force, any_failed);

    struct stat st;
    if (lstat(path, &st) != 0) return;
    if (!S_ISDIR(st.st_mode)) return;

    if ((st.st_mode & 0111) == 0) {
        fail_operand(display_path, "cannot read directory", force, any_failed);
        return;
    }

    DIR *dir = opendir(path);
    if (!dir) {
        fail_operand(display_path, strerror(errno), force, any_failed);
        return;
    }

    char names[256][256];
    int count = 0;
    struct dirent *ent;

    while ((ent = readdir(dir)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0)
            continue;
        if (count < 256) {
            strncpy(names[count], ent->d_name, 255);
            names[count][255] = '\0';
            count++;
        }
    }
    closedir(dir);

    qsort(names, (size_t)count, sizeof(names[0]), name_cmp);

    for (int i = 0; i < count; i++) {
        char child[4096];
        char child_display[4096];
        size_t plen = strlen(path);
        if (plen > 0 && path[plen - 1] == '/')
            snprintf(child, sizeof(child), "%s%s", path, names[i]);
        else
            snprintf(child, sizeof(child), "%s/%s", path, names[i]);

        size_t dlen = strlen(display_path);
        if (dlen > 0 && display_path[dlen - 1] == '/')
            snprintf(child_display, sizeof(child_display), "%s%s", display_path, names[i]);
        else
            snprintf(child_display, sizeof(child_display), "%s/%s", display_path, names[i]);

        struct stat cst;
        if (lstat(child, &cst) != 0) {
            fail_operand(child_display, strerror(errno), force, any_failed);
            continue;
        }

        if (S_ISLNK(cst.st_mode)) continue;

        if (S_ISDIR(cst.st_mode)) {
            walk_recursive(child, child_display, is_octal, octal_val, sym, report_level, force, any_failed);
        } else {
            apply_to_path(child, child_display, is_octal, octal_val, sym, report_level, force, any_failed);
        }
    }
}

static void usage(void) {
    fprintf(stderr, "usage: new_chmod MODE FILE...\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "new_chmod: missing operand\n");
        usage();
        return 1;
    }

    int recursive = 0;
    int report_level = REPORT_NONE;
    int force = 0;
    int i = 1;
    while (i < argc && argv[i][0] == '-') {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        } else if (strcmp(argv[i], "--recursive") == 0) {
            recursive = 1;
            i++;
        } else if (strcmp(argv[i], "--changes") == 0) {
            report_level = REPORT_CHANGES;
            i++;
        } else if (strcmp(argv[i], "--verbose") == 0) {
            report_level = REPORT_VERBOSE;
            i++;
        } else if (strcmp(argv[i], "--silent") == 0) {
            force = 1;
            i++;
        } else if (strcmp(argv[i], "--quiet") == 0) {
            force = 1;
            i++;
        } else if (argv[i][1] == '-' && argv[i][2] != '\0') {
            fprintf(stderr, "new_chmod: unknown option -- %s\n", argv[i]);
            usage();
            return 1;
        } else {
            const char *p = argv[i] + 1;
            int unknown = 0;
            while (*p) {
                if (*p == 'R') { recursive = 1; }
                else if (*p == 'c') { report_level = REPORT_CHANGES; }
                else if (*p == 'v') { report_level = REPORT_VERBOSE; }
                else if (*p == 'f') { force = 1; }
                else { unknown = 1; break; }
                p++;
            }
            if (unknown) {
                fprintf(stderr, "new_chmod: unknown option -- %s\n", argv[i]);
                usage();
                return 1;
            }
            i++;
        }
    }

    if (i >= argc) {
        fprintf(stderr, "new_chmod: missing operand\n");
        usage();
        return 1;
    }

    const char *mode_str = argv[i];
    int file_start = i + 1;

    if (file_start >= argc) {
        fprintf(stderr, "new_chmod: missing operand\n");
        usage();
        return 1;
    }

    int is_octal_form = is_valid_octal(mode_str);
    mode_t octal_val = 0;
    symbolic_mode_t sym;

    if (is_octal_form) {
        parse_octal(mode_str, &octal_val);
    } else {
        if (parse_symbolic(mode_str, &sym) != 0) {
            fprintf(stderr, "new_chmod: invalid mode: %s\n", mode_str);
            return 1;
        }
    }

    int any_failed = 0;

    for (int fi = file_start; fi < argc; fi++) {
        char path_buf[4096];
        size_t pathlen = strlen(argv[fi]);
        while (pathlen > 1 && argv[fi][pathlen - 1] == '/') pathlen--;
        memcpy(path_buf, argv[fi], pathlen);
        path_buf[pathlen] = '\0';
        const char *path = path_buf;
        struct stat st;

        if (stat(path, &st) != 0) {
            fail_operand(path, strerror(errno), force, &any_failed);
            continue;
        }

        if (recursive && S_ISDIR(st.st_mode)) {
            walk_recursive(path, path, is_octal_form, octal_val, &sym, report_level, force, &any_failed);
        } else {
            int is_dir = S_ISDIR(st.st_mode);
            mode_t old_mode = st.st_mode & 07777;
            mode_t new_mode;
            if (is_octal_form) {
                new_mode = octal_val;
            } else {
                new_mode = apply_symbolic(&sym, old_mode, is_dir);
            }
            if (chmod(path, new_mode) != 0) {
                fail_operand(path, strerror(errno), force, &any_failed);
                continue;
            }
            if (report_level >= REPORT_CHANGES) {
                if (new_mode != old_mode) {
                    report_change(path, old_mode, new_mode);
                } else if (report_level == REPORT_VERBOSE) {
                    report_retained(path, new_mode);
                }
            }
        }
    }

    return any_failed;
}
