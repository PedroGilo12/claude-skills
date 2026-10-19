#include <stddef.h>

#include "debounce.h"

int debounce_init(debounce_t *d, uint8_t threshold, bool initial)
{
	if (d == NULL || threshold == 0 || threshold > DEBOUNCE_MAX_THRESHOLD) {
		return -1;
	}
	d->threshold = threshold;
	d->count = 0;
	d->stable = initial;
	return 0;
}

bool debounce_update(debounce_t *d, bool raw)
{
	if (d == NULL) {
		return false;
	}
	if (raw == d->stable) {
		d->count = 0;
		return false;
	}
	if (++d->count < d->threshold) {
		return false;
	}
	d->stable = raw;
	d->count = 0;
	return true;
}

bool debounce_state(const debounce_t *d)
{
	return d != NULL && d->stable;
}
