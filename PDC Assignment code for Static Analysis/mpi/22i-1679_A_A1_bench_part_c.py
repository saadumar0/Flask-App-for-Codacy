#!/usr/bin/env python3
"""
bench_part_c.py - Automated benchmarking harness for Part C

Features:
 - Runs mpi_align across modes (p2p, scatter, multi) for a set of process counts.
 - Collects timing (ms) from stdout and generates CSV & Markdown summaries.
 - Supports repeated runs for averaging & std deviation.
 - Can auto-generate a list of random index pairs for multi mode or accept a pair list.

Requirements:
 - Python 3.8+
 - mpirun (MS-MPI or OpenMPI/MPICH) accessible in PATH.
 - Built mpi_align executable in working directory (or provide --exe path).

Example:
  python bench_part_c.py --tfa data_combined.tfa --pair 0:1 \
      --multi-pairs 16 --procs 2 4 8 --repeats 5 --out bench_results

Outputs:
  bench_results.csv  (raw measurements per run)
  bench_results_summary.md (aggregated table)
  bench_results.json (structured data)

Author: (fill your name / id)
"""
import argparse, subprocess, statistics, json, csv, random, re, shutil, time, os, sys
from pathlib import Path

TIME_RE = re.compile(r"TimeMs=([0-9]+\.[0-9]+)")
DIST_RE = re.compile(r"EditDistance\((P2P|SCATTER|MULTI)\)=([0-9]+)")

MODES_SINGLE = ["p2p", "scatter"]
MODE_MULTI = "multi"

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', default='mpi_align', help='Path to mpi_align executable (omit .exe on Windows; auto-detected)')
    ap.add_argument('--tfa', required=True, help='Multi-sequence .tfa file')
    ap.add_argument('--pair', action='append', help='Single pair index A:B (repeatable) for single-pair modes; first used')
    ap.add_argument('--multi-pairs', type=int, default=16, help='Number of random pairs for multi mode')
    ap.add_argument('--procs', type=int, nargs='+', required=True, help='Process counts, e.g. 2 4 8')
    ap.add_argument('--repeats', type=int, default=3, help='Repeats per mode/process')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out', default='bench_part_c', help='Base output filename (no ext)')
    ap.add_argument('--dry-run', action='store_true', help='Show planned commands only')
    return ap.parse_args()


def pick_pair(pair_args):
    if not pair_args:
        raise SystemExit('Provide at least one --pair A:B for single-pair modes')
    tok = pair_args[0]
    if ':' not in tok:
        raise SystemExit('Bad --pair format (expected A:B)')
    a,b = tok.split(':',1)
    return int(a), int(b)


def gen_random_pairs(nseq, k, rng):
    pairs = set()
    while len(pairs) < k:
        a = rng.randrange(nseq)
        b = rng.randrange(nseq)
        if a==b: continue
        pairs.add(tuple(sorted((a,b))))
    return sorted(pairs)


def run_cmd(cmd):
    t0 = time.time()
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dt = (time.time()-t0)*1000.0
    return cp.returncode, cp.stdout, cp.stderr, dt


def extract_time(stdout):
    # Try explicit TimeMs= first
    m = TIME_RE.search(stdout)
    if m:
        return float(m.group(1))
    # fallback: no time label (should not happen)
    return None


