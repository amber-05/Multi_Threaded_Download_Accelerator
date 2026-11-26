"""
Multi-threaded download accelerator.

Idea: instead of downloading a file over one connection, split it into
parts and download each part on its own thread using HTTP Range requests.
Network downloads spend most of their time waiting, so several threads
waiting at the same time finish sooner than one.

Usage:
    python downloader.py <url> [-t THREADS] [-o OUTPUT]
"""

import argparse
import os
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse
from urllib.request import url2pathname

CHUNK_SIZE = 64 * 1024   # bytes read from the socket at a time
RETRIES = 3              # attempts per part before giving up
TIMEOUT = 15             # seconds to wait on the network

# Shared between threads, so every access must be protected by a lock.
progress_lock = threading.Lock()
file_lock = threading.Lock()
downloaded = 0


def get_file_info(url):
    """Ask the server for the file size and whether it supports ranges."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            size = resp.headers.get("Content-Length")
            accepts_ranges = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
        return (int(size) if size else None), accepts_ranges
    except Exception:
        # Some servers reject HEAD; probe with a 1-byte ranged GET instead.
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                if resp.status == 206:
                    total = resp.headers.get("Content-Range", "").split("/")[-1]
                    if total.isdigit():
                        return int(total), True
        except Exception:
            pass
        return None, False


def split_ranges(size, parts):
    """Split [0, size) into `parts` byte ranges. Returns (start, end) pairs."""
    parts = max(1, min(parts, size))        # never more parts than bytes
    base = size // parts
    ranges = []
    start = 0
    for i in range(parts):
        end = start + base - 1
        if i == parts - 1:                  # last part takes the leftover bytes
            end = size - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def download_part(url, start, end, out_file):
    """Download bytes start..end and write them at the right place in the file."""
    global downloaded
    position = start

    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            position = start
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                if resp.status != 206:
                    raise IOError("server ignored the Range header")
                while position <= end:
                    data = resp.read(min(CHUNK_SIZE, end - position + 1))
                    if not data:
                        raise IOError("connection closed early")
                    # Only one thread may seek+write at a time, otherwise
                    # one thread could move the file pointer under another.
                    with file_lock:
                        out_file.seek(position)
                        out_file.write(data)
                    position += len(data)
                    with progress_lock:
                        downloaded += len(data)
            return
        except Exception as err:
            print(f"\npart {start}-{end} failed (attempt {attempt}/{RETRIES}): {err}")
            # bytes counted for this failed attempt will be downloaded again
            with progress_lock:
                downloaded -= position - start
            time.sleep(attempt)

    raise RuntimeError(f"part {start}-{end} could not be downloaded")


def show_progress(total, stop_event, progress_callback=None):
    """Runs on its own thread and reports progress until told to stop."""
    start_time = time.time()
    while not stop_event.is_set():
        with progress_lock:
            done = downloaded
        elapsed = max(time.time() - start_time, 0.001)
        speed = done / elapsed / 1024 / 1024
        if progress_callback:
            progress_callback(done, total, speed)
        else:
            print(f"\r{done / total * 100:5.1f}%  {speed:6.2f} MB/s", end="", flush=True)
        time.sleep(0.3)


def download(url, output, threads, progress_callback=None, status_callback=None):
    global downloaded
    downloaded = 0

    size, accepts_ranges = get_file_info(url)

    if size is None or not accepts_ranges:
        print("Server does not support ranges (or gave no size). Using 1 thread.")
        threads = 1
        if status_callback:
            status_callback(1, "Server does not support ranges; using one connection")

    start_time = time.time()

    if threads == 1 and (size is None or not accepts_ranges):
        # Plain single-connection download
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp, open(output, "wb") as f:
            while True:
                data = resp.read(CHUNK_SIZE)
                if not data:
                    break
                f.write(data)
        size = os.path.getsize(output)
    else:
        ranges = split_ranges(size, threads)
        print(f"File size: {size} bytes, downloading in {len(ranges)} parts")
        if status_callback:
            status_callback(len(ranges), f"Using {len(ranges)} worker thread(s), one per byte range")

        with open(output, "wb") as f:
            f.truncate(size)                # reserve the full file size first

            stop_event = threading.Event()
            reporter = threading.Thread(
                target=show_progress,
                args=(size, stop_event, progress_callback),
            )
            reporter.start()

            errors = []

            def worker(s, e):
                try:
                    download_part(url, s, e, f)
                except Exception as err:
                    errors.append(err)

            workers = [threading.Thread(target=worker, args=r) for r in ranges]
            for t in workers:
                t.start()
            for t in workers:
                t.join()                    # wait for every part to finish

            stop_event.set()
            reporter.join()

            if errors:
                raise RuntimeError(f"Download failed: {errors[0]}")

    elapsed = time.time() - start_time
    final_size = os.path.getsize(output)
    print(f"\nDone: {output} ({final_size} bytes) in {elapsed:.2f}s")
    if final_size != size:
        print("Warning: file size does not match what the server reported!")
    return elapsed


def local_path(source):
    """Return a local file path if `source` is a file:// URL or an existing file."""
    if source.lower().startswith("file:"):
        return url2pathname(urlparse(source).path)
    if os.path.isfile(os.path.expanduser(source)):
        return os.path.expanduser(source)
    return None


def copy_local(src, output, progress_callback=None):
    """Copy a file on this computer, showing progress."""
    size = os.path.getsize(src)
    start_time = time.time()
    done = 0
    with open(src, "rb") as fin, open(output, "wb") as fout:
        while True:
            data = fin.read(CHUNK_SIZE * 16)
            if not data:
                break
            fout.write(data)
            done += len(data)
            if progress_callback:
                progress_callback(done, size, 0)
            else:
                print(f"\r{done / max(size, 1) * 100:5.1f}%", end="", flush=True)
    elapsed = time.time() - start_time
    if not progress_callback:
        print(f"\nDone: {output} ({os.path.getsize(output)} bytes) in {elapsed:.2f}s")
    return elapsed


def main():
    parser = argparse.ArgumentParser(description="Multi-threaded downloader")
    parser.add_argument("url", nargs="?")
    parser.add_argument("-t", "--threads", type=int, default=4)
    parser.add_argument("-o", "--output")
    args = parser.parse_args()

    url = args.url or input("Enter a URL or a file path on this computer: ")
    url = url.strip().strip('"').strip("'")     # pasted paths often have quotes
    if not url:
        parser.error("a URL or file path is required")

    local = local_path(url)
    if local:
        output = args.output or os.path.basename(local)
        if os.path.abspath(output) == os.path.abspath(local):
            output = os.path.join(
                os.path.dirname(output), "copy_of_" + os.path.basename(output)
            )                                   # never overwrite the source
        copy_local(local, output)
    else:
        output = args.output or os.path.basename(urlparse(url).path) or "download.bin"
        download(url, output, args.threads)


if __name__ == "__main__":
    main()
