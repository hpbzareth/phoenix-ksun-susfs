# AnyKernel3 Ramdisk Mod Script
# osm0sis @ xda-developers

## AnyKernel setup
# begin properties
properties() { '
kernel.string=Phoenix Kernel with KernelSU-Next & SuSFS by hpbzareth
do.devicecheck=1
do.modules=0
do.cleanup=1
do.cleanuponabort=0
device.name1=phoenix
device.name2=phoenixin
supported.versions=
'; } # end properties

# shell variables
block=/dev/block/bootdevice/by-name/boot;
is_slot_device=0;
ramdisk_compression=auto;
patch_vbmeta_flag=auto;

## AnyKernel methods (DO NOT CHANGE)
# import patching functions/variables - see for reference
. tools/ak3-core.sh;

## AnyKernel boot install
dump_boot;

# begin ramdisk changes
# migrate from /overlay to /overlay.d to enable SAR Magisk
if [ -d $ramdisk/overlay ]; then
  rm -rf $ramdisk/overlay;
fi;

write_boot;
## end boot install

# Install post-boot performance daemon if Magisk/KernelSU service.d exists
if [ -f $home/00-phoenix-perf.sh ]; then
  for sdir in /data/adb/service.d /data/adb/post-fs-data.d; do
    if [ -d "$sdir" ]; then
      ui_print "  • Installing Phoenix RAM & Memory Speed Optimizer to $sdir...";
      cp -f $home/00-phoenix-perf.sh "$sdir/00-phoenix-perf.sh";
      chmod 755 "$sdir/00-phoenix-perf.sh";
    fi;
  done;
fi;
