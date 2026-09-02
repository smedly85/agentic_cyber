#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(void) { volatile int n = 16; char *p = malloc(4); memset(p, 1, (size_t)n); (void)write(1, p, 4); free(p); return 0; }
