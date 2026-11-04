/* Offline C2 updater validation: native buffer/decoder control, software AES
 * service fixture, and native output buffering with a read-only hash consumer.
 * Connected original header and image extraction stages; exact local file
 * redirection only. No device access or device writer.
 * Original firmware libraries and private signing material are not included.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <link.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static const char *owner_public,*body_image_path,*version_fixture;
static int connected_mode;
static int body_fd=-1;
static uint64_t body_bytes;
static unsigned body_opens,body_closes,body_callbacks,body_execution,mounts_blocked,metadata_reads,metadata_unknown;
static unsigned char callback_info[24];
static uint64_t fs_writes,key_redirects,rsa_calls,crypto_allocs,crypto_inits,crypto_updates,crypto_finals;
static uint64_t unexpected_requests,output_reads,output_bytes,output_ends,source_pos,input_bytes;
static const unsigned char *input_data;
static void *crypto;
static unsigned char slot8[32];static size_t slot8_size;
static unsigned char digest_context[256] __attribute__((aligned(16)));
typedef int (*sha_update_fn)(void*,const void*,size_t);
static sha_update_fn sha_update;
struct aes_context { unsigned char key[512] __attribute__((aligned(16)));unsigned char iv[16]; };
static struct aes_context *active_context;


static int mapped_directory(const char*path,char*out,size_t capacity) {
    if(!connected_mode)return 0;
    if(strcmp(path,"/tmp_updater/")&&strcmp(path,"/tmp_updater/updater/")&&strcmp(path,"/tmp_updater/updater"))return 0;
    int n=snprintf(out,capacity,"%s",body_image_path);if(n<0||(size_t)n>=capacity)return 0;
    char*slash=strrchr(out,'/');if(!slash)return 0;*slash=0;
    size_t used=strlen(out);n=snprintf(out+used,capacity-used,"/sandbox-tmp%s",path+12);
    return n>=0&&(size_t)n<capacity-used;
}
int __xstat(int version,const char*path,struct stat*out) {
    (void)version;char mapped[2048];
    if(mapped_directory(path,mapped,sizeof(mapped)))return syscall(SYS_newfstatat,AT_FDCWD,mapped,out,0);
    if(!strcmp(path,"/"))return syscall(SYS_newfstatat,AT_FDCWD,path,out,0);
    if(!strcmp(path,"/ramdsk/UFP")||!strcmp(path,"/ramdsk/dev/mode")||!strcmp(path,"/root/IAMLDUDWRT")||!strcmp(path,"/ramdsk/mode5")) {
        errno=ENOENT;return -1;
    }
    fprintf(stderr,"CONNECTED_UNKNOWN_STAT %s\n",path);++metadata_unknown;errno=EACCES;return -1;
}
int mkdir(const char*path,mode_t mode) {
    (void)mode;char mapped[2048];
    if(mapped_directory(path,mapped,sizeof(mapped)))return syscall(SYS_mkdirat,AT_FDCWD,mapped,0700);
    fprintf(stderr,"CONNECTED_UNKNOWN_MKDIR %s\n",path);++metadata_unknown;errno=EACCES;return -1;
}
int mount(const char*a,const char*b,const char*c,unsigned long d,const void*e) {
    (void)a;(void)b;(void)c;(void)d;(void)e;++mounts_blocked;errno=EPERM;return -1;
}
int umount(const char*path){(void)path;++metadata_unknown;errno=EPERM;return -1;}
int remove(const char*path){(void)path;++metadata_unknown;errno=EROFS;return -1;}
int unlink(const char*path){(void)path;++metadata_unknown;errno=EROFS;return -1;}
ssize_t write(int fd,const void*data,size_t length) {
    if(fd==1||fd==2)return syscall(SYS_write,fd,data,length);
    if(fd<0||fd!=body_fd){++metadata_unknown;errno=EROFS;return -1;}
    ssize_t n=syscall(SYS_write,fd,data,length);
    if(n>0){
        if(!sha_update(digest_context,data,(size_t)n)){++unexpected_requests;return -1;}
        body_bytes+=n;output_bytes+=n;++output_reads;
    }
    return n;
}
int close(int fd) {
    if(fd>=0&&fd==body_fd){++body_closes;body_fd=-1;}
    return syscall(SYS_close,fd);
}
static void on_header(void*self,int phase,const void*info,unsigned char*cancel) {
    (void)self;++body_callbacks;
    if(phase!=2||!info||!cancel){++metadata_unknown;return;}
    memcpy(callback_info,info,24);*cancel=1;
    uint32_t*p=(uint32_t*)callback_info;
    printf("C2_CONNECTED_HEADER_CALLBACK phase=%d major=%u minor=%u model=%08x region=%08x cancel=1\n",phase,p[1],p[2],p[3],p[4]);
}
static int reject_body(void*self){(void)self;++body_execution;return 0;}

/* Redirect the immutable verification-key name. Connected mode additionally
   redirects one output image and explicit metadata fixtures; other file writes
   through these diagnostic seams are rejected. */
