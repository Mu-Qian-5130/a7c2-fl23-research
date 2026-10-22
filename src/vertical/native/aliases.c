/* Three fixed portrait-bank aliases to this body's existing image banks.
 * Does not change AP/CP, bank bytes, bank indices, Backup settings or RAM.
 * Modes: 0 readonly inspection, 1 add, 2 remove exact aliases only.
 */
#define _init probe_init
#include "probe.c"
#undef _init
#ifndef VERTICAL_RECOVERY
#define VERTICAL_RECOVERY 0
#endif
struct RsStat {u64 dev,ino;u32 mode,nlink,uid,gid;u64 rdev,pad1;i64 size;u32 blksize,pad2;u64 blocks,rest[7];};
_Static_assert(sizeof(struct RsStat)==128,"stat ABI");
struct RsResult {u8 magic[8];u32 version,mode,phase,count;i64 status,rollback,readonly;u32 source_ok,prior,created,removed,counts[3],reserved;u64 sizes[3];};
_Static_assert(sizeof(struct RsResult)==104,"resource alias ABI");
static struct RsResult r;
static const char *src[3]={"/usr/share/app/image_00_32_IPSX.uxc","/usr/share/app/image_01_32_IPSX.uxc","/usr/share/app/image_02_32_IPSX.uxc"};
static const char *dst[3]={"/usr/share/app/image_00_23_IPSX.uxc","/usr/share/app/image_01_23_IPSX.uxc","/usr/share/app/image_02_23_IPSX.uxc"};
static const char *target[3]={"image_00_32_IPSX.uxc","image_01_32_IPSX.uxc","image_02_32_IPSX.uxc"};
static struct RsStat original[3];
static int rs_same(const u8*a,const u8*b,u32 n){for(u32 i=0;i<n;i++)if(a[i]!=b[i])return 0;return 1;}
static u32 rs_len(const char*s){u32 n=0;while(s[n])n++;return n;}
static i64 rs_mount(int ro) {
 i64 n=read_all("/proc/mounts",mounts,sizeof(mounts));if(n<0)return n;
 const u8 prefix[]="/dev/nflasha15 /usr ext2 ";u32 len=sizeof(prefix)-1,count=0;
 for(u32 i=0;i+len+3<=(u32)n;i++)if((!i||mounts[i-1]=='\n')&&rs_same(mounts+i,prefix,len)) {
  if(mounts[i+len]!='r'||mounts[i+len+1]!=(ro?'o':'w')||mounts[i+len+2]!=',')return -30;count++;
 }
 return count==1?0:-22;
}
static i64 rs_remount(int ro){i64 n=sc(40,0,(i64)"/usr",0,0xc30UL+(ro?1:0),0,0);return n?n:rs_mount(ro);}
static i64 rs_sync(void){i64 fd=op("/usr/share/app",0x10000);if(fd<0)return fd;i64 n=sc(82,fd,0,0,0,0,0);cl(fd);return n;}
static i64 rs_link_state(u32 i) {
 u8 buf[64];i64 n=sc(78,-100,(i64)dst[i],(i64)buf,sizeof(buf),0,0);
 if(n==-2)return 0;
 if(n<0)return n==-22?-17:n;
 return (u32)n==rs_len(target[i])&&rs_same(buf,(const u8*)target[i],(u32)n)?1:-17;
}
static i64 rs_source(u32 i) {
 i64 fd=op(src[i],0x20000);if(fd<0)return fd;
 struct RsStat st;u8 head[16];i64 n=sc(80,fd,(i64)&st,0,0,0,0);
 if(!n&&((st.mode&0170000)!=0100000||st.size<20||st.size>33554432))n=-22;
 if(!n&&sc(67,fd,(i64)head,16,0,0,0)!=16)n=-5;
 cl(fd);if(n)return n;
 const u8 magic[8]={'u','x','d',7,0,0,0,0};u32 desc=*(u32*)(head+12),count=desc&8191;
 if(!rs_same(head,magic,8)||*(unsigned short*)(head+8)!=8||*(unsigned short*)(head+10)!=i||!count||desc!=(count|(((count+1)&~1U)<<12)))return -22;
 original[i]=st;r.counts[i]=count;r.sizes[i]=st.size;r.source_ok|=1U<<i;return 0;
}
static i64 rs_alias(u32 i) {
 if(rs_link_state(i)!=1)return -17;
 i64 fd=op(dst[i],0);if(fd<0)return fd;struct RsStat st;i64 n=sc(80,fd,(i64)&st,0,0,0,0);cl(fd);
 if(!n&&(st.dev!=original[i].dev||st.ino!=original[i].ino||st.size!=original[i].size||st.mode!=original[i].mode))n=-116;return n;
}
static i64 rs_remove(u32 mask) {
 i64 first=0;
 for(u32 i=0;i<3;i++)if(mask&(1U<<i)) {
  i64 n=rs_link_state(i);
  if(n==1){n=sc(35,-100,(i64)dst[i],0,0,0,0);if(!n)r.removed|=1U<<i;}
  else if(n==0)continue;
  if(n&&!first)first=n;
 }
 return first;
}
__attribute__((visibility("default"))) void _init(void) {
 probe_init();const u8 magic[8]={'A','7','V','R','S','0','0','1'};for(u32 i=0;i<8;i++)r.magic[i]=magic[i];
 r.version=1;r.count=3;r.status=report.status;r.mode=0xffffffffU;
 if(!r.status&&report.index!=16)r.status=-22;
 if(!r.status) {
  u8 request[16];i64 fd=op("/tmp/jiritsu/a7c2.names.request",0);
  if(fd<0)r.status=fd;
  else {u8 more;i64 n=sc(67,fd,(i64)request,16,0,0,0),tail=sc(67,fd,(i64)&more,1,16,0,0);cl(fd);
   if(n!=16||tail||!rs_same(request,magic,8)||*(u32*)(request+12))r.status=-22;
   else {r.mode=*(u32*)(request+8);if(r.mode>2)r.status=-22;}
  }
 }
 if(!r.status) {
  r.status=rs_mount(1);
  if(VERTICAL_RECOVERY&&r.mode!=1&&r.status==-30&&!rs_mount(0))r.status=0;
 }
 for(u32 i=0;i<3&&!r.status;i++) {
  r.status=rs_source(i);if(r.status)break;
  i64 state=rs_link_state(i);if(state<0){r.status=state;break;}
  if(state==1)r.prior|=1U<<i;
  if(r.mode==1&&state){r.status=-17;break;}
  if(state==1&&r.mode==0)r.status=rs_alias(i);
 }
 if(!r.status)r.phase=1;
 int completed_busy=0;
 if(!r.status&&r.mode) {
  i64 rw=rs_remount(0);r.phase=2;
  if(rw)r.status=rw;
  if(!r.status&&r.mode==1)for(u32 i=0;i<3&&!r.status;i++) {
   r.status=sc(36,(i64)target[i],-100,(i64)dst[i],0,0,0);
   if(!r.status){r.created|=1U<<i;r.status=rs_alias(i);}
  }
  if(!r.status&&r.mode==2)r.status=rs_remove(r.prior);
  if(!r.status)r.status=rs_sync();
  if(r.status&&r.mode==1){r.rollback=rs_remove(r.created);if(!r.rollback)r.rollback=rs_sync();}
  r.readonly=rs_remount(1);
  completed_busy=VERTICAL_RECOVERY&&r.mode==2&&!r.status&&r.readonly==-16;
  if(!r.status)r.status=r.readonly;
 }
 else {
  r.readonly=rs_mount(1);
  if(VERTICAL_RECOVERY&&r.mode==0&&r.readonly==-30&&!rs_mount(0))r.readonly=-16;
 }
 if(!r.status&&r.mode==1)for(u32 i=0;i<3&&!r.status;i++)r.status=rs_alias(i);
 if((!r.status||completed_busy)&&r.mode==2)for(u32 i=0;i<3;i++)if(rs_link_state(i)!=0){r.status=-17;completed_busy=0;break;}
 if(!r.status||completed_busy)r.phase=r.mode?5:1;
 i64 fd=op("/tmp/jiritsu/a7c2.names.result",0x241);
 if(fd>=0){write_all(fd,&r,sizeof(r));sc(82,fd,0,0,0,0,0);cl(fd);}
}
