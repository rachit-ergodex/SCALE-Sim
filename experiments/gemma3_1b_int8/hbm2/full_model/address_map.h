#pragma once
#include <cstdint>
// Bijective layout for the fixed 16-channel / 16-GiB HBM2 profile. Preserve
// byte and physical-channel bits [0:8]; interleave pseudochannel and bankgroup
// before the five column bits. Row bits [20:33] and bank bits [18:19] stay put.
inline std::uint64_t hbm_physical_address(std::uint64_t address, bool interleave) {
    if (!interleave) return address;
    constexpr unsigned destinations[9]={14,16,17,9,10,11,12,13,15};
    std::uint64_t result=address & ~(std::uint64_t(511)<<9);
    for (unsigned i=0;i<9;++i) result |= ((address>>(9+i))&1)<<destinations[i];
    return result;
}
