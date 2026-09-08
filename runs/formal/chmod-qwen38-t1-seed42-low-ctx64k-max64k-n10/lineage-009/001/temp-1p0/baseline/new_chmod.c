#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>

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

static void usage(void) {
    fprintf(stderr, "usage: new_chmod MODE FILE...\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "new_chmod: missing operand\n");
        usage();
        return 1;
    }

    int i = 1;
    while (i < argc && argv[i][0] == '-') {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        } else {
            fprintf(stderr, "new_chmod: unknown option -- %s\n", argv[i]);
            usage();
            return 1;
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
        const char *path = argv[fi];
        struct stat st;

        if (stat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
            continue;
        }

        int is_dir = S_ISDIR(st.st_mode);
        mode_t current = st.st_mode & 07777;
        mode_t new_mode;

        if (is_octal_form) {
            new_mode = octal_val;
        } else {
            new_mode = apply_symbolic(&sym, current, is_dir);
        }

        if (chmod(path, new_mode) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
        }
    }

    return any_failed;
}
