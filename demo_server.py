"""Serve a local file with HTTP byte-range support for an offline project demo.

Run in one terminal:
    python demo_server.py benchmark_tmp.bin

Then enter this URL in app.py:
    http://127.0.0.1:8000/benchmark_tmp.bin
"""

import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RangeHandler(BaseHTTPRequestHandler):
    file_path = None

    def _send_headers(self, status, start=0, end=None):
        size = os.path.getsize(self.file_path)
        end = size - 1 if end is None else end
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

    def do_HEAD(self):
        self._send_headers(200)

    def do_GET(self):
        size = os.path.getsize(self.file_path)
        start, end = 0, size - 1
        requested = self.headers.get("Range")
        if requested:
            try:
                unit, values = requested.split("=", 1)
                first, last = values.split("-", 1)
                if unit.strip() != "bytes":
                    raise ValueError
                start = int(first)
                end = int(last) if last else end
                if start < 0 or end < start or start >= size:
                    raise ValueError
                end = min(end, size - 1)
            except ValueError:
                self.send_error(416, "Invalid byte range")
                return
            self._send_headers(206, start, end)
        else:
            self._send_headers(200)

        with open(self.file_path, "rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                data = source.read(min(64 * 1024, remaining))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="Local HTTP range-request demo server")
    parser.add_argument("file", nargs="?", default="benchmark_tmp.bin")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    path = os.path.abspath(args.file)
    if not os.path.isfile(path):
        parser.error(f"file not found: {path}")

    RangeHandler.file_path = path
    print(f"Serving {os.path.basename(path)} ({os.path.getsize(path):,} bytes)")
    print(f"Open app.py and enter: http://127.0.0.1:{args.port}/{os.path.basename(path)}")
    print("Press Ctrl+C to stop the server.")
    ThreadingHTTPServer(("127.0.0.1", args.port), RangeHandler).serve_forever()


if __name__ == "__main__":
    main()
