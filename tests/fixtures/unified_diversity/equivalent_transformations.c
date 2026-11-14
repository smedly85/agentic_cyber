#include <stdint.h>
#include <stdio.h>

static uint32_t core(uint32_t x) {
    return x * 3u + 7u;
}

static uint32_t wrap_base(uint32_t x) {
    return core(x);
}

static uint32_t wrap_variant(uint32_t x) {
    if ((x & 1u) != 0u) {
        return core(x);
    }
    return core(x);
}

static uint32_t helper_base(uint32_t x) {
    return x * 5u + 11u;
}

static uint32_t extracted_helper(uint32_t x) {
    return x * 5u + 11u;
}

static uint32_t helper_variant(uint32_t x) {
    return extracted_helper(x);
}

static uint32_t padding_base(uint32_t x) {
    return core(x);
}

static uint32_t padding_variant(uint32_t x) {
    uint32_t dead = (x ^ x) + (x - x);
    return core(x) + (dead & 0u);
}

static uint32_t branch_base(uint32_t x) {
    if ((x & 1u) != 0u) {
        return x + 3u;
    }
    return x + 5u;
}

static uint32_t branch_variant(uint32_t x) {
    switch (x & 1u) {
    case 1u:
        return x + 3u;
    default:
        return x + 5u;
    }
}

static int check(uint32_t x) {
    return wrap_base(x) == wrap_variant(x)
        && helper_base(x) == helper_variant(x)
        && padding_base(x) == padding_variant(x)
        && branch_base(x) == branch_variant(x);
}

int main(void) {
    static const uint32_t boundaries[] = {
        0u, 1u, 2u, 3u, UINT32_MAX, UINT32_MAX - 1u, 0x80000000u, 0x7fffffffu
    };
    for (uint32_t x = 0; x < 10000u; ++x) {
        if (!check(x)) {
            return 1;
        }
    }
    for (unsigned i = 0; i < sizeof(boundaries) / sizeof(boundaries[0]); ++i) {
        if (!check(boundaries[i])) {
            return 2;
        }
    }
    puts("equivalent-output-domain:pass");
    return 0;
}
