/* Offline C2 updater validation: native buffer/decoder control, software AES
 * service fixture, and a hash-only output sink. No device access or writer.
 * Original firmware libraries and private signing material are not included.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <link.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static const char *owner_public;
static uint64_t fs_writes,key_redirects,rsa_calls,crypto_allocs,crypto_inits,crypto_updates,crypto_finals;
static uint64_t unexpected_requests,sink_calls,output_bytes,output_ends,source_pos,input_bytes;
static const unsigned char *input_data;
static void *crypto;
static unsigned char slot8[32];static size_t slot8_size;
static unsigned char digest_context[256] __attribute__((aligned(16)));
typedef int (*sha_update_fn)(void*,const void*,size_t);
static sha_update_fn sha_update;
struct aes_context { unsigned char key[512] __attribute__((aligned(16)));unsigned char iv[16]; };
static struct aes_context *active_context;

/* Redirect only the immutable key filename expected by original execWriteFirm.
   Every attempted write through these diagnostic file seams is rejected. */
int open(const char *path,int flags,...) {
    if(flags&(O_WRONLY|O_RDWR|O_CREAT|O_TRUNC)){errno=EROFS;return -1;}
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

/* Native input BufferManager and RingBuffer are instantiated below. */
static void wait_copied(void *self){(void)self;}
static uint64_t hash_sink(void *self,const void *data,uint64_t length,int end) {
    (void)self;if(!length || length>1020 || output_ends){++unexpected_requests;return 0;}
    if(!sha_update(digest_context,data,(size_t)length)){++unexpected_requests;return 0;}
    output_bytes+=length;++sink_calls;if(end)++output_ends;
    if(!(sink_calls&65535))fprintf(stderr,"PIPELINE_PROGRESS input=%"PRIu64" output=%"PRIu64"\n",source_pos,output_bytes);
    return length;
}
extern int c2_exec_pipeline(void*,void*);
static uint32_t be32(const unsigned char *p){return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}

int main(int argc,char **argv) {
    if(argc!=7)return 64;
    setbuf(stdout,NULL);setbuf(stderr,NULL);owner_public=argv[3];
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
    if(!manager_ctor||!manager_init||!manager_dtor||!get_buffer||!module_init||!module_fini||!ring_write)return 77;
    unsigned char manager[0x40] __attribute__((aligned(16)))={0};manager_ctor(manager);
    fprintf(stderr,"PIPELINE_NATIVE_BUFFER_INITIALIZING\n");
    if(c2_exec_pipeline((void*)manager_init,manager))return 78;
    void *firmware_buffer=get_buffer(manager);if(!firmware_buffer)return 79;
    uint64_t native_capacity=*(uint64_t*)((unsigned char*)firmware_buffer+0x20);
    printf("C2_NATIVE_BUFFER_CAPACITY bytes=%"PRIu64" host_vm_allocation=true physical_ram_verified=false\n",native_capacity);
    if(native_capacity<input_bytes){manager_dtor(manager);return 80;}
    void *output_vtable[16]={0};output_vtable[0x30/8]=(void*)hash_sink;void *output_object[1]={output_vtable};
    module_init(object,firmware_buffer,output_object,NULL);
    void *source_ring=*(void**)(object+0x48);
    if(ring_write(source_ring,input_data,input_bytes,1)!=input_bytes)return 81;
    *(uint64_t*)(object+0x540)=input_bytes;run(object+0x10);

    fprintf(stderr,"PIPELINE_START bytes=%"PRIu64" mode=%s\n",input_bytes,argv[5]);
    int exception=c2_exec_pipeline(execute,object);
    uint64_t remaining_native=*(uint64_t*)((unsigned char*)source_ring+0x28);
    source_pos=input_bytes-remaining_native;
    printf("C2_NATIVE_RING_REMAINDER bytes=%"PRIu64"\n",remaining_native);
    module_fini(object);manager_dtor(manager);
    unsigned char digest[32];sha_final(digest,digest_context);
    printf("C2_PIPELINE_RESULT exception=%d input_bytes=%"PRIu64" consumed=%"PRIu64" output_bytes=%"PRIu64" blocks=%"PRIu64" ends=%"PRIu64" fs_writes=%"PRIu64" rsa_calls=%"PRIu64" key_redirects=%"PRIu64" crypto_inits=%"PRIu64" crypto_updates=%"PRIu64" crypto_finals=%"PRIu64" unexpected=%"PRIu64" sha256=",
        exception,input_bytes,source_pos,output_bytes,sink_calls,output_ends,fs_writes,rsa_calls,key_redirects,crypto_inits,crypto_updates,crypto_finals,unexpected_requests);
    for(unsigned i=0;i<32;i++)printf("%02x",digest[i]);putchar('\n');
    munmap(mapped,st.st_size);close(fd);return exception?1:0;
}
