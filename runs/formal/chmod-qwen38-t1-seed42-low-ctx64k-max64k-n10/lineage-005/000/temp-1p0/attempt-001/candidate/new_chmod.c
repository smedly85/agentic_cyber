#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <ctype.h>

#define MAX_CLAUSES 256

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

        /* Class letters */
        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            if (*p == 'u' || *p == 'a') c.classes |= 1;
            if (*p == 'g' || *p == 'a') c.classes |= 2;
            if (*p == 'o' || *p == 'a') c.classes |= 4;
            p++;
        }

        if (c.classes == 0) c.classes = 7;

        /* Operator (required) */
        if (*p != '+' && *p != '-' && *p != '=') return -1;
        c.op = *p++;

        /* Permission letters */
        while (*p == 'r' || *p == 'w' || *p == 'x' || *p == 'X') {
            if (*p == 'r') c.perms |= 4;
            else if (*p == 'w') c.perms |= 2;
            else if (*p == 'x') c.perms |= 1;
            else if (*p == 'X') c.perms |= 8;
            p++;
        }

        spec->clauses[spec->nclauses++] = c;

        /* Separator: comma or end */
        if (*p == ',') {
            p++;
            if (*p == '\0') return -1; /* trailing comma */
        } else if (*p != '\0') {
            return -1; /* unexpected character */
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

        /* Resolve X: contributes x only if dir or any x bit already set */
        unsigned eff = c->perms & 7;
        if (c->perms & 8) {
            if (is_dir || (perm & 0111))
                eff |= 1; /* x = bit 0 in our encoding */
        }

        if (c->classes & 1) { /* u */
            mode_t m = (mode_t)eff << 6;
            if (c->op == '+')      perm |= m;
            else if (c->op == '-') perm &= ~m;
            else                   perm = (perm & ~0700) | m;
        }
        if (c->classes & 2) { /* g */
            mode_t m = (mode_t)eff << 3;
            if (c->op == '+')      perm |= m;
            else if (c->op == '-') perm &= ~m;
            else                   perm = (perm & ~0070) | m;
        }
        if (c->classes & 4) { /* o */
            mode_t m = (mode_t)eff;
            if (c->op == '+')      perm |= m;
            else if (c->op == '-') perm &= ~m;
            else                   perm = (perm & ~0007) | m;
        }
    }

    return special | perm;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "new_chmod: missing arguments\n");
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    }

    const char *mode_str;
    int operand_start;

    if (strcmp(argv[1], "--") == 0) {
        if (argc < 4) {
            fprintf(stderr, "new_chmod: missing mode or operand\n");
            fprintf(stderr, "usage: new_chmod MODE FILE...\n");
            return 1;
        }
        mode_str = argv[2];
        operand_start = 3;
    } else if (argv[1][0] == '-') {
        fprintf(stderr, "new_chmod: unknown option: %s\n", argv[1]);
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    } else {
        if (argc < 3) {
            fprintf(stderr, "new_chmod: missing operand\n");
            fprintf(stderr, "usage: new_chmod MODE FILE...\n");
            return 1;
        }
        mode_str = argv[1];
        operand_start = 2;
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

        int is_dir = S_ISDIR(st.st_mode);
        mode_t new_mode = apply_spec(&spec, st.st_mode, is_dir);

        if (chmod(path, new_mode) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}
