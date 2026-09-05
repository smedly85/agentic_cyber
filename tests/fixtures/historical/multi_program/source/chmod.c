static void deep_chmod_helper(void) {}

static void chmod_helper(void) {
    deep_chmod_helper();
}

int main(void) {
    chmod_helper();
    return 0;
}
