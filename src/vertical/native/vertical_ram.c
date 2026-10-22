/* Experimental RAM-only field write. No backup API, ROM or mount writes.
 * This does not prove that the camera itself will never auto-save the field.
 * Always preserve the observed original value and explicitly restore it.
 */
#define _init probe_init
#include "probe.c"
#undef _init
#ifndef DESIRED
#error DESIRED must be zero or one
#endif
struct TrialResult {u8 magic[8];u32 version,model;i64 status;u64 value_rva;u32 before,after,desired,wrote;u8 info[24];};
static struct TrialResult result;
static const u8 expected[40]={32,175,2,144,0,96,19,145,0,136,64,145,0,128,55,145,192,3,95,214,32,175,2,144,0,96,19,145,0,136,64,145,0,160,55,145,192,3,95,214};
__attribute__((visibility("default"))) void _init(void) {
 probe_init();const u8 magic[8]={'A','7','V','T','R','0','0','1'};
 for(u32 i=0;i<8;i++)result.magic[i]=magic[i];
 result.version=1;result.model=report.index;result.status=report.status;
 result.value_rva=0x7e732b8UL;result.desired=DESIRED;
 if(!result.status && report.index!=16)result.status=-22;
 if(!result.status) {
  i64 mem=op("/proc/self/mem",2);
  if(mem<0)result.status=mem;
  else {
   u8 actual[40],info_after[24];
   if(sc(67,mem,(i64)actual,40,report.base+0x286caa0UL,0,0)!=40)result.status=-5;
   for(u32 i=0;i<40 && !result.status;i++)if(actual[i]!=expected[i])result.status=-84;
   if(!result.status && sc(67,mem,(i64)&result.before,4,report.base+result.value_rva,0,0)!=4)result.status=-5;
   result.after=result.before;
   if(!result.status && result.before>1)result.status=-22;
   if(!result.status && sc(67,mem,(i64)result.info,24,report.base+0x7e732c0UL,0,0)!=24)result.status=-5;
   if(!result.status && result.before!=result.desired) {
    i64 n=sc(68,mem,(i64)&result.desired,4,report.base+result.value_rva,0,0);
    result.wrote=(n==4);
    if(n!=4)result.status=n<0?n:-5;
   }
   if(!result.status && sc(67,mem,(i64)&result.after,4,report.base+result.value_rva,0,0)!=4)result.status=-5;
   if(!result.status && result.after!=result.desired)result.status=-5;
   if(!result.status && sc(67,mem,(i64)info_after,24,report.base+0x7e732c0UL,0,0)!=24)result.status=-5;
   for(u32 i=0;i<24 && !result.status;i++)if(info_after[i]!=result.info[i])result.status=-84;
   cl(mem);
  }
 }
 i64 fd=op("/tmp/jiritsu/a7c2.runtime.result",0x241);
 if(fd>=0) {write_all(fd,&result,sizeof(result));sc(82,fd,0,0,0,0,0);cl(fd);}
}
