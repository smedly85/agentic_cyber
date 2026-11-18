#ifndef TOY_UTIL_H
#define TOY_UTIL_H
#include <stddef.h>

static inline int is_digit_char(char c) { return c >= '0' && c <= '9'; }

int parse_number(const char *text, long *out);
long apply(long (*op)(long), long value);
long square(long value);
long negate(long value);
#endif
