# AnyKernel3 Ramdisk Mod Script
# osm0sis @ xda-developers

## AnyKernel setup
# begin properties
properties() { '
kernel.string=Phoenix Kernel with KernelSU-Next & SuSFS by hpbzareth
do.devicecheck=1
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
device.name1=phoenix
device.name2=phoenixin
device.name3=phoenix_in
device.name4=Redmi K30
device.name5=POCO X2
supported.versions=11 - 15
'; } # end properties

# Dynamic partition block detection for Poco X2 / Redmi K30
BLOCK="";
for p in \
  /dev/block/by-name/boot \
  /dev/block/bootdevice/by-name/boot \
  /dev/block/platform/soc/1d84000.ufshc/by-name/boot \
  /dev/block/platform/soc/*/by-name/boot \
  /dev/block/platform/*/*/by-name/boot \
  /dev/block/mapper/boot; do
  if [ -e "$p" ]; then
    BLOCK="$p";
    break;
  fi;
done;

if [ -z "$BLOCK" ]; then
  find_boot=$(find /dev/block -name "boot" 2>/dev/null | head -n 1);
  if [ -n "$find_boot" ] && [ -e "$find_boot" ]; then
    BLOCK="$find_boot";
  else
    BLOCK=boot;
  fi;
fi;

# Set both upper and lower case for maximum AK3 version compatibility
block=$BLOCK;
IS_SLOT_DEVICE=auto;
is_slot_device=auto;
RAMDISK_COMPRESSION=auto;
ramdisk_compression=auto;
PATCH_VBMETA_FLAG=auto;
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
  [ -d /data/adb ] && mkdir -p /data/adb/service.d /data/adb/post-fs-data.d 2>/dev/null;
  for sdir in /data/adb/service.d /data/adb/post-fs-data.d; do
    if [ -d "$sdir" ]; then
      ui_print "  • Installing Phoenix RAM & Memory Speed Optimizer to $sdir...";
      cp -f $home/00-phoenix-perf.sh "$sdir/00-phoenix-perf.sh";
      chmod 755 "$sdir/00-phoenix-perf.sh";
    fi;
  done;
fi;
