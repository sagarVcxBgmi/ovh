import psutil

net_stats = psutil.net_io_counters()
bytes_sent = net_stats.bytes_sent
gb_sent = bytes_sent / (1024 ** 3)
print(f"Total outbound data: {bytes_sent} bytes ({gb_sent:.2f} GB)")
