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

static int walk_dir(const char *path, const parsed_mode_t *pm, int depth) {
    DIR *dir = opendir(path);
    if (!dir) {
        fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
        return 1;
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
            fprintf(stderr, "new_chmod: %s: %s\n", full, strerror(errno));
            failed = 1;
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
            fprintf(stderr, "new_chmod: %s: %s\n", full, strerror(errno));
            failed = 1;
        }

        if (is_dir) {
            if (depth + 1 > MAX_DEPTH) {
                fprintf(stderr, "new_chmod: %s: maximum recursion depth exceeded\n", full);
                failed = 1;
            } else if (walk_dir(full, pm, depth + 1)) {
                failed = 1;
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
            if (strcmp(argv[start], "-R") == 0 || strcmp(argv[start], "--recursive") == 0) {
                recursive = 1;
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
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
            continue;
        }

        int is_dir = S_ISDIR(st.st_mode);
        mode_t current = st.st_mode & 07777;
        mode_t new_mode = (mode_t)compute_new_mode(&pm, current, is_dir);

        if (chmod(path, new_mode) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
        }

        if (recursive && is_dir) {
            if (walk_dir(path, &pm, 0))
                any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}
