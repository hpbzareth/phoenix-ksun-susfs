# 🚀 Poco X2 / Redmi K30 4G (phoenix / phoenixin) Kernel Builder

Automated CI/CD builder for Xiaomi Poco X2 / Redmi K30 4G (`phoenix`, `phoenixin`) kernel featuring **KernelSU-Next v3.4.2 (UAPI 5)**, **SuSFS 2.x (v2.2.0)**, and comprehensive **RAM & Memory Speed Optimizations**.

---

## 📱 Device Specifications
- **Device**: Xiaomi Poco X2 / Redmi K30 4G
- **Codenames**: `phoenix` / `phoenixin`
- **Chipset**: Qualcomm Snapdragon 730G (SM7150 - 2x Kryo 470 Gold @ 2.2GHz + 6x Kryo 470 Silver @ 1.8GHz)
- **GPU**: Adreno 618
- **Storage**: UFS 2.1
- **Kernel Version**: Linux 4.14.357-openela
- **Kernel Source**: [tillua467-s-Playground/android_kernel_xiaomi_phoenix](https://github.com/tillua467-s-Playground/android_kernel_xiaomi_phoenix) (Branch: `v2.4`)

---

## ⚡ Key Features & Integrations

### 1. 🌿 KernelSU-Next v3.4.2 (Official Release - UAPI 5)
- Embedded in-tree KernelSU-Next v3.4.2 driver.
- Configured with native **UAPI 5** (as specified for maximum manager compatibility without dev-branch regressions).
- Manual hook integration for seamless syscall interception.

### 2. 🛡️ SuSFS v2.2.0 (Non-GKI 4.14)
- Full stealth root hiding:
  - `CONFIG_KSU_SUSFS_SUS_PATH`: Hide suspicious files and directories from unprivileged apps.
  - `CONFIG_KSU_SUSFS_SUS_MOUNT`: Hide root mounts from `/proc/self/mounts` and `/proc/self/mountinfo`.
  - `CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT` & `AUTO_ADD_SUS_BIND_MOUNT`.
  - `CONFIG_KSU_SUSFS_SUS_KSTAT`: Inode and stat spoofing.
  - `CONFIG_KSU_SUSFS_TRY_UMOUNT`: Automated unmounting in app namespaces via `path_umount`.
  - `CONFIG_KSU_SUSFS_SPOOF_UNAME`: Kernel release spoofing.
  - `CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG`: Clean `/proc/cmdline`.
  - `CONFIG_KSU_SUSFS_OPEN_REDIRECT`: Path redirection.
  - `CONFIG_KSU_SUSFS_SUS_MAP` & `SUS_MEMFD`: Maps and memfd cloaking.
  - `CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS`: Filter kallsyms entries.

### 3. 🚀 RAM & Memory Speed Optimizations
- **ZRAM with ZSTD Ultra Compression**:
  - `CONFIG_CRYPTO_ZSTD=y` & `CONFIG_ZRAM_DEFAULT_COMP_ALGORITHM="zstd"`.
  - Replaces slow/lossy compression with ZSTD, providing 35-40% higher compression ratio to hold dramatically more background apps in RAM.
- **Virtual Memory (VM) Latency Tuning**:
  - `swappiness = 160`: Encourages idle memory pages to be compressed into fast ZRAM rather than aggressively killing background processes.
  - `page-cluster = 0`: Reads single 4KB pages from ZRAM on demand, eliminating micro-stutters and I/O latency spikes.
  - `vfs_cache_pressure = 80`: Preserves directory and inode dentry caches, accelerating app launch speeds and navigation.
  - `dirty_ratio = 20` & `dirty_background_ratio = 5`: Early and smooth background page flushing to prevent I/O stalls during intensive multitasking.
  - `extra_free_kbytes = 24576`: Allocates memory watermark headroom to eliminate allocation delays during heavy bursts.
  - `stat_interval = 10`: Reduces background vmstat timer interrupts and CPU wakeups.
- **Simple LMK Cluster Bitmasks**:
  - `CONFIG_LITTLE_CPU_MASK=63` (Little cores 0-5).
  - `CONFIG_BIG_CPU_MASK=192` (Big cores 6-7).
- **UFS 2.1 Multi-Queue I/O Scheduler**:
  - `mq-deadline` & `bfq` with 256KB read-ahead queue.
  - Disables entropy gathering and I/O accounting overhead on high-speed flash storage.
- **Devfreq Memory Bandwidth & Bus Latency Governors**:
  - `CONFIG_DEVFREQ_GOV_PERFORMANCE=y`, `CONFIG_DEVFREQ_GOV_QCOM_BW_HWMON=y`, `CONFIG_DEVFREQ_GOV_MEMLAT=y`.
- **TCP BBR & FQ Hardware Pacing**:
  - `CONFIG_TCP_CONG_BBR=y` with Fair Queueing (`CONFIG_NET_SCH_FQ=y`) for minimal latency and bufferbloat reduction.

---

## 🛠️ How to Trigger Build

1. Go to the **Actions** tab on GitHub.
2. Select **Build Poco X2 / Redmi K30 Kernel with KernelSU-Next & SuSFS**.
3. Choose your options:
   - **SU Variant**: `ksun_uapi5_susfs` (default), `ksun_uapi5_nosusfs`, or `vanilla`
   - **Toolchain**: `proton` (Proton Clang 13 - recommended)
   - **Release Tag**: `Revision-1`
4. Click **Run workflow**.
5. Once completed, download the flashable AnyKernel3 `.zip` from Artifacts or GitHub Releases!
