/* Offline original body-loader header/callback probe. No body writer.
 * Metadata fixtures and blocked filesystem seams are explicit diagnostics. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static const char *version_fixture;
static unsigned callbacks,body_calls,mount_attempts,write_attempts,version_reads,unknown_io;
static unsigned char callback_info[24];
int open(const char *path,int flags,...) {
    if(flags&(O_WRONLY|O_RDWR|O_CREAT|O_TRUNC)){++write_attempts;errno=EROFS;return -1;}
    if(!strcmp(path,"/setting/updater/dat4")){++version_reads;return syscall(SYS_openat,AT_FDCWD,version_fixture,flags,0);}
    if(!strcmp(path,"/setting/Backup.bak")){errno=ENOENT;return -1;}
    fprintf(stderr,"BLOCKED_UNKNOWN_OPEN path=%s\n",path);++unknown_io;errno=EACCES;return -1;
}
int open64(const char *path,int flags,...){return open(path,flags);}
int mount(const char *a,const char*b,const char*c,unsigned long d,const void*e) {
    (void)a;(void)b;(void)c;(void)d;(void)e;++mount_attempts;errno=EPERM;return -1;
}
int umount(const char *path){(void)path;++unknown_io;errno=EPERM;return -1;}
int remove(const char *path){(void)path;++write_attempts;errno=EROFS;return -1;}
int __xstat(int version,const char *path,struct stat *out) {
    (void)version;(void)out;
    if(!strcmp(path,"/ramdsk/UFP")||!strcmp(path,"/ramdsk/dev/mode")||!strcmp(path,"/root/IAMLDUDWRT")||!strcmp(path,"/ramdsk/mode5")) {
        errno=ENOENT;return -1;
    }
    fprintf(stderr,"BLOCKED_UNKNOWN_STAT path=%s\n",path);++unknown_io;errno=EACCES;return -1;
}
#define BLOCK_FSYS(name) long name(void *a,...){(void)a;++unknown_io;return -1;}
BLOCK_FSYS(Fsys_Init) BLOCK_FSYS(Fsys_Exit) BLOCK_FSYS(Fsys_FindFirst)
BLOCK_FSYS(Fsys_Mount) BLOCK_FSYS(Fsys_Unmount) BLOCK_FSYS(Fsys_Open)
BLOCK_FSYS(Fsys_Close) BLOCK_FSYS(Fsys_Read) BLOCK_FSYS(Fsys_Seek)
long Fsys_Write(void*a,...){(void)a;++write_attempts;return -1;}
int osal_valloc_msg_wait(uint32_t a,void**b,uint32_t c,uint32_t d) {
    (void)a;(void)b;(void)c;(void)d;++unknown_io;return -1;
}
int osal_snd_sync_msg(uint32_t a,void*b){(void)a;(void)b;++unknown_io;return -1;}
void osal_free_msg(uint32_t a,void*b){(void)a;(void)b;++unknown_io;}

static void on_header(void*self,int phase,const void*info,unsigned char*cancel) {
    (void)self;++callbacks;
    if(phase!=2||!info||!cancel){++unknown_io;return;}
    memcpy(callback_info,info,sizeof(callback_info));*cancel=1;
    uint32_t *p=(uint32_t*)callback_info;
    printf("C2_BODY_HEADER_CALLBACK phase=%d major=%u minor=%u model=%08x region=%08x cancel=1\n",
           phase,p[1],p[2],p[3],p[4]);
}
static int reject_body(void*self){(void)self;++body_calls;return 0;}
extern int c2_exec_pipeline(void*,void*);
int main(int argc,char**argv) {
    if(argc!=6)return 64;setbuf(stdout,NULL);setbuf(stderr,NULL);version_fixture=argv[4];
    if(strcmp(argv[5],"valid")&&strcmp(argv[5],"bad_crc")&&strcmp(argv[5],"truncated"))return 64;
    /* Explicit command-line input uses a raw read-only descriptor; library open
       calls remain restricted to the two metadata paths above. */
    int fd=syscall(SYS_openat,AT_FDCWD,argv[3],O_RDONLY,0);unsigned char header[512];
    if(fd<0||read(fd,header,sizeof(header))!=sizeof(header))return 65;close(fd);
    uint64_t length=512;if(!strcmp(argv[5],"bad_crc"))header[8]^=1;
    if(!strcmp(argv[5],"truncated"))length=511;
    void*talk=dlopen(argv[1],RTLD_LAZY|RTLD_GLOBAL);
    void*sd=dlopen(argv[2],RTLD_LAZY|RTLD_GLOBAL);
    if(!talk||!sd){fprintf(stderr,"DLOPEN=%s\n",dlerror());return 66;}
    typedef void(*init_fn)(void*);
    typedef void(*ctor_fn)(void*,int,int);
    typedef void*(*get_fn)(void*);
    typedef void(*module_init_fn)(void*,void*,void*,void*);
    typedef uint64_t(*write_fn)(void*,const void*,uint64_t,int);
    init_fn common_ctor=dlsym(sd,"_ZN7Updater19CommonBufferManagerC1Ev");
    init_fn common_init=dlsym(sd,"_ZN7Updater19CommonBufferManager10InitializeEv");
    init_fn common_dtor=dlsym(sd,"_ZN7Updater19CommonBufferManagerD1Ev");
    get_fn get_work=dlsym(sd,"_ZN7Updater19CommonBufferManager13GetWorkBufferEv");
    ctor_fn body_ctor=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModuleC1ENS_19UPDATER_ACTION_MODEEb");
    init_fn body_dtor=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModuleD1Ev");
    init_fn run=dlsym(sd,"_ZN7Updater10BaseModule12ThreadStatus3RunEv");
    module_init_fn module_init=dlsym(sd,"_ZN7Updater10BaseModule10InitializeEPNS_15BufferContainerEPS0_PNS_17CallbackInterfaceE");
    write_fn write=dlsym(sd,"_ZN7Updater10RingBuffer9WriteDataEPKhmb");
    void*execute=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModule7executeEv");
    void**sd_vtable=dlsym(sd,"_ZTVN7Updater27SDFileInputBodyLoaderModuleE");
    if(!common_ctor||!common_init||!common_dtor||!get_work||!body_ctor||!body_dtor||!run||!module_init||!write||!execute||!sd_vtable)return 67;
    unsigned char common[0x40] __attribute__((aligned(16)))={0};common_ctor(common);
    if(c2_exec_pipeline((void*)common_init,common))return 68;
    void*buffer=get_work(common);if(!buffer)return 69;
    /* Base constructor avoids querying a physical current-camera identity.
       The original SD vtable supplies checkFirmware; bodyExecute is a counted
       rejecting tripwire. A real callback requests cancellation before it. */
    /* SD manager constructor passes true for the user filesystem selector. */
    unsigned char body[0x180] __attribute__((aligned(16)))={0};body_ctor(body,3,1);
    void*vtable[32]={0};memcpy(vtable,sd_vtable+2,0xa8);
    vtable[0x90/8]=(void*)reject_body;*(void***)body=vtable;
    void*callback_vtable[3]={NULL,NULL,(void*)on_header};void*callback[1]={callback_vtable};
    module_init(body,buffer,NULL,callback);void*ring=*(void**)(body+0x48);
    if(write(ring,header,length,1)!=length)return 70;run(body+0x10);
    int exception=c2_exec_pipeline(execute,body);
    printf("C2_BODY_LOADER_RESULT mode=%s exception=%d callbacks=%u body_calls=%u mounts_blocked=%u version_reads=%u writes=%u unknown_io=%u remaining=%llu\n",
           argv[5],exception,callbacks,body_calls,mount_attempts,version_reads,write_attempts,unknown_io,
           (unsigned long long)*(uint64_t*)((unsigned char*)ring+0x28));
    body_dtor(body);common_dtor(common);
    int valid=!strcmp(argv[5],"valid");
    return (body_calls||write_attempts||unknown_io||callbacks!=(unsigned)valid||exception!=!valid
            ||mount_attempts!=(unsigned)valid||version_reads!=(unsigned)valid)?1:0;
}
