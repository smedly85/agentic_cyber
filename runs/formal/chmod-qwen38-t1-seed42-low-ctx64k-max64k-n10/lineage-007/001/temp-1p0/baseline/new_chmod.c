#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

#define MAX_CLAUSES 256

typedef struct {
    int classes;  /* bitmask: bit0=U, bit1=G, bit2=O */
    int op;       /* 0='+', 1='-', 2='=' */
    int perms;    /* bitmask: bit0=r, bit1=w, bit2=x, bit3=X */
} clause_t;

typedef struct {
    int is_octal;
    unsigned long value;
    int clause_count;
    clause_t clauses[MAX_CLAUSES];
} mode_spec_t;

static int parse_octal(const char *s, mode_spec_t *spec) {
    size_t len = strlen(s);
    if (len < 1 || len > 4) return -1;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '7') return -1;
    }
    spec->is_octal = 1;
    spec->value = 0;
    for (size_t i = 0; i < len; i++)
        spec->value = spec->value * 8 + (unsigned long)(s[i] - '0');
    return 0;
}

static int parse_symbolic(const char *s, mode_spec_t *spec) {
    spec->is_octal = 0;
    spec->clause_count = 0;

    const char *p = s;
    while (*p) {
        const char *clause_start = p;
        while (*p && *p != ',') p++;
        size_t clause_len = (size_t)(p - clause_start);
        if (*p == ',') p++;

        if (clause_len == 0) return -1;
        if (spec->clause_count >= MAX_CLAUSES) return -1;

        clause_t *c = &spec->clauses[spec->clause_count];
        c->classes = 0;
        c->op = -1;
        c->perms = 0;

        const char *q = clause_start;
        const char *qend = clause_start + clause_len;

        const char *op_pos = NULL;
        for (const char *r = q; r < qend; r++) {
            if (*r == '+' || *r == '-' || *r == '=') {
                op_pos = r;
                break;
            }
        }
        if (!op_pos) return -1;

        for (const char *r = q; r < op_pos; r++) {
            switch (*r) {
                case 'u': c->classes |= 1; break;
                case 'g': c->classes |= 2; break;
                case 'o': c->classes |= 4; break;
                case 'a': c->classes |= 7; break;
                default: return -1;
            }
        }
        if (c->classes == 0) c->classes = 7;

        switch (*op_pos) {
            case '+': c->op = 0; break;
            case '-': c->op = 1; break;
            case '=': c->op = 2; break;
        }

        for (const char *r = op_pos + 1; r < qend; r++) {
            switch (*r) {
                case 'r': c->perms |= 1; break;
                case 'w': c->perms |= 2; break;
                case 'x': c->perms |= 4; break;
                case 'X': c->perms |= 8; break;
                default: return -1;
            }
        }

        spec->clause_count++;
    }

    if (strlen(s) > 0 && s[strlen(s) - 1] == ',') return -1;
    if (spec->clause_count == 0) return -1;
    return 0;
}

static int parse_mode(const char *s, mode_spec_t *spec) {
    if (s[0] == '\0') return -1;
    size_t len = strlen(s);
    int all_octal = (len >= 1 && len <= 4);
    if (all_octal) {
        for (size_t i = 0; i < len; i++) {
            if (s[i] < '0' || s[i] > '7') { all_octal = 0; break; }
        }
    }
    if (all_octal) return parse_octal(s, spec);
    return parse_symbolic(s, spec);
}

static unsigned long apply_mode(const mode_spec_t *spec, unsigned long current, int is_dir) {
    if (spec->is_octal)
        return spec->value & 07777;

    unsigned long mode = current & 07777;

    for (int i = 0; i < spec->clause_count; i++) {
        const clause_t *c = &spec->clauses[i];

        if (c->op == 2) {
            unsigned long clear_mask = 0;
            if (c->classes & 1) clear_mask |= 0700;
            if (c->classes & 2) clear_mask |= 0070;
            if (c->classes & 4) clear_mask |= 0007;
            mode &= ~clear_mask;
        }

        unsigned long set_mask = 0;
        unsigned long clear_mask = 0;

        for (int cls = 0; cls < 3; cls++) {
            if (!(c->classes & (1 << cls))) continue;
            unsigned long r_bit, w_bit, x_bit;
            if (cls == 0)      { r_bit = 0400; w_bit = 0200; x_bit = 0100; }
            else if (cls == 1) { r_bit = 0040; w_bit = 0020; x_bit = 0010; }
            else               { r_bit = 0004; w_bit = 0002; x_bit = 0001; }

            if (c->perms & 1) {
                if (c->op == 1) clear_mask |= r_bit; else set_mask |= r_bit;
            }
            if (c->perms & 2) {
                if (c->op == 1) clear_mask |= w_bit; else set_mask |= w_bit;
            }
            if (c->perms & 4) {
                if (c->op == 1) clear_mask |= x_bit; else set_mask |= x_bit;
            }
            if (c->perms & 8) {
                if (is_dir || (mode & 0111)) {
                    if (c->op == 1) clear_mask |= x_bit; else set_mask |= x_bit;
                }
            }
        }

        mode |= set_mask;
        mode &= ~clear_mask;
    }
    return mode & 07777;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "new_chmod: missing arguments\n");
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    }

    const char *mode_str = NULL;
    char **operands = NULL;
    int operand_count = 0;

    if (argv[1][0] == '-') {
        if (strcmp(argv[1], "--") == 0) {
            if (argc < 3) {
                fprintf(stderr, "new_chmod: missing MODE after --\n");
                fprintf(stderr, "usage: new_chmod MODE FILE...\n");
                return 1;
            }
            mode_str = argv[2];
            operands = &argv[3];
            operand_count = argc - 3;
        } else {
            fprintf(stderr, "new_chmod: unknown option: %s\n", argv[1]);
            fprintf(stderr, "usage: new_chmod MODE FILE...\n");
            return 1;
        }
    } else {
        mode_str = argv[1];
        operands = &argv[2];
        operand_count = argc - 2;
    }

    if (operand_count < 1) {
        fprintf(stderr, "new_chmod: missing FILE operand\n");
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    }

    mode_spec_t spec;
    memset(&spec, 0, sizeof(spec));
    if (parse_mode(mode_str, &spec) != 0) {
        fprintf(stderr, "new_chmod: invalid mode: %s\n", mode_str);
        return 1;
    }

    int any_failed = 0;
    for (int i = 0; i < operand_count; i++) {
        const char *path = operands[i];
        struct stat st;
        if (stat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
            continue;
        }
        int is_dir = S_ISDIR(st.st_mode);
        unsigned long current = (unsigned long)st.st_mode & 07777;
        unsigned long new_mode = apply_mode(&spec, current, is_dir);
        if (chmod(path, (mode_t)new_mode) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
            continue;
        }
    }
    return any_failed ? 1 : 0;
}
