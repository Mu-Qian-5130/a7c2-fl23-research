#define _init probe_init
#include "probe.c"
#undef _init
struct VerticalResult {u8 magic[8];u32 version,model;i64 status;u64 value_rva;u32 value,reserved;u8 info[24];};
static struct VerticalResult result;
static const u8 expected[40]={32,175,2,144,0,96,19,145,0,136,64,145,0,128,55,145,192,3,95,214,32,175,2,144,0,96,19,145,0,136,64,145,0,160,55,145,192,3,95,214};
__attribute__((visibility("default"))) void _init(void) {
 probe_init();const u8 magic[8]={'A','7','V','U','I','0','0','1'};
 for(u32 i=0;i<8;i++)result.magic[i]=magic[i];
 result.version=1;result.model=report.index;result.status=report.status;result.value_rva=0x7e732b8UL;
 if(!result.status && report.index!=16)result.status=-22;
 if(!result.status) {
  i64 mem=op("/proc/self/mem",0);
  if(mem<0)result.status=mem;
  else {
   u8 actual[40];
   if(sc(67,mem,(i64)actual,40,report.base+0x286caa0UL,0,0)!=40)result.status=-5;
   for(u32 i=0;i<40 && !result.status;i++)if(actual[i]!=expected[i])result.status=-84;
   if(!result.status && sc(67,mem,(i64)&result.value,4,report.base+result.value_rva,0,0)!=4)result.status=-5;
   if(!result.status && result.value>1)result.status=-22;
   if(!result.status && sc(67,mem,(i64)result.info,24,report.base+0x7e732c0UL,0,0)!=24)result.status=-5;
   cl(mem);
  }
 }
 i64 fd=op("/tmp/jiritsu/a7c2.runtime.result",0x241);
 if(fd>=0) {write_all(fd,&result,sizeof(result));sc(82,fd,0,0,0,0,0);cl(fd);}
}
