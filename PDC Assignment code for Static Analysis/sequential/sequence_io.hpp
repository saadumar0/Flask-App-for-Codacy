#pragma once
#include <string>
#include <vector>
#include <fstream>
#include <stdexcept>
#include <cctype>

// Load FASTA / TFA style file: lines beginning with '>' are headers; sequences may span multiple lines.
// Returns vector of cleaned sequences (uppercase, letters only). Headers are discarded.
inline std::vector<std::string> load_fasta_sequences(const std::string& path, std::size_t max_sequences = static_cast<std::size_t>(-1)) {
    std::ifstream in(path);
    if(!in) throw std::runtime_error("Cannot open file: " + path);
    std::vector<std::string> seqs;
    std::string line;
    std::string current;
    auto flush = [&]() {
        if(!current.empty()) {
            seqs.push_back(current);
            current.clear();
        }
    };
    while(std::getline(in, line)) {
        if(line.empty()) continue;
        if(line[0] == '>') { // header
            if(max_sequences != static_cast<std::size_t>(-1) && seqs.size() >= max_sequences) break;
            flush();
            continue; // ignore header content
        }
        for(char c : line) {
            if(std::isalpha(static_cast<unsigned char>(c))) {
                current.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(c))));
            }
        }
    }
    flush();
    if(max_sequences != static_cast<std::size_t>(-1) && seqs.size() > max_sequences) {
        seqs.resize(max_sequences);
    }
    return seqs;
}

// Generate pair indices for scenario 3: produce (i,j) with j = (i+1) for adjacent pairs.
// If odd count, last one is ignored unless allow_wrap.
inline std::vector<std::pair<std::size_t,std::size_t>> adjacent_pairs(std::size_t n, bool allow_wrap = false) {
    std::vector<std::pair<std::size_t,std::size_t>> pairs;
    if(n < 2) return pairs;
    for(std::size_t i=0; i+1<n; i+=2) {
        pairs.emplace_back(i, i+1);
    }
    if(allow_wrap && (n % 2 == 1)) {
        pairs.emplace_back(n-1, 0);
    }
    return pairs;
}

// Simple edit distance (Levenshtein / unit costs) for validation; rolling two-row buffer.
inline int edit_distance_unit(const std::string& a, const std::string& b) {
    const std::size_t m = a.size();
    const std::size_t n = b.size();
    if(m == 0) return static_cast<int>(n);
    if(n == 0) return static_cast<int>(m);
    std::vector<int> prev(n+1), cur(n+1);
    for(std::size_t j=0; j<=n; ++j) prev[j] = static_cast<int>(j);
    for(std::size_t i=1; i<=m; ++i) {
        cur[0] = static_cast<int>(i);
        for(std::size_t j=1; j<=n; ++j) {
            int cost = (a[i-1] == b[j-1]) ? 0 : 1;
            int del = prev[j] + 1;
            int ins = cur[j-1] + 1;
            int sub = prev[j-1] + cost;
            int best = del < ins ? del : ins;
            if(sub < best) best = sub;
            cur[j] = best;
        }
        std::swap(prev, cur);
    }
    return prev[n];
}

// Partition sequences across ranks for scenario 3 (round-robin assignment): returns vector of indices owned by rank.
inline std::vector<std::size_t> distribute_indices_rr(std::size_t total, int world_rank, int world_size) {
    std::vector<std::size_t> idx;
    for(std::size_t i=0; i<total; ++i) {
        if(static_cast<int>(i % world_size) == world_rank) idx.push_back(i);
    }
    return idx;
}
