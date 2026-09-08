#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>

#define MAX_CLAUSES 256

typedef struct {
    int classes;
    int op;
    int perms;
} clause_t;

typedef struct {
    int is_octal;
    unsigned long value;
    int clause_count;
    clause_t clauses[MAX_CLAUSES];
} mode_spec_t;

enum { REPORT_NONE = 0, REPORT_CHANGES = 1, REPORT_VERBOSE = 2 };

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
        c->classes = 0; c->op = -1; c->perms = 0;
        const char *q = clause_start;
        const char *qend = clause_start + clause_len;
        const char *op_pos = NULL;
        for (const char *r = q; r < qend; r++) {
            if (*r == '+' || *r == '-' || *r == '=') { op_pos = r; break; }
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
        unsigned long set_mask = 0, clear_mask = 0;
        for (int cls = 0; cls < 3; cls++) {
            if (!(c->classes & (1 << cls))) continue;
            unsigned long r_bit, w_bit, x_bit;
            if (cls == 0)      { r_bit = 0400; w_bit = 0200; x_bit = 0100; }
            else if (cls == 1) { r_bit = 0040; w_bit = 0020; x_bit = 0010; }
            else               { r_bit = 0004; w_bit = 0002; x_bit = 0001; }
            if (c->perms & 1) { if (c->op == 1) clear_mask |= r_bit; else set_mask |= r_bit; }
            if (c->perms & 2) { if (c->op == 1) clear_mask |= w_bit; else set_mask |= w_bit; }
            if (c->perms & 4) { if (c->op == 1) clear_mask |= x_bit; else set_mask |= x_bit; }
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

static void format_symbolic(unsigned long mode, char *out) {
    unsigned long perms = mode & 0777;
    unsigned long special = mode & 07000;
    int bits[9];
    bits[0] = (perms & 0400) != 0;
    bits[1] = (perms & 0200) != 0;
    bits[2] = (perms & 0100) != 0;
    bits[3] = (perms & 0040) != 0;
    bits[4] = (perms & 0020) != 0;
    bits[5] = (perms & 0010) != 0;
    bits[6] = (perms & 0004) != 0;
    bits[7] = (perms & 0002) != 0;
    bits[8] = (perms & 0001) != 0;

    const char *letters = "rwxrwxrwx";
    for (int i = 0; i < 9; i++)
        out[i] = bits[i] ? letters[i] : '-';

    if (special & 04000) out[2] = bits[2] ? 's' : 'S';
    if (special & 02000) out[5] = bits[5] ? 's' : 'S';
    if (special & 01000) out[8] = bits[8] ? 't' : 'T';
    out[9] = '\0';
}

static void report_change(const char *display_path, unsigned long old_mode, unsigned long new_mode) {
    char sym_old[10], sym_new[10];
    format_symbolic(old_mode, sym_old);
    format_symbolic(new_mode, sym_new);
    printf("mode of '%s' changed from %04lo (%s) to %04lo (%s)\n",
           display_path, old_mode, sym_old, new_mode, sym_new);
}

static void report_retained(const char *display_path, unsigned long mode) {
    char sym[10];
    format_symbolic(mode, sym);
    printf("mode of '%s' retained as %04lo (%s)\n",
           display_path, mode, sym);
}

static int byte_compare(const void *a, const void *b) {
    const char *sa = *(const char * const *)a;
    const char *sb = *(const char * const *)b;
    size_t la = strlen(sa), lb = strlen(sb);
    size_t minlen = la < lb ? la : lb;
    int cmp = memcmp(sa, sb, minlen);
    if (cmp != 0) return cmp;
    if (la < lb) return -1;
    if (la > lb) return 1;
    return 0;
}

static int apply_to_path(const mode_spec_t *spec, const char *path,
                         const char *display_path, int report_level) {
    struct stat st;
    if (stat(path, &st) != 0) {
        fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
        return -1;
    }
    int is_dir = S_ISDIR(st.st_mode);
    unsigned long current = (unsigned long)st.st_mode & 07777;
    unsigned long new_mode = apply_mode(spec, current, is_dir);
    if (chmod(path, (mode_t)new_mode) != 0) {
        fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
        return -1;
    }
    if (report_level != REPORT_NONE) {
        struct stat st2;
        if (stat(path, &st2) == 0) {
            unsigned long actual = (unsigned long)st2.st_mode & 07777;
            if (actual != current) {
                report_change(display_path, current, actual);
            } else if (report_level == REPORT_VERBOSE) {
                report_retained(display_path, actual);
            }
        }
    }
    return 0;
}

static int walk_recursive(const mode_spec_t *spec, const char *root,
                          const char *display_base, int report_level) {
    int any_failed = 0;
    size_t cap = 64, sp = 0;
    char **stack = malloc(cap * sizeof(char *));
    if (!stack) return -1;

    size_t root_len = strlen(root);
    char *root_copy = strdup(root);
    if (!root_copy) { free(stack); return -1; }
    stack[sp++] = root_copy;

    while (sp > 0) {
        char *path = stack[--sp];
        struct stat st;
        if (stat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
            any_failed = 1;
            free(path);
            continue;
        }

        const char *disp;
        if (strcmp(path, root) == 0) {
            disp = display_base;
        } else {
            size_t rel_offset = root_len + 1;
            size_t rel_len = strlen(path) - rel_offset;
            size_t disp_len = strlen(display_base) + 1 + rel_len;
            char *disp_buf = malloc(disp_len + 1);
            if (disp_buf) {
                snprintf(disp_buf, disp_len + 1, "%s/%s", display_base, path + rel_offset);
                disp = disp_buf;
            } else {
                disp = path;
            }
        }

        if (apply_to_path(spec, path, disp, report_level) != 0)
            any_failed = 1;

        if (disp != path && disp != display_base)
            free((void *)disp);

        if (S_ISDIR(st.st_mode)) {
            DIR *dp = opendir(path);
            if (dp) {
                char **names = NULL;
                size_t count = 0, ncap = 0;
                struct dirent *entry;
                while ((entry = readdir(dp)) != NULL) {
                    if (strcmp(entry->d_name, ".") == 0 ||
                        strcmp(entry->d_name, "..") == 0)
                        continue;
                    size_t plen = strlen(path) + 1 + strlen(entry->d_name) + 1;
                    char *full = malloc(plen);
                    if (!full) {
                        for (size_t k = 0; k < count; k++) free(names[k]);
                        free(names); closedir(dp); free(path); free(stack);
                        return -1;
                    }
                    snprintf(full, plen, "%s/%s", path, entry->d_name);
                    struct stat lst;
                    if (lstat(full, &lst) != 0) {
                        fprintf(stderr, "new_chmod: %s: %s\n", full, strerror(errno));
                        any_failed = 1;
                        free(full);
                        continue;
                    }
                    if (S_ISLNK(lst.st_mode)) {
                        free(full);
                        continue;
                    }
                    if (count == ncap) {
                        ncap = ncap ? ncap * 2 : 16;
                        char **tmp = realloc(names, ncap * sizeof(char *));
                        if (!tmp) {
                            free(full);
                            for (size_t k = 0; k < count; k++) free(names[k]);
                            free(names); closedir(dp); free(path); free(stack);
                            return -1;
                        }
                        names = tmp;
                    }
                    names[count++] = full;
                }
                closedir(dp);
                if (count > 0) {
                    qsort(names, count, sizeof(char *), byte_compare);
                    for (size_t j = count; j > 0; j--) {
                        if (sp == cap) {
                            size_t ncap2 = cap * 2;
                            char **tmp = realloc(stack, ncap2 * sizeof(char *));
                            if (!tmp) {
                                for (size_t k = 0; k < count; k++) free(names[k]);
                                free(names); free(path); free(stack);
                                return -1;
                            }
                            stack = tmp; cap = ncap2;
                        }
                        stack[sp++] = names[j - 1];
                    }
                }
                free(names);
            } else {
                fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
                any_failed = 1;
            }
        }
        free(path);
    }
    free(stack);
    return any_failed ? -1 : 0;
}

static char *strip_trailing_slashes(const char *s) {
    size_t len = strlen(s);
    while (len > 1 && s[len - 1] == '/') len--;
    char *result = malloc(len + 1);
    if (!result) return strdup(s);
    memcpy(result, s, len);
    result[len] = '\0';
    return result;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "new_chmod: missing arguments\n");
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
    }

    int recursive = 0;
    int report_level = REPORT_NONE;
    int i = 1;

    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        } else if (strcmp(argv[i], "--changes") == 0) {
            report_level = REPORT_CHANGES;
            i++;
        } else if (strcmp(argv[i], "--recursive") == 0) {
            recursive = 1;
            i++;
        } else if (strcmp(argv[i], "--verbose") == 0) {
            report_level = REPORT_VERBOSE;
            i++;
        } else if (argv[i][0] == '-' && argv[i][1] == '\0') {
            break;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (argv[i][1] == '-') {
                fprintf(stderr, "new_chmod: unknown option: %s\n", argv[i]);
                fprintf(stderr, "usage: new_chmod MODE FILE...\n");
                return 1;
            }
            const char *p = argv[i] + 1;
            for (; *p; p++) {
                if (*p == 'R') recursive = 1;
                else if (*p == 'c') report_level = REPORT_CHANGES;
                else if (*p == 'v') report_level = REPORT_VERBOSE;
                else {
                    fprintf(stderr, "new_chmod: unknown option: %s\n", argv[i]);
                    fprintf(stderr, "usage: new_chmod MODE FILE...\n");
                    return 1;
                }
            }
            i++;
        } else {
            break;
        }
    }

    const char *mode_str = NULL;
    char **operands;
    int operand_count;

    if (i < argc) {
        mode_str = argv[i];
        i++;
        operands = &argv[i];
        operand_count = argc - i;
    } else {
        operands = &argv[argc];
        operand_count = 0;
    }

    if (!mode_str) {
        fprintf(stderr, "new_chmod: missing MODE\n");
        fprintf(stderr, "usage: new_chmod MODE FILE...\n");
        return 1;
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
    for (int j = 0; j < operand_count; j++) {
        const char *path = operands[j];
        if (recursive) {
            struct stat st;
            if (stat(path, &st) != 0) {
                fprintf(stderr, "new_chmod: %s: %s\n", path, strerror(errno));
                any_failed = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                char *db = strip_trailing_slashes(path);
                if (walk_recursive(&spec, path, db, report_level) != 0)
                    any_failed = 1;
                free(db);
            } else {
                if (apply_to_path(&spec, path, path, report_level) != 0)
                    any_failed = 1;
            }
        } else {
            if (apply_to_path(&spec, path, path, report_level) != 0)
                any_failed = 1;
        }
    }
    return any_failed ? 1 : 0;
}
