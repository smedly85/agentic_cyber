#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <unistd.h>

static int create_parents = 0;
static int mode_value = -1;

static int parse_octal(const char *s) {
    if (*s == '\0') return -1;
    int val = 0;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '7') return -1;
        val = val * 8 + (*p - '0');
    }
    return val & 07777;
}

static int parse_symbolic(const char *s) {
    if (*s == '\0') return -1;

    int mode = 0777;
    const char *p = s;

    while (*p) {
        int classes = 0;
        int has_class = 0;
        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            has_class = 1;
            switch (*p) {
                case 'u': classes |= 1; break;
                case 'g': classes |= 2; break;
                case 'o': classes |= 4; break;
                case 'a': classes |= 7; break;
            }
            p++;
        }
        if (!has_class) classes = 7;

        if (*p != '+' && *p != '-' && *p != '=') return -1;
        char op = *p++;

        int has_r = 0, has_w = 0, has_x = 0;
        int has_s = 0, has_t = 0;
        while (*p && *p != ',') {
            switch (*p) {
                case 'r': has_r = 1; break;
                case 'w': has_w = 1; break;
                case 'x': case 'X': has_x = 1; break;
                case 's': has_s = 1; break;
                case 't': has_t = 1; break;
                default: return -1;
            }
            p++;
        }

        int bits = 0;
        if (has_r) {
            if (classes & 1) bits |= 0400;
            if (classes & 2) bits |= 0040;
            if (classes & 4) bits |= 0004;
        }
        if (has_w) {
            if (classes & 1) bits |= 0200;
            if (classes & 2) bits |= 0020;
            if (classes & 4) bits |= 0002;
        }
        if (has_x) {
            if (classes & 1) bits |= 0100;
            if (classes & 2) bits |= 0010;
            if (classes & 4) bits |= 0001;
        }
        if (has_s) {
            if (classes & 1) bits |= 04000;
            if (classes & 2) bits |= 02000;
        }
        if (has_t) {
            bits |= 01000;
        }

        int affected = 0;
        if (classes & 1) affected |= 0700;
        if (classes & 2) affected |= 0070;
        if (classes & 4) affected |= 0007;
        if (classes & 1) affected |= 04000;
        if (classes & 2) affected |= 02000;
        if (classes & 4) affected |= 01000;

        if (op == '+') {
            mode |= bits;
        } else if (op == '-') {
            mode &= ~bits;
        } else {
            mode = (mode & ~affected) | bits;
        }

        if (*p == ',') p++;
    }

    return mode & 07777;
}

static int parse_mode(const char *s) {
    if (*s == '\0') return -1;
    int r = parse_octal(s);
    if (r >= 0) return r;
    r = parse_symbolic(s);
    if (r >= 0) return r;
    return -1;
}

static int parse_args(int argc, char *argv[], int *first_operand_idx) {
    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                create_parents = 1;
                i++;
                continue;
            }
            if (strcmp(argv[i], "-m") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'm'\n");
                    return 1;
                }
                int m = parse_mode(argv[i + 1]);
                if (m < 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i + 1]);
                    return 1;
                }
                mode_value = m;
                i += 2;
                continue;
            }
            if (strncmp(argv[i], "--mode=", 7) == 0) {
                const char *mstr = argv[i] + 7;
                int m = parse_mode(mstr);
                if (m < 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", mstr);
                    return 1;
                }
                mode_value = m;
                i++;
                continue;
            }
            if (strcmp(argv[i], "--mode") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'mode'\n");
                    return 1;
                }
                int m = parse_mode(argv[i + 1]);
                if (m < 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i + 1]);
                    return 1;
                }
                mode_value = m;
                i += 2;
                continue;
            }
            fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                            "Try 'mkdir --help' for more information.\n",
                    argv[i]);
            return 1;
        }
        break;
    }

    if (i >= argc) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    *first_operand_idx = i;
    return 0;
}

static int make_parent_dirs(const char *path) {
    char *tmp = strdup(path);
    if (!tmp) return -1;

    char *p = tmp;
    if (*p == '/') p++;

    while (*p) {
        while (*p && *p != '/') p++;
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, 0777) != 0 && errno != EEXIST) {
                free(tmp);
                return -1;
            }
            *p = '/';
        }
        p++;
    }

    free(tmp);
    return 0;
}

int main(int argc, char *argv[]) {
    int first_operand;
    if (parse_args(argc, argv, &first_operand) != 0) {
        return 1;
    }

    int any_failed = 0;
    for (int j = first_operand; j < argc; j++) {
        const char *path = argv[j];

        if (create_parents) {
            if (make_parent_dirs(path) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
                continue;
            }
        }

        if (mkdir(path, 0777) != 0) {
            if (errno == EEXIST && create_parents) {
                continue;
            }
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            any_failed = 1;
            continue;
        }

        if (mode_value >= 0) {
            if (chmod(path, (mode_t)mode_value) != 0) {
                fprintf(stderr, "mkdir: cannot set mode for '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
            }
        }
    }

    return any_failed ? 1 : 0;
}