def main():
    args = parse_args()
    rng = random.Random(args.seed)

    exe = Path(args.exe)
    # On Windows allow automatic .exe suffix detection
    if os.name == 'nt' and exe.suffix == '' and not exe.exists():
        candidate = exe.with_suffix('.exe')
        if candidate.exists():
            exe = candidate
    if not exe.exists():
        print(f"ERROR: Executable {exe} not found. Try specifying --exe mpi_align.exe or ensure you are in the build directory.", file=sys.stderr)
        # List nearby executables as a hint
        here_bins = [p.name for p in Path('.').glob('mpi_align*')]
        if here_bins:
            print(f"Found similar files in current dir: {here_bins}", file=sys.stderr)
        sys.exit(1)

    # Determine MPI launcher (prefer mpirun then mpiexec)
    def pick_launcher():
        for cand in ('mpirun','mpiexec'):
            if shutil.which(cand):
                return cand
        print('ERROR: Neither mpirun nor mpiexec found in PATH.', file=sys.stderr)
        sys.exit(1)
    launcher = pick_launcher()

    # Ensure TFA exists; if not, offer quick synthetic generation tip
    if not Path(args.tfa).exists():
        print(f"ERROR: TFA file '{args.tfa}' not found.", file=sys.stderr)
        print("You can create one using a small synthetic example, e.g.:", file=sys.stderr)
        print(">seq0\nACGTACGT\n>seq1\nACGTCGTT\n>seq2\nGGCATGCA", file=sys.stderr)
        print("Save that as data_combined.tfa or specify --tfa path to your dataset.", file=sys.stderr)
        print("If you have multiple .fasta/.tfa files, concatenate them or use concat_tfa.py (if present).", file=sys.stderr)
        sys.exit(1)

    # Quick probe to count sequences (read lines starting with >) - lightweight
    nseq = 0
    with open(args.tfa,'r',errors='ignore') as f:
        for line in f:
            if line.startswith('>'): nseq += 1
    if nseq < 2:
        print('Need at least two sequences in TFA for benchmarking.', file=sys.stderr)
        sys.exit(1)

    a_idx, b_idx = pick_pair(args.pair)
    if a_idx >= nseq or b_idx >= nseq:
        print('Pair indices exceed number of sequences.', file=sys.stderr)
        sys.exit(1)

    multi_pairs = gen_random_pairs(nseq, args.multi_pairs, rng)

    records = []  # rows: dict

    for p in args.procs:
        for mode in MODES_SINGLE + [MODE_MULTI]:
            reps = args.repeats
            for r in range(reps):
                if mode in MODES_SINGLE:
                    cmd = [launcher,'-np',str(p), str(exe), '--mode', mode, '--tfa', args.tfa, '--a-index', str(a_idx), '--b-index', str(b_idx), '--plain']
                else:
                    # build multiple --pairs tokens
                    pair_args = []
                    for A,B in multi_pairs:
                        pair_args += ['--pairs', f'{A}:{B}']
                    cmd = [launcher,'-np',str(p), str(exe), '--mode','multi','--tfa', args.tfa] + pair_args + ['--plain']
                if args.dry_run:
                    print('DRY:', ' '.join(cmd))
                    continue
                rc, out, err, wall = run_cmd(cmd)
                t_ms = extract_time(out)
                # For multi, timing printed separately; TimeMs line comes after results or missing? We captured if present
                records.append({
                    'procs': p,
                    'mode': mode,
                    'repeat': r,
                    'time_ms': t_ms if t_ms is not None else wall,
                    'return_code': rc,
                    'stderr': err.strip()[:500]
                })
                if rc != 0:
                    print(f"Warning: rc={rc} mode={mode} procs={p} repeat={r}")

    if args.dry_run:
        return

    base = args.out
    # Write CSV
    csv_path = base + '.csv'
    with open(csv_path,'w',newline='') as f:
        w = csv.writer(f)
        w.writerow(['procs','mode','repeat','time_ms','return_code'])
        for rec in records:
            w.writerow([rec['procs'], rec['mode'], rec['repeat'], f"{rec['time_ms']:.3f}", rec['return_code']])

    # Aggregate
    summary = {}
    for rec in records:
        key = (rec['procs'], rec['mode'])
        summary.setdefault(key, []).append(rec['time_ms'])

    rows = []
    for (procs, mode), vals in sorted(summary.items()):
        avg = statistics.mean(vals)
        sd = statistics.pstdev(vals) if len(vals)>1 else 0.0
        rows.append({'procs':procs,'mode':mode,'avg_ms':avg,'std_ms':sd,'runs':len(vals)})

    # Write JSON
    with open(base + '.json','w') as f:
        json.dump({'records':records,'summary':rows,'multi_pairs':multi_pairs,'single_pair':(a_idx,b_idx)}, f, indent=2)

    # Markdown summary
    md_path = base + '_summary.md'
    by_procs = {}
    for row in rows:
        by_procs.setdefault(row['procs'], {}).update({row['mode']: row})
    with open(md_path,'w') as f:
        f.write('# Part C Benchmark Summary\n\n')
        f.write(f'Single pair used for p2p/scatter: {a_idx}:{b_idx}\n\n')
        f.write(f'Multi mode pairs (k={len(multi_pairs)}): {multi_pairs[:10]}{" ..." if len(multi_pairs)>10 else ""}\n\n')
        f.write('| Procs | P2P avg ms | Scatter avg ms | Multi avg ms | Scatter/P2P | Multi/P2P |\n')
        f.write('|-------|------------:|---------------:|-------------:|------------:|----------:|\n')
        for p in sorted(by_procs):
            p2p = by_procs[p].get('p2p')
            sca = by_procs[p].get('scatter')
            mul = by_procs[p].get('multi')
            def fmt(row):
                return f"{row['avg_ms']:.2f}±{row['std_ms']:.2f}" if row else '—'
            sp = (sca['avg_ms']/p2p['avg_ms']) if (sca and p2p) else 0.0
            mp = (mul['avg_ms']/p2p['avg_ms']) if (mul and p2p) else 0.0
            f.write(f"| {p} | {fmt(p2p)} | {fmt(sca)} | {fmt(mul)} | {sp:.2f} | {mp:.2f} |\n")
        f.write('\nInterpretation: Ratios < 1.00 indicate speedup relative to P2P baseline for that process count.\n')

    print(f'Wrote: {csv_path}, {md_path}, {base}.json')

if __name__ == '__main__':
    main()
