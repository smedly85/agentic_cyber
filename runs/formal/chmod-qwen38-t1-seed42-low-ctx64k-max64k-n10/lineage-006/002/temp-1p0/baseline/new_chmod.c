#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <ctype.h>
#include <dirent.h>

#define MAX_DEPTH 1000

typedef struct {
    int classes;   /* bit 0: u, bit 1: g, bit 2: o */
    int op;        /* '+', '-', '=' */
    int perms;     /* bit 0: r, bit 1: w, bit 2: x */
    int has_upper_X; /* uppercase X was in the permission list */
} clause_t;

typedef struct {
    int is_octal;
    mode_t octal_val;
    clause_t clauses[128];
    int nclauses;
} mode_spec_t;

static int is_all_octal_digits(const char *s, size_t len)
{
    if (len == 0)
        return 0;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '7')
            return 0;
    }
    return 1;
}

static int parse_octal(const char *s, size_t len, mode_t *out)
{
    if (len < 1 || len > 4)
        return 0;
    mode_t val = 0;
    for (size_t i = 0; i < len; i++) {
        val = (val << 3) | (mode_t)(s[i] - '0');
    }
    *out = val;
    return 1;
}

static int parse_clause(const char *s, size_t len, clause_t *out)
{
    if (len == 0)
        return 0;

    size_t i = 0;
    int classes = 0;

    while (i < len) {
        char c = s[i];
        if (c == 'u') classes |= 1;
        else if (c == 'g') classes |= 2;
        else if (c == 'o') classes |= 4;
        else if (c == 'a') classes |= 7;
        else break;
        i++;
    }

    if (i >= len)
        return 0;
    int op = s[i];
    if (op != '+' && op != '-' && op != '=')
        return 0;
    i++;

    int perms = 0;
    int has_upper_X = 0;
    while (i < len) {
        char c = s[i];
        if (c == 'r') perms |= 1;
        else if (c == 'w') perms |= 2;
        else if (c == 'x') perms |= 4;
        else if (c == 'X') has_upper_X = 1;
        else return 0;
        i++;
    }

    if (classes == 0)
        classes = 7;
    out->classes = classes;
    out->op = op;
    out->perms = perms;
    out->has_upper_X = has_upper_X;
    return 1;
}

static int parse_mode(const char *s, size_t len, mode_spec_t *spec)
{
    memset(spec, 0, sizeof(*spec));
    if (len == 0)
        return 0;

    if (is_all_octal_digits(s, len)) {
        if (!parse_octal(s, len, &spec->octal_val))
            return 0;
        spec->is_octal = 1;
        return 1;
    }

    spec->is_octal = 0;
    size_t start = 0;
    for (size_t i = 0; i <= len; i++) {
        if (i == len || s[i] == ',') {
            size_t clen = i - start;
            if (clen == 0)
                return 0;
            if (spec->nclauses >= 128)
                return 0;
            if (!parse_clause(s + start, clen, &spec->clauses[spec->nclauses]))
                return 0;
            spec->nclauses++;
            start = i + 1;
        }
    }
    return spec->nclauses > 0;
}

static mode_t apply_symbolic(mode_t current, const clause_t *clauses, int n, int is_dir)
{
    mode_t result = current & 07777;

    for (int i = 0; i < n; i++) {
        const clause_t *cl = &clauses[i];
        int has_exec = (result & 0111) != 0;

        int r_bit = cl->perms & 1;
        int w_bit = cl->perms & 2;
        int x_bit = cl->perms & 4;
        int effective_x = x_bit;
        if (!x_bit && cl->has_upper_X)
            effective_x = is_dir || has_exec;

        for (int cls = 0; cls < 3; cls++) {
            if (!(cl->classes & (1 << cls)))
                continue;

            mode_t class_mask = (mode_t)(0700 >> (cls * 3));
            mode_t perm = 0;
            if (r_bit)
                perm |= (mode_t)(0400 >> (cls * 3));
            if (w_bit)
                perm |= (mode_t)(0200 >> (cls * 3));
            if (effective_x)
                perm |= (mode_t)(0100 >> (cls * 3));

            if (cl->op == '+')
                result |= perm;
            else if (cl->op == '-')
                result &= ~perm;
            else
                result = (result & ~class_mask) | perm;
        }
    }

    return result | (current & 07000);
}

static int name_cmp(const void *a, const void *b)
{
    const char *na = *(const char *const *)a;
    const char *nb = *(const char *const *)b;
    return strcmp(na, nb);
}

