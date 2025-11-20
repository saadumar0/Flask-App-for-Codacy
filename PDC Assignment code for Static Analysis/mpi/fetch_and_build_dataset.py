#!/usr/bin/env python3
"""
fetch_and_build_dataset.py

Unified dataset builder for Assignment 1.

Given a list of dataset archive URLs (tar.gz or .tar), this script:
 1. Downloads each archive (skips if already cached unless --force).
 2. Extracts into a temporary workspace under --work-dir.
 3. Scans extracted files for FASTA / TFA style sequence files (.tfa, .fa, .fasta, .faa, .txt heuristic).
 4. Parses sequences (lines starting with '>') and cleans sequence lines (letters only, uppercase).
 5. Concatenates sequences into a single output .tfa until reaching --target (default 100) sequences.
 6. Optionally shuffles before truncation (--shuffle).
 7. Outputs basic statistics (count, avg length, min, max) and writes a manifest JSON.

Usage Example:
  python scripts/fetch_and_build_dataset.py \
      --output data_combined.tfa --target 120 --shuffle \
      --work-dir .cache_datasets

Then use the produced file with bench_part_c.py:
  python alignment/mpi/bench_part_c.py --tfa data_combined.tfa --pair 0:1 --multi-pairs 32 --procs 2 4 8

Archive Sources (default list can be overridden):
  BAliBASE_R1-5.tar.gz
  bali3fam-26.tar.gz
  data-set1.tar.gz
  data-set2.tar.gz
  homfam-20110613-25.tar.gz
  quantest2.tar

Note: We only need raw sequences; headers like >1aab_ are preserved but ignored by scoring logic downstream.
"""
from __future__ import annotations
import argparse, tarfile, tempfile, shutil, sys, os, re, json, random, hashlib
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

DEFAULT_URLS = [
    "http://www.lbgi.fr/balibase/BalibaseDownload/BAliBASE_R1-5.tar.gz",
    "http://clustal.org/omega/bali3fam-26.tar.gz",
    "http://projects.binf.ku.dk/pgardner/bralibase/data-set1.tar.gz",
    "http://projects.binf.ku.dk/pgardner/bralibase/data-set2.tar.gz",
    "http://www.clustal.org/omega/homfam-20110613-25.tar.gz",
    "http://bioinf.ucd.ie/quantest2.tar",
]

FA_EXTS = {'.tfa','.fa','.fasta','.faa'}
HEADER_RE = re.compile(r'^>')
SEQ_CLEAN_RE = re.compile(r'[^A-Za-z]')

def sha1_of_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(data).hexdigest()

def download(url: str, cache_dir: Path, force: bool) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    fname = url.split('/')[-1]
    dest = cache_dir / fname
    if dest.exists() and not force:
        return dest
    print(f"[download] {url}")
    try:
        req = Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urlopen(req, timeout=60) as resp:
            data = resp.read()
        tmp = dest.with_suffix(dest.suffix + '.part')
        with open(tmp,'wb') as f: f.write(data)
        os.replace(tmp, dest)
        print(f"[download] saved {dest} size={len(data)} sha1={sha1_of_bytes(data)[:10]}")
        return dest
    except (URLError, HTTPError) as e:
        print(f"[download] ERROR {url}: {e}", file=sys.stderr)
        raise

def iter_fasta_files(root: Path):
    for path in root.rglob('*'):
        if path.is_file():
            if path.suffix.lower() in FA_EXTS:
                yield path
            elif path.suffix.lower() == '.txt':  # heuristic: maybe FASTA
                # quick peek first line
                try:
                    with path.open('r',errors='ignore') as f:
                        for _ in range(5):
                            line = f.readline()
                            if not line: break
                            if line.startswith('>'):
                                yield path
                                break
                except Exception:
                    pass

def parse_fasta(path: Path):
    header=None; seq_lines=[]
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        for raw in f:
            line = raw.strip()
            if not line: continue
            if HEADER_RE.match(line):
                if header and seq_lines:
                    yield header, ''.join(seq_lines)
                header = line
                seq_lines=[]
            else:
                seq_lines.append(line)
    if header and seq_lines:
        yield header, ''.join(seq_lines)

def clean_seq(seq: str) -> str:
    return SEQ_CLEAN_RE.sub('', seq).upper()

def collect_sequences(extract_dir: Path, target: int, allow_exceed: bool):
    collected = []
    for f in iter_fasta_files(extract_dir):
        try:
            for h, s in parse_fasta(f):
                cs = clean_seq(s)
                if not cs: continue
                collected.append((h, cs))
                if not allow_exceed and len(collected) >= target:
                    return collected
        except Exception as e:
            print(f"[warn] parse failed {f}: {e}")
    return collected

def extract_archive(archive: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    mode = 'r:gz' if archive.suffixes[-1] == '.gz' else 'r:'
    with tarfile.open(archive, mode) as tf:
        tf.extractall(dest)


def build_dataset(urls, target: int, work_dir: Path, output: Path, shuffle: bool, force: bool, allow_exceed: bool):
    cache_dir = work_dir / 'downloads'
    extract_root = work_dir / 'extracted'
    if extract_root.exists() and force:
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True, exist_ok=True)

    archives=[]
    for url in urls:
        try:
            a = download(url, cache_dir, force)
            archives.append(a)
        except Exception:
            print(f"[skip] {url}")

    for a in archives:
        subdir = extract_root / a.stem
        if subdir.exists() and not force:
            print(f"[extract] skip existing {subdir}")
        else:
            print(f"[extract] {a} -> {subdir}")
            try:
                extract_archive(a, subdir)
            except Exception as e:
                print(f"[extract] ERROR {a}: {e}")

    sequences = collect_sequences(extract_root, target, allow_exceed)
    if shuffle:
        random.shuffle(sequences)
    if not sequences:
        print("No sequences collected.", file=sys.stderr)
        sys.exit(2)
    final = sequences if allow_exceed else sequences[:target]

    with output.open('w', encoding='utf-8') as f:
        for h, s in final:
            f.write(f"{h}\n{s}\n")
    lengths = [len(s) for _,s in final]
    stats = {
        'count': len(final),
        'avg_len': sum(lengths)/len(lengths),
        'min_len': min(lengths),
        'max_len': max(lengths),
        'target': target,
        'allow_exceed': allow_exceed,
        'source_urls': urls,
    }
    with (output.parent / (output.name + '.manifest.json')).open('w') as mf:
        json.dump(stats, mf, indent=2)
    print(f"[done] Wrote {output} sequences={stats['count']} avg_len={stats['avg_len']:.1f} min={stats['min_len']} max={stats['max_len']}")
    return stats


def main():
    ap = argparse.ArgumentParser(description="Download & concatenate alignment benchmark sequences")
    ap.add_argument('--output', type=Path, default=Path('data_combined.tfa'))
    ap.add_argument('--target', type=int, default=100)
    ap.add_argument('--urls', nargs='*', help='Override dataset URLs (space separated)')
    ap.add_argument('--work-dir', type=Path, default=Path('.dataset_work'))
    ap.add_argument('--shuffle', action='store_true')
    ap.add_argument('--force', action='store_true', help='Re-download & re-extract')
    ap.add_argument('--allow-exceed', action='store_true', help='Do not truncate at target; collect all')
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    urls = args.urls if args.urls else DEFAULT_URLS
    build_dataset(urls, args.target, args.work_dir, args.output, args.shuffle, args.force, args.allow_exceed)

if __name__ == '__main__':
    main()
