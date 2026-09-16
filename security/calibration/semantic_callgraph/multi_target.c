static void foo(void) {}
static void bar(void) {}
int main(int argc, char **argv) {
    void (*fp)(void) = argc > 1 ? foo : bar;
    (void) argv;
    fp();
    return 0;
}
