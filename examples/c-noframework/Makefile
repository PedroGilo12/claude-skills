CFLAGS ?= -Wall -Wextra -O2

libdebounce.a: src/debounce.o
	$(AR) rcs $@ $^

clean:
	rm -f src/*.o libdebounce.a
