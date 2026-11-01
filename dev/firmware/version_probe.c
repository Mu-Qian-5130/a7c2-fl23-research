#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

int main(void) {
    void *common=dlopen("libupdatercommon.so",RTLD_LAZY|RTLD_GLOBAL);
    if(!common){fprintf(stderr,"dlopen common: %s\n",dlerror());return 20;}
    void *core=dlopen("libupdatercorecommon.so",RTLD_LAZY|RTLD_GLOBAL);
    if(!core){fprintf(stderr,"dlopen core: %s\n",dlerror());return 20;}
    void (*ctor)(void*,const char*)=dlsym(common,"_ZN7Updater11VersionFileC1EPKc");
    void (*write_value)(void*,unsigned)=dlsym(common,"_ZN7Updater27BaseFirmwareInformationFile10WriteValueEj");
    unsigned (*get_value)(void*)=dlsym(common,"_ZNK7Updater27BaseFirmwareInformationFile8GetValueEv");
    void (*version)(void*,unsigned*,unsigned*)=dlsym(core,"_ZN7Updater15CurrentFirmware10getVersionEPjS1_");
    if(!ctor||!write_value||!get_value||!version)return 21;
    mkdir("/tmp_updater",0700);mkdir("/tmp_updater/updater",0700);
    mkdir("/tmp_updater/updater/current",0700);mkdir("/tmp_updater/updater/current/updater",0700);
    union {unsigned long align; unsigned char bytes[128];} obj;
    memset(&obj,0,sizeof(obj));ctor(&obj,"/tmp_updater/updater/current");
    unsigned values[]={0x0301,0x0200,0x0201};
    for(unsigned i=0;i<3;i++){
        unsigned major=0,minor=0;
        write_value(&obj,values[i]);
        if(get_value(&obj)!=values[i])return 22;
        version(NULL,&major,&minor);
        if(major!=(values[i]>>8)||minor!=(values[i]&255))return 23;
        FILE*f=fopen("/tmp_updater/updater/current/updater/dat4","rb");
        if(!f)return 24;
        unsigned char raw[8];size_t n=fread(raw,1,sizeof(raw),f);fclose(f);
        printf("NATIVE_VERSION=%02x.%02x BYTES=%zu HEX=",major,minor,n);
        for(size_t k=0;k<n;k++)printf("%02x",raw[k]);puts("");
    }
    puts("A7C2_NATIVE_VERSION_ROUNDTRIP_OK");return 0;
}