int open(const char *path,int flags,...) {

    if(connected_mode && !strcmp(path,"/tmp_updater/updater/bodyimg") && flags==0x241 && !body_opens) {
        ++body_opens;body_fd=syscall(SYS_openat,AT_FDCWD,body_image_path,O_WRONLY|O_CREAT|O_EXCL,0600);return body_fd;
    }
    if(connected_mode && !strcmp(path,"/setting/updater/dat4")){++metadata_reads;path=version_fixture;}
    if(connected_mode && !strcmp(path,"/setting/Backup.bak")){errno=ENOENT;return -1;}
    if(flags&(O_WRONLY|O_RDWR|O_CREAT|O_TRUNC)){++metadata_unknown;errno=EROFS;return -1;}

    if(owner_public && !strcmp(path,"/etc/VerificationKey.pem")){path=owner_public;++key_redirects;}
    return (int)syscall(SYS_openat,AT_FDCWD,path,flags,0);
}
FILE *fopen(const char *path,const char *mode) {
    typedef FILE *(*fn)(const char*,const char*);
    fn real=(fn)dlsym(RTLD_NEXT,"fopen");
    if(!real || strpbrk(mode,"wa+")){errno=EROFS;return NULL;}
    if(owner_public && !strcmp(path,"/etc/VerificationKey.pem")){path=owner_public;++key_redirects;}
    return real(path,mode);
}
FILE *fopen64(const char *path,const char *mode){return fopen(path,mode);}
long Fsys_Init(void *a,...){(void)a;return -1;}
long Fsys_Exit(void *a,...){(void)a;return -1;}
long Fsys_FindFirst(void *a,...){(void)a;return -1;}
long Fsys_Mount(void *a,...){(void)a;return -1;}
long Fsys_Unmount(void *a,...){(void)a;return -1;}
long Fsys_Open(void *a,...){(void)a;return -1;}
long Fsys_Close(void *a,...){(void)a;return -1;}
long Fsys_Read(void *a,...){(void)a;return -1;}
long Fsys_Seek(void *a,...){(void)a;return -1;}
long Fsys_Write(void *a,...){(void)a;++fs_writes;errno=EROFS;return -1;}

