#include <stdio.h>
int main(void) { char buffer[16]; return fgets(buffer, sizeof buffer, stdin) ? 0 : 0; }
