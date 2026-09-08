#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

/* --- Mode parsing --- */

static int parse_mode_octal(const char *str, size_t len, mode_t *result)
{
    if (len == 0 || len > 4) return -1;
    unsigned long val = 0;
    for (size_t i = 0; i < len; i++) {
        if (str[i] < '0' || str[i] > '7') return -1;
        val = val * 8 + (unsigned long)(str[i] - '0');
    }
    if (val > 07777UL) return -1;
    *result = (mode_t)val;
    return 0;
}

static int parse_mode_symbolic(const char *str, mode_t *result)
{
    mode_t mode = 0777;
    const char *p = str;

    while (1) {
        /* Parse target class letters */
        int classes = 0;
        int has_class = 0;
        while (*p && strchr("ugoa", *p)) {
            if (*p == 'u') classes |= 1;
            else if (*p == 'g') classes |= 2;
            else if (*p == 'o') classes |= 4;
            else if (*p == 'a') classes |= 7;
            has_class = 1;
            p++;
        }
        if (!has_class) classes = 7;

        /* Parse operator */
        if (*p != '+' && *p != '-' && *p != '=') return -1;
        char op = *p;
        p++;

        /* Parse permission letters */
        int perms = 0;
        while (*p && *p != ',') {
            switch (*p) {
                case 'r': perms |= 0444; break;
                case 'w': perms |= 0222; break;
                case 'x': case 'X': perms |= 0111; break;
                case 's': perms |= 06000; break;
                case 't': perms |= 01000; break;
                default: return -1;
            }
            p++;
        }

        /* Build the class mask to limit which bits are affected */
        int mask = 0;
        if (classes & 1) mask |= 0700 | 04000; /* u: rwx + setuid */
        if (classes & 2) mask |= 0070 | 02000; /* g: rwx + setgid */
        if (classes & 4) mask |= 0007 | 01000; /* o: rwx + sticky  */
        perms &= mask;

        /* Apply operator */
        switch (op) {
            case '+': mode |= (mode_t)perms; break;
            case '-': mode &= ~(mode_t)perms; break;
            case '=': mode = (mode & ~(mode_t)mask) | (mode_t)perms; break;
        }

        /* Advance to next clause or finish */
        if (*p == ',') { p++; continue; }
        break;
    }

    *result = mode;
    return 0;
}

static int parse_mode(const char *str, mode_t *result)
{
    size_t len = strlen(str);
    if (len == 0) return -1;

    int all_octal = 1;
    for (size_t i = 0; i < len; i++) {
        if (str[i] < '0' || str[i] > '7') { all_octal = 0; break; }
    }
    if (all_octal) return parse_mode_octal(str, len, result);

    return parse_mode_symbolic(str, result);
}

/* --- mkdir -p with optional final-directory mode --- */

static int mkdir_p(const char *path, mode_t final_mode, int has_mode)
{
    size_t len = strlen(path);
    char *buf = malloc(len + 1);
    if (!buf) return -1;
    memcpy(buf, path, len + 1);

    int rc = 0;

    for (size_t i = 0; i <= len; i++) {
        if (i < len && buf[i] != '/') continue;

        size_t prefix_len = i;
        if (i < len) buf[i] = '\0';

        if (prefix_len == 0 || (prefix_len == 1 && buf[0] == '/')) {
            if (i < len) buf[i] = '/';
            continue;
        }

        int is_final = (i == len);

        struct stat st;
        if (stat(buf, &st) == 0) {
            if (!S_ISDIR(st.st_mode)) {
                errno = is_final ? EEXIST : ENOTDIR;
                rc = -1;
                break;
            }
            /* Already exists: do NOT modify its mode */
        } else if (mkdir(buf, 0777) != 0) {
            rc = -1;
            break;
        } else if (is_final && has_mode) {
            /* Newly created final directory: set exact mode (no umask) */
            if (chmod(buf, final_mode) != 0) {
                rc = -1;
                break;
            }
        }
        /* Intermediates (or final without -m): leave as 0777 masked by umask */

        if (i < len) buf[i] = '/';
    }

    free(buf);
    return rc;
}

int main(int argc, char *argv[])
{
    char **operands = NULL;
    int noperands = 0;
    int cap = 0;
    int end_of_opts = 0;
    int parents = 0;
    mode_t mode_val = 0;
    int has_mode = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_opts && strcmp(argv[i], "--") == 0) {
            end_of_opts = 1;
            continue;
        }
        if (!end_of_opts && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
                continue;
            }
            if (strcmp(argv[i], "-m") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'm'\n");
                    free(operands);
                    return 1;
                }
                mode_t tmp;
                if (parse_mode(argv[i + 1], &tmp) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i + 1]);
                    free(operands);
                    return 1;
                }
                mode_val = tmp;
                has_mode = 1;
                i++;
                continue;
            }
            if (strncmp(argv[i], "--mode=", 7) == 0) {
                const char *val = argv[i] + 7;
                mode_t tmp;
                if (parse_mode(val, &tmp) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", val);
                    free(operands);
                    return 1;
                }
                mode_val = tmp;
                has_mode = 1;
                continue;
            }
            if (strcmp(argv[i], "--mode") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'mode'\n");
                    free(operands);
                    return 1;
                }
                mode_t tmp;
                if (parse_mode(argv[i + 1], &tmp) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i + 1]);
                    free(operands);
                    return 1;
                }
                mode_val = tmp;
                has_mode = 1;
                i++;
                continue;
            }
            fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                    "Try 'mkdir --help' for more information.\n", argv[i]);
            free(operands);
            return 1;
        }
        if (noperands == cap) {
            int newcap = cap ? cap * 2 : 4;
            char **tmp = realloc(operands, (size_t)newcap * sizeof(char *));
            if (!tmp) {
                fprintf(stderr, "mkdir: memory exhaustion\n");
                free(operands);
                return 1;
            }
            operands = tmp;
            cap = newcap;
        }
        operands[noperands++] = argv[i];
    }

    if (noperands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    int any_failed = 0;

    for (int i = 0; i < noperands; i++) {
        const char *path = operands[i];

        if (parents) {
            if (mkdir_p(path, mode_val, has_mode) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
            }
        } else {
            struct stat st;
            if (lstat(path, &st) == 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
                any_failed = 1;
                continue;
            }
            if (mkdir(path, 0777) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
                continue;
            }
            if (has_mode) {
                if (chmod(path, mode_val) != 0) {
                    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                            path, strerror(errno));
                    any_failed = 1;
                }
            }
        }
    }

    free(operands);
    return any_failed ? 1 : 0;
}
