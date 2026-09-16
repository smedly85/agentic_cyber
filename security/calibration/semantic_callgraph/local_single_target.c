static void target(void) {}
int main(void) {
    void (*fp)(void) = target;
    fp();
    return 0;
}
