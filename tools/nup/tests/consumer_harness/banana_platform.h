#pragma once
#include <openssl/sha.h>
static inline void plat_sha256(const void* data, size_t size, unsigned char out[32]){SHA256(data,size,out);}