int osal_valloc_msg_wait(uint32_t qid,void **out,uint32_t size,uint32_t flags) {
    (void)flags;if(qid!=0x025906beU || size<40 || size>1064){++unexpected_requests;return -99;}
    ++crypto_allocs;*out=calloc(1,size);return *out?0:-1;
}
void osal_free_msg(uint32_t qid,void *msg){(void)qid;free(msg);}
int osal_snd_sync_msg(uint32_t qid,void *message) {
    unsigned char *p=message;uint64_t *fields=message;
    if(qid!=0x025906beU){++unexpected_requests;return -99;}
    uint64_t operation=fields[0],context=fields[1],length=fields[4];
    if(operation==2 && context==0 && fields[2]==8 && length==16 && !active_context) {
        typedef int(*setup_fn)(const unsigned char*,int,void*);
        setup_fn setup=(setup_fn)dlsym(crypto,"AES_set_decrypt_key");
        active_context=calloc(1,sizeof(*active_context));if(!active_context||!setup)return -1;
        if(setup(slot8,(int)slot8_size*8,active_context->key))return -1;
        memcpy(active_context->iv,p+40,16);context=(uint64_t)(uintptr_t)active_context;
        memcpy(p+40,&context,8);fields[4]=8;fields[0]=1;++crypto_inits;return 0;
    }
    if(operation==3 && active_context && context==(uint64_t)(uintptr_t)active_context && length && length<=1024 && !(length&15)) {
        typedef void(*cbc_fn)(const unsigned char*,unsigned char*,size_t,const void*,unsigned char*,int);
        cbc_fn cbc=(cbc_fn)dlsym(crypto,"AES_cbc_encrypt");if(!cbc)return -1;
        cbc(p+40,p+40,(size_t)length,active_context->key,active_context->iv,0);
        fields[0]=1;++crypto_updates;return 0;
    }
    if(operation==4 && active_context && context==(uint64_t)(uintptr_t)active_context) {
        free(active_context);active_context=NULL;fields[0]=1;++crypto_finals;return 0;
    }
    fprintf(stderr,"UNEXPECTED_CRYPTO_REQUEST op=%"PRIu64" len=%"PRIu64"\n",operation,length);
    ++unexpected_requests;return -99;
}
int RSA_verify(int type,const unsigned char *m,unsigned n,const unsigned char *signature,unsigned signature_size,void *rsa) {
    typedef int(*fn)(int,const unsigned char*,unsigned,const unsigned char*,unsigned,void*);
    fn verify=(fn)dlsym(crypto,"RSA_verify");if(!verify)return 0;++rsa_calls;
    int result=verify(type,m,n,signature,signature_size,rsa);
    fprintf(stderr,"PIPELINE_RSA_RESULT=%d\n",result);return result;
}

/* Both sides use original BaseModule/RingBuffer. In connected mode the native
   body loader handles the header and creates one host-only image; remaining
   plaintext is read and hashed. No body-library/device writer is executed. */
static void wait_copied(void *self){(void)self;}
extern int c2_exec_pipeline(void*,void*);
typedef uint64_t(*read_ring_fn)(void*,void*,uint64_t);
typedef int(*end_ring_fn)(void*);
typedef void(*stop_ring_fn)(void*);
struct output_consumer {
    void *ring;
    read_ring_fn read;
    end_ring_fn end;
    stop_ring_fn stop;
    int aborted,failed;
    void *body,*header_execute,*create_image;
    uint64_t (*peek)(void*,void**,uint64_t);
};
static void drain_output(void *opaque) {
    struct output_consumer *consumer=opaque;

    unsigned char buffer[131072];
    if(consumer->body) {
        void*header=NULL;
        uint64_t count=consumer->peek(consumer->ring,&header,512);
        if(__atomic_load_n(&consumer->aborted,__ATOMIC_ACQUIRE))return;
        if(count!=512||!header||!sha_update(digest_context,header,512)) {
            consumer->failed=1;consumer->stop(consumer->ring);return;
        }
        output_bytes+=512;++output_reads;
        if(c2_exec_pipeline(consumer->header_execute,consumer->body)
           ||c2_exec_pipeline(consumer->create_image,consumer->body)) {
            if(!__atomic_load_n(&consumer->aborted,__ATOMIC_ACQUIRE))consumer->failed=1;
            consumer->stop(consumer->ring);return;
        }
    }
    while(!__atomic_load_n(&consumer->aborted,__ATOMIC_ACQUIRE)) {
        uint64_t length=consumer->read(consumer->ring,buffer,sizeof(buffer));
        if(length>sizeof(buffer) || (length && !sha_update(digest_context,buffer,(size_t)length))) {
            consumer->failed=1;consumer->stop(consumer->ring);return;
        }
        if(length){output_bytes+=length;++output_reads;}
        if(consumer->end(consumer->ring)){output_ends=1;return;}
        if(!length && !__atomic_load_n(&consumer->aborted,__ATOMIC_ACQUIRE)) {
            consumer->failed=1;consumer->stop(consumer->ring);return;
        }
        if(output_reads && !(output_reads&511))
            fprintf(stderr,"PIPELINE_PROGRESS output=%"PRIu64" reads=%"PRIu64"\n",output_bytes,output_reads);
    }
}
static void *consume_output(void *opaque) {
    struct output_consumer *consumer=opaque;
    if(c2_exec_pipeline((void*)drain_output,consumer)) {
        consumer->failed=1;consumer->stop(consumer->ring);
    }
    return NULL;
}
static uint32_t be32(const unsigned char *p){return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}

