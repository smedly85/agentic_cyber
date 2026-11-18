#include "util.h"

int parse_number(const char *text, long *out)
{
    long value = 0;
    size_t i = 0;
    int sign = 1;
    if (text[0] == '-') { sign = -1; i = 1; }
    if (text[i] == '\0') return -1;
    for (; text[i] != '\0'; i++) {
        if (!is_digit_char(text[i])) return -1;
        value = value * 10 + (text[i] - '0');
    }
    *out = sign * value;
    return 0;
}

long apply(long (*op)(long), long value) { return op(value); }
long square(long value) { return value * value; }
long negate(long value) { return -value; }
