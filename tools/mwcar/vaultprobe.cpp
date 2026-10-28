// vaultprobe: list the attribute collections of one class in GLOBAL\attributes.bin,
// or dump every field record of one collection.
//   vaultprobe <attributes.bin> <class>                 e.g. pvehicle
//   vaultprobe <attributes.bin> <class> <collection>    e.g. pvehicle taxi
#include <cstdio>
#include <fstream>
#include <iterator>
#include <set>
#include <string>
#include <vector>

#include <mwsdk/hashing.hpp>
#include <mwsdk/vault.hpp>

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: vaultprobe <attributes.bin> <class> [collection]\n");
        return 2;
    }
    std::ifstream f(argv[1], std::ios::binary);
    std::vector<std::uint8_t> buf((std::istreambuf_iterator<char>(f)), {});
    auto recs = mwsdk::vault::read_decoded(buf);
    if (!recs) {
        std::fprintf(stderr, "vault decode failed\n");
        return 1;
    }
    const std::uint32_t cls = mwsdk::hash::attrib(argv[2]);
    if (argc == 3) {
        std::set<std::uint32_t> keys;
        for (const auto& r : *recs)
            if (r.class_hash == cls) keys.insert(r.collection_key);
        for (std::uint32_t k : keys) std::printf("%08x\n", k);
        std::printf("%zu collections\n", keys.size());
        return 0;
    }
    // A collection is given by name, or by its key as 0x-prefixed hex (as the listing prints them).
    const std::string col_arg = argv[3];
    const std::uint32_t col = col_arg.rfind("0x", 0) == 0
                                  ? static_cast<std::uint32_t>(std::stoul(col_arg.substr(2), nullptr, 16))
                                  : mwsdk::hash::attrib(argv[3]);
    std::printf("class %s=%08x collection %s=%08x\n", argv[2], cls, argv[3], col);
    int n = 0;
    for (const auto& r : *recs) {
        if (r.class_hash != cls || r.collection_key != col) continue;
        auto name = mwsdk::vault::field_name(r.field_hash);
        std::printf("  field %08x %-32.*s type %08x parent %08x\n", r.field_hash, (int)name.size(), name.data(),
                    r.type_id, r.parent_key);
        ++n;
    }
    std::printf("%d records\n", n);
    return 0;
}
