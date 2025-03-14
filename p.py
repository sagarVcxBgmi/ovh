import psutil
import time

def print_net_io(interval=1):
    old_stats = psutil.net_io_counters()
    while True:
        time.sleep(interval)
        new_stats = psutil.net_io_counters()
        sent = new_stats.bytes_sent - old_stats.bytes_sent
        recv = new_stats.bytes_recv - old_stats.bytes_recv
        print(f"Sent: {sent/1024:.2f} KB/s, Received: {recv/1024:.2f} KB/s")
        old_stats = new_stats

print_net_io()
