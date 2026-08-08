#ifndef NORX_STDINT_H
#define NORX_STDINT_H

typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef signed short int16_t;
typedef unsigned short uint16_t;
typedef signed int int32_t;
typedef unsigned int uint32_t;
typedef signed long long int64_t;
typedef unsigned long long uint64_t;
typedef signed long intptr_t;
typedef unsigned long uintptr_t;

typedef uint8_t uint_least8_t;
typedef uint16_t uint_least16_t;
typedef uint32_t uint_least32_t;
typedef uint64_t uint_least64_t;

#define INT64_MAX 9223372036854775807LL
#define UINT64_MAX 18446744073709551615ULL
#define UINTPTR_MAX 18446744073709551615UL

#endif
