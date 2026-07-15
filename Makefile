CC ?= cc
CFLAGS := -std=c11 -Wall -Wextra -Werror -pedantic -O2

TARGET := build/new_sort
SOURCE := src/new_sort/new_sort.c

.PHONY: all test clean

all: $(TARGET)

$(TARGET): $(SOURCE)
	mkdir -p build
	$(CC) $(CFLAGS) $(SOURCE) -o $(TARGET)

test: $(TARGET)
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v

clean:
	rm -rf build tests/__pycache__ .pytest_cache
