static volatile int keep_going = 1;
static int descend(int n) { volatile char pad[4096]; pad[0] = (char)n; return keep_going ? descend(n + pad[0]) : n; }
int main(void) { return descend(1); }