static void walk_dir(const char *dir, const mode_spec_t *spec, int *any_failed, int depth)
{
    if (depth > MAX_DEPTH) {
        fprintf(stderr, "new_chmod: maximum depth exceeded for '%s'\n", dir);
        *any_failed = 1;
        return;
    }

    DIR *d = opendir(dir);
    if (!d) {
        fprintf(stderr, "new_chmod: cannot open directory '%s': %s\n",
                dir, strerror(errno));
        *any_failed = 1;
        return;
    }

    char **names = NULL;
    int n = 0, cap = 0;
    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0)
            continue;
        if (n >= cap) {
            cap = cap ? cap * 2 : 16;
            char **tmp = realloc(names, (size_t)cap * sizeof(char *));
            if (!tmp) {
                for (int i = 0; i < n; i++) free(names[i]);
                free(names);
                closedir(d);
                *any_failed = 1;
                return;
            }
            names = tmp;
        }
        names[n] = strdup(ent->d_name);
        if (!names[n]) {
            for (int i = 0; i < n; i++) free(names[i]);
            free(names);
            closedir(d);
            *any_failed = 1;
            return;
        }
        n++;
    }
    closedir(d);

    qsort(names, (size_t)n, sizeof(char *), name_cmp);

    for (int i = 0; i < n; i++) {
        size_t full_len = strlen(dir) + 1 + strlen(names[i]) + 1;
        char *full = malloc(full_len);
        if (!full) {
            for (int j = 0; j < n; j++) free(names[j]);
            free(names);
            *any_failed = 1;
            return;
        }
        snprintf(full, full_len, "%s/%s", dir, names[i]);

        struct stat st;
        if (lstat(full, &st) != 0) {
            fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                    full, strerror(errno));
            *any_failed = 1;
            free(full);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(full);
            continue;
        }

        mode_t new_mode;
        if (spec->is_octal) {
            new_mode = spec->octal_val;
        } else {
            new_mode = apply_symbolic(st.st_mode, spec->clauses,
                                      spec->nclauses, S_ISDIR(st.st_mode));
        }

        if (chmod(full, new_mode) != 0) {
            fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                    full, strerror(errno));
            *any_failed = 1;
            free(full);
            continue;
        }

        if (S_ISDIR(st.st_mode)) {
            walk_dir(full, spec, any_failed, depth + 1);
        }

        free(full);
    }

    for (int i = 0; i < n; i++) free(names[i]);
    free(names);
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "new_chmod: missing operand\n");
        return 1;
    }

    int recursive = 0;
    int idx = 1;

    while (idx < argc) {
        if (strcmp(argv[idx], "--") == 0) {
            idx++;
            break;
        } else if (strcmp(argv[idx], "-R") == 0) {
            recursive = 1;
            idx++;
        } else if (strcmp(argv[idx], "--recursive") == 0) {
            recursive = 1;
            idx++;
        } else if (argv[idx][0] == '-' && argv[idx][1] != '\0') {
            fprintf(stderr, "new_chmod: unknown option '%s'\n", argv[idx]);
            return 1;
        } else {
            break;
        }
    }

    if (idx >= argc) {
        fprintf(stderr, "new_chmod: missing operand\n");
        return 1;
    }

    const char *mode_str = argv[idx];
    idx++;

    if (idx >= argc) {
        fprintf(stderr, "new_chmod: missing operand\n");
        return 1;
    }

    size_t mode_len = strlen(mode_str);
    mode_spec_t spec;
    if (!parse_mode(mode_str, mode_len, &spec)) {
        fprintf(stderr, "new_chmod: invalid mode '%s'\n", mode_str);
        return 1;
    }

    int any_failed = 0;
    for (int i = idx; i < argc; i++) {
        const char *path = argv[i];
        struct stat st;
        if (stat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                    path, strerror(errno));
            any_failed = 1;
            continue;
        }

        if (recursive && S_ISDIR(st.st_mode)) {
            mode_t new_mode;
            if (spec.is_octal) {
                new_mode = spec.octal_val;
            } else {
                new_mode = apply_symbolic(st.st_mode, spec.clauses,
                                          spec.nclauses, 1);
            }
            if (chmod(path, new_mode) != 0) {
                fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
            }
            walk_dir(path, &spec, &any_failed, 1);
        } else {
            mode_t new_mode;
            if (spec.is_octal) {
                new_mode = spec.octal_val;
            } else {
                new_mode = apply_symbolic(st.st_mode, spec.clauses,
                                          spec.nclauses, S_ISDIR(st.st_mode));
            }
            if (chmod(path, new_mode) != 0) {
                fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
            }
        }
    }

    return any_failed ? 1 : 0;
}
