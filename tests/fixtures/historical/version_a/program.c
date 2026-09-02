static void vulnerable(void) {}

int main(void) {
    vulnerable();
    return 0;
}

static void unreachable(void) {}

