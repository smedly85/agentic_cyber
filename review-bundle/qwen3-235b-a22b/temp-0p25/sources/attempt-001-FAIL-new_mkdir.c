#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

int
process_path(char *path)
    {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
    char *end = path + strlen(path) - 1;
    while (end > path && *end == '/')     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        *end-- = '\0';
    }
    // Remove trailing slashes
    char *p = path + strlen(path) - 1;
    while (p > path && *p == '/')     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        *p-- = '\0';
    }
    // Remove trailing slashes
    char *p = path + strlen(path) - 1;
    while (p > path && *p == '/')     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        *p-- = '\0';
    }
    char parent[1024];
    char *slash = strrchr(path, '/');

    if (slash)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        if (slash == path)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
            strcpy(parent, "/");
        } else     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
            strncpy(parent, path, slash - path);
            parent[slash - path] = '\0';
        }
    } else     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        strcpy(parent, ".");
    }

    if (stat(parent, &st) != 0)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        return 1;
    }
    if (!S_ISDIR(st.st_mode))     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
        return 1;
    }

    if (stat(path, &st) == 0)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
        return 1;
    }
    if (errno != ENOENT)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        return 1;
    }

    if (mkdir(path, 0777) != 0)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        return 1;
    }
    return 0;
}

int
main(int argc, char *argv[])
    {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
    int operands_start = 1;
    int error_count = 0;

    for (int i = 1; i < argc; i++)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        if (argv[i][0] == '-')     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
            if (strcmp(argv[i], "--") == 0)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
                operands_start = i + 1;
                break;
            } else if (strcmp(argv[i], "-") != 0)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
                fprintf(stderr, "mkdir: invalid option %s\n", argv[i]);
                exit(1);
            }
        }
    }

    if (argc - operands_start < 1)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        fprintf(stderr, "mkdir: missing operand\n");
        exit(1);
    }

    for (int i = operands_start; i < argc; i++)     {
    // Remove trailing slashes
    char *tr = path + strlen(path) - 1;
    while (tr > path && *tr == '/') {
        *tr-- = '\0';
    }
    // Remove trailing slashes
    char *trail = path + strlen(path) - 1;
    while (trail > path && *trail == '/') {
        *trail-- = '\0';
    }
        error_count += process_path(argv[i]);
    }

    return error_count ? 1 : 0;
}