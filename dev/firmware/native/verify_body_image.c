/* Original createBodyImage with native work-ring input. Only the exact bodyimg
 * path and its directory are redirected into a new host workspace. No mounts
 * or device writes; output is independently compared with the FDAT slice. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <pthread.h>
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>


static const char *output_path;
static int output_fd=-1;
static unsigned write_attempts,unknown_io,opens,closes;
static uint64_t written_bytes;
static int mapped_directory(const char*path,char*out,size_t capacity) {
    if(strcmp(path,"/tmp_updater/")&&strcmp(path,"/tmp_updater/updater/")&&strcmp(path,"/tmp_updater/updater"))return 0;
    int n=snprintf(out,capacity,"%s",output_path);if(n<0||(size_t)n>=capacity)return 0;
    char*slash=strrchr(out,'/');if(!slash)return 0;*slash=0;
    size_t used=strlen(out);n=snprintf(out+used,capacity-used,"/sandbox-tmp%s",path+12);
    return n>=0&&(size_t)n<capacity-used;
}
int __xstat(int version,const char*path,struct stat*out) {
    (void)version;char mapped[2048];
    if(mapped_directory(path,mapped,sizeof(mapped)))return syscall(SYS_newfstatat,AT_FDCWD,mapped,out,0);
    if(!strcmp(path,"/"))return syscall(SYS_newfstatat,AT_FDCWD,path,out,0);
    fprintf(stderr,"BLOCKED_STAT %s\n",path);++unknown_io;errno=EACCES;return -1;
}
int open(const char *path,int flags,...) {
    if(!strcmp(path,"/tmp_updater/updater/bodyimg") && flags==0x241 && !opens) {
        ++opens;output_fd=syscall(SYS_openat,AT_FDCWD,output_path,O_WRONLY|O_CREAT|O_EXCL,0600);return output_fd;
    }
    fprintf(stderr,"BLOCKED_OPEN path=%s flags=%x\n",path,flags);++unknown_io;errno=EACCES;return -1;
}
int mkdir(const char *path,mode_t mode) {
    (void)mode;
    /* DirectoryHandler stats and creates a real isolated directory tree. */
    if(!strcmp(path,"/tmp_updater/")||!strcmp(path,"/tmp_updater/updater/")||!strcmp(path,"/tmp_updater/updater")) {
        char mapped[2048];if(!mapped_directory(path,mapped,sizeof(mapped)))return -1;
        return syscall(SYS_mkdirat,AT_FDCWD,mapped,0700);
    }
    fprintf(stderr,"BLOCKED_MKDIR path=%s\n",path);++unknown_io;errno=EACCES;return -1;
}
ssize_t write(int fd,const void*buffer,size_t length) {
    if(fd==1||fd==2)return syscall(SYS_write,fd,buffer,length);
    if(fd!=output_fd||fd<0){++write_attempts;errno=EROFS;return -1;}
    ssize_t n=syscall(SYS_write,fd,buffer,length);if(n>0)written_bytes+=n;return n;
}
int close(int fd) {
    if(fd==output_fd&&fd>=0){++closes;output_fd=-1;}
    return syscall(SYS_close,fd);
}
int mount(const char*a,const char*b,const char*c,unsigned long d,const void*e) {
    (void)a;(void)b;(void)c;(void)d;(void)e;++unknown_io;errno=EPERM;return -1;
}
int unlink(const char*path){fprintf(stderr,"BLOCKED_UNLINK %s\n",path);++write_attempts;errno=EROFS;return -1;}
int remove(const char*path){(void)path;++write_attempts;errno=EROFS;return -1;}
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


