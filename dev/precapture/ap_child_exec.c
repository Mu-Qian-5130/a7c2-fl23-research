#include "ap_child_exec.h"
#include "ap_linux_aarch64.h"

_Static_assert(sizeof(child_u64)==8,"AArch64 only");
_Static_assert(sizeof(struct child_exec_result)==88,"child execution evidence ABI");

static int descriptor_number(const unsigned char *text,child_u32 size,child_u32 *value){
    child_u64 n=0;
    if(!size||size>10)return 0;
    for(child_u32 i=0;i<size;i++){
        if(text[i]<'0'||text[i]>'9')return 0;
        n=n*10+text[i]-'0';
        if(n>0x7fffffff)return 0;
    }
    *value=(child_u32)n;
    return 1;
}

static void hex8(child_u32 value,char *out){
    const char *digits="0123456789abcdef";
    for(child_u32 i=0;i<8;i++)out[7-i]=digits[(value>>(4*i))&15];
    out[8]=0;
}

static child_i64 close_inherited(child_i64 keep,volatile struct child_exec_result *r,
    struct child_exec_workspace *workspace,child_syscall sc){
    unsigned char *buffer=workspace->directory;
    r->step=CHILD_OPEN_DIRECTORY;
    child_i64 directory=sc(56,-100,(child_i64)"/proc/self/fd",AP_A64_OPEN_DIRECTORY,0,0,0);
    r->directory_descriptor=directory;
    if(directory<0)return directory;
    child_i64 status=-75;
    for(child_u32 attempt=0;attempt<128;attempt++){
        r->step=CHILD_READ_DIRECTORY;r->directory_reads++;
        child_i64 bytes=sc(61,directory,(child_i64)buffer,sizeof(workspace->directory),0,0,0);
        r->enumeration_status=bytes;
        if(bytes<0){status=bytes;break;}
        if((child_u64)bytes>sizeof(workspace->directory)){status=-5;break;}
        if(!bytes){status=0;break;}
        child_u32 at=0;
        while(at<(child_u32)bytes){
            r->step=CHILD_VALIDATE_DIRECTORY;
            if((child_u32)bytes-at<24){status=-74;goto done;}
            child_u32 size=buffer[at+16]|(child_u32)buffer[at+17]<<8;
            if(size<24||(size&7)||size>(child_u32)bytes-at){status=-74;goto done;}
            child_u32 end=0;
            const unsigned char *name=buffer+at+19;
            while(end<size-19&&name[end])end++;
            if(end==size-19){status=-74;goto done;}
            child_u32 fd;
            if(descriptor_number(name,end,&fd)&&fd!=(child_u32)keep&&fd!=(child_u32)directory){
                r->step=CHILD_CLOSE_DESCRIPTOR;
                if(r->closed_fds>=4096){status=-75;goto done;}
                child_i64 closed=sc(57,fd,0,0,0,0,0);
                if(closed){r->failed_descriptor=fd;status=closed<0?closed:-5;goto done;}
                r->closed_fds++;
            }
            at+=size;
        }
    }
done:
    /* Preserve the primary failure step if closing this owned directory also
     * fails. A close failure never gets retried or converted into success.
     */
    r->directory_close_status=sc(57,directory,0,0,0,0,0);
    if(!status&&r->directory_close_status){
        r->step=CHILD_CLOSE_DIRECTORY;
        status=r->directory_close_status<0?r->directory_close_status:-5;
    }
    return status;
}

child_i64 precapture_child_exec_once(child_i64 executable_fd,child_u32 nonce,
    const char *image_name,volatile struct child_exec_result *r,struct child_exec_workspace *workspace,child_syscall sc){
    if(executable_fd<0||executable_fd>0x7fffffff||!nonce||!image_name||!r||!workspace||!sc)return -22;
    child_u64 rb=(child_u64)r,re=rb+sizeof(*r),wb=(child_u64)workspace,we=wb+sizeof(*workspace);
    if(re<=rb||we<=wb||(rb<we&&wb<re))return -22;
    const volatile unsigned char *raw=(const volatile unsigned char *)r;
    for(child_u32 i=0;i<sizeof(*r);i++)if(raw[i])return -16;
    r->magic=0x58454843u;r->version=1;r->consumed=1;r->nonce=nonce;
    r->directory_descriptor=r->directory_close_status=r->failed_descriptor=-1;
    r->enumeration_status=r->execveat_status=r->execve_status=r->return_status=-1;
    child_i64 status=close_inherited(executable_fd,r,workspace,sc);
    if(status){r->return_status=status;return status;}
    char nonce_text[9],count[9];hex8(nonce,nonce_text);hex8(r->closed_fds,count);
    char *argv[4]={(char *)image_name,nonce_text,count,0};char *env[1]={0};
    r->step=CHILD_EXECVEAT;r->exec_attempts=1;
    status=sc(281,executable_fd,(child_i64)"",(child_i64)argv,(child_i64)env,0x1000,0);
    r->execveat_status=status;
    if(status==-38){
        char path[40],digits[10];const char *prefix="/proc/self/fd/";
        child_u32 at=0,n=0,value=(child_u32)executable_fd;
        while(prefix[at]){path[at]=prefix[at];at++;}
        do{digits[n++]='0'+value%10;value/=10;}while(value);
        while(n)path[at++]=digits[--n];path[at]=0;
        r->step=CHILD_EXECVE_FALLBACK;r->exec_attempts=2;
        status=sc(221,(child_i64)path,(child_i64)argv,(child_i64)env,0,0,0);
        r->execve_status=status;
    }
    /* Successful exec must never return. Reject an impossible nonnegative
     * result rather than marking the selftest successful or returning to AP.
     */
    r->return_status=status<0?status:-5;
    return r->return_status;
}
