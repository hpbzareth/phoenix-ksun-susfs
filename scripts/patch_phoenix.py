#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess

def log(msg):
    print(f"[+] {msg}", flush=True)

def inject_poll_helpers(kernel_dir):
    poll_h = os.path.join(kernel_dir, "include", "linux", "poll.h")
    if os.path.exists(poll_h):
        with open(poll_h, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if "__poll_t" not in content:
            target = "#include <uapi/linux/poll.h>"
            helpers = """#include <uapi/linux/poll.h>

#ifndef __poll_t
#define __poll_t __poll_t
typedef unsigned int __poll_t;
#endif
"""
            if target in content:
                content = content.replace(target, helpers, 1)
                with open(poll_h, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                log("Injected __poll_t typedef into include/linux/poll.h")

    # Fallback in event_queue.h if present
    eq_h = os.path.join(kernel_dir, "drivers", "kernelsu", "kernel", "infra", "event_queue.h")
    if os.path.exists(eq_h):
        with open(eq_h, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "__poll_t" not in c:
            hdr = """#ifndef __poll_t
#define __poll_t __poll_t
typedef unsigned int __poll_t;
#endif
"""
            c = hdr + c
            with open(eq_h, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Injected __poll_t fallback into event_queue.h")

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
\tstruct mount *mnt = real_mount(path->mnt);

\tif (flags & ~(MNT_FORCE | MNT_DETACH | MNT_EXPIRE | UMOUNT_NOFOLLOW))
\t\treturn -EINVAL;
\tif (!may_mount())
\t\treturn -EPERM;
\tif (path->dentry != path->mnt->mnt_root)
\t\treturn -EINVAL;
\tif (!check_mnt(mnt))
\t\treturn -EINVAL;
\tif (mnt->mnt.mnt_flags & MNT_LOCKED)
\t\treturn -EINVAL;
\tif (flags & MNT_FORCE && !capable(CAP_SYS_ADMIN))
\t\treturn -EPERM;
\treturn 0;
}

int path_umount(struct path *path, int flags)
{
\tstruct mount *mnt = real_mount(path->mnt);
\tint ret;

\tret = can_umount(path, flags);
\tif (!ret)
\t\tret = do_umount(mnt, flags);

\tdput(path->dentry);
\tmntput_no_expire(mnt);
\treturn ret;
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

def patch_fs_files(kernel_dir):
    # 1. fs/Makefile
    mk = os.path.join(kernel_dir, "fs", "Makefile")
    if os.path.exists(mk):
        with open(mk, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "CONFIG_KSU_SUSFS" not in c:
            c = c.replace("nsfs.o", "nsfs.o\nobj-$(CONFIG_KSU_SUSFS) += susfs.o\n", 1)
            with open(mk, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Patched fs/Makefile")

    # 2. fs/proc/cmdline.c
    cmd_c = os.path.join(kernel_dir, "fs", "proc", "cmdline.c")
    if os.path.exists(cmd_c):
        with open(cmd_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "susfs_spoof_cmdline_or_bootconfig" not in c:
            hdr = """#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
extern int susfs_spoof_cmdline_or_bootconfig(struct seq_file *m);
#endif
"""
            c = hdr + c
            target = "static int cmdline_proc_show(struct seq_file *m, void *v)\n{"
            hook = target + """
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
\tif (!susfs_spoof_cmdline_or_bootconfig(m)) {
\t\tseq_putc(m, '\\n');
\t\treturn 0;
\t}
#endif"""
            c = c.replace(target, hook, 1)
            with open(cmd_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Patched fs/proc/cmdline.c")

    # 3. fs/proc/task_mmu.c
    tmmu_c = os.path.join(kernel_dir, "fs", "proc", "task_mmu.c")
    if os.path.exists(tmmu_c):
        with open(tmmu_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "susfs_sus_ino_for_show_map_vma" not in c:
            inc = """#if defined(CONFIG_KSU_SUSFS_SUS_KSTAT) || defined(CONFIG_KSU_SUSFS_SUS_MAP) || defined(CONFIG_KSU_SUSFS_OPEN_REDIRECT)
#include <linux/susfs_def.h>
#endif
#include <linux/shmem_fs.h>"""
            c = c.replace("#include <linux/shmem_fs.h>", inc, 1)

            fwd = """#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
extern void susfs_sus_ino_for_show_map_vma(unsigned long ino, dev_t *out_dev, unsigned long *out_ino);
#endif

static void\nshow_map_vma"""
            c = c.replace("static void\nshow_map_vma", fwd, 1)

            old_code = """\t\tdev = inode->i_sb->s_dev;
\t\tino = inode->i_ino;"""
            new_code = """#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
\t\tif (unlikely(inode->i_state & INODE_STATE_SUS_KSTAT)) {
\t\t\tsusfs_sus_ino_for_show_map_vma(inode->i_ino, &dev, &ino);
\t\t\tgoto bypass_orig_flow;
\t\t}
#endif
\t\tdev = inode->i_sb->s_dev;
\t\tino = inode->i_ino;
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
bypass_orig_flow:
#endif"""
            c = c.replace(old_code, new_code, 1)

            old_smap = "static void smap_gather_stats(struct vm_area_struct *vma,\n\t\t\t     struct mem_size_stats *mss)\n{"
            new_smap = old_smap + """
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
\tif (vma->vm_file && SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))) {
\t\treturn;
\t}
#endif"""
            c = c.replace(old_smap, new_smap, 1)

            with open(tmmu_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Patched fs/proc/task_mmu.c")

    # 4. fs/proc/base.c
    base_c = os.path.join(kernel_dir, "fs", "proc", "base.c")
    if os.path.exists(base_c):
        with open(base_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "CONFIG_KSU_SUSFS_SUS_MAP" not in c:
            hdr_target = '#include "fd.h"'
            hdr_repl = """#include "fd.h"
#if defined(CONFIG_KSU_SUSFS_SUS_MAP) || defined(CONFIG_KSU_SUSFS_OPEN_REDIRECT)
#include <linux/susfs_def.h>
#endif"""
            c = c.replace(hdr_target, hdr_repl, 1)

            fwd_target = "static int do_proc_readlink(struct path *path, char __user *buffer, int buflen)"
            fwd_repl = """#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
extern int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen);
#endif

static int do_proc_readlink(struct path *path, char __user *buffer, int buflen)"""
            c = c.replace(fwd_target, fwd_repl, 1)

            readlink_target = "\tif (!tmp)\n\t\treturn -ENOMEM;\n"
            readlink_repl = readlink_target + """
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tif (SUSFS_IS_INODE_OPEN_REDIRECT(path->dentry->d_inode)) {
\t\tif (!susfs_open_redirect_spoof_do_proc_readlink(path->dentry->d_inode, tmp, buflen)) {
\t\t\tlen = strlen(tmp);
\t\t\tif (copy_to_user(buffer, tmp, len))
\t\t\t\tlen = -EFAULT;
\t\t\tgoto out;
\t\t}
\t}
#endif
"""
            c = c.replace(readlink_target, readlink_repl, 1)

            map_target = """\t\t\tif (!vma->vm_file)
\t\t\t\tcontinue;"""
            map_repl = map_target + """
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
\t\t\tif (SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))) {
\t\t\t\tcontinue;
\t\t\t}
#endif"""
            c = c.replace(map_target, map_repl, 1)

            with open(base_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Patched fs/proc/base.c")

    # 5. security/selinux/avc.c
    avc_c = os.path.join(kernel_dir, "security", "selinux", "avc.c")
    if os.path.exists(avc_c):
        with open(avc_c, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        if "susfs_is_avc_log_spoofing_enabled" not in c:
            avc_hdr = """#define avc_cache_stats_incr(field)\tdo {} while (0)
#endif

#ifdef CONFIG_KSU_SUSFS
extern u32 susfs_ksu_sid;
extern u32 susfs_priv_app_sid;
bool susfs_is_avc_log_spoofing_enabled = false;
#endif"""
            c = c.replace("#define avc_cache_stats_incr(field)\tdo {} while (0)\n#endif", avc_hdr, 1)

            avc_dump_target = "rc = security_sid_to_context(state, tsid, &scontext, &scontext_len);"
            avc_dump_repl = avc_dump_target + """
#ifdef CONFIG_KSU_SUSFS
\tif (unlikely(tsid == susfs_ksu_sid && susfs_is_avc_log_spoofing_enabled)) {
\t\tif (rc)
\t\t\taudit_log_format(ab, " tsid=%d", susfs_priv_app_sid);
\t\telse
\t\t\taudit_log_format(ab, " tcontext=%s", "u:r:priv_app:s0:c512,c768");
\t\tgoto bypass_orig_flow;
\t}
#endif"""
            c = c.replace(avc_dump_target, avc_dump_repl, 1)

            avc_bypass_target = "BUG_ON(!tclass || tclass >= ARRAY_SIZE(secclass_map));"
            avc_bypass_repl = """#ifdef CONFIG_KSU_SUSFS
bypass_orig_flow:
#endif
\tBUG_ON(!tclass || tclass >= ARRAY_SIZE(secclass_map));"""
            c = c.replace(avc_bypass_target, avc_bypass_repl, 1)

            with open(avc_c, "w", encoding="utf-8", newline="\n") as f:
                f.write(c)
            log("Patched security/selinux/avc.c")

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
        "CONFIG_KSU",
        "CONFIG_SUSFS",
        "CONFIG_OVERLAY_FS",
        "CONFIG_KPROBES",
        "CONFIG_KPROBE_EVENTS",
        "CONFIG_HAVE_KPROBES",
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
CONFIG_KSU_MANUAL_HOOK=y
CONFIG_OVERLAY_FS=y
CONFIG_KPROBES=y
CONFIG_KPROBE_EVENTS=y
CONFIG_HAVE_KPROBES=y

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
CONFIG_LOCALVERSION="-Phoenix-KSUNext-uapi5-SuSFS-v2.2"
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
    
    inject_poll_helpers(kernel_dir)
    inject_path_umount(kernel_dir)
    patch_fs_files(kernel_dir)
    
    # Try git apply for the remaining clean files in the patch
    phoenix_patch = os.path.join(patches_dir, "susfs_v2.2_for_begonia.patch")
    if os.path.exists(phoenix_patch):
        log("Applying remaining SuSFS 2.2 hooks via git apply...")
        subprocess.run(["git", "apply", "-C1", "--ignore-whitespace", "--whitespace=nowarn", phoenix_patch],
                       cwd=kernel_dir, capture_output=True, text=True)

    susfs_dir = os.path.join(patches_dir, "susfs")
    copy_susfs_files(kernel_dir, susfs_dir)
    bridge_ksu_susfs(kernel_dir)
    setup_ksu_makefiles(kernel_dir, patches_dir)
    tune_phoenix_defconfig(kernel_dir)
    
    log("All Phoenix kernel patches, RAM optimizations, and SuSFS hooks applied successfully!")

if __name__ == "__main__":
    main()
