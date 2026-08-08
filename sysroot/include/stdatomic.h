#ifndef NORX_STDATOMIC_H
#define NORX_STDATOMIC_H

#include <stdint.h>

typedef _Atomic(uint_least64_t) atomic_uint_least64_t;

typedef enum {
    memory_order_relaxed = __ATOMIC_RELAXED,
    memory_order_consume = __ATOMIC_CONSUME,
    memory_order_acquire = __ATOMIC_ACQUIRE,
    memory_order_release = __ATOMIC_RELEASE,
    memory_order_acq_rel = __ATOMIC_ACQ_REL,
    memory_order_seq_cst = __ATOMIC_SEQ_CST,
} memory_order;

#define atomic_init(object, value) __c11_atomic_init(object, value)
#define atomic_load(object) __c11_atomic_load(object, memory_order_seq_cst)
#define atomic_load_explicit(object, order) __c11_atomic_load(object, order)
#define atomic_store(object, value) __c11_atomic_store(object, value, memory_order_seq_cst)
#define atomic_store_explicit(object, value, order) __c11_atomic_store(object, value, order)
#define atomic_fetch_add(object, value) __c11_atomic_fetch_add(object, value, memory_order_seq_cst)
#define atomic_fetch_add_explicit(object, value, order) __c11_atomic_fetch_add(object, value, order)

#endif
