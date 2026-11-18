#include <stdio.h>
#include <string.h>
#include "util.h"

static long sum_all(int count, char **items, int *ok)
{
    long total = 0, value = 0;
    for (int i = 0; i < count; i++) {
        if (parse_number(items[i], &value) != 0) { *ok = 0; return 0; }
        total += value;
    }
    *ok = 1;
    return total;
}

static void unused_debug(void) { puts("never called"); }

int main(int argc, char **argv)
{
    int ok = 0;
    if (argc < 2) { fprintf(stderr, "usage: toy [-s|-n] NUM...\n"); return 2; }
    long (*op)(long) = 0;
    int first = 1;
    if (strcmp(argv[1], "-s") == 0) { op = square; first = 2; }
    else if (strcmp(argv[1], "-n") == 0) { op = negate; first = 2; }
    long total = sum_all(argc - first, argv + first, &ok);
    if (!ok) { fprintf(stderr, "toy: invalid number\n"); return 1; }
    if (op) total = apply(op, total);
    printf("%ld\n", total);
    return 0;
}
