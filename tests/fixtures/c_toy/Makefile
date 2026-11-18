CC ?= clang
CFLAGS ?= -std=c11 -Wall -Wextra -O0 -g
toy: main.c util.c util.h
	$(CC) $(CFLAGS) main.c util.c -o toy
clean:
	rm -f toy
