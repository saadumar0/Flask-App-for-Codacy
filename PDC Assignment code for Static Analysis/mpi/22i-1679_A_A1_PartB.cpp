/*
 * Assignment #: 1
 * Course: Parallel and Distributive Computing (CS 3006)
 * Component: Part B - MPI Parallel Alignment
 * Student Name: Saad Umar
 * Student ID: 22i-1679
 *
 * Usage Example (Scenario 1):
 *   mpirun -np 4 mpi_align --mode p2p --seqA ACGTAG --seqB ACTG
 *   mpirun -np 4 mpi_align --mode p2p --tfa data.tfa --a-index 0 --b-index 1
 *   g++ -O3 -std=c++17 -I msmpi_local\include mpi_align.cpp -L msmpi_local\lib -lmsmpi -o mpi_align.exe   
 *   mpiexec -np 4 .\mpi_align.exe --mode p2p --tfa data_combined.tfa --a-index 0 --b-index 1 --validate     
 *   mpiexec -np 4 .\mpi_align.exe --mode scatter --tfa data_combined.tfa --a-index 0 --b-index 1 --validate  
 *   python .\bench_part_c.py --tfa data_combined.tfa --pair 0:1 --multi-pairs 32 --procs 2 4 8 --repeats 7 --out bench_part_c_repeats7
 */

#include <mpi.h>
#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <stdexcept>
#include <algorithm>
#include <iomanip>
#include <numeric>
#include <sstream>
#include <fstream>

#include "sequence_io.hpp"

struct Args {
    std::string seqA; std::string seqB; std::string tfa_path; int a_index = -1; int b_index = -1; std::string mode = "p2p"; bool plain = false; bool validate = false;
    // Scenario 3 (multi)
    std::vector<std::pair<int,int>> pairs; std::string pair_file; };


static void print_help(int rank) {
    if(rank!=0) return;
    std::cout << "Usage: mpi_align [options]\n"
              << "Options:\n"
              << "  --seqA STR            Direct sequence A\n"
              << "  --seqB STR            Direct sequence B\n"
              << "  --tfa FILE            Multi-sequence .tfa/.fasta file\n"
              << "  --a-index N           Index of sequence A (with --tfa)\n"
              << "  --b-index N           Index of sequence B (with --tfa)\n"
              << "  --mode p2p|scatter|multi  Parallel strategy (default p2p)\n"
              << "  --pairs i:j [more i:j]  (multi mode) add sequence index pair\n"
              << "  --pair-file FILE       (multi mode) file with lines: i j\n"
              << "  --plain               Only print numeric result(s) (rank 0)\n"
              << "  --validate            Extra small-size validation vs sequential\n"
              << "  --help                Show this help\n";
}

// Parse a single pair spec token like "3:7" or "3,7"
static std::pair<int,int> parse_pair_token(const std::string& tok){
    size_t pos = tok.find_first_of(":,");
    if(pos==std::string::npos) throw std::runtime_error("Bad pair token (expected i:j): "+tok);
    int a = std::stoi(tok.substr(0,pos));
    int b = std::stoi(tok.substr(pos+1));
    return {a,b};

}


// Parse all CLI arguments
static Args parse_args(int argc, char** argv) {
    Args args;
    for(int i=1;i<argc;++i){
        std::string k = argv[i];
        auto need = [&](const char* name){ if(i+1>=argc) throw std::runtime_error(std::string("Missing value for ")+name); return std::string(argv[++i]); };
        if(k=="--seqA") args.seqA = need("--seqA");
        else if(k=="--seqB") args.seqB = need("--seqB");
        else if(k=="--tfa") args.tfa_path = need("--tfa");
        else if(k=="--a-index") args.a_index = std::stoi(need("--a-index"));
        else if(k=="--b-index") args.b_index = std::stoi(need("--b-index"));
        else if(k=="--mode") args.mode = need("--mode");
        else if(k=="--pairs") { args.pairs.push_back(parse_pair_token(need("--pairs"))); }
        else if(k=="--pair-file") args.pair_file = need("--pair-file");
        else if(k=="--plain") args.plain = true;
        else if(k=="--validate") args.validate = true;
        else if(k=="--help") { /* handled later */ }
        else throw std::runtime_error("Unknown argument: "+k);
    }
    if(!args.pair_file.empty()) {
        std::ifstream fin(args.pair_file);
        if(!fin) throw std::runtime_error("Cannot open pair file: "+args.pair_file);
        int a,b; while(fin>>a>>b){ args.pairs.emplace_back(a,b);}    }
    return args;
}

