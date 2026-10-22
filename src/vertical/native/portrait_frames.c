/* Small data-only portrait frame transaction. No code hooks or full-bank copy. */
#define _init probe_init
#include "probe.c"
#undef _init
#include PATCH_MANIFEST

struct PfStat {u64 dev,ino;u32 mode,nlink,uid,gid;u64 rdev,pad1;i64 size;u32 blksize,pad2;u64 blocks,rest[7];};
struct PfResult {u8 magic[8];u32 version,mode,phase,file,window,completed;i64 status,readonly;u64 bytes_written;u32 writes,cow_ranges;};
_Static_assert(sizeof(struct PfStat)==128,"stat ABI");
_Static_assert(sizeof(struct PfResult)==64,"portrait report ABI");
static struct PfResult result;
static i64 handles[3]={-1,-1,-1};
static u8 io_buf[4096],memory_buf[4096],verify_buf[4096];

static int pf_same(const u8*a,const u8*b,u32 n){for(u32 i=0;i<n;i++)if(a[i]!=b[i])return 0;return 1;}
static u32 pf_len(const char*s){u32 n=0;while(s[n])n++;return n;}
static i64 pf_read(i64 fd,u8*out,u32 size,u64 offset) {
 u32 at=0,retries=0;
 while(at<size){i64 n=sc(67,fd,(i64)(out+at),size-at,offset+at,0,0);
  if(n==-4&&retries++<3)continue;if(n<0)return n;if(!n||(u64)n>size-at)return -5;at+=(u32)n;}
 return 0;
}
static i64 pf_write(i64 fd,const u8*in,u32 size,u64 offset) {
 u32 at=0,retries=0;
 while(at<size){i64 n=sc(68,fd,(i64)(in+at),size-at,offset+at,0,0);
  if(n==-4&&retries++<3)continue;if(n<0)return n;if(!n||(u64)n>size-at)return -5;
  at+=(u32)n;result.bytes_written+=(u64)n;}
 return 0;
}
static i64 pf_size(i64 fd,u64*out){struct PfStat st;i64 n=sc(80,fd,(i64)&st,0,0,0,0);
 if(n)return n;if((st.mode&0170000)!=0100000||st.size<0)return -22;*out=(u64)st.size;return 0;}
static i64 pf_mount(void) {
 i64 n=read_all("/proc/mounts",mounts,sizeof(mounts));if(n<0)return n;
 const u8 prefix[]="/dev/nflasha15 /usr ext2 ";u32 count=0;int state=-22;
 for(u32 i=0;i+sizeof(prefix)+2<=(u32)n;i++)if((!i||mounts[i-1]=='\n')&&pf_same(mounts+i,prefix,sizeof(prefix)-1)) {
  u32 at=i+sizeof(prefix)-1;count++;
  if(mounts[at]=='r'&&mounts[at+2]==',')state=mounts[at+1]=='o'?0:mounts[at+1]=='w'?1:-22;
 }
 return count==1?state:-22;
}
static i64 pf_remount(int ro){i64 n=sc(40,0,(i64)"/usr",0,0xc30UL+(ro?1:0),0,0);if(n)return n;
 n=pf_mount();return n<0?n:(n==(ro?0:1)?0:-30);}
static i64 pf_window(i64 fd,const struct PfWindow*w,int target) {
 if(!w->size||w->size>sizeof(io_buf))return -22;
 i64 n=pf_read(fd,io_buf,w->size,w->at);if(n)return n;
 for(u32 j=0;j<w->size;j++)if(io_buf[j]!=w->old[j]&&io_buf[j]!=w->value[j]&&(!w->previous||io_buf[j]!=w->previous[j]))return -84;
 if(!target)return 0;
 const u8*value=result.mode>=2?w->old:w->value;
 if(pf_same(io_buf,value,w->size))return 0;
 n=pf_write(fd,value,w->size,w->at);if(n)return n;
 n=sc(82,fd,0,0,0,0,0);if(n)return n;
 n=pf_read(fd,io_buf,w->size,w->at);if(n)return n;
 if(!pf_same(io_buf,value,w->size))return -84;result.writes++;return 0;
}
static i64 pf_tail(i64 fd,const struct PfFile*f,u64 size) {
 if(size<f->before_size||size>f->after_size||f->after_size-f->before_size!=f->tail_size)return -22;
 u64 remaining=size-f->before_size,at=0;
 while(at<remaining){u32 amount=remaining-at>sizeof(io_buf)?sizeof(io_buf):(u32)(remaining-at);
  i64 n=pf_read(fd,io_buf,amount,f->before_size+at);if(n)return n;
  if(!pf_same(io_buf,f->tail+at,amount))return -84;at+=amount;}
 return 0;
}
/* Freeze affected private mapping pages by writing back their exact current
 * bytes. Disk edits then cannot replace those pages in the running UI. No
 * functional RAM value changes. Shared mappings are not modified. */
