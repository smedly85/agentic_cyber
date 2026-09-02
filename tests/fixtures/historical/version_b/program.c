static void vulnerable(void) {}

static void bridge(void) {
    vulnerable();
}

int main(void) {
    bridge();
    return 0;
}