// Sequential edit distance reference (rolling rows)
static int seq_edit_distance_ref(const std::string& A, const std::string& B){
    const int n=A.size(), m=B.size();
    std::vector<int> prev(m+1), cur(m+1);
    for(int j=0;j<=m;++j) prev[j]=j;
    for(int i=1;i<=n;++i){
        cur[0]=i;
        for(int j=1;j<=m;++j){
            int cost = (A[i-1]==B[j-1])?0:1;
            cur[j] = std::min({ prev[j] + 1, cur[j-1] + 1, prev[j-1] + cost });
        }
        std::swap(prev,cur);
    }
    return prev[m];
}

// Scenario 1: simple row-block pipeline via point-to-point handoff of boundary row.
static int scenario_p2p_edit_distance(const std::string& A, const std::string& B, int rank, int size){
    int n = (int)A.size(); int m = (int)B.size();
    // Partition rows contiguously
    int base = n / size; int rem = n % size;
    int start = rank * base + std::min(rank, rem);
    int rows = base + (rank < rem ? 1 : 0);
    int end = start + rows; // exclusive
    std::vector<int> prev(m+1), cur(m+1);
    if(rank==0){ for(int j=0;j<=m;++j) prev[j]=j; }
    else { // receive prev row from predecessor
        MPI_Recv(prev.data(), m+1, MPI_INT, rank-1, 100, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    }
    for(int local_i=0; local_i<rows; ++local_i){
        int global_i = start + local_i + 1; // DP row index (1-based)
        cur[0] = global_i;
        for(int j=1;j<=m;++j){
            int cost = (A[global_i-1]==B[j-1])?0:1;
            cur[j] = std::min({ prev[j]+1, cur[j-1]+1, prev[j-1]+cost });
        }
        std::swap(prev,cur);
    }
    if(rank < size-1){
        MPI_Send(prev.data(), m+1, MPI_INT, rank+1, 100, MPI_COMM_WORLD);
    }
    int result = -1;
    if(rank==size-1) result = prev[m];
    MPI_Bcast(&result,1,MPI_INT,size-1,MPI_COMM_WORLD);
    return result;
}

// Scenario 2: scatter/gather style using anti-diagonals (simplified collective allgather of row after each step).
static int scenario_scatter_edit_distance(const std::string& A, const std::string& B, int rank, int size){
    const int n = (int)A.size();
    const int m = (int)B.size();
    // Diagonal indexing: d = i + j, 0..n+m. Length of diagonal d:
    // i ranges max(0, d-m) .. min(n, d); number of points len = min(n,d) - max(0,d-m) + 1
    // We store previous two diagonals to compute current.
    std::vector<int> diag_prev2; // d-2
    std::vector<int> diag_prev1; // d-1
    std::vector<int> diag_curr;  // d
    int final_distance = -1;

    for(int d=0; d<=n+m; ++d){
        int i_lo = std::max(0, d - m);
        int i_hi = std::min(n, d);
        int len  = i_hi - i_lo + 1; // cells on diagonal d
        if(len <= 0){
            // should not happen
            continue;
        }
        // Partition this diagonal among ranks: simple block distribution
        int base = len / size; int rem = len % size;
        // Root prepares (start,count) pairs and scatters them (2 ints per rank)
        int pair_buf[2] = {0,0};
        if(rank==0){
            std::vector<int> meta(2*size);
            int offset=0;
            for(int r=0;r<size;++r){
                int cnt = base + (r < rem ? 1 : 0);
                meta[2*r] = offset;
                meta[2*r+1] = cnt;
                offset += cnt;
            }
            MPI_Scatter(meta.data(), 2, MPI_INT, pair_buf, 2, MPI_INT, 0, MPI_COMM_WORLD);
        } else {
            MPI_Scatter(nullptr, 2, MPI_INT, pair_buf, 2, MPI_INT, 0, MPI_COMM_WORLD);
        }
        int my_start = pair_buf[0];
        int my_count = pair_buf[1];
        if(my_count < 0) my_count = 0; // safety

        // Compute local segment
        // Allocate space for current diagonal if root; other ranks will allocate local vector and then gather.
        std::vector<int> local_vals(my_count);

        auto get_from_prev = [&](const std::vector<int>& diag, int diag_d, int i)->int{
            // diag contains values for diagonal diag_d.
            // For diagonal diag_d, i_lo' = max(0, diag_d - m)
            int i_lo_p = std::max(0, diag_d - m);
            int idx = i - i_lo_p; // position within that diagonal
            return diag[idx];
        };

        for(int k=0; k<my_count; ++k){
            int pos_on_diag = my_start + k; // 0-based within this diagonal
            int i = i_lo + pos_on_diag;
            int j = d - i;
            int val = 0;
            if(d==0){ // (0,0)
                val = 0;
            } else if(i==0){ // top edge
                val = j; // insertions
            } else if(j==0){ // left edge
                val = i; // deletions
            } else {
                // dependencies: (i-1,j) on diag d-1, (i,j-1) on diag d-1, (i-1,j-1) on diag d-2
                int up    = get_from_prev(diag_prev1, d-1, i-1);     // (i-1,j)
                int left  = get_from_prev(diag_prev1, d-1, i);       // (i,j-1)
                int diagv = get_from_prev(diag_prev2, d-2, i-1);     // (i-1,j-1)
                int cost = (A[i-1]==B[j-1]) ? 0 : 1;
                val = std::min({ up + 1, left + 1, diagv + cost });
            }
            local_vals[k] = val;
            if(i==n && j==m) final_distance = val;
        }

        // Gather current diagonal to root then broadcast (explicit Scatter/Gather pattern per assignment spec)
        std::vector<int> recv_counts, displs; std::vector<int> full_diag;
        if(rank==0){
            recv_counts.resize(size);
            displs.resize(size);
            int offset=0;
            for(int r=0;r<size;++r){
                int cnt = base + (r < rem ? 1 : 0);
                recv_counts[r]=cnt; displs[r]=offset; offset+=cnt;
            }
            full_diag.resize(len);
        }
        MPI_Gatherv(local_vals.data(), my_count, MPI_INT,
                    rank==0? full_diag.data():nullptr,
                    rank==0? recv_counts.data():nullptr,
                    rank==0? displs.data():nullptr,
                    MPI_INT, 0, MPI_COMM_WORLD);
        if(rank!=0) full_diag.resize(len);
        MPI_Bcast(full_diag.data(), len, MPI_INT, 0, MPI_COMM_WORLD);

        // Roll diagonals forward
        diag_prev2 = std::move(diag_prev1);
        diag_prev1 = std::move(full_diag);
    }

    // Propagate final distance (only set by rank owning cell (n,m))
    int fd = final_distance;
    MPI_Allreduce(&fd, &final_distance, 1, MPI_INT, MPI_MAX, MPI_COMM_WORLD);
    return final_distance;
}

// Scenario 3: multi independent pairs.
static void scenario_multi(const std::vector<std::string>& seqs, const std::vector<std::pair<int,int>>& pairs,
                           int rank, int size, bool plain, bool validate){
    int P = (int)pairs.size();
    // Each rank computes a disjoint subset (round-robin)
    std::vector<int> local(P,-1);
    for(int i=0;i<P;++i){ if(i % size == rank){ auto [a,b]=pairs[i];
            if(a<0||b<0||a>=(int)seqs.size()||b>=(int)seqs.size()) local[i]=-2; else local[i]=seq_edit_distance_ref(seqs[a], seqs[b]); } }
    // Gather all partial result arrays at root
    std::vector<int> gather_buf; if(rank==0) gather_buf.resize(P*size);
    MPI_Gather(local.data(), P, MPI_INT, rank==0? gather_buf.data():nullptr, P, MPI_INT, 0, MPI_COMM_WORLD);
    if(rank==0){
        std::vector<int> final(P,-1);
        for(int i=0;i<P;++i){
            int best=-1; for(int r=0;r<size;++r){ int v = gather_buf[r*P + i]; if(v>best) best=v; }
            final[i]=best;
        }
        if(validate && P<=32){
            for(int i=0;i<P;++i){ auto [a,b]=pairs[i]; if(a>=0&&b>=0&&a<(int)seqs.size()&&b<(int)seqs.size()){
                int ref = seq_edit_distance_ref(seqs[a], seqs[b]); if(ref!=final[i]) std::cerr<<"[validate] mismatch pair "<<a<<":"<<b<<" got="<<final[i]<<" ref="<<ref<<"\n"; }} }
        if(plain){ for(int i=0;i<P;++i) std::cout<<final[i]<<(i+1<P?"\n":"\n"); }
        else { for(int i=0;i<P;++i){ auto [a,b]=pairs[i]; std::cout<<"EditDistance(MULTI)["<<a<<":"<<b<<"]="<<(final[i]==-2? -1: final[i])<<"\n"; } }
    }
}

int main(int argc, char** argv){
    MPI_Init(&argc,&argv);
    int rank=0,size=1; MPI_Comm_rank(MPI_COMM_WORLD,&rank); MPI_Comm_size(MPI_COMM_WORLD,&size);
    Args args;
    try { args = parse_args(argc, argv); }
    catch(const std::exception& ex){ if(rank==0){ std::cerr<<"Error: "<<ex.what()<<"\n"; print_help(rank);} MPI_Finalize(); return 1; }
    for(int i=1;i<argc;++i){ if(std::string(argv[i])=="--help"){ print_help(rank); MPI_Finalize(); return 0; } }

    std::vector<std::string> all_seqs; std::string A,B;
    bool need_all = (args.mode=="multi");
    try {
        if(!args.tfa_path.empty()){
            all_seqs = load_fasta_sequences(args.tfa_path);
            if(!need_all){
                if(args.a_index<0 || args.b_index<0) throw std::runtime_error("Provide --a-index and --b-index with --tfa");
                if(args.a_index >= (int)all_seqs.size() || args.b_index >= (int)all_seqs.size()) throw std::runtime_error("Index out of range");
                A = all_seqs[args.a_index]; B = all_seqs[args.b_index];
            } else {
                if(args.pairs.empty()) throw std::runtime_error("Provide --pairs or --pair-file for multi mode");
            }
        } else {
            if(need_all) throw std::runtime_error("--mode multi requires --tfa");
            if(args.seqA.empty()||args.seqB.empty()) throw std::runtime_error("Provide --seqA/--seqB or --tfa with indices");
            A=args.seqA; B=args.seqB;
        }
    } catch(const std::exception& ex){ if(rank==0){ std::cerr<<"Error: "<<ex.what()<<"\n"; print_help(rank);} MPI_Finalize(); return 2; }

    // Broadcast sequences as needed
    if(args.mode=="p2p" || args.mode=="scatter"){
        int m=A.size(), n=B.size();
        MPI_Bcast(&m,1,MPI_INT,0,MPI_COMM_WORLD); MPI_Bcast(&n,1,MPI_INT,0,MPI_COMM_WORLD);
        if(rank!=0){ A.resize(m); B.resize(n);} MPI_Bcast(A.data(),m,MPI_CHAR,0,MPI_COMM_WORLD); MPI_Bcast(B.data(),n,MPI_CHAR,0,MPI_COMM_WORLD);
    } else if(args.mode=="multi"){
        int count = (int)all_seqs.size(); MPI_Bcast(&count,1,MPI_INT,0,MPI_COMM_WORLD); if(rank!=0) all_seqs.resize(count);
        for(int i=0;i<count;++i){ int len=(int)all_seqs[i].size(); MPI_Bcast(&len,1,MPI_INT,0,MPI_COMM_WORLD); if(rank!=0) all_seqs[i].resize(len); MPI_Bcast(all_seqs[i].data(), len, MPI_CHAR, 0, MPI_COMM_WORLD);}        int P=(int)args.pairs.size(); MPI_Bcast(&P,1,MPI_INT,0,MPI_COMM_WORLD); if(rank!=0) args.pairs.resize(P);
        for(int i=0;i<P;++i){ int a=args.pairs[i].first, b=args.pairs[i].second; MPI_Bcast(&a,1,MPI_INT,0,MPI_COMM_WORLD); MPI_Bcast(&b,1,MPI_INT,0,MPI_COMM_WORLD); if(rank!=0) args.pairs[i]={a,b}; }
    }

    MPI_Barrier(MPI_COMM_WORLD);
    auto t0 = std::chrono::high_resolution_clock::now();
    int distance=-1;
    if(args.mode=="p2p") distance = scenario_p2p_edit_distance(A,B,rank,size);
    else if(args.mode=="scatter") distance = scenario_scatter_edit_distance(A,B,rank,size);
    else if(args.mode=="multi") scenario_multi(all_seqs, args.pairs, rank, size, args.plain, args.validate);
    else { if(rank==0) std::cerr<<"Mode not implemented: "<<args.mode<<"\n"; MPI_Finalize(); return 3; }
    MPI_Barrier(MPI_COMM_WORLD);
    auto t1 = std::chrono::high_resolution_clock::now(); double ms = std::chrono::duration<double,std::milli>(t1-t0).count();

    if(rank==0 && args.mode!="multi"){ if(args.plain) std::cout<<distance<<"\n"; else std::cout<<"EditDistance("<<(args.mode=="p2p"?"P2P":args.mode=="scatter"?"SCATTER":"?")<<")="<<distance<<" TimeMs="<<std::fixed<<std::setprecision(3)<<ms<<"\n"; }
    else if(rank==0 && args.mode=="multi" && !args.plain){ std::cout<<"TimeMs="<<std::fixed<<std::setprecision(3)<<ms<<" (MULTI)\n"; }
    MPI_Finalize();
    return 0;
}

// --- File restored: multi-mode and scenarios reintroduced after accidental truncation ---
