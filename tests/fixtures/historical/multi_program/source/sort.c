static void vulnerable_sort(void) {}

static void sort_helper(void) {
    vulnerable_sort();
}

int main(void) {
    sort_helper();
    return 0;
}
