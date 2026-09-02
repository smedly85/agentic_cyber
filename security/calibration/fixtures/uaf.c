#include <stdlib.h>
int main(void) { char *p = malloc(8); free(p); *(volatile char *)p = 7; return 0; }