static i64 pf_freeze(void) {
 i64 mem=op("/proc/self/mem",2);if(mem<0)return mem;i64 error=0;
 u32 ap_seen=0;
 for(u32 file=0;file<pf_count&&!error;file++) {
  const struct PfFile*f=&pf_files[file];u32 length=pf_len(f->path),begin=0;
  for(u32 line=0;line<report.maps_len&&!error;line++)if(maps[line]=='\n') {
   u32 end=line,at=begin;begin=line+1;
   if(end-at<length||!pf_same(maps+end-length,(const u8*)f->path,length))continue;
   u64 start,stop,offset;
   if(!hex(maps,end,&at,&start)||at>=end||maps[at++]!='-'||!hex(maps,end,&at,&stop)||at>=end||maps[at++]!=' '){error=-22;break;}
   if(at+5>=end){error=-22;break;}
   int readable=maps[at]=='r',private_map=maps[at+3]=='p';at+=5;
   if(!hex(maps,end,&at,&offset)||stop<=start){error=-22;break;}
   for(u32 window=0;window<f->count&&!error;window++) {
    const struct PfWindow*w=&f->windows[window];u64 a=w->at>offset?w->at:offset;
    u64 b=w->at+w->size<offset+stop-start?w->at+w->size:offset+stop-start;
    if(a>=b)continue;
    result.file=file;result.window=window;
    /* ELF guard/alignment mappings can be ---p. They are irrelevant unless
     * they actually cover an edited byte; do not reject the whole file. */
    if(!readable){error=-13;break;}
    if(result.mode!=3&&!private_map){error=-95;break;}
    u64 address=start+a-offset;u32 size=(u32)(b-a);
    error=pf_read(mem,memory_buf,size,address);
    if(!error&&result.mode==3){
     if(!pf_same(memory_buf,w->old+(a-w->at),size)){error=-11;break;}
     if(file==pf_count-1&&a==w->at&&b==w->at+w->size)ap_seen|=1U<<window;
     continue;
    }
    if(!error){u64 written=result.bytes_written;error=pf_write(mem,memory_buf,size,address);result.bytes_written=written;}
    if(!error)error=pf_read(mem,verify_buf,size,address);
    if(!error&&!pf_same(memory_buf,verify_buf,size))error=-84;
    if(!error)result.cow_ranges++;
   }
  }
 }
 if(!error&&result.mode==3&&ap_seen!=((1U<<pf_files[pf_count-1].count)-1U))error=-11;
 cl(mem);return error;
}
static i64 pf_apply_file(u32 index) {
 const struct PfFile*f=&pf_files[index];i64 fd=handles[index];u64 size=0;i64 n=pf_size(fd,&size);if(n)return n;
 if(result.mode==1&&size<f->after_size) {
  u64 at=size-f->before_size;
  while(at<f->tail_size){u32 amount=f->tail_size-at>sizeof(io_buf)?sizeof(io_buf):(u32)(f->tail_size-at);
   n=pf_write(fd,f->tail+at,amount,f->before_size+at);if(n)return n;at+=amount;}
  n=sc(82,fd,0,0,0,0,0);if(n)return n;
  n=pf_tail(fd,f,f->after_size);if(n)return n;
 }
 for(u32 step=0;step<f->count;step++) {
  u32 window=result.mode>=2?f->count-1-step:step;result.window=window;
  n=pf_window(fd,&f->windows[window],1);if(n)return n;
 }
 if(((result.mode==2&&!f->retain_tail)||result.mode==3)&&size!=f->before_size) {
  n=sc(46,fd,f->before_size,0,0,0,0);if(n)return n;
  n=sc(82,fd,0,0,0,0,0);if(n)return n;
 }
 return 0;
}
__attribute__((visibility("default"))) void _init(void) {
 probe_init();const u8 magic[8]={'A','7','P','F','L','0','0','1'};
 for(u32 i=0;i<8;i++)result.magic[i]=magic[i];result.version=1;result.mode=0xffffffffU;result.status=report.status;
 if(!result.status&&(report.index!=16||report.euid!=0))result.status=-22;
 if(!result.status){u8 request[16];i64 fd=op("/tmp/jiritsu/portrait.request",0);
  if(fd<0)result.status=fd;else{result.status=pf_read(fd,request,16,0);cl(fd);
   if(!result.status){result.mode=*(u32*)(request+8);if(!pf_same(request,magic,8)||result.mode>3||*(u32*)(request+12))result.status=-22;}}}
 if(!result.status){i64 state=pf_mount();if(state<0)result.status=state;}
 result.phase=1;
 for(u32 i=0;i<pf_count&&!result.status;i++) {
  result.file=i;handles[i]=op(pf_files[i].path,0x20000);
  if(handles[i]<0){result.status=handles[i];break;}
  u64 size=0;result.status=pf_size(handles[i],&size);
  if(!result.status)result.status=pf_tail(handles[i],&pf_files[i],size);
  for(u32 w=0;w<pf_files[i].count&&!result.status;w++){
   result.window=w;result.status=pf_window(handles[i],&pf_files[i].windows[w],0);
   if(!result.status&&result.mode==3&&!pf_same(io_buf,pf_files[i].windows[w].old,pf_files[i].windows[w].size))result.status=-11;
  }
 }
 if(!result.status&&result.mode) {
  result.phase=2;result.status=pf_freeze();
  if(!result.status){result.phase=3;result.status=pf_remount(0);}
  if(!result.status)for(u32 i=0;i<pf_count&&!result.status;i++) {
   cl(handles[i]);handles[i]=op(pf_files[i].path,0x20002);if(handles[i]<0)result.status=handles[i];
  }
  if(!result.status)result.phase=4;
  for(u32 step=0;step<pf_count&&!result.status;step++) {
   u32 i=result.mode>=2?pf_count-1-step:step;result.file=i;
   result.status=pf_apply_file(i);if(!result.status)result.completed++;
  }
  if(!result.status)result.phase=5;
  for(u32 i=0;i<pf_count;i++){cl(handles[i]);handles[i]=-1;}
  result.readonly=pf_remount(1);
  if(!result.status&&result.readonly)result.status=result.readonly;
 }
 else if(!result.status){i64 state=pf_mount();result.readonly=state==0?0:state==1?-16:state;}
 for(u32 i=0;i<pf_count;i++)cl(handles[i]);
 i64 out=op("/tmp/jiritsu/portrait.result",0x241);
 if(out>=0){write_all(out,&result,sizeof(result));sc(82,out,0,0,0,0,0);cl(out);}
}
