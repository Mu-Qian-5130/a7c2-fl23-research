/* Fixed RAM-only SSH session worker. No program/settings writes or remounts.
 * Session path, file lengths and digests are compiled by the offline planner.
 * No arbitrary command/path argument crosses the USB request ABI.
 */
typedef unsigned long u64;
typedef long i64;
typedef unsigned int u32;
typedef unsigned char u8;
static i64 sc(i64 no,i64 a,i64 b,i64 c,i64 d,i64 e,i64 f) {
    register i64 x0 __asm__("x0")=a,x1 __asm__("x1")=b,x2 __asm__("x2")=c;
    register i64 x3 __asm__("x3")=d,x4 __asm__("x4")=e,x5 __asm__("x5")=f,x8 __asm__("x8")=no;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5),"r"(x8) : "memory","cc");
    return x0;
}
#include "sha256.h"
struct File {const char *name;u64 size;const u8 *hash;u32 mode;};
#include PATCH_MANIFEST
#ifndef SSH_TMP_ROOT
#define SSH_TMP_ROOT "/tmp_wbshd"
#endif
#ifndef SSH_MAILBOX
#define SSH_MAILBOX "/tmp/jiritsu"
#endif
struct Request {u8 magic[8];u32 mode,index;u64 offset;u32 count,reserved;};
struct Report {u8 magic[8];u32 version,mode;i64 status,pid;u64 progress;};
struct Stat {u64 dev,ino;u32 mode,nlink,uid,gid;u64 rdev,pad1;i64 size;u32 blksize,pad2;u64 blocks,rest[7];};
struct StatFS {i64 type,bsize;u64 blocks,bfree,bavail,files,ffree;u32 fsid[2];i64 namelen,frsize,flags,spare[4];};
static struct Request req;static struct Report result;
static u8 buf[65536];static i64 dirfd=-1;
static const char *proc_paths[]={"/proc/sys/kernel/random/boot_id","/proc/version","/proc/self/mounts","/proc/net/dev","/proc/net/route","/proc/net/fib_trie","/proc/net/tcp"};
static const u32 proc_limits[]={64,1024,8192,2048,4096,32768,16384};
static u32 proc_lengths[7];static u8 proc_data[64576];static u32 proc_total=0;
static int same(const void*a,const void*b,u32 n) {const u8*x=a,*y=b;for(u32 i=0;i<n;i++)if(x[i]!=y[i])return 0;return 1;}
static u32 length(const char*s) {u32 n=0;while(s[n])n++;return n;}
// Linux AArch64 differs from x86: O_DIRECTORY=0x4000, O_NOFOLLOW=0x8000.
static i64 openat(i64 dir,const char*p,i64 flags,u32 mode) {return sc(56,dir,(i64)p,flags|0x8000,mode,0,0);}
static i64 closefd(i64 fd) {return fd<0?0:sc(57,fd,0,0,0,0,0);}
static i64 exact(i64 fd,void*out,u32 count,u64 offset,int write) {
    u32 done=0;while(done<count) {
        i64 n=sc(write?68:67,fd,(i64)((u8*)out+done),count-done,offset+done,0,0);
        if(n==-4)continue;if(n<=0||(u64)n>count-done)return n<0?n:-5;done+=n;
    }return 0;
}
static i64 regular(i64 fd,struct Stat*s) {
    i64 v=sc(80,fd,(i64)s,0,0,0,0);if(v)return v;
    return (s->mode&0170000)==0100000&&s->nlink==1&&!s->uid?0:-22;
}
static i64 file_hash(const struct File*f) {
    i64 fd=openat(dirfd,f->name,0,0);if(fd<0)return fd;
    struct Stat s;i64 v=regular(fd,&s);if(!v&&(s.size!=(i64)f->size||(s.mode&0777)!=f->mode))v=-22;
    SHA256 hash;sha_init(&hash);u64 at=0;
    while(!v&&at<f->size) {u32 n=f->size-at>sizeof(buf)?sizeof(buf):f->size-at;
        v=exact(fd,buf,n,at,0);if(!v){sha_add(&hash,buf,n);at+=n;}}
    u8 digest[32];if(!v){sha_end(&hash,digest);if(!same(digest,f->hash,32))v=-84;}
    closefd(fd);return v;
}
static i64 all_files(void) {for(u32 i=0;i<file_count;i++){i64 v=file_hash(&files[i]);if(v)return v;}return 0;}
static i64 absent(const char*p) {i64 fd=openat(dirfd,p,0,0);if(fd==-2)return 0;if(fd<0)return fd;closefd(fd);return -17;}
static i64 snapshot(void) {
    for(u32 i=0;i<7;i++) {
        i64 fd=openat(-100,proc_paths[i],0,0);if(fd<0)return fd;
        u32 count=0;while(count<proc_limits[i]) {
            i64 n=sc(63,fd,(i64)(proc_data+proc_total+count),proc_limits[i]-count,0,0,0);
            if(n==-4)continue;if(n<0){closefd(fd);return n;}if(!n)break;count+=n;
        }
        if(count==proc_limits[i]){closefd(fd);return -75;}
        closefd(fd);proc_lengths[i]=count;proc_total+=count;
    }result.progress=proc_total;return 0;
}
static i64 pid(void) {
    i64 fd=openat(dirfd,"dropbear.pid",0,0);if(fd<0)return fd;
    struct Stat s;i64 v=regular(fd,&s);if(!v&&(s.size<2||s.size>12))v=-22;
    if(!v)v=exact(fd,buf,s.size,0,0);closefd(fd);if(v)return v;
    i64 value=0;u32 n=0;while(n<(u32)s.size&&buf[n]>='0'&&buf[n]<='9'){value=value*10+buf[n++]-'0';if(value>4194304)return -22;}
    if(n+1!=(u32)s.size||buf[n]!='\n'||value<2)return -22;
    char path[64]="/proc/";u32 at=6;char digits[16];u32 count=0;i64 copy=value;
    do{digits[count++]=48+copy%10;copy/=10;}while(copy);
    while(count)path[at++]=digits[--count];const char*suffix="/exe";for(u32 i=0;suffix[i];i++)path[at++]=suffix[i];path[at]=0;
    i64 size=sc(78,-100,(i64)path,(i64)buf,sizeof(buf),0,0);
    if(size<0)return size;
    if((u64)size!=length(server_path)||!same(buf,server_path,size))return -116;
    // The launcher owns a new process group; never signal a reused foreign PID.
    i64 group=sc(155,value,0,0,0,0,0);if(group!=value)return -116;
    return value;
}
static i64 launch(void) {
    i64 v=all_files();if(v)return v;
    if((v=absent("started"))||(v=absent("dropbear.pid")))return v;
    // A receipt written before clone prevents replay after a lost result.
    i64 marker=openat(dirfd,"launch-intent",0xc1,0600);if(marker<0)return marker;closefd(marker);
    int pipes[2];v=sc(59,(i64)pipes,0x80000,0,0,0,0);if(v)return v;
    i64 child=sc(220,17,0,0,0,0,0);
    if(child<0){closefd(pipes[0]);closefd(pipes[1]);return child;}
    if(!child) {
        closefd(pipes[0]);i64 status=sc(220,17,0,0,0,0,0);
        if(status>0){sc(94,0,0,0,0,0,0);__builtin_unreachable();}
        if(status<0)goto failed;
        status=sc(157,0,0,0,0,0,0);
        if(status<0)goto failed;
        // All descendant I/O is separate from the app's USB/native-worker FDs.
        i64 nullfd=openat(-100,"/dev/null",0,0),logfd=openat(dirfd,"session.log",0xc1,0600);
        if(nullfd<0||logfd<0){status=-5;goto failed;}
        sc(24,nullfd,0,0,0,0,0);sc(24,logfd,1,0,0,0,0);sc(24,logfd,2,0,0,0,0);
        for(int fd=3;fd<65536;fd++)if(fd!=pipes[1])closefd(fd);
        char *argv[]={"/bin/sh",(char*)script_path,(char*)session_path,"start",(char*)bind_ip,0};
        char *env[]={"PATH=/sbin:/bin:/usr/sbin:/usr/bin","HOME=/","LANG=C",0};
        status=sc(221,(i64)"/bin/sh",(i64)argv,(i64)env,0,0,0);
failed:
        sc(64,pipes[1],(i64)&status,sizeof(status),0,0,0);sc(94,127,0,0,0,0,0);__builtin_unreachable();
    }
    closefd(pipes[1]);
    struct {int fd;short events,revents;} pollfd={pipes[0],1,0};i64 timeout[2]={3,0};
    v=sc(73,(i64)&pollfd,1,(i64)timeout,0,0,0);
    if(v>0){i64 status=0,n=sc(63,pipes[0],(i64)&status,sizeof(status),0,0,0);v=n==0?0:n==sizeof(status)?status:-5;}
    else if(!v)v=-110;
    closefd(pipes[0]);int child_status;sc(260,child,(i64)&child_status,0,0,0,0);return v;
}
static i64 work(void) {
    i64 fd=openat(-100,SSH_MAILBOX "/a7c2.install.request",0,0);if(fd<0)return fd;
    i64 v=exact(fd,&req,sizeof(req),0,0);closefd(fd);if(v)return v;
    result.mode=req.mode;
    if(!same(req.magic,"A7SSH001",8)||req.reserved||req.mode>6||req.index>=file_count||req.count>65536)return -22;
    if(sc(175,0,0,0,0,0,0))return -13;
    if(req.mode==6)return snapshot();
    i64 base=openat(-100,SSH_TMP_ROOT,0x4000,0);if(base<0)return base;
    struct StatFS fs;v=sc(44,base,(i64)&fs,0,0,0,0);
    if(!v&&fs.type!=0x01021994)v=-22;
    struct Stat parent;if(!v)v=sc(80,base,(i64)&parent,0,0,0,0);
    if(!v&&(parent.uid||((parent.mode&0022)&&!(parent.mode&01000))))v=-22;
    if(v){closefd(base);return v;}
    if(!req.mode){v=sc(34,base,(i64)session_name,0700,0,0,0);if(v){closefd(base);return v;}}
    dirfd=openat(base,session_name,0x4000,0);closefd(base);if(dirfd<0)return dirfd;
    struct Stat dir;v=sc(80,dirfd,(i64)&dir,0,0,0,0);
    if(v)return v;if((dir.mode&0177777)!=0040700||dir.uid)return -22;
    if(!req.mode)return 0;
    if(req.mode==4||req.mode==5){i64 p=pid();result.pid=p;if(p<0)return p;return req.mode==5?sc(129,-p,15,0,0,0,0):0;}
    if(req.mode==3)return launch();
    if((v=absent("launch-intent")))return v;
    if(req.mode==2)return all_files();
    const struct File*f=&files[req.index];
    if(!req.count||req.offset>f->size||req.count>f->size-req.offset)return -22;
    i64 chunk=openat(-100,SSH_MAILBOX "/resource.chunk",0,0);if(chunk<0)return chunk;
    struct Stat cs;v=regular(chunk,&cs);if(!v&&cs.size!=req.count)v=-22;
    if(!v)v=exact(chunk,buf,req.count,0,0);closefd(chunk);if(v)return v;
    fd=openat(dirfd,f->name,req.offset?1:0xc1,0600);if(fd<0)return fd;
    struct Stat before;v=regular(fd,&before);if(!v&&before.size!=(i64)req.offset)v=-116;
    if(!v)v=exact(fd,buf,req.count,req.offset,1);
    if(!v&&req.offset+req.count==f->size)v=sc(52,fd,f->mode,0,0,0,0);
    if(!v)v=sc(82,fd,0,0,0,0,0);closefd(fd);
    result.progress=req.offset+req.count;return v;
}
__attribute__((visibility("default"))) void _init(void) {
    for(u32 i=0;i<8;i++)result.magic[i]="A7SSR001"[i];result.version=1;
    result.status=sc(35,-100,(i64)SSH_MAILBOX "/libJit.so",0,0,0,0);
    if(!result.status)result.status=work();closefd(dirfd);
    i64 out=openat(-100,SSH_MAILBOX "/a7c2.runtime.result",0x241,0600);
    if(out>=0){exact(out,&result,sizeof(result),0,1);
        if(req.mode==6&&!result.status){exact(out,proc_lengths,sizeof(proc_lengths),sizeof(result),1);exact(out,proc_data,proc_total,sizeof(result)+sizeof(proc_lengths),1);}
        sc(82,out,0,0,0,0,0);closefd(out);}
}
