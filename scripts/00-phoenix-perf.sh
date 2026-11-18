#!/system/bin/sh
# Phoenix Kernel Auto-Perf & Memory Optimizer (Poco X2 / Redmi K30)
# Developed by hpbzareth

# Wait for Android boot completed
while [ "$(getprop sys.boot_completed)" != "1" ]; do
  sleep 2
done

# 1. RAM & Virtual Memory Tuning (Optimized for ZSTD ZRAM)
if [ -d /proc/sys/vm ]; then
  # Keep anonymous memory compressed in ZRAM, avoiding app kills
  echo 160 > /proc/sys/vm/swappiness 2>/dev/null
  # Read single 4KB pages from ZRAM on demand, eliminating swap latency spikes
  echo 0 > /proc/sys/vm/page-cluster 2>/dev/null
  # Cache directory & inode dentries longer for rapid app launching
  echo 80 > /proc/sys/vm/vfs_cache_pressure 2>/dev/null
  # Steady dirty page flushing, preventing write stalls
  echo 5 > /proc/sys/vm/dirty_background_ratio 2>/dev/null
  echo 20 > /proc/sys/vm/dirty_ratio 2>/dev/null
  # Headroom for burst allocations
  echo 24576 > /proc/sys/vm/extra_free_kbytes 2>/dev/null
  # Reduce vmstat background timer wakeups
  echo 10 > /proc/sys/vm/stat_interval 2>/dev/null
fi

# 2. UFS 2.1 Storage Latency & Multi-Queue Tuning
for blk in /sys/block/sd* /sys/block/dm-*; do
  if [ -d "$blk/queue" ]; then
    # Set 256KB read-ahead buffer for UFS 2.1
    echo 256 > "$blk/queue/read_ahead_kb" 2>/dev/null
    # Prefer mq-deadline or bfq for foreground UI responsiveness
    if grep -q "mq-deadline" "$blk/queue/scheduler" 2>/dev/null; then
      echo mq-deadline > "$blk/queue/scheduler" 2>/dev/null
    elif grep -q "bfq" "$blk/queue/scheduler" 2>/dev/null; then
      echo bfq > "$blk/queue/scheduler" 2>/dev/null
    fi
    # Disable entropy contribution overhead on flash storage
    echo 0 > "$blk/queue/add_random" 2>/dev/null
    # Enable request merging for maximum bandwidth
    echo 0 > "$blk/queue/nomerges" 2>/dev/null
    # Disable I/O accounting overhead
    echo 0 > "$blk/queue/iostats" 2>/dev/null
  fi
done

# 3. CPU Schedutil / WALT Touch Ramp-Up
for pol in /sys/devices/system/cpu/cpufreq/policy*; do
  if [ -d "$pol/schedutil" ]; then
    echo 500 > "$pol/schedutil/up_rate_limit_us" 2>/dev/null
    echo 20000 > "$pol/schedutil/down_rate_limit_us" 2>/dev/null
  fi
done

# 4. Devfreq Memory Bus & GPU Latency
for df in /sys/class/devfreq/*; do
  if [ -f "$df/polling_interval" ]; then
    # Keep active bus polling for memory responsiveness
    echo 50 > "$df/polling_interval" 2>/dev/null
  fi
done

# GPU Adreno 618 power profile
if [ -d /sys/class/kgsl/kgsl-3d0 ]; then
  echo 0 > /sys/class/kgsl/kgsl-3d0/throttling 2>/dev/null
fi

exit 0
