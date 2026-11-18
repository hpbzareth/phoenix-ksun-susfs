#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess

def log(msg):
    print(f"[+] {msg}", flush=True)

def inject_path_umount(kernel_dir):
    ns_c = os.path.join(kernel_dir, "fs", "namespace.c")
    if not os.path.exists(ns_c):
        return
    with open(ns_c, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    if "int path_umount" not in content:
        log("Injecting can_umount and path_umount into fs/namespace.c")
        if "static inline int check_mnt(struct mount *mnt);" not in content:
            fwd_decls = (
                '#include "internal.h"\n'
                'static inline int check_mnt(struct mount *mnt);\n'
                'static int do_umount(struct mount *mnt, int flags);\n'
                'static void mntput_no_expire(struct mount *mnt);\n'
                'static inline bool may_mount(void);\n'
            )
            content = content.replace('#include "internal.h"', fwd_decls, 1)
        
        path_umount_impl = """
static int can_umount(const struct path *path, int flags)
{
	struct mount *mnt = real_mount(path->mnt);

	if (flags & ~(MNT_FORCE | MNT_DETACH | MNT_EXPIRE | UMOUNT_NOFOLLOW))
		return -EINVAL;
	if (!may_mount())
		return -EPERM;
	if (path->dentry != path->mnt->mnt_root)
		return -EINVAL;
	if (!check_mnt(mnt))
		return -EINVAL;
	if (mnt->mnt.mnt_flags & MNT_LOCKED)
		return -EINVAL;
	if (flags & MNT_FORCE && !capable(CAP_SYS_ADMIN))
		return -EPERM;
	return 0;
}

int path_umount(struct path *path, int flags)
{
	struct mount *mnt = real_mount(path->mnt);
	int ret;

	ret = can_umount(path, flags);
	if (!ret)
		ret = do_umount(mnt, flags);

	dput(path->dentry);
	mntput_no_expire(mnt);
	return ret;
}
EXPORT_SYMBOL(path_umount);

"""
        target = "SYSCALL_DEFINE2(umount"
        if target in content:
            content = content.replace(target, path_umount_impl + target, 1)
        else:
            content += path_umount_impl
        
        with open(ns_c, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        log("Successfully injected path_umount into fs/namespace.c")

    internal_h = os.path.join(kernel_dir, "fs", "internal.h")
    if os.path.exists(internal_h):
        with open(internal_h, "r", encoding="utf-8", errors="ignore") as f:
            ih_content = f.read()
        if "path_umount" not in ih_content:
            target = "extern void __init mnt_init(void);"
            replacement = target + "\nextern int path_umount(struct path *path, int flags);\n"
            if target in ih_content:
                ih_content = ih_content.replace(target, replacement, 1)
            else:
                ih_content += "\nextern int path_umount(struct path *path, int flags);\n"
            with open(internal_h, "w", encoding="utf-8", newline="\n") as f:
                f.write(ih_content)
            log("Added path_umount declaration to fs/internal.h")

def apply_susfs_patch(kernel_dir, patch_file):
    if not os.path.exists(patch_file):
        log(f"Patch file {patch_file} not found!")
        return False
    
    log(f"Applying SuSFS 2.2 kernel patch: {patch_file}")
    res = subprocess.run(["git", "apply", "-C1", "--ignore-whitespace", "--whitespace=nowarn", "--recount", patch_file],
                         cwd=kernel_dir, capture_output=True, text=True)
    if res.returncode == 0:
        log("SuSFS 2.2 patch applied cleanly!")
        return True
    
    log(f"Direct git apply failed: {res.stderr.strip()[:300]}")
    if shutil.which("patch"):
        log("Retrying with patch -p1 --fuzz=3...")
        res3 = subprocess.run(["patch", "-p1", "--fuzz=3", "-i", patch_file],
                              cwd=kernel_dir, capture_output=True, text=True)
        if res3.returncode == 0:
            log("SuSFS 2.2 patch applied via patch -p1 --fuzz=3!")
            return True
        log(f"Patch stderr: {res3.stderr[:300]}")

    return False

def copy_susfs_files(kernel_dir, susfs_dir):
    fs_dir = os.path.join(kernel_dir, "fs")
    inc_dir = os.path.join(kernel_dir, "include", "linux")
    os.makedirs(fs_dir, exist_ok=True)
    os.makedirs(inc_dir, exist_ok=True)
    
    for f in ["susfs.c"]:
        src = os.path.join(susfs_dir, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(fs_dir, f))
            log(f"Copied {f} to fs/")
    for f in ["susfs.h", "susfs_def.h"]:
        src = os.path.join(susfs_dir, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(inc_dir, f))
            log(f"Copied {f} to include/linux/")

def bridge_ksu_susfs(kernel_dir):
    selinux_c = os.path.join(kernel_dir, "drivers", "kernelsu", "kernel", "selinux", "selinux.c")
    if os.path.exists(selinux_c):
        with open(selinux_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "susfs_is_current_ksu_domain" not in c:
            bridge_code = """
#ifdef CONFIG_KSU_SUSFS
#include <linux/security.h>

u32 susfs_ksu_sid __read_mostly = 0;
u32 susfs_init_sid __read_mostly = 0;
u32 susfs_zygote_sid __read_mostly = 0;
u32 susfs_zygote_next_sid __read_mostly = 0;
u32 susfs_priv_app_sid __read_mostly = 0;

static inline void susfs_set_sid(const char *secctx_name, u32 *out_sid)
{
\tint error;
\tif (!*out_sid) {
\t\terror = security_secctx_to_secid(secctx_name, strlen(secctx_name), out_sid);
\t\tif (error) {
\t\t\tpr_err("susfs: failed to get sid from %s, error: %d\\n", secctx_name, error);
\t\t}
\t}
}

bool susfs_is_current_zygote_domain(void) {
\treturn unlikely(current_sid() == susfs_zygote_sid);
}
EXPORT_SYMBOL(susfs_is_current_zygote_domain);

bool susfs_is_current_ksu_domain(void) {
\treturn unlikely(current_sid() == susfs_ksu_sid);
}
EXPORT_SYMBOL(susfs_is_current_ksu_domain);

bool susfs_is_current_init_domain(void) {
\treturn unlikely(current_sid() == susfs_init_sid);
}
EXPORT_SYMBOL(susfs_is_current_init_domain);

void susfs_set_batch_sid(void) {
\tsusfs_set_sid("u:r:zygote:s0", &susfs_zygote_sid);
\tsusfs_set_sid("u:r:zygote_secondary:s0", &susfs_zygote_next_sid);
\tsusfs_set_sid(KERNEL_SU_CONTEXT, &susfs_ksu_sid);
\tsusfs_set_sid("u:r:init:s0", &susfs_init_sid);
\tsusfs_set_sid("u:r:priv_app:s0:c512,c768", &susfs_priv_app_sid);
}
EXPORT_SYMBOL(susfs_set_batch_sid);

void setup_selinux(const char *domain, struct cred *cred) {
\ttransive_to_domain(domain, cred, false);
}
EXPORT_SYMBOL(setup_selinux);
#endif
"""
            c += bridge_code
            with open(selinux_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Injected SuSFS bridging symbols into drivers/kernelsu/kernel/selinux/selinux.c")

def patch_ksu_arm64_414(kernel_dir):
    # 1. drivers/kernelsu/kernel/include/arch.h
    # Linux 4.14 ARM64 does not use syscall wrapper (__arm64_sys_*). It uses sys_*
    arch_h = os.path.join(kernel_dir, "drivers", "kernelsu", "kernel", "include", "arch.h")
    if os.path.exists(arch_h):
        with open(arch_h, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        target = '#define REBOOT_SYMBOL "__arm64_sys_reboot"'
        repl = """#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 19, 0)
#define REBOOT_SYMBOL "__arm64_sys_reboot"
#define SYS_READ_SYMBOL "__arm64_sys_read"
#define SYS_EXECVE_SYMBOL "__arm64_sys_execve"
#define SYS_FSTAT_SYMBOL "__arm64_sys_newfstat"
#else
#define REBOOT_SYMBOL "sys_reboot"
#define SYS_READ_SYMBOL "sys_read"
#define SYS_EXECVE_SYMBOL "sys_execve"
#define SYS_FSTAT_SYMBOL "sys_newfstat"
#endif"""
        if target in c and "LINUX_VERSION_CODE" not in c:
            old_block = """#define REBOOT_SYMBOL "__arm64_sys_reboot"
#define SYS_READ_SYMBOL "__arm64_sys_read"
#define SYS_EXECVE_SYMBOL "__arm64_sys_execve"
// https://cs.android.com/android/kernel/superproject/+/common-android-mainline:common/scripts/syscalltbl.sh;l=57;drc=9142be9e6443fd641ca37f820efe00d9cd890eb1
// https://cs.android.com/android/kernel/superproject/+/common-android-mainline:common/scripts/syscall.tbl;l=104;drc=b36d4b6aa88ef039647228b98c59a875e92f8c8e
#define SYS_FSTAT_SYMBOL "__arm64_sys_newfstat\""""
            if old_block in c:
                c = c.replace(old_block, repl, 1)
            else:
                c = c.replace(target, repl, 1)
            with open(arch_h, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Patched arch.h for 4.14 non-syscall-wrapper ARM64 symbols (sys_reboot, sys_execve, etc.)")

    # 2. drivers/kernelsu/kernel/hook/arm64/syscall_hook.c
    # In Linux 4.14 ARM64, ni_syscall is 'sys_ni_syscall' not '__arm64_sys_ni_syscall'
    hook_c = os.path.join(kernel_dir, "drivers", "kernelsu", "kernel", "hook", "arm64", "syscall_hook.c")
    if os.path.exists(hook_c):
        with open(hook_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        old_slot = 'ni_syscall = (unsigned long)ksu_resolve_symbol_for_functable_hook("__arm64_sys_ni_syscall");'
        new_slot = """ni_syscall = (unsigned long)ksu_resolve_symbol_for_functable_hook("__arm64_sys_ni_syscall");
    if (!ni_syscall)
        ni_syscall = (unsigned long)ksu_resolve_symbol_for_functable_hook("sys_ni_syscall");"""
        if old_slot in c and "sys_ni_syscall" not in c:
            c = c.replace(old_slot, new_slot, 1)
            with open(hook_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Patched syscall_hook.c to resolve sys_ni_syscall on Linux 4.14")

    # 3. drivers/kernelsu/kernel/selinux/rules.c
    # Ensure susfs_set_batch_sid() is called so SuSFS knows the KSU domain
    rules_c = os.path.join(kernel_dir, "drivers", "kernelsu", "kernel", "selinux", "rules.c")
    if os.path.exists(rules_c):
        with open(rules_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "susfs_set_batch_sid" not in c:
            target = "reset_avc_cache();\nout_unlock:"
            repl = """reset_avc_cache();
#ifdef CONFIG_KSU_SUSFS
    extern void susfs_set_batch_sid(void);
    susfs_set_batch_sid();
#endif
out_unlock:"""
            c = c.replace(target, repl, 1)
            with open(rules_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Injected susfs_set_batch_sid() hook into selinux/rules.c")

    # 4. drivers/kernelsu/kernel/manager/apk_sign.c
    # Support both KernelSU-Next and official KernelSU Manager signatures
    apk_c = os.path.join(kernel_dir, "drivers", "kernelsu", "kernel", "manager", "apk_sign.c")
    if os.path.exists(apk_c):
        with open(apk_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        old_sign = "return check_v2_signature(path, EXPECTED_MANAGER_SIZE, EXPECTED_MANAGER_HASH);"
        new_sign = """return check_v2_signature(path, EXPECTED_MANAGER_SIZE, EXPECTED_MANAGER_HASH) ||
	       check_v2_signature(path, 0x377, "d3469712b6214462764a1d8d3e5cbe1d6819a0b629791b9f4101867821f1df64");"""
        if old_sign in c:
            c = c.replace(old_sign, new_sign, 1)
            with open(apk_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Enhanced apk_sign.c to accept both KSU-Next and official Manager signatures")

def setup_ksu_makefiles(kernel_dir, patches_dir):
    # 1. Copy su_variants.Kconfig to drivers/su_variants.Kconfig
    su_variants_src = os.path.join(patches_dir, "su_variants.Kconfig")
    su_variants_dst = os.path.join(kernel_dir, "drivers", "su_variants.Kconfig")
    if os.path.exists(su_variants_src):
        shutil.copy2(su_variants_src, su_variants_dst)
        log("Copied su_variants.Kconfig to drivers/")

    # 2. drivers/kernelsu/Kconfig redirect
    ksu_dir = os.path.join(kernel_dir, "drivers", "kernelsu")
    os.makedirs(ksu_dir, exist_ok=True)
    with open(os.path.join(ksu_dir, "Kconfig"), "w", encoding="utf-8", newline="\n") as f:
        f.write('source "drivers/kernelsu/kernel/Kconfig"\n')
    with open(os.path.join(ksu_dir, "Makefile"), "w", encoding="utf-8", newline="\n") as f:
        f.write('obj-y += kernel/\n')

    # 3. drivers/Makefile
    drv_mk = os.path.join(kernel_dir, "drivers", "Makefile")
    if os.path.exists(drv_mk):
        with open(drv_mk, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "kernelsu" not in c:
            c += "\n# KernelSU-Next\nobj-$(CONFIG_KSU_NEXT) += kernelsu/kernel/\nobj-$(CONFIG_KSU) += kernelsu/kernel/\n"
            with open(drv_mk, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Added KernelSU build targets to drivers/Makefile")

    # 4. drivers/Kconfig
    drv_kc = os.path.join(kernel_dir, "drivers", "Kconfig")
    if os.path.exists(drv_kc):
        with open(drv_kc, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "drivers/su_variants.Kconfig" not in c:
            if "endmenu" in c:
                idx = c.rfind("endmenu")
                c = c[:idx] + 'source "drivers/su_variants.Kconfig"\n\nendmenu' + c[idx+7:]
            else:
                c += '\nsource "drivers/su_variants.Kconfig"\n'
            with open(drv_kc, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Added source drivers/su_variants.Kconfig to drivers/Kconfig")

def tune_phoenix_defconfig(kernel_dir):
    cfg_path = os.path.join(kernel_dir, "arch", "arm64", "configs", "vendor", "phoenix_defconfig")
    if not os.path.exists(cfg_path):
        log(f"Defconfig not found at {cfg_path}")
        return

    with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    # Stripping lines to replace
    strip_keys = [
        "CONFIG_LOCALVERSION=",
        "CONFIG_LOCALVERSION_AUTO",
        "CONFIG_KSU",
        "CONFIG_SUSFS",
        "CONFIG_OVERLAY_FS",
        "CONFIG_KPROBES",
        "CONFIG_KPROBE_EVENTS",
        "CONFIG_HAVE_KPROBES",
        "CONFIG_HAVE_KRETPROBES",
        "CONFIG_KRETPROBES",
        "CONFIG_HAVE_SYSCALL_TRACEPOINTS",
        "CONFIG_ZRAM",
        "CONFIG_ZSTD",
        "CONFIG_CRYPTO_ZSTD",
        "CONFIG_IOSCHED_BFQ",
        "CONFIG_BFQ_GROUP_IOSCHED",
        "CONFIG_TCP_CONG_BBR",
        "CONFIG_NET_SCH_FQ",
        "CONFIG_LITTLE_CPU_MASK",
        "CONFIG_BIG_CPU_MASK",
        "CONFIG_SLUB_DEBUG"
    ]
    clean_lines = [l for l in lines if not any(l.startswith(k) for k in strip_keys)]

    tuning_lines = """
# === KernelSU-Next & SuSFS 2.x Integration ===
CONFIG_KSU_NEXT=y
CONFIG_KSU=y
CONFIG_OVERLAY_FS=y
CONFIG_KPROBES=y
CONFIG_KPROBE_EVENTS=y
CONFIG_HAVE_KPROBES=y
CONFIG_HAVE_KRETPROBES=y
CONFIG_KRETPROBES=y
CONFIG_HAVE_SYSCALL_TRACEPOINTS=y

# SuSFS 2.2 Features
CONFIG_KSU_SUSFS=y
CONFIG_KSU_SUSFS_SUS_PATH=y
CONFIG_KSU_SUSFS_SUS_MOUNT=y
CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT=y
CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT=y
CONFIG_KSU_SUSFS_SUS_KSTAT=y
CONFIG_KSU_SUSFS_SUS_OVERLAYFS=y
CONFIG_KSU_SUSFS_TRY_UMOUNT=y
CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT=y
CONFIG_KSU_SUSFS_SPOOF_UNAME=y
CONFIG_KSU_SUSFS_ENABLE_LOG=y
CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y
CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y
CONFIG_KSU_SUSFS_OPEN_REDIRECT=y
CONFIG_KSU_SUSFS_SUS_MAP=y
CONFIG_KSU_SUSFS_SUS_MEMFD=y

# === RAM & Virtual Memory Ultra Tuning (Poco X2 / K30) ===
CONFIG_CRYPTO_ZSTD=y
CONFIG_ZSTD_COMPRESS=y
CONFIG_ZSTD_DECOMPRESS=y
CONFIG_ZRAM=y
CONFIG_ZRAM_WRITEBACK=y
CONFIG_ZRAM_DEFAULT_COMP_ALGORITHM="zstd"
# CONFIG_ZRAM_MEMORY_TRACKING is not set
# CONFIG_SLUB_DEBUG is not set
CONFIG_ANDROID_SIMPLE_LMK=y
CONFIG_LITTLE_CPU_MASK=63
CONFIG_BIG_CPU_MASK=192
CONFIG_BALANCE_ANON_FILE_RECLAIM=y

# === UFS 2.1 Storage & Multi-Queue I/O Scheduling ===
CONFIG_IOSCHED_BFQ=y
CONFIG_BFQ_GROUP_IOSCHED=y
CONFIG_DEFAULT_MQ_IOSCHED="mq-deadline"

# === Devfreq Memory Bus & Latency Scaling ===
CONFIG_DEVFREQ_GOV_PERFORMANCE=y
CONFIG_DEVFREQ_GOV_QCOM_BW_HWMON=y
CONFIG_DEVFREQ_GOV_MEMLAT=y
CONFIG_QCOM_DEVFREQ_DEVBW=y

# === Networking & BBR Hardware Pacing ===
CONFIG_TCP_CONG_ADVANCED=y
CONFIG_TCP_CONG_BBR=y
CONFIG_DEFAULT_TCP_CONG="bbr"
CONFIG_NET_SCH_FQ=y
CONFIG_DEFAULT_NET_SCH="fq"
CONFIG_DEFAULT_FQ=y
# CONFIG_LOCALVERSION_AUTO is not set
CONFIG_LOCALVERSION="-Phoenix-KSUN-SuSFS"
"""
    clean_lines.append(tuning_lines)
    with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(clean_lines)
    log("Successfully tuned arch/arm64/configs/vendor/phoenix_defconfig!")

def main():
    if len(sys.argv) < 3:
        print("Usage: patch_phoenix.py <kernel_dir> <patches_dir>")
        sys.exit(1)
        
    kernel_dir = os.path.abspath(sys.argv[1])
    patches_dir = os.path.abspath(sys.argv[2])
    
    log(f"Kernel source dir: {kernel_dir}")
    log(f"Patches dir: {patches_dir}")
    
    inject_path_umount(kernel_dir)
    
    phoenix_patch = os.path.join(patches_dir, "susfs_v2.2_for_phoenix.patch")
    if not os.path.exists(phoenix_patch):
        phoenix_patch = os.path.join(patches_dir, "susfs_v2.2_for_begonia.patch")
        
    apply_susfs_patch(kernel_dir, phoenix_patch)

    susfs_dir = os.path.join(patches_dir, "susfs")
    copy_susfs_files(kernel_dir, susfs_dir)
    bridge_ksu_susfs(kernel_dir)
    patch_ksu_arm64_414(kernel_dir)
    setup_ksu_makefiles(kernel_dir, patches_dir)
    tune_phoenix_defconfig(kernel_dir)
    
    log("All Phoenix kernel patches, RAM optimizations, and SuSFS hooks applied successfully!")

if __name__ == "__main__":
    main()
