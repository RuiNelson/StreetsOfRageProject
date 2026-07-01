#ifndef SOR_MAME_Z80_SHARED_H
#define SOR_MAME_Z80_SHARED_H

#include <stdio.h>
#include <string.h>

#define LSB_FIRST 1
#define INLINE static inline

#define logerror(...) fprintf(stderr, __VA_ARGS__)
#define cpu_getactivecpu() 0

#endif