int main(int argc,char **argv) {
    if(argc!=7&&argc!=9)return 64;
    connected_mode=argc==9;
    setbuf(stdout,NULL);setbuf(stderr,NULL);owner_public=argv[3];
    if(connected_mode){body_image_path=argv[7];version_fixture=argv[8];}
    FILE *key=fopen(argv[4],"rb");if(!key)return 65;
    slot8_size=fread(slot8,1,sizeof(slot8),key);fclose(key);
    if(slot8_size!=16 && slot8_size!=24 && slot8_size!=32)return 66;
    int fd=open(argv[2],O_RDONLY);struct stat st;if(fd<0||fstat(fd,&st))return 67;
    unsigned char *mapped=mmap(NULL,st.st_size,PROT_READ|PROT_WRITE,MAP_PRIVATE,fd,0);if(mapped==MAP_FAILED)return 68;
    if(memcmp(mapped,"\x89UFU\r\n\x1a\n",8))return 69;
    uint64_t at=8;
    while(at+8<=(uint64_t)st.st_size && memcmp(mapped+at+4,"FDAT",4))at+=8+(uint64_t)be32(mapped+at);
    if(at+8>(uint64_t)st.st_size)return 70;
    input_bytes=be32(mapped+at);input_data=mapped+at+8;
    if(input_bytes<1296 || input_bytes>(uint64_t)st.st_size-at-8 || (input_bytes-272)%1024)return 71;
    if(!strcmp(argv[5],"tamper_cipher"))((unsigned char*)input_data)[1024]^=1;
    char path[2048];snprintf(path,sizeof(path),"%s/libupdatertalk.so",argv[6]);
    void *talk=dlopen(path,RTLD_LAZY|RTLD_GLOBAL);if(!talk){fprintf(stderr,"TALK=%s\n",dlerror());return 72;}
    void *sd=dlopen(argv[1],RTLD_LAZY|RTLD_GLOBAL);if(!sd){fprintf(stderr,"SD=%s\n",dlerror());return 73;}
    crypto=dlopen("libcrypto.so.1.1",RTLD_NOW|RTLD_NOLOAD);if(!crypto)return 74;
    typedef int(*sha_init_fn)(void*);typedef int(*sha_final_fn)(unsigned char*,void*);
    sha_init_fn sha_init=(sha_init_fn)dlsym(crypto,"SHA256_Init");
    sha_update=(sha_update_fn)dlsym(crypto,"SHA256_Update");
    sha_final_fn sha_final=(sha_final_fn)dlsym(crypto,"SHA256_Final");
    if(!sha_init||!sha_update||!sha_final)return 75;sha_init(digest_context);
    typedef void(*init_fn)(void*);
    init_fn ctor=(init_fn)dlsym(sd,"_ZN7Updater15DecryptorModuleC1Ev");
    init_fn run=(init_fn)dlsym(sd,"_ZN7Updater10BaseModule12ThreadStatus3RunEv");
    void *execute=dlsym(sd,"_ZN7Updater17SDDecryptorModule13execWriteFirmEv");
    void **original_vtable=(void**)dlsym(sd,"_ZTVN7Updater17SDDecryptorModuleE");
    if(!ctor||!run||!execute||!original_vtable)return 76;
    unsigned char object[0x600] __attribute__((aligned(16)))={0};ctor(object);
    void *vtable[32]={0};memcpy(vtable,original_vtable+2,0xb8);vtable[0xa0/8]=(void*)wait_copied;*(void***)object=vtable;

    init_fn manager_ctor=(init_fn)dlsym(sd,"_ZN7Updater13BufferManagerC1Ev");
    init_fn manager_init=(init_fn)dlsym(sd,"_ZN7Updater13BufferManager10InitializeEv");
    init_fn manager_dtor=(init_fn)dlsym(sd,"_ZN7Updater13BufferManagerD1Ev");
    typedef void*(*get_buffer_fn)(void*);
    get_buffer_fn get_buffer=(get_buffer_fn)dlsym(sd,"_ZN7Updater13BufferManager17GetFirmwareBufferEv");
    typedef void(*module_init_fn)(void*,void*,void*,void*);
    module_init_fn module_init=(module_init_fn)dlsym(sd,"_ZN7Updater10BaseModule10InitializeEPNS_15BufferContainerEPS0_PNS_17CallbackInterfaceE");
    init_fn module_fini=(init_fn)dlsym(sd,"_ZN7Updater10BaseModule8FinalizeEv");
    typedef uint64_t(*write_ring_fn)(void*,const void*,uint64_t,int);
    write_ring_fn ring_write=(write_ring_fn)dlsym(sd,"_ZN7Updater10RingBuffer9WriteDataEPKhmb");
    read_ring_fn ring_read=(read_ring_fn)dlsym(sd,"_ZN7Updater10RingBuffer8ReadDataEPhm");
    end_ring_fn ring_end=(end_ring_fn)dlsym(sd,"_ZN7Updater10RingBuffer5IsEndEv");
    stop_ring_fn ring_stop=(stop_ring_fn)dlsym(sd,"_ZN7Updater10RingBuffer4StopEv");
    init_fn common_ctor=(init_fn)dlsym(sd,"_ZN7Updater19CommonBufferManagerC1Ev");
    init_fn common_init=(init_fn)dlsym(sd,"_ZN7Updater19CommonBufferManager10InitializeEv");
    init_fn common_dtor=(init_fn)dlsym(sd,"_ZN7Updater19CommonBufferManagerD1Ev");
    get_buffer_fn get_work=(get_buffer_fn)dlsym(sd,"_ZN7Updater19CommonBufferManager13GetWorkBufferEv");
    typedef void(*body_ctor_fn)(void*,int,int);
    init_fn base_ctor=(init_fn)dlsym(sd,"_ZN7Updater10BaseModuleC1Ev");
    body_ctor_fn body_ctor=(body_ctor_fn)dlsym(sd,"_ZN7Updater20BaseBodyLoaderModuleC1ENS_19UPDATER_ACTION_MODEEb");
    init_fn base_dtor=(init_fn)dlsym(sd,connected_mode?"_ZN7Updater20BaseBodyLoaderModuleD1Ev":"_ZN7Updater10BaseModuleD1Ev");
    void *header_execute=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModule7executeEv");
    void *create_image=dlsym(sd,"_ZN7Updater20BaseBodyLoaderModule15createBodyImageEv");
    void **body_vtable=dlsym(sd,"_ZTVN7Updater27SDFileInputBodyLoaderModuleE");
    uint64_t (*peek)(void*,void**,uint64_t)=dlsym(sd,"_ZN7Updater10RingBuffer19ReadDataWithoutCopyEPPhm");
    if(connected_mode&&(!body_ctor||!header_execute||!create_image||!body_vtable||!peek))return 86;
    if(!manager_ctor||!manager_init||!manager_dtor||!get_buffer||!module_init||!module_fini||!ring_write
       ||!ring_read||!ring_end||!ring_stop||!common_ctor||!common_init||!common_dtor||!get_work||!base_ctor||!base_dtor)return 77;
    unsigned char manager[0x40] __attribute__((aligned(16)))={0};manager_ctor(manager);
    fprintf(stderr,"PIPELINE_NATIVE_BUFFER_INITIALIZING\n");
    if(c2_exec_pipeline((void*)manager_init,manager))return 78;
    void *firmware_buffer=get_buffer(manager);if(!firmware_buffer)return 79;
    uint64_t native_capacity=*(uint64_t*)((unsigned char*)firmware_buffer+0x20);
    printf("C2_NATIVE_BUFFER_CAPACITY bytes=%"PRIu64" host_vm_allocation=true physical_ram_verified=false\n",native_capacity);
    if(native_capacity<input_bytes){manager_dtor(manager);return 80;}
    unsigned char common[0x40] __attribute__((aligned(16)))={0};common_ctor(common);
    if(c2_exec_pipeline((void*)common_init,common))return 82;
    void *work_buffer=get_work(common);if(!work_buffer)return 83;
    uint64_t output_capacity=*(uint64_t*)((unsigned char*)work_buffer+0x20);
    printf("C2_NATIVE_OUTPUT_CAPACITY bytes=%"PRIu64"\n",output_capacity);
    unsigned char output_object[0x180] __attribute__((aligned(16)))={0};
    void *output_vtable[32]={0};
    void *callback_vtable[3]={NULL,NULL,(void*)on_header};void *callback[1]={callback_vtable};
    if(connected_mode) {
        body_ctor(output_object,3,1);memcpy(output_vtable,body_vtable+2,0xa8);
        output_vtable[0x90/8]=(void*)reject_body;*(void***)output_object=output_vtable;
        module_init(output_object,work_buffer,NULL,callback);run(output_object+0x10);
    } else {base_ctor(output_object);module_init(output_object,work_buffer,NULL,NULL);}
    void *output_ring=*(void**)(output_object+0x48);
    module_init(object,firmware_buffer,output_object,NULL);
    void *source_ring=*(void**)(object+0x48);
    if(ring_write(source_ring,input_data,input_bytes,1)!=input_bytes)return 81;
    *(uint64_t*)(object+0x540)=input_bytes;run(object+0x10);
    struct output_consumer consumer={output_ring,ring_read,ring_end,ring_stop,0,0,connected_mode?output_object:NULL,header_execute,create_image,peek};
    pthread_t thread;if(pthread_create(&thread,NULL,consume_output,&consumer))return 84;

    fprintf(stderr,"PIPELINE_START bytes=%"PRIu64" mode=%s\n",input_bytes,argv[5]);
    int exception=c2_exec_pipeline(execute,object);
    if(exception) {
        __atomic_store_n(&consumer.aborted,1,__ATOMIC_RELEASE);
        ring_stop(output_ring);
    }
    if(pthread_join(thread,NULL))return 85;
    uint64_t remaining_native=*(uint64_t*)((unsigned char*)source_ring+0x28);
    source_pos=input_bytes-remaining_native;
    printf("C2_NATIVE_RING_REMAINDER bytes=%"PRIu64"\n",remaining_native);
    printf("C2_NATIVE_OUTPUT_RESULT reads=%"PRIu64" ends=%"PRIu64" remaining=%"PRIu64" consumer_failed=%d aborted=%d\n",
        output_reads,output_ends,*(uint64_t*)((unsigned char*)output_ring+0x28),consumer.failed,consumer.aborted);

    if(connected_mode)printf("C2_CONNECTED_RESULT callbacks=%u body_execution=%u body_opens=%u body_closes=%u body_bytes=%"PRIu64" mounts_blocked=%u metadata_reads=%u unknown_io=%u\n",
        body_callbacks,body_execution,body_opens,body_closes,body_bytes,mounts_blocked,metadata_reads,metadata_unknown);
    module_fini(object);manager_dtor(manager);
    module_fini(output_object);base_dtor(output_object);common_dtor(common);
    unsigned char digest[32];sha_final(digest,digest_context);
    printf("C2_PIPELINE_RESULT exception=%d input_bytes=%"PRIu64" consumed=%"PRIu64" output_bytes=%"PRIu64" reads=%"PRIu64" ends=%"PRIu64" fs_writes=%"PRIu64" rsa_calls=%"PRIu64" key_redirects=%"PRIu64" crypto_inits=%"PRIu64" crypto_updates=%"PRIu64" crypto_finals=%"PRIu64" unexpected=%"PRIu64" sha256=",
        exception,input_bytes,source_pos,output_bytes,output_reads,output_ends,fs_writes,rsa_calls,key_redirects,crypto_inits,crypto_updates,crypto_finals,unexpected_requests);
    for(unsigned i=0;i<32;i++)printf("%02x",digest[i]);putchar('\n');
    munmap(mapped,st.st_size);close(fd);return exception?1:0;
}
