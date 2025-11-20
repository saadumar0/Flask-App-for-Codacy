#!/usr/bin/env python3
"""Minimal MS-MPI environment bootstrap for Windows (dependencies only).

Default behavior (no flags):
  * Ensure Microsoft MPI runtime (mpiexec) is installed.
  * Ensure MS-MPI SDK is installed (to obtain mpi.h & msmpi.lib).
  * Copy minimal compile artifacts (mpi.h, msmpi.lib, msmpi.dll if found) into a local 'msmpi_local' folder
    next to this script for portable manual compilation.
  * (Does NOT compile any C++ sources.)

Rationale: Keeps assignment portable — after running once on a new PC you can compile:
  g++ -std=c++17 mpi_align.cpp -O2 -I msmpi_local/include -L msmpi_local/lib -lmsmpi -o mpi_align.exe

Exit codes:
 0 success
 1 winget missing
 2 runtime install failed
 3 runtime still missing after install
 6 SDK install failed (msiexec error)
 7 mpi.h still missing after SDK install
 9 SDK download failed (all strategies)
10 SDK file invalid (downloaded but below size threshold)

Flags:
  --force-runtime   Force reinstall runtime
  --force-sdk       Force reinstall SDK
  --min-msi-size N  Override minimum size check (bytes, default 5,000,000)
  --no-copy         Skip copying local msmpi_local artifacts
  --verbose         Verbose logging
  --dry-run         Show intended actions without executing
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import urllib.request
import ssl

RUNTIME_ID = "Microsoft.MPI"
SDK_BASE_URL = "https://download.microsoft.com/download/A/0/3/A03F5A89-5C0C-4C1F-ABF8-A1439F2F1C36/msmpisdk.msi"
SCRIPT_ROOT = Path(__file__).resolve().parent
LOCAL_DIR = SCRIPT_ROOT / "msmpi_local"

MPI_INCLUDE = Path(r"C:/Program Files (x86)/Microsoft SDKs/MPI/Include")
MPI_LIBDIR  = Path(r"C:/Program Files (x86)/Microsoft SDKs/MPI/Lib/x64")
MPI_BINDIR  = Path(r"C:/Program Files/Microsoft MPI/Bin")  # msmpi.dll typically here
MPI_HEADER  = MPI_INCLUDE / "mpi.h"
MPI_LIB     = MPI_LIBDIR / "msmpi.lib"

COLOR = {"ok":"\033[32m","warn":"\033[33m","err":"\033[31m","reset":"\033[0m"}

def c(msg, kind="ok"): return f"{COLOR.get(kind,'')}{msg}{COLOR['reset']}"

def log(msg, kind="ok", verbose=True):
    if verbose:
        print(c(msg, kind))

def have(cmd): return shutil.which(cmd) is not None

def run(cmd, verbose=True, check=True):
    log("$ "+" ".join(cmd), "warn", verbose)
    return subprocess.run(cmd, check=check)

def ensure_runtime(args):
    if have("mpiexec") and not args.force_runtime:
        log("Microsoft MPI runtime present.")
        return True
    if not have("winget"):
        log("winget not found.", "err"); sys.exit(1)
    if args.dry_run:
        log("[dry-run] Would install Microsoft MPI runtime", "warn")
        return have("mpiexec")
    r = run(["winget","install","-e","--id",RUNTIME_ID,
             "--accept-package-agreements","--accept-source-agreements"], verbose=args.verbose, check=False)
    if r.returncode != 0 and not have("mpiexec"):
        log("Runtime install failed","err"); sys.exit(2)
    if not have("mpiexec"):
        log("Runtime still missing","err"); sys.exit(3)
    log("Runtime ready.")
    return True

def attempt_download(url: str, dest: Path, args) -> bool:
    methods = ["urllib", "powershell", "curl", "bitsadmin"]
    for m in methods:
        if m == "urllib":
            try:
                urllib.request.urlretrieve(url, dest)
                if dest.exists() and dest.stat().st_size > 0: return True
            except Exception as e:
                log(f"urllib failed: {e}", "warn", args.verbose)
        elif m == "powershell":
            ps_cmd = ("try { Invoke-WebRequest -Headers @{'User-Agent'='Mozilla/5.0'} -Uri '"+url+"' -OutFile '"+str(dest)+"' -UseBasicParsing -ErrorAction Stop } catch { exit 55 }")
            r = subprocess.run(["powershell","-NoLogo","-NoProfile","-Command", ps_cmd])
            if r.returncode == 0 and dest.exists() and dest.stat().st_size>0: return True
        elif m == "curl" and have("curl"):
            r = subprocess.run(["curl","-L","-A","Mozilla/5.0","-o",str(dest),url])
            if r.returncode == 0 and dest.exists() and dest.stat().st_size>0: return True
        elif m == "bitsadmin" and have("bitsadmin"):
            job=f"msmpi_{int(time.time())}"; subprocess.run(["bitsadmin","/create",job]); subprocess.run(["bitsadmin","/addfile",job,url,str(dest)]); subprocess.run(["bitsadmin","/resume",job]); subprocess.run(["bitsadmin","/complete",job])
            if dest.exists() and dest.stat().st_size>0: return True
    return False

def download_sdk(msi: Path, args) -> bool:
    urls = [SDK_BASE_URL, f"{SDK_BASE_URL}?r={int(time.time())}"]
    for u in urls:
        log(f"Trying SDK URL: {u}", "warn", args.verbose)
        if attempt_download(u, msi, args):
            return True
    return False

def ensure_sdk(args):
    if MPI_HEADER.exists() and MPI_LIB.exists() and not args.force_sdk:
        log("MS-MPI SDK detected.")
        return True
    if args.dry_run:
        log("[dry-run] Would download & install SDK", "warn")
        return MPI_HEADER.exists()
    with tempfile.TemporaryDirectory() as td:
        msi = Path(td)/"msmpisdk.msi"
        if not download_sdk(msi, args):
            log("All download methods failed.", "err"); sys.exit(9)
        size = msi.stat().st_size
        if size < args.min_msi_size:
            bad = SCRIPT_ROOT/f"msmpisdk_invalid_{int(time.time())}.bin"
            shutil.copy(str(msi), bad)
            log(f"Invalid SDK file (too small: {size} bytes). Saved {bad}", "err")
            sys.exit(10)
        r = run(["msiexec","/i",str(msi),"/quiet","/norestart"], verbose=args.verbose, check=False)
        if r.returncode != 0:
            log("SDK install failed.", "err"); sys.exit(6)
    if not MPI_HEADER.exists():
        log("mpi.h still missing after install.", "err"); sys.exit(7)
    log("SDK ready.")
    return True

def copy_local(args):
    if args.no_copy:
        log("Skipping local artifact copy (--no-copy).", "warn")
        return
    include_dir = LOCAL_DIR / "include"
    lib_dir = LOCAL_DIR / "lib"
    include_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)
    # Copy header
    try:
        shutil.copy(MPI_HEADER, include_dir / "mpi.h")
        log(f"Copied mpi.h -> {include_dir}")
    except Exception as e:
        log(f"Failed to copy mpi.h: {e}", "warn")
    # Copy lib
    try:
        shutil.copy(MPI_LIB, lib_dir / "msmpi.lib")
        log(f"Copied msmpi.lib -> {lib_dir}")
    except Exception as e:
        log(f"Failed to copy msmpi.lib: {e}", "warn")
    # Copy runtime dll if present
    dll = None
    for candidate in [MPI_BINDIR/"msmpi.dll", Path("C:/Windows/System32/msmpi.dll")]:
        if candidate.exists():
            dll = candidate
            break
    if dll:
        try:
            shutil.copy(dll, LOCAL_DIR / "msmpi.dll")
            log(f"Copied msmpi.dll -> {LOCAL_DIR}")
        except Exception as e:
            log(f"Failed to copy msmpi.dll: {e}", "warn")
    else:
        log("msmpi.dll not found (runtime should still be in PATH).", "warn")

def parse_args():
    p = argparse.ArgumentParser(description="MS-MPI dependency bootstrap (no compilation)")
    p.add_argument("--force-runtime", action="store_true")
    p.add_argument("--force-sdk", action="store_true")
    p.add_argument("--min-msi-size", type=int, default=5_000_000)
    p.add_argument("--no-copy", action="store_true", help="Do not copy local msmpi_local artifacts")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    ensure_runtime(args)
    ensure_sdk(args)
    copy_local(args)
    log("Dependencies prepared. You can now compile manually.")
    log("Example:", "warn")
    log("  g++ -std=c++17 mpi_align.cpp -O2 -I msmpi_local/include -L msmpi_local/lib -lmsmpi -o mpi_align.exe")
    return 0

if __name__ == "__main__":
    sys.exit(main())