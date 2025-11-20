/*
 * Assignment #: 1
 * Course: Parallel and Distributive Computing (CS 3006)
 * Component: Part A - Sequential Baseline (Edit Distance / Needleman-Wunsch)
 * Student Name: YOUR_NAME_HERE
 * Student ID: YOUR_ROLL_NUMBER_HERE
 * Description: Provides a sequential implementation of unit-cost Edit Distance
 *              (Levenshtein) and an optional Needleman–Wunsch global alignment
 *              variant with configurable scoring. Serves as the correctness
 *              baseline for subsequent MPI parallel implementations.
 * Notes: Output kept concise to satisfy assignment formatting. Use --plain
 *        to suppress timing if only the numeric result is desired for marking.
 */

#include <iostream>
#include <vector>
#include <string>
#include <optional>
#include <chrono>
#include <algorithm>
#include <stdexcept>
#include <cstring>
#include <iomanip>

#include "sequence_io.hpp" // reuse utilities

struct Args {
    std::string seqA;
    std::string seqB;
    std::string tfa_path;
    int a_index = -1;
    int b_index = -1;
    std::string mode = "edit"; // edit | nw
    bool show_alignment = false;
    bool self_test = false;
    bool plain = false; // only output distance/score number (no label or timing)
    // NW scoring
    int match = 0; // For pure edit distance semantics, match = 0
    int mismatch = 1; // substitution cost
    int gap = 1; // insertion/deletion cost
};

static void print_help() {
    std::cout << "Usage: seq_align [options]\n"
              << "Options:\n"
              << "  --seqA STR            Direct sequence A\n"
              << "  --seqB STR            Direct sequence B\n"
              << "  --tfa FILE            Multi-sequence .tfa/.fasta file\n"
              << "  --a-index N           Index of sequence A in file (0-based)\n"
              << "  --b-index N           Index of sequence B in file (0-based)\n"
              << "  --mode edit|nw        Algorithm: unit edit distance or Needleman-Wunsch (default edit)\n"
              << "  --match V             NW match score (default 0)\n"
              << "  --mismatch V          NW mismatch penalty (default 1)\n"
              << "  --gap V               Gap penalty (default 1)\n"
              << "  --show-alignment      Reconstruct and print alignment (NW mode only)\n"
              << "  --self-test           Run internal tests and exit\n"
              << "  --help                Show this help\n";
}

static Args parse_args(int argc, char** argv) {
    Args args;
    for(int i=1; i<argc; ++i) {
        std::string key = argv[i];
        auto need = [&](const char* name)->std::string { if(i+1>=argc) throw std::runtime_error(std::string("Missing value for ")+name); return argv[++i]; };
        if(key == "--seqA") args.seqA = need("--seqA");
        else if(key == "--seqB") args.seqB = need("--seqB");
        else if(key == "--tfa") args.tfa_path = need("--tfa");
        else if(key == "--a-index") args.a_index = std::stoi(need("--a-index"));
        else if(key == "--b-index") args.b_index = std::stoi(need("--b-index"));
        else if(key == "--mode") args.mode = need("--mode");
        else if(key == "--match") args.match = std::stoi(need("--match"));
        else if(key == "--mismatch") args.mismatch = std::stoi(need("--mismatch"));
        else if(key == "--gap") args.gap = std::stoi(need("--gap"));
        else if(key == "--show-alignment") args.show_alignment = true;
        else if(key == "--self-test") args.self_test = true;
    else if(key == "--plain") args.plain = true;
        else if(key == "--help") { print_help(); std::exit(0);} 
        else {
            throw std::runtime_error("Unknown argument: " + key);
        }
    }
    return args;
}

// Standard unit-cost edit distance (already available as edit_distance_unit, re-exposed for clarity)
int edit_distance(const std::string& A, const std::string& B) {
    return edit_distance_unit(A, B);
}

struct NWResult { int score; std::string alignA; std::string alignB; };

