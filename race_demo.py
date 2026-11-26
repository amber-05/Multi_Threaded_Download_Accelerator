"""
Why we need a lock: several threads updating one shared counter.

Updating a shared variable is really three steps: read it, add 1, write it
back. If a thread is switched out between the read and the write, another
thread's update gets overwritten and lost. This is a race condition.

(The steps are written out and a tiny sleep is added so the problem shows
up every time. In real code the same thing happens, just less predictably.)
"""

import threading
import time

counter = 0
lock = threading.Lock()


def add_without_lock(times):
    global counter
    for _ in range(times):
        temp = counter          # read
        time.sleep(0)           # let another thread run here
        counter = temp + 1      # write


def add_with_lock(times):
    global counter
    for _ in range(times):
        with lock:              # only one thread can do all three steps at once
            temp = counter
            time.sleep(0)
            counter = temp + 1


def run(target, label):
    global counter
    counter = 0
    threads = [threading.Thread(target=target, args=(5000,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"{label}: expected 20000, got {counter}")


run(add_without_lock, "without lock")
run(add_with_lock, "with lock   ")
