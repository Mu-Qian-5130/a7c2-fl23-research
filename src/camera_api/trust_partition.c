/* Temporary C2 updater partition worker: bounded read, compare, write/readback.
 * No setting, mount, RAM, reboot or other partition changes. Host owns backup.
 */
typedef unsigned long u64;typedef long i64;typedef unsigned int u32;typedef unsigned char u8;
static i64 sc(i64 n,i64 a,i64 b,i64 c,i64 d,i64 e,i64 f){
 register i64 x0 __asm__("x0")=a,x1 __asm__("x1")=b,x2 __asm__("x2")=c,x3 __asm__("x3")=d,x4 __asm__("x4")=e,x5 __asm__("x5")=f,x8 __asm__("x8")=n;
 __asm__ volatile("svc 0":"+r"(x0):"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5),"r"(x8):"memory","cc");return x0;
}
#include PATCH_MANIFEST
#ifndef TRUST_VM
#define TRUST_DEVICE "/dev/nflasha1"
#define TRUST_RESULT "/tmp/jiritsu/a7c2.trust.result"
#define TRUST_CHUNK "/tmp/jiritsu/a7c2.trust.chunk"
#endif
struct Stat {u64 dev,ino;u32 mode,nlink,uid,gid;u64 rdev,pad1;i64 size;u32 blksize,pad2;u64 blocks;u64 rest[7];};
struct Report {u8 magic[8];u32 version,mode,phase,writes;u64 offset,count,capacity,completed; i64 status,euid,close_status,sync_status;};
static struct Report r;static u8 buffer[16384],mounts[16384];
static i64 op(const char*p,i64 flags){return sc(56,-100,(i64)p,flags,0600,0,0);}
static i64 closefd(i64*fd){if(*fd<0)return 0;i64 result=sc(57,*fd,0,0,0,0,0);*fd=-1;return result;}
static int equal(const u8*a,const u8*b,u64 n){for(u64 i=0;i<n;i++)if(a[i]!=b[i])return 0;return 1;}
static i64 read_exact(i64 fd,void*data,u64 n,u64 at){
 u64 done=0;u32 interrupted=0;
 while(done<n){i64 got=sc(67,fd,(i64)((u8*)data+done),n-done,at+done,0,0);
  if(got==-4&&interrupted++<3)continue;if(got<=0||(u64)got>n-done)return got<0?got:-5;done+=got;}
 return 0;
}
static i64 write_exact(i64 fd,const void*data,u64 n,u64 at,int persistent){
 u64 done=0;u32 interrupted=0;
 while(done<n){i64 got=sc(68,fd,(i64)((const u8*)data+done),n-done,at+done,0,0);
  if(got==-4&&interrupted++<3)continue;if(got<=0||(u64)got>n-done)return got<0?got:-5;
  done+=got;if(persistent){r.completed+=got;r.writes++;}}
 return 0;
}
static i64 unmounted(u64 device){
#ifdef TRUST_VM
 return 0;
#else
 i64 fd=op("/proc/self/mountinfo",0);if(fd<0)return fd;u64 count=0;
 while(count<sizeof(mounts)){i64 n=sc(63,fd,(i64)(mounts+count),sizeof(mounts)-count,0,0,0);
  if(n<0){closefd(&fd);return n;}if(!n)break;count+=n;}closefd(&fd);
 if(count==sizeof(mounts))return -75;
 u64 major=((device>>8)&0xfff)|((device>>32)&0xfffff000),minor=(device&0xff)|((device>>12)&0xffffff00);
 for(u64 at=0;at<count;){
  u64 end=at;while(end<count&&mounts[end]!='\n')end++;
  u32 spaces=0;while(at<end&&spaces<2)if(mounts[at++]==' ')spaces++;
  u64 a=0,b=0;while(at<end&&mounts[at]>='0'&&mounts[at]<='9')a=a*10+mounts[at++]-'0';
  if(at<end&&mounts[at++]==':'){while(at<end&&mounts[at]>='0'&&mounts[at]<='9')b=b*10+mounts[at++]-'0';
   if(at<end&&mounts[at]==' '&&a==major&&b==minor)return -16;}
  at=end+1;
 }
 return 0;
#endif
}
static void work(void){
 i64 fd=-1,out=-1;struct Stat st;r.phase=1;
 if(r.euid!=0){r.status=-1;return;}
 if(TRUST_COUNT==0||TRUST_OFFSET%512||TRUST_COUNT%512||TRUST_OFFSET+TRUST_COUNT>25100288UL||
    (TRUST_MODE==0?TRUST_COUNT>1048576:TRUST_COUNT>sizeof(buffer))){r.status=-22;return;}
 fd=op(TRUST_DEVICE,TRUST_MODE==2?2:0);if(fd<0){r.status=fd;return;}
 r.status=sc(80,fd,(i64)&st,0,0,0,0);if(r.status)goto end;
#ifdef TRUST_VM
 if((st.mode&0170000)!=0100000){r.status=-22;goto end;}r.capacity=st.size;
#else
 if((st.mode&0170000)!=0060000){r.status=-15;goto end;}
 r.status=sc(29,fd,0x80081272UL,(i64)&r.capacity,0,0,0);if(r.status)goto end;
#endif
 if(r.capacity!=25100288UL){r.status=-75;goto end;}
 r.status=read_exact(fd,buffer,512,0);if(r.status)goto end;
 if(buffer[11]!=0||buffer[12]!=2||buffer[13]!=32||buffer[16]!=2||!equal(buffer+54,(const u8*)"FAT12",5)){r.status=-84;goto end;}
 if(TRUST_MODE){r.status=unmounted(st.rdev);if(r.status)goto end;}
 r.phase=2;
 if(TRUST_MODE==0){
  out=op(TRUST_CHUNK,0x241);if(out<0){r.status=out;goto end;}
  for(u64 at=0;at<TRUST_COUNT&&!r.status;){u64 n=TRUST_COUNT-at;if(n>sizeof(buffer))n=sizeof(buffer);
   r.status=read_exact(fd,buffer,n,TRUST_OFFSET+at);if(!r.status)r.status=write_exact(out,buffer,n,at,0);at+=n;}
  if(!r.status)r.status=sc(82,out,0,0,0,0,0);if(!r.status)r.completed=TRUST_COUNT;
 }else{
  r.status=read_exact(fd,buffer,TRUST_COUNT,TRUST_OFFSET);if(r.status)goto end;
  if(!equal(buffer,trust_before,TRUST_COUNT)){r.status=-84;goto end;}
  if(TRUST_MODE==2){r.phase=3;r.status=write_exact(fd,trust_after,TRUST_COUNT,TRUST_OFFSET,1);
   r.sync_status=sc(82,fd,0,0,0,0,0);if(!r.status)r.status=r.sync_status;if(r.status)goto end;
   r.phase=4;r.status=read_exact(fd,buffer,TRUST_COUNT,TRUST_OFFSET);
   if(!r.status&&!equal(buffer,trust_after,TRUST_COUNT))r.status=-84;
  }
 }
 if(!r.status)r.phase=9;
end:
 {i64 code=closefd(&out);if(!r.status)r.status=code;}
 r.close_status=closefd(&fd);if(!r.status)r.status=r.close_status;
}
static void run(void){
 const u8 magic[]="A7TRST01";for(u32 i=0;i<8;i++)r.magic[i]=magic[i];
 r.version=1;r.mode=TRUST_MODE;r.offset=TRUST_OFFSET;r.count=TRUST_COUNT;r.euid=sc(175,0,0,0,0,0,0);
#ifndef TRUST_VM
 sc(35,-100,(i64)"/tmp/jiritsu/libJit.so",0,0,0,0);
#endif
 work();i64 fd=op(TRUST_RESULT,0x241);if(fd>=0){write_exact(fd,&r,sizeof(r),0,0);sc(82,fd,0,0,0,0,0);closefd(&fd);}
}
#ifdef TRUST_VM
int main(void){run();return r.status?1:0;}
#else
__attribute__((visibility("default")))void _init(void){run();}
#endif