extern int c2_exec_pipeline(void*,void*);
typedef void(*init_fn)(void*);
typedef uint64_t(*write_fn)(void*,const void*,uint64_t,int);
struct producer {void*ring;write_fn write;const void*data;uint64_t length,result;};
static void feed_data(void*p) {
    struct producer*producer=p;producer->result=producer->write(producer->ring,producer->data,producer->length,1);
}
static void*feed(void*p) {
    if(c2_exec_pipeline((void*)feed_data,p))_exit(75);
    return NULL;
}
static uint32_t le32(const unsigned char*p){return p[0]|p[1]<<8|p[2]<<16|(uint32_t)p[3]<<24;}
int main(int argc,char**argv) {
    if(argc!=5)return 64;setbuf(stdout,NULL);setbuf(stderr,NULL);output_path=argv[4];
    int fd=syscall(SYS_openat,AT_FDCWD,argv[3],O_RDONLY,0);struct stat st;
    if(fd<0||fstat(fd,&st)||st.st_size<512)return 65;
    unsigned char*data=mmap(NULL,st.st_size,PROT_READ,MAP_PRIVATE,fd,0);if(data==MAP_FAILED)return 66;
    uint64_t prefix=le32(data+0x30);if(prefix<512||prefix>(uint64_t)st.st_size)return 67;
    void*talk=dlopen(argv[1],RTLD_LAZY|RTLD_GLOBAL);void*sd=dlopen(argv[2],RTLD_LAZY|RTLD_GLOBAL);
    if(!talk||!sd){fprintf(stderr,"DLOPEN=%s\n",dlerror());return 68;}
    typedef void(*ctor_fn)(void*,int,int);
    typedef void*(*get_fn)(void*);
    typedef void(*module_init_fn)(void*,void*,void*,void*);
    typedef void(*set_fn)(void*,const void*,uint64_t);
    typedef int(*check_fn)(void*);
    typedef uint64_t(*read_fn)(void*,void*,uint64_t);
    init_fn common_ctor=dlsym(sd,"_ZN7Updater19CommonBufferManagerC1Ev");
    init_fn common_init=dlsym(sd,"_ZN7Updater19CommonBufferManager10InitializeEv");
    init_fn common_dtor=dlsym(sd,"_ZN7Updater19CommonBufferManagerD1Ev");
    get_fn get_work=dlsym(sd,"_ZN7Updater19CommonBufferManager13GetWorkBufferEv");
    ctor_fn body_ctor=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModuleC1ENS_19UPDATER_ACTION_MODEEb");
    init_fn body_dtor=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModuleD1Ev");
    init_fn run=dlsym(sd,"_ZN7Updater10BaseModule12ThreadStatus3RunEv");
    init_fn stop=dlsym(sd,"_ZN7Updater10RingBuffer4StopEv");
    module_init_fn module_init=dlsym(sd,"_ZN7Updater10BaseModule10InitializeEPNS_15BufferContainerEPS0_PNS_17CallbackInterfaceE");
    write_fn ring_write=dlsym(sd,"_ZN7Updater10RingBuffer9WriteDataEPKhmb");
    read_fn ring_read=dlsym(sd,"_ZN7Updater10RingBuffer8ReadDataEPhm");
    set_fn set_header=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModule14FirmwareHeader9SetHeaderEPKhm");
    check_fn check=dlsym(sd,"_ZNK7Updater20BaseBodyLoaderModule14FirmwareHeader5CheckEv");
    void*execute=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModule15createBodyImageEv");
    if(!common_ctor||!common_init||!common_dtor||!get_work||!body_ctor||!body_dtor||!run||!stop||!module_init||!ring_write||!ring_read||!set_header||!check||!execute)return 69;
    unsigned char common[0x40] __attribute__((aligned(16)))={0};common_ctor(common);
    if(c2_exec_pipeline(common_init,common))return 70;
    void*buffer=get_work(common);if(!buffer)return 71;
    unsigned char body[0x180] __attribute__((aligned(16)))={0};body_ctor(body,3,1);
    module_init(body,buffer,NULL,NULL);void*ring=*(void**)(body+0x48);
    set_header(body+0xc0,data,512);if(!check(body+0xc0))return 76;run(body+0x10);
    struct producer producer={ring,ring_write,data,prefix,0};pthread_t thread;
    if(pthread_create(&thread,NULL,feed,&producer))return 72;
    if(ring_read(ring,NULL,512)!=512)return 73;
    int exception=c2_exec_pipeline(execute,body);
    if(exception)stop(ring);if(pthread_join(thread,NULL))return 74;
    uint64_t remaining=*(uint64_t*)((unsigned char*)ring+0x28);
    body_dtor(body);common_dtor(common);munmap(data,st.st_size);close(fd);
    printf("C2_BODY_IMAGE_RESULT exception=%d prefix=%llu fed=%llu written=%llu remaining=%llu opens=%u closes=%u unknown=%u unexpected_writes=%u\n",
           exception,(unsigned long long)prefix,(unsigned long long)producer.result,(unsigned long long)written_bytes,(unsigned long long)remaining,opens,closes,unknown_io,write_attempts);
    return exception||remaining||producer.result!=prefix||opens!=1||closes!=1||unknown_io||write_attempts;
}
