#include <limits.h>
#include <stdlib.h>
int main(void) { volatile int n = INT_MAX; n += 1; char *p = malloc((size_t)n); free(p); return 0; }
