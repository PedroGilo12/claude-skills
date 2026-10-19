#ifndef DEBOUNCE_H
#define DEBOUNCE_H

#include <stdbool.h>
#include <stdint.h>

/* Debounce de entrada digital: o estado estável só muda depois de `threshold`
 * amostras consecutivas iguais e diferentes do estado atual. */
typedef struct {
	uint8_t threshold;  /* 1..DEBOUNCE_MAX_THRESHOLD */
	uint8_t count;
	bool stable;
} debounce_t;

#define DEBOUNCE_MAX_THRESHOLD 32

/* Retorna 0, ou -1 se d == NULL ou threshold fora de 1..DEBOUNCE_MAX_THRESHOLD. */
int debounce_init(debounce_t *d, uint8_t threshold, bool initial);

/* Alimenta uma amostra crua. Retorna true se o estado estável mudou nesta chamada. */
bool debounce_update(debounce_t *d, bool raw);

bool debounce_state(const debounce_t *d);

#endif
