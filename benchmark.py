"""
Downloads the same file with different thread counts and prints the times.

Usage:
    python benchmark.py <url>
"""

import os
import sys

from downloader import download

if len(sys.argv) < 2:
    print("Usage: python benchmark.py <url>")
    sys.exit(1)

url = sys.argv[1]
results = []
TEMP_OUTPUT = "benchmark_download.bin"

for n in [1, 2, 4, 8, 16]:
    print(f"\n--- {n} thread(s) ---")
    seconds = download(url, TEMP_OUTPUT, n)
    results.append((n, seconds))
    os.remove(TEMP_OUTPUT)

base = results[0][1]
print("\nThreads   Time (s)   Speedup")
for n, seconds in results:
    print(f"{n:7d}   {seconds:8.2f}   {base / seconds:6.2f}x")
