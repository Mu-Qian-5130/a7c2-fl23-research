/* Fixed resource allowlist only. Atomic inode replacement keeps the running
 * UI's old mmap intact. Old hardlinks remain until named-UI verification. Job-pinned names appended without replacing existing records.
 * Modes: 0 check, 1 stage/install, 2 restore (plain AP), 3 cleanup (named AP).
 * No AP/CP writes, Backup settings, arbitrary paths, WBI, shell or reboot.
 */
typedef unsigned long u64; typedef unsigned int u32; typedef long i64; typedef unsigned char u8;
static i64 sc(i64 n,i64 a,i64 b,i64 c,i64 d,i64 e,i64 f) {
 register i64 x0 __asm__("x0")=a,x1 __asm__("x1")=b,x2 __asm__("x2")=c;
 register i64 x3 __asm__("x3")=d,x4 __asm__("x4")=e,x5 __asm__("x5")=f,x8 __asm__("x8")=n;
 __asm__ volatile("svc 0":"+r"(x0):"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5),"r"(x8):"memory","cc");return x0;
}
static i64 op(const char*p,i64 flags,u32 mode) {return sc(56,-100,(i64)p,flags,mode,0,0);}
static i64 cl(i64*f) {if(*f<0)return 0;i64 r=sc(57,*f,0,0,0,0,0);*f=-1;return r;}
static int same(const u8*a,const u8*b,u32 n) {for(u32 i=0;i<n;i++)if(a[i]!=b[i])return 0;return 1;}
#include "sha256.h"
struct Asset {const char*name;u32 size;u8 before[32],after[32];};
#include PATCH_MANIFEST
struct Stat {u64 dev,ino;u32 mode,nlink,uid,gid;u64 rdev,pad1;i64 size;u32 blksize,pad2;u64 blocks,rest[7];};
_Static_assert(sizeof(struct Stat)==128,"stat ABI");
struct Request {u8 magic[8];u32 mode,reserved;};
struct Report {
 u8 magic[8];u32 version,mode,phase,count;
 i64 status,rollback,remount,readonly,plugin_unlink,euid,pid;
 u32 staged,linked,committed,restored,removed_backups,reserved;
 u8 ap_hash[32];
};
_Static_assert(sizeof(struct Report)==136,"name asset result ABI");
static struct Request req;static struct Report r;
static u8 hashbuf[65536],assetbuf[524288],mounts[8192];
static u8 temp_created[68],backup_created[68],committed[68];
static u8 restore_needed[68],old_present[68];
static struct Stat initial[68];
static int mounted_rw=0;
static char actual[256],temp[256],backup[256];
static void paths(u32 i) {
 const char*a="/usr/share/app/",*b=backup_prefix;
 u32 x=0;while(a[x]) {actual[x]=a[x];x++;}u32 y=0;while(assets[i].name[y])actual[x++]=assets[i].name[y++];actual[x]=0;
 x=0;while(b[x]) {temp[x]=backup[x]=b[x];x++;}y=0;
 while(assets[i].name[y]) {temp[x]=backup[x]=assets[i].name[y++];x++;}
 const char*t=".stage",*o=".original";y=0;while(t[y])temp[x+y]=t[y],y++;temp[x+y]=0;
 y=0;while(o[y])backup[x+y]=o[y],y++;backup[x+y]=0;
}
static i64 read_exact(i64 fd,u8*out,u32 n,u64 at) {
 u32 done=0,retry=0;while(done<n) {i64 v=sc(67,fd,(i64)(out+done),n-done,at+done,0,0);
  if(v==-4&&retry++<3)continue;if(v<=0||(u64)v>n-done)return v<0?v:-5;done+=(u32)v;}return 0;
}
static i64 write_exact(i64 fd,const u8*in,u32 n) {
 u32 done=0,retry=0;while(done<n) {i64 v=sc(64,fd,(i64)(in+done),n-done,0,0,0);
  if(v==-4&&retry++<3)continue;if(v<=0||(u64)v>n-done)return v<0?v:-5;done+=(u32)v;}return 0;
}
static i64 hash_path(const char*p,u64 size,u8*out,struct Stat*st) {
 i64 fd=op(p,0x20000,0);if(fd<0)return fd;
 struct Stat s;i64 status=sc(80,fd,(i64)&s,0,0,0,0);
 if(!status&&((s.mode&0170000)!=0100000||s.size!=(i64)size||s.uid!=original_uid||s.gid!=original_gid))status=-22;
 SHA256 h;sha_init(&h);u64 at=0;
 while(!status&&at<size) {u32 n=size-at>sizeof(hashbuf)?sizeof(hashbuf):(u32)(size-at);
  status=read_exact(fd,hashbuf,n,at);if(!status)sha_add(&h,hashbuf,n);at+=n;}
 if(!status) {i64 n=sc(67,fd,(i64)hashbuf,1,size,0,0);if(n)status=n<0?n:-27;}
 i64 c=cl(&fd);if(!status)status=c;if(!status) {sha_end(&h,out);if(st)*st=s;}return status;
}
static i64 verify(const char*p,u64 size,const u8*hash,struct Stat*st) {
 u8 actual_hash[32];i64 v=hash_path(p,size,actual_hash,st);return v?v:same(actual_hash,hash,32)?0:-84;
}
static i64 absent(const char*p) {i64 fd=op(p,0x20000,0);if(fd==-2)return 0;if(fd<0)return fd;cl(&fd);return -17;}
static i64 mount_state(int ro) {
 i64 fd=op("/proc/mounts",0,0);if(fd<0)return fd;
 i64 n=sc(63,fd,(i64)mounts,sizeof(mounts),0,0,0),c=cl(&fd);if(c)return c;
 if(n<=0||n>=(i64)sizeof(mounts))return -75;
 const u8 prefix[]="/dev/nflasha15 /usr ext2 ";u32 len=sizeof(prefix)-1,count=0;
 for(u32 i=0;i+len+3<=(u32)n;i++)if((!i||mounts[i-1]=='\n')&&same(mounts+i,prefix,len)) {
  if(mounts[i+len]!='r'||mounts[i+len+1]!=(ro?'o':'w')||mounts[i+len+2]!=',')return -30;count++;}
 return count==1?0:-22;
}
static i64 remount(int ro) {i64 v=sc(40,0,(i64)"/usr",0,0xc30UL+(ro?1:0),0,0);return v?v:mount_state(ro);}
static i64 sync_dir(void) {i64 fd=op("/usr/share/app",0x10000,0);if(fd<0)return fd;
 i64 v=sc(82,fd,0,0,0,0,0),c=cl(&fd);return v?v:c;}
static i64 unlink_path(const char*p) {return sc(35,-100,(i64)p,0,0,0,0);}
static i64 rename_path(const char*a,const char*b) {return sc(38,-100,(i64)a,-100,(i64)b,0,0);}
static i64 stage_one(u32 i) {
 paths(i);const struct Asset*a=&assets[i];if(after_sizes[i]>sizeof(assetbuf)||a->size<5740)return -22;
 i64 fd=op(actual,0x20000,0);if(fd<0)return fd;
 struct Stat s;i64 v=sc(80,fd,(i64)&s,0,0,0,0);
 if(!v&&(s.dev!=initial[i].dev||s.ino!=initial[i].ino||s.size!=a->size))v=-116;
 if(!v)v=read_exact(fd,assetbuf,a->size,0);i64 c=cl(&fd);if(!v)v=c;if(v)return v;
 if(a->size<16||!same(assetbuf,(const u8[]){117,120,99,7,0,0,0,0},8))return -22;
 u32 descriptor=*(u32*)(assetbuf+12),count=descriptor&8191U;
 if(*(unsigned short*)(assetbuf+8)!=8||*(unsigned short*)(assetbuf+10)!=5||count!=old_counts[i]||(count!=2860U&&count!=2866U)||descriptor!=(count|(((count+1)&~1U)<<12)))return -22;
 u32 base=(16+2*count+3)&~3U,at=a->size;
 if(count==2860U) {
  if(a->size+12>sizeof(assetbuf))return -22;
  for(u32 j=a->size;j>base;j--)assetbuf[j+11]=assetbuf[j-1];
  for(u32 j=0;j<12;j++)assetbuf[base+j]=255;
  *(u32*)(assetbuf+12)=2866U|(2866U<<12);base+=12;at+=12;
 }
 for(u32 j=0;j<6;j++)if((selected_mask&(1U<<j))||count==2860U) {
  u32 index=(label_ids[j]&0xffffff)-0xa000U,p=16+2*index;
  if(index>=2866U||p+2>base)return -22;
  u32 old=assetbuf[p]|((u32)assetbuf[p+1]<<8),record=base+old*4;
  if(old!=old_pointers[i][j])return -84;
  if(count!=2860U&&(old==65535U||record+5>a->size||*(u32*)(assetbuf+record)!=(0x1e000000|(label_ids[j]&0xffffff))))return -84;
  u32 len=0;while(len<64&&names[j][len])len++;
  if(!len||len>=64||at+4+len+4>sizeof(assetbuf))return -22;
  u32 pointer=(at-base)/4;if(pointer>=65535U)return -75;
  assetbuf[p]=pointer;assetbuf[p+1]=pointer>>8;
  *(u32*)(assetbuf+at)=0x1e000000|(label_ids[j]&0xffffff);at+=4;
  for(u32 k=0;k<len;k++)assetbuf[at++]=names[j][k];assetbuf[at++]=0;
  while(at&3)assetbuf[at++]=0;
 }
 if(at!=after_sizes[i])return -84;
 SHA256 h;u8 digest[32];sha_init(&h);sha_add(&h,assetbuf,after_sizes[i]);sha_end(&h,digest);
 if(!same(digest,a->after,32))return -84;
 fd=op(temp,0x200c1,s.mode&07777);if(fd<0)return fd;temp_created[i]=1;
 v=sc(55,fd,s.uid,s.gid,0,0,0);if(!v)v=sc(52,fd,s.mode&07777,0,0,0,0);if(!v)v=write_exact(fd,assetbuf,after_sizes[i]);
 if(!v)v=sc(82,fd,0,0,0,0,0);c=cl(&fd);if(!v)v=c;if(v)return v;
 v=verify(temp,after_sizes[i],a->after,0);if(!v)r.staged++;return v;
}
static i64 recreate_original(u32 i) {
 paths(i);const struct Asset*a=&assets[i];if(after_sizes[i]>sizeof(assetbuf))return -22;
 i64 fd=op(actual,0x20000,0);if(fd<0)return fd;
 struct Stat st;i64 v=sc(80,fd,(i64)&st,0,0,0,0);
 if(!v)v=read_exact(fd,assetbuf,after_sizes[i],0);i64 c=cl(&fd);if(!v)v=c;if(v)return v;
 if(a->size<16||!same(assetbuf,(const u8[]){117,120,99,7,0,0,0,0},8))return -22;
 if(old_counts[i]==2860U) {
  u32 base=16+2860U*2;
  for(u32 j=base;j<a->size;j++)assetbuf[j]=assetbuf[j+12];
  *(u32*)(assetbuf+12)=2860U|(2860U<<12);
 }
 for(u32 j=0;j<6;j++)if((selected_mask&(1U<<j))&&old_counts[i]!=2860U) {
  u32 index=(label_ids[j]&0xffffff)-0xa000U,p=16+2*index;
  if(p+2>a->size)return -22;
  assetbuf[p]=old_pointers[i][j];assetbuf[p+1]=old_pointers[i][j]>>8;
 }
 SHA256 h;u8 hash[32];sha_init(&h);sha_add(&h,assetbuf,a->size);sha_end(&h,hash);
 if(!same(hash,a->before,32))return -84;
 fd=op(backup,0x200c1,st.mode&07777);if(fd<0)return fd;backup_created[i]=1;
 v=sc(55,fd,st.uid,st.gid,0,0,0);if(!v)v=sc(52,fd,st.mode&07777,0,0,0,0);if(!v)v=write_exact(fd,assetbuf,a->size);
 if(!v)v=sc(82,fd,0,0,0,0,0);c=cl(&fd);if(!v)v=c;if(v)return v;
 v=verify(backup,a->size,a->before,0);if(!v)r.staged++;return v;
}
static i64 rollback_install(void) {
 i64 status=0;
 for(u32 j=asset_count;j>0;j--) {u32 i=j-1;paths(i);
  if(committed[i]) {i64 v=rename_path(backup,actual);if(v&&!status)status=v;
   if(!v) {committed[i]=0;backup_created[i]=0;r.restored++;}}
 }
 if(!status)for(u32 i=0;i<asset_count;i++) {paths(i);i64 v=verify(actual,assets[i].size,assets[i].before,0);if(v){status=v;break;}}
 if(!status)status=sync_dir();return status;
}
static void work(void) {
 i64 fd=op("/tmp/jiritsu/a7c2.names.request",0,0);if(fd<0){r.status=fd;return;}
 r.status=read_exact(fd,(u8*)&req,sizeof(req),0);i64 c=cl(&fd);if(!r.status)r.status=c;
 if(r.status)return;
 if(!same(req.magic,(const u8*)"A7NAM001",8)||req.mode>3||req.reserved||!asset_count||asset_count>68){r.status=-22;return;}
 r.mode=req.mode;r.count=asset_count;if(r.euid){r.status=-13;return;}
 r.phase=1;r.status=mount_state(1);if(r.status)return;
 r.status=hash_path("/usr/lib/appFw.so",ap_size,r.ap_hash,0);if(r.status)return;
 if(!same(r.ap_hash,req.mode==3?ap_named_hash:ap_plain_hash,32)){r.status=-84;return;}
 for(u32 i=0;i<asset_count;i++) {paths(i);const struct Asset*a=&assets[i];
  r.status=absent(temp);if(r.status)return;
  if(req.mode<2) {r.status=verify(actual,a->size,a->before,&initial[i]);if(!r.status)r.status=absent(backup);}
  else if(req.mode==2) {
   r.status=verify(actual,after_sizes[i],a->after,0);
   if(r.status) {r.status=verify(actual,a->size,a->before,0);restore_needed[i]=0;}
   else restore_needed[i]=1;
   if(!r.status) {i64 missing=absent(backup);old_present[i]=missing!=0;
    if(missing!=0)r.status=verify(backup,a->size,a->before,0);}
  } else {r.status=verify(actual,after_sizes[i],a->after,0);
   if(!r.status) {i64 missing=absent(backup);old_present[i]=missing!=0;
    if(missing!=0)r.status=verify(backup,a->size,a->before,0);}}
  if(r.status)return;
 }
 r.phase=2;if(!req.mode){r.phase=9;return;}
 mounted_rw=1;r.remount=remount(0);if(r.remount){r.status=r.remount;return;}
 if(req.mode==1) {
  r.phase=3;for(u32 i=0;i<asset_count;i++){r.status=stage_one(i);if(r.status)return;}
  r.phase=4;for(u32 i=0;i<asset_count;i++){paths(i);
   r.status=verify(actual,assets[i].size,assets[i].before,0);if(r.status)return;
   r.status=sc(37,-100,(i64)actual,-100,(i64)backup,0,0);if(r.status)return;backup_created[i]=1;r.linked++;}
  r.status=sync_dir();if(r.status)return;
  r.phase=5;for(u32 i=0;i<asset_count;i++){paths(i);r.status=rename_path(temp,actual);if(r.status)return;
   committed[i]=1;temp_created[i]=0;r.committed++;}
  for(u32 i=0;i<asset_count;i++){paths(i);r.status=verify(actual,after_sizes[i],assets[i].after,0);if(r.status)return;}
 } else if(req.mode==2) {
  r.phase=3;for(u32 i=0;i<asset_count;i++)if(restore_needed[i]&&!old_present[i]) {
   r.status=recreate_original(i);if(r.status)return;
  }
  r.status=sync_dir();if(r.status)return;
  r.phase=6;for(u32 i=0;i<asset_count;i++){if(!restore_needed[i])continue;paths(i);r.status=rename_path(backup,actual);if(r.status)return;r.restored++;}
  for(u32 i=0;i<asset_count;i++){paths(i);r.status=verify(actual,assets[i].size,assets[i].before,0);if(r.status)return;}
  for(u32 i=0;i<asset_count;i++)if(!restore_needed[i]&&old_present[i]){paths(i);r.status=unlink_path(backup);if(r.status)return;r.removed_backups++;}
 } else {
  r.phase=7;for(u32 i=0;i<asset_count;i++){paths(i);if(!absent(backup))continue;
   r.status=unlink_path(backup);if(r.status)return;r.removed_backups++;}
 }
 r.status=sync_dir();if(!r.status)r.phase=9;
}
__attribute__((visibility("default"))) void _init(void) {
 for(u32 i=0;i<8;i++)r.magic[i]=((const u8*)"A7NMR001")[i];r.version=1;
 r.euid=sc(175,0,0,0,0,0,0);r.pid=sc(172,0,0,0,0,0,0);
 r.plugin_unlink=unlink_path("/tmp/jiritsu/libJit.so");
 if(r.plugin_unlink)r.status=r.plugin_unlink;else work();
 if(r.status&&req.mode==1&&mounted_rw)r.rollback=rollback_install();
 if(r.status&&req.mode==1&&mounted_rw)for(u32 i=0;i<asset_count;i++) {paths(i);
  if(temp_created[i]) {i64 v=unlink_path(temp);if(v&&!r.rollback)r.rollback=v;}
  if(!r.rollback&&backup_created[i]) {i64 v=unlink_path(backup);if(v&&!r.rollback)r.rollback=v;}
 }
 if(r.status&&req.mode==2&&!r.restored&&mounted_rw)for(u32 i=0;i<asset_count;i++)if(backup_created[i]) {
  paths(i);i64 v=unlink_path(backup);if(v&&!r.rollback)r.rollback=v;
 }
 if(r.status&&(req.mode==1||req.mode==2)&&mounted_rw) {
  i64 v=sync_dir();if(v&&!r.rollback)r.rollback=v;
 }
 if(mounted_rw){r.readonly=remount(1);if(!r.status)r.status=r.readonly;}
 else r.readonly=mount_state(1);
 i64 out=op("/tmp/jiritsu/a7c2.names.result",0x241,0644);
 if(out>=0){write_exact(out,(const u8*)&r,sizeof(r));sc(82,out,0,0,0,0,0);cl(&out);}
}
