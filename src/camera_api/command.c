/* Invocation-only fixed command; stdin contains data, never file offsets. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#include CAMERA_CONFIG

static const char *root="",*error="io";
static const char *mounts[]={"/setting","/cp","/usr"};
static int remounted[3];
static unsigned long mount_flags[3];
static int bad(const char *why){error=why;return -1;}
static void path(char *out,size_t size,const char *suffix){snprintf(out,size,"%s%s",root,suffix);}
static uint32_t get32(const unsigned char *p){return p[0]|p[1]<<8|p[2]<<16|(uint32_t)p[3]<<24;}
static int get16(const unsigned char *p){return (int16_t)(p[0]|p[1]<<8);}
static void put32(unsigned char *p,uint32_t v){for(int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static int transfer(int fd,void *data,size_t size,off_t at,int writing) {
    unsigned char *p=data;
    while(size){ssize_t n=writing?pwrite(fd,p,size,at):pread(fd,p,size,at);if(n<0&&errno==EINTR)continue;if(n<=0)return bad(writing?"write":"read");p+=n;size-=n;at+=n;}return 0;
}
static int replace_bytes(int fd,off_t at,const void *data,size_t size) {
    unsigned char check[1024];if(transfer(fd,(void*)data,size,at,1)||fsync(fd))return bad("write");
    const unsigned char *p=data;
    while(size){size_t n=size<sizeof(check)?size:sizeof(check);if(transfer(fd,check,n,at,0)||memcmp(check,p,n))return bad("readback");size-=n;p+=n;at+=n;}return 0;
}
static int writable(int index) {
    char p[640];path(p,sizeof(p),mounts[index]);struct statvfs s;
    if(statvfs(p,&s))return bad("mount-info");
    if(s.f_flag&ST_RDONLY){
        unsigned long flags=0;
#define KEEP_FLAG(name) if(s.f_flag&ST_##name)flags|=MS_##name
        KEEP_FLAG(NOSUID);KEEP_FLAG(NODEV);KEEP_FLAG(NOEXEC);KEEP_FLAG(SYNCHRONOUS);
        KEEP_FLAG(MANDLOCK);KEEP_FLAG(NOATIME);KEEP_FLAG(NODIRATIME);KEEP_FLAG(RELATIME);
#undef KEEP_FLAG
        mount_flags[index]=flags;
        if(mount(NULL,p,NULL,MS_REMOUNT|flags,NULL))return bad("mount-rw");remounted[index]=1;
    }return 0;
}
static int restore_mounts(void) {
    int result=0;for(int i=2;i>=0;i--)if(remounted[i]){char p[640];path(p,sizeof(p),mounts[i]);if(mount(NULL,p,NULL,MS_REMOUNT|MS_RDONLY|mount_flags[i],NULL))result=bad("mount-ro");}return result;
}
static int input(unsigned char *out,size_t capacity,size_t *size) {
    *size=0;while(*size<capacity){ssize_t n=read(0,out+*size,capacity-*size);if(n<0&&errno==EINTR)continue;if(n<0)return bad("input");if(!n)return 0;*size+=n;}
    unsigned char extra;ssize_t n;do{n=read(0,&extra,1);}while(n<0&&errno==EINTR);return n?bad("input-size"):0;
}
static int boot_id(char *id) {
    char p[640];path(p,sizeof(p),"/proc/sys/kernel/random/boot_id");FILE *f=fopen(p,"r");if(!f)return bad("boot-id");
    int ok=fgets(id,40,f)!=NULL;fclose(f);if(!ok)return bad("boot-id");id[strcspn(id,"\r\n")]=0;return 0;
}
static int save_state(const char *state,const char *operation) {
    char p[640],to[640],id[40];if(boot_id(id))return -1;
    path(p,sizeof(p),"/setting/a7c2-api.task.new");path(to,sizeof(to),"/setting/a7c2-api.task");
    FILE *f=fopen(p,"w");if(!f)return bad("task-write");int ok=fprintf(f,"%s %s %s\n",state,id,operation)>=0;
    if(fflush(f)||fsync(fileno(f)))ok=0;if(fclose(f))ok=0;if(!ok||rename(p,to))return bad("task-write");return 0;
}
static int read_state(char *state,char *id,char *operation) {
    char p[640];path(p,sizeof(p),"/setting/a7c2-api.task");FILE *f=fopen(p,"r");if(!f){if(errno==ENOENT)return 0;return bad("task-read");}
    int n=fscanf(f,"%31s %39s %31s",state,id,operation);fclose(f);return n==3?1:bad("task-read");
}
static int task(void) {
    char state[32],saved[40],op[32],current[40];int n=read_state(state,saved,op);if(n<0)return -1;
    if(!n){puts("{\"state\":\"idle\"}");return 0;}if(boot_id(current))return -1;
    if(!strcmp(state,"running"))strcpy(state,"failed");
    if(!strcmp(state,"pending_reload")&&strcmp(saved,current))strcpy(state,"active");
    printf("{\"state\":\"%s\",\"operation\":\"%s\"}\n",state,op);return 0;
}
static int ready(void) {
    char state[32],saved[40],op[32],current[40];int n=read_state(state,saved,op);if(n<0)return -1;if(!n)return 0;
    if(!strcmp(state,"running"))return bad("previous-result-unknown");if(boot_id(current))return -1;
    if(!strcmp(state,"pending_reload")&&!strcmp(saved,current))return bad("pending-reload");return 0;
}
static int name_file(const char *filename,int slot,const char *name,int writing) {
    char p[640];snprintf(p,sizeof(p),"%s/usr/share/app/%s",root,filename);int fd=open(p,writing?O_RDWR:O_RDONLY);
    if(fd<0)return bad("name-open");int result=-1;unsigned char header[16],pointer[2],tag[4];struct stat s;
    if(transfer(fd,header,16,0,0)||fstat(fd,&s))goto done;
    unsigned count=get32(header+12)&0x1fff;off_t base=(16+count*2+3)&~3;
    if(memcmp(header,"uxc\7\0\0\0\0",8)||header[8]!=8||header[9]||header[10]!=5||header[11]||count!=2866||s.st_size%4||s.st_size<base){bad("name-layout");goto done;}
    unsigned rid=label_ids[slot-1];off_t index=16+2*((rid&0xffffff)-0xa000);
    if(transfer(fd,pointer,2,index,0)||transfer(fd,tag,4,base+4*(pointer[0]|pointer[1]<<8),0))goto done;
    if(get32(tag)!=(0x1e000000|(rid&0xffffff))){bad("name-layout");goto done;}
    unsigned next=(s.st_size-base)/4;if(next>=65535){bad("name-space");goto done;}
    if(writing){
        unsigned char record[72]={0};put32(record,0x1e000000|(rid&0xffffff));memcpy(record+4,name,strlen(name));size_t size=(4+strlen(name)+1+3)&~3;
        pointer[0]=next&255;pointer[1]=next>>8;
        if(replace_bytes(fd,s.st_size,record,size)||replace_bytes(fd,index,pointer,2))goto done;
    }
    result=0;
done:close(fd);return result;
}
static int cp_open(void){char p[640];path(p,sizeof(p),"/cp/cpapp-b.bin");return open(p,O_RDWR);}
static int install_look(int slot,const char *name,const unsigned char *data) {
    if(writable(1)||writable(2))return -1;int fd=cp_open();if(fd<0)return bad("cp-open");int result=-1;
    unsigned char header[8],sum[4],mask[4];if(transfer(fd,header,8,table_offset,0))goto done;
    if(get32(header)!=table_magic||get32(header+4)!=table_layout){bad("table-layout");goto done;}
    uint32_t value=2166136261U;for(int i=0;i<1215;i++)value=(value^data[i])*16777619U;put32(sum,value);
    if(replace_bytes(fd,table_offset+32+(slot-1)*1215,data,1215)||replace_bytes(fd,table_offset+8+(slot-1)*4,sum,4))goto done;
    if(photo_available){
        if(transfer(fd,mask,4,photo_mask_offset,0))goto done;value=get32(mask);
        value=data[1215]?value|(1U<<(slot-1)):value&~(1U<<(slot-1));put32(mask,value);
        if(replace_bytes(fd,photo_params_offset+(slot-1)*108,data+1216,108)||replace_bytes(fd,photo_mask_offset,mask,4))goto done;
    }
    for(unsigned i=0;i<name_count;i++)if(name_file(name_files[i],slot,name,1))goto done;result=0;
done:close(fd);return result;
}
static int sound_current(int fd) {
    unsigned char table[5],gate[SOUND_GATE_SIZE];if(transfer(fd,table,5,sound_table_offset,0)||transfer(fd,gate,sizeof(gate),sound_gate_offset,0))return -1;
    for(unsigned i=0;i<sound_states;i++)if(!memcmp(table,sound_tables[i],5)&&!memcmp(gate,sound_gates[i],sizeof(gate)))return sound_flags[i];return bad("sound-layout");
}
static int sound_switch(int selection,int enabled) {
    if(writable(1))return -1;int fd=cp_open();if(fd<0)return bad("cp-open");int result=-1,current=sound_current(fd);if(current<0)goto done;
    int next=enabled?(current|selection):(current&~selection);
    if(next==current){result=0;goto done;}
    if(replace_bytes(fd,sound_table_offset,sound_tables[next],5)||replace_bytes(fd,sound_gate_offset,sound_gates[next],SOUND_GATE_SIZE)
       ||replace_bytes(fd,sound_front_offset,sound_front,2)||replace_bytes(fd,sound_mechanical_offset,sound_mechanical,2))goto done;result=0;
done:close(fd);return result;
}
struct audio_row {unsigned present,file,size,offset;};
static const char *audio_names[]={"custom-shutter.bin","custom-shutter-a.bin","custom-shutter-b.bin"};
static int audio_config(struct audio_row *rows) {
    char p[640],line[512];path(p,sizeof(p),"/usr/share/avsystemsound/custom.txt");FILE *f=fopen(p,"r");if(!f)return errno==ENOENT?0:bad("audio-config");
    while(fgets(line,sizeof(line),f)) {
        if(strncmp(line,"CUSTOM,",7))continue;unsigned kind,size,offset;char name[64];
        if(sscanf(line,"CUSTOM,0x%X,APP,%63[^,],0x%X,0x%X,",&kind,name,&size,&offset)!=4||kind<1||kind>3||!size||size>51200||offset>51200-size||size%64||offset%64){fclose(f);return bad("audio-config");}
        unsigned file;for(file=0;file<3;file++)if(!strcmp(name,audio_names[file]))break;
        if(file==3||rows[kind-1].present){fclose(f);return bad("audio-config");}rows[kind-1]=(struct audio_row){1,file,size,offset};
    }
    int result=ferror(f)?bad("audio-config"):0;fclose(f);
    if(rows[0].present!=rows[1].present)return bad("audio-config");return result;
}
static int install_audio(int selection,unsigned char *audio,size_t length,struct audio_row *rows) {
    unsigned file;for(file=0;file<3;file++){int used=0;for(int i=0;i<3;i++)if(rows[i].present&&rows[i].file==file)used=1;if(!used)break;}
    if(file==3)return bad("audio-space");if(writable(2))return -1;
    char p[640];snprintf(p,sizeof(p),"%s/usr/share/avsystemsound/%s",root,audio_names[file]);int fd=open(p,O_RDWR|O_CREAT|O_TRUNC,0644);if(fd<0)return bad("audio-open");
    size_t stored=length;if(selection&1){memset(audio+length,0,64);stored+=64;}int ok=replace_bytes(fd,0,audio,stored);close(fd);if(ok)return -1;
    if(selection&1){rows[0]=(struct audio_row){1,file,length,0};rows[1]=(struct audio_row){1,file,64,length};}
    if(selection&2)rows[2]=(struct audio_row){1,file,length,0};
    path(p,sizeof(p),"/usr/share/avsystemsound/.a7c2-api.csv");FILE *f=fopen(p,"w");if(!f)return bad("audio-config-write");
    fputs("\n/* START */\n/usr/share/avsystemsound/\n",f);
    for(int i=0;i<3;i++)if(rows[i].present)fprintf(f,"CUSTOM,0x%04X,APP,%s,0x%X,0x%X,AA_RT,6,%d,0,0,0\n",i+1,audio_names[rows[i].file],rows[i].size,rows[i].offset,i+1);
    fputs("/* END */\n",f);ok=fflush(f)||fsync(fileno(f));if(fclose(f))ok=1;if(ok)return bad("audio-config-write");
    char target[640];path(target,sizeof(target),"/usr/share/avsystemsound/custom.txt");if(rename(p,target))return bad("audio-publish");return 0;
}
int main(int argc,char **argv) {
#ifdef CAMERA_API_TEST
    root=getenv("A7C2_TEST_ROOT");if(!root)return 2;
#endif
    int result=-1;
    if(argc==2&&!strcmp(argv[1],"info")) {
        printf("{\"slots\":[");int comma=0;for(int i=0;i<6;i++)if(slot_mask&(1<<i)){printf("%s%d",comma?",":"",i+1);comma=1;}
        printf("],\"sound\":[%s],\"sound_operations\":[%s],\"native_photo\":%s}\n",sound_available?"\"mechanical\",\"electronic\",\"both\"":"",
            !sound_available?"":custom_audio_available?"\"on\",\"off\",\"custom\"":"\"on\",\"off\"",photo_available?"true":"false");return 0;
    }
    if(argc==2&&!strcmp(argv[1],"task")){result=task();goto answer;}
    int is_look=argc==4&&!strcmp(argv[1],"look"),selection=0,custom=0,enabled=0,slot=0;
    unsigned char data[51200];size_t size=0;struct audio_row rows[3]={{0}};
    if(is_look) {
        char *end;long value=strtol(argv[2],&end,10);if(*end||value<1||value>6||!(slot_mask&(1<<(value-1)))){bad("slot");goto answer;}slot=value;
        size_t length=strlen(argv[3]);if(!length||length>63){bad("name");goto answer;}
        for(size_t i=0;i<length;i++)if((unsigned char)argv[3][i]<32){bad("name");goto answer;}
        if(input(data,1324,&size)||size!=1324||data[1215]>1){bad("look-size");goto answer;}
        for(int i=0;i<1215;i++)if((signed char)data[i]<-64||(signed char)data[i]>63){bad("look-range");goto answer;}
        if(data[1215]&&!photo_available){bad("photo-unavailable");goto answer;}
        if(data[1215])for(int i=0;i<54;i++) {
            int v=get16(data+1216+2*i),limit=(i<3||i>=30)?1024:2048;
            if(v < -limit||v>limit){bad("photo-range");goto answer;}
        }
        for(unsigned i=0;i<name_count;i++)if(name_file(name_files[i],slot,argv[3],0))goto answer;
    } else if(argc==4&&!strcmp(argv[1],"sound")&&sound_available) {
        selection=!strcmp(argv[2],"mechanical")?1:!strcmp(argv[2],"electronic")?2:!strcmp(argv[2],"both")?3:0;
        custom=!strcmp(argv[3],"custom");enabled=!strcmp(argv[3],"on");
        if(!selection||(!custom&&!enabled&&strcmp(argv[3],"off"))){bad("arguments");goto answer;}
        if(custom){
            if(!custom_audio_available){bad("custom-unavailable");goto answer;}
            if(input(data,51136,&size)||!size||size%64){bad("audio-size");goto answer;}
            for(size_t i=0;i<size;i+=32)if(data[i]>8){bad("audio-codec");goto answer;}
            if(audio_config(rows))goto answer;
        }
    } else {bad("arguments");goto answer;}
    char p[640];path(p,sizeof(p),"/tmp_wbshd/a7c2-api.lock");int lock=open(p,O_RDWR|O_CREAT,0600);
    if(lock<0||flock(lock,LOCK_EX|LOCK_NB)){if(lock>=0)close(lock);bad("busy");goto answer;}
    if(ready()||writable(0)){close(lock);goto answer;}
    if(save_state("running",argv[1])){close(lock);goto cleanup;}
    if(is_look)result=install_look(slot,argv[3],data);
    else if(custom){if(!install_audio(selection,data,size,rows))result=sound_switch(selection,1);}
    else result=sound_switch(selection,enabled);
    const char *operation=argv[1];if(result){const char *saved=error;save_state("failed",operation);error=saved;}
    else if(save_state("pending_reload",operation))result=-1;
    close(lock);
cleanup:if(restore_mounts())result=-1;
answer:if(result)printf("{\"state\":\"failed\",\"error\":\"%s\"}\n",error);
    else if(argc!=2)puts("{\"state\":\"pending_reload\"}");return result?1:0;
}
