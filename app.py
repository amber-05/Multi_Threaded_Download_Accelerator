"""A small desktop interface for the multi-threaded download accelerator."""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

from downloader import copy_local, download, local_path


class DownloaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Download Accelerator")
        self.resizable(False, False)
        self.events = queue.Queue()
        self._build()
        self.after(100, self._read_events)

    def _build(self):
        frame = ttk.Frame(self, padding=22)
        frame.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Download Accelerator", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(frame, text="Download a URL faster by splitting it into concurrent parts.").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(3, 18)
        )

        ttk.Label(frame, text="URL or local file").grid(row=2, column=0, sticky="w")
        self.source = ttk.Entry(frame, width=52)
        self.source.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        ttk.Button(frame, text="Browse…", command=self._browse_source).grid(row=3, column=2, padx=(8, 0), pady=(4, 12))

        ttk.Label(frame, text="Save as").grid(row=4, column=0, sticky="w")
        self.output = ttk.Entry(frame, width=52)
        self.output.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        ttk.Button(frame, text="Choose…", command=self._browse_output).grid(row=5, column=2, padx=(8, 0), pady=(4, 12))

        ttk.Label(frame, text="Connections").grid(row=6, column=0, sticky="w")
        self.threads = tk.IntVar(value=4)
        ttk.Spinbox(frame, from_=1, to=16, width=7, textvariable=self.threads).grid(row=7, column=0, sticky="w", pady=(4, 16))
        ttk.Label(frame, text="Use 1 connection if the server does not support range requests.").grid(row=7, column=1, columnspan=2, sticky="w", pady=(4, 16))

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100, length=470)
        self.progress.grid(row=8, column=0, columnspan=3, sticky="ew")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status).grid(row=9, column=0, columnspan=2, sticky="w", pady=(7, 0))
        self.start_button = ttk.Button(frame, text="Start download", command=self._start)
        self.start_button.grid(row=9, column=2, sticky="e", pady=(7, 0))

        self.activity = tk.StringVar(value="Activity: waiting to start")
        ttk.Label(frame, textvariable=self.activity, foreground="#555555").grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(9, 0)
        )

    def _browse_source(self):
        path = filedialog.askopenfilename(title="Choose a local file")
        if path:
            self.source.delete(0, tk.END)
            self.source.insert(0, path)
            if not self.output.get():
                self.output.insert(0, os.path.basename(path))

    def _browse_output(self):
        path = filedialog.asksaveasfilename(title="Save download as")
        if path:
            self.output.delete(0, tk.END)
            self.output.insert(0, path)

    def _start(self):
        source = self.source.get().strip().strip('"').strip("'")
        if not source:
            messagebox.showwarning("Source required", "Enter a URL or choose a local file.")
            return
        output = self.output.get().strip() or os.path.basename(urlparse(source).path) or "download.bin"
        try:
            threads = int(self.threads.get())
            if threads < 1:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning("Invalid connections", "Connections must be a positive number.")
            return

        self.progress["value"] = 0
        self.status.set(f"Preparing download with {threads} connection(s)…")
        self.activity.set(f"Activity: creating {threads} worker thread(s)")
        self.start_button.state(["disabled"])
        threading.Thread(target=self._run_download, args=(source, output, threads), daemon=True).start()

    def _run_download(self, source, output, threads):
        used_threads = 1

        def report(done, total, speed):
            self.events.put(("progress", done, total, speed))

        def report_workers(count, message):
            nonlocal used_threads
            used_threads = count
            self.events.put(("workers", count, message))

        try:
            local = local_path(source)
            if local:
                if os.path.abspath(output) == os.path.abspath(local):
                    output = os.path.join(
                        os.path.dirname(output), "copy_of_" + os.path.basename(output)
                    )
                self.events.put(("workers", 1, "Local files are copied with one worker thread"))
                elapsed = copy_local(local, output, report)
            else:
                elapsed = download(source, output, threads, report, report_workers)
            self.events.put(("complete", output, elapsed, used_threads))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _read_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, done, total, speed = event
                    percent = (done / total * 100) if total else 0
                    self.progress["value"] = percent
                    detail = f"{percent:.1f}%"
                    if speed:
                        detail += f"  •  {speed:.2f} MB/s"
                    self.status.set(detail)
                    self.activity.set("Activity: worker threads are downloading separate byte ranges")
                elif event[0] == "workers":
                    _, count, message = event
                    self.status.set(f"Using {count} connection(s)")
                    self.activity.set(f"Activity: {message}")
                elif event[0] == "complete":
                    _, output, elapsed, threads = event
                    self.progress["value"] = 100
                    self.status.set(f"Completed with {threads} connection(s) in {elapsed:.2f}s")
                    self.activity.set(f"Activity: all {threads} worker thread(s) joined successfully")
                    self.start_button.state(["!disabled"])
                    messagebox.showinfo(
                        "Download complete",
                        f"Used {threads} connection(s)\nTime: {elapsed:.2f}s\n\nSaved to:\n{os.path.abspath(output)}",
                    )
                else:
                    self.status.set("Download failed")
                    self.activity.set("Activity: a worker reported an error")
                    self.start_button.state(["!disabled"])
                    messagebox.showerror("Download failed", event[1])
        except queue.Empty:
            pass
        self.after(100, self._read_events)


if __name__ == "__main__":
    DownloaderApp().mainloop()
