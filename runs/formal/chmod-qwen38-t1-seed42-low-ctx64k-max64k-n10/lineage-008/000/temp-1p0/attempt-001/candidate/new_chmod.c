#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

enum op { OP_ADD, OP_SUB, OP_SET };

typedef struct {
    mode_t class_mask;
    enum op op;
    mode_t perm_mask;
    bool has_X;
} clause_t;

typedef struct {
    bool is_octal;
    mode_t octal_value;
    clause_t clauses[256];
    int nclauses;
} mode_spec_t;

static int parse_octal(const char *s, mode_spec_t *spec)
{
    size_t len = strlen(s);
    if (len < 1 || len > 4)
        return -1;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '7')
            return -1;
    }
    spec->is_octal = true;
    spec->octal_value = 0;
    for (size_t i = 0; i < len; i++)
        spec->octal_value = (spec->octal_value << 3) | (mode_t)(s[i] - '0');
    return 0;
}

static int parse_symbolic(const char *s, mode_spec_t *spec)
{
    spec->is_octal = false;
    spec->nclauses = 0;

    size_t slen = strlen(s);
    if (slen == 0 || s[slen - 1] == ',')
        return -1;

    const char *p = s;
    while (*p) {
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);

        if (len == 0)
            return -1;
        if (spec->nclauses >= 256)
            return -1;

        clause_t *cl = &spec->clauses[spec->nclauses];
        cl->class_mask = 0;
        cl->op = OP_ADD;
        cl->perm_mask = 0;
        cl->has_X = false;

        size_t i = 0;
        bool has_class = false;

        while (i < len && (p[i] == 'u' || p[i] == 'g' || p[i] == 'o' || p[i] == 'a')) {
            has_class = true;
            switch (p[i]) {
            case 'u': cl->class_mask |= 0700; break;
            case 'g': cl->class_mask |= 0070; break;
            case 'o': cl->class_mask |= 0007; break;
            case 'a': cl->class_mask |= 0777; break;
            }
            i++;
        }
        if (!has_class)
            cl->class_mask = 0777;

        if (i >= len)
            return -1;
        switch (p[i]) {
        case '+': cl->op = OP_ADD; break;
        case '-': cl->op = OP_SUB; break;
        case '=': cl->op = OP_SET; break;
        default: return -1;
        }
        i++;

        while (i < len) {
            switch (p[i]) {
            case 'r': cl->perm_mask |= 0444; break;
            case 'w': cl->perm_mask |= 0222; break;
            case 'x': cl->perm_mask |= 0111; break;
            case 'X': cl->has_X = true; break;
            default: return -1;
            }
            i++;
        }

        spec->nclauses++;
        if (end)
            p = end + 1;
        else
            break;
    }

    if (spec->nclauses == 0)
        return -1;
    return 0;
}

static mode_t apply_symbolic(const mode_spec_t *spec, mode_t current, bool is_dir)
{
    mode_t mode = current & 0777;

    for (int i = 0; i < spec->nclauses; i++) {
        const clause_t *cl = &spec->clauses[i];
        mode_t perm = cl->perm_mask;

        if (cl->has_X) {
            if (is_dir || (mode & 0111))
                perm |= 0111;
        }

        mode_t effective = perm & cl->class_mask;

        switch (cl->op) {
        case OP_ADD: mode |= effective; break;
        case OP_SUB: mode &= ~effective; break;
        case OP_SET: mode = (mode & ~cl->class_mask) | effective; break;
        }
    }

    return (current & 07000) | (mode & 0777);
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    }

    int mode_idx;
    if (strcmp(argv[1], "--") == 0) {
        mode_idx = 2;
    } else if (argv[1][0] == '-') {
        fprintf(stderr, "new_chmod: unknown option: %s\n", argv[1]);
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    } else {
        mode_idx = 1;
    }

    if (argc <= mode_idx + 1) {
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    }

    const char *mode_str = argv[mode_idx];
    mode_spec_t spec;
    memset(&spec, 0, sizeof(spec));

    bool all_octal = false;
    size_t mlen = strlen(mode_str);
    if (mlen >= 1 && mlen <= 4) {
        all_octal = true;
        for (size_t i = 0; i < mlen; i++) {
            if (mode_str[i] < '0' || mode_str[i] > '7') {
                all_octal = false;
                break;
            }
        }
    }

    if (all_octal) {
        if (parse_octal(mode_str, &spec) != 0) {
            fprintf(stderr, "new_chmod: invalid mode: %s\n", mode_str);
            return 1;
        }
    } else {
        if (parse_symbolic(mode_str, &spec) != 0) {
            fprintf(stderr, "new_chmod: invalid mode: %s\n", mode_str);
            return 1;
        }
    }

    int exit_code = 0;
    for (int i = mode_idx + 1; i < argc; i++) {
        const char *path = argv[i];
        struct stat st;

        if (stat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                    path, strerror(errno));
            exit_code = 1;
            continue;
        }

        bool is_dir = S_ISDIR(st.st_mode);
        mode_t new_mode;

        if (spec.is_octal)
            new_mode = spec.octal_value;
        else
            new_mode = apply_symbolic(&spec, st.st_mode, is_dir);

        if (chmod(path, new_mode) != 0) {
            fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                    path, strerror(errno));
            exit_code = 1;
        }
    }

    return exit_code;
}
