static void recurse(unsigned n) { if (n != 0) recurse(n - 1); }
int main(void) { recurse(2); return 0; }