NWResult needleman_wunsch(const std::string& A, const std::string& B, int match, int mismatch, int gap, bool reconstruct) {
    const int m = static_cast<int>(A.size());
    const int n = static_cast<int>(B.size());
    std::vector<int> prev(n+1), cur(n+1);
    for(int j=0; j<=n; ++j) prev[j] = j * (-gap); // if using penalties as positive costs, adapt; here we treat gap as penalty -> subtract
    // We'll treat gap/mismatch as positive penalties; convert scoring to negative cost accumulation? Simpler: standard NW scoring style:
    // Score scheme: match adds +match (could be positive), mismatch adds -mismatch, gap adds -gap.
    // Initialize first column similarly.
    // For clarity, re-implement with full matrix if reconstruct requested.
    std::vector<int> full; full.reserve((m+1)*(n+1));
    auto idx = [&](int i,int j){return i*(n+1)+j;};
    full.resize((m+1)*(n+1));
    full[idx(0,0)] = 0;
    for(int j=1;j<=n;++j) full[idx(0,j)] = full[idx(0,j-1)] - gap;
    for(int i=1;i<=m;++i) full[idx(i,0)] = full[idx(i-1,0)] - gap;
    for(int i=1;i<=m;++i){
        for(int j=1;j<=n;++j){
            int score_diag = full[idx(i-1,j-1)] + (A[i-1]==B[j-1] ? match : -mismatch);
            int score_up   = full[idx(i-1,j)] - gap;
            int score_left = full[idx(i,j-1)] - gap;
            int best = std::max({score_diag, score_up, score_left});
            full[idx(i,j)] = best;
        }
    }
    NWResult res; res.score = full[idx(m,n)];
    if(reconstruct){
        std::string a_aln, b_aln;
        int i=m, j=n;
        while(i>0 || j>0){
            int curScore = full[idx(i,j)];
            bool moved=false;
            if(i>0 && j>0){
                int diagScore = full[idx(i-1,j-1)] + (A[i-1]==B[j-1] ? match : -mismatch);
                if(diagScore == curScore){ a_aln.push_back(A[i-1]); b_aln.push_back(B[j-1]); --i; --j; moved=true; }
            }
            if(!moved && i>0){
                int upScore = full[idx(i-1,j)] - gap;
                if(upScore == curScore){ a_aln.push_back(A[i-1]); b_aln.push_back('-'); --i; moved=true; }
            }
            if(!moved && j>0){
                int leftScore = full[idx(i,j-1)] - gap;
                if(leftScore == curScore){ a_aln.push_back('-'); b_aln.push_back(B[j-1]); --j; moved=true; }
            }
            if(!moved){ // fallback (should not happen)
                if(i>0){ a_aln.push_back(A[i-1]); b_aln.push_back('-'); --i; }
                else { a_aln.push_back('-'); b_aln.push_back(B[j-1]); --j; }
            }
        }
        std::reverse(a_aln.begin(), a_aln.end());
        std::reverse(b_aln.begin(), b_aln.end());
        res.alignA = std::move(a_aln);
        res.alignB = std::move(b_aln);
    }
    return res;
}

// Basic internal self-test
static bool self_test() {
    struct Case { std::string a,b; int dist; };
    std::vector<Case> cases = {
        {"", "", 0},
        {"A", "", 1},
        {"", "ACT", 3},
        {"ACG", "ACG", 0},
        {"ACG", "AGG", 1},
        {"kitten", "sitting", 3}
    };
    bool ok=true;
    for(auto& c: cases){
        int d = edit_distance(c.a, c.b);
        if(d != c.dist){
            std::cerr << "Self-test failed: ("<<c.a<<","<<c.b<<") expected "<<c.dist<<" got "<<d<<"\n";
            ok=false;
        }
    }
    return ok;
}

int main(int argc, char** argv) {
    try {
        auto args = parse_args(argc, argv);
        if(args.self_test){
            bool ok = self_test();
            std::cout << (ok ? "SELF-TEST PASS" : "SELF-TEST FAIL") << "\n";
            return ok?0:1;
        }
        std::string A,B;
        if(!args.tfa_path.empty()){
            if(args.a_index < 0 || args.b_index < 0) throw std::runtime_error("Provide --a-index and --b-index with --tfa");
            auto seqs = load_fasta_sequences(args.tfa_path);
            if(args.a_index >= (int)seqs.size() || args.b_index >= (int)seqs.size()) throw std::runtime_error("Index out of range in tfa file");
            A = seqs[args.a_index];
            B = seqs[args.b_index];
        } else {
            if(args.seqA.empty() || args.seqB.empty()) throw std::runtime_error("Provide --seqA/--seqB or --tfa with indices");
            A = args.seqA; B = args.seqB;
        }
        auto start = std::chrono::high_resolution_clock::now();
        if(args.mode == "edit") {
            int dist = edit_distance(A,B);
            auto end = std::chrono::high_resolution_clock::now();
            double ms = std::chrono::duration<double,std::milli>(end-start).count();
            if(args.plain) {
                std::cout << dist << "\n";
            } else {
                std::cout << "EditDistance=" << dist << " TimeMs=" << std::fixed << std::setprecision(3) << ms << "\n";
            }
        } else if(args.mode == "nw") {
            auto res = needleman_wunsch(A,B,args.match,args.mismatch,args.gap,args.show_alignment);
            auto end = std::chrono::high_resolution_clock::now();
            double ms = std::chrono::duration<double,std::milli>(end-start).count();
            if(args.plain) {
                std::cout << res.score << "\n";
            } else {
                std::cout << "NWScore=" << res.score << " TimeMs=" << std::fixed << std::setprecision(3) << ms << "\n";
            }
            if(args.show_alignment){
                std::cout << res.alignA << "\n" << res.alignB << "\n";
            }
        } else {
            throw std::runtime_error("Unknown mode: " + args.mode);
        }
    } catch(const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        print_help();
        return 1;
    }
    return 0;
}
