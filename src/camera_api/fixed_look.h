/* Fixed persisted source. Runtime activation is a separate explicit operation. */
#if API_FIXED_BANK
#define X_GAMMA 0x20U
#define X_DIRECTORY 0xa00U
#define X_MODES 0xb40U
#define X_BASIS 0xc00U
#define X_SLOTS 0x2000U
#define X_STRIDE 0x3100U
#define X_RECORD 0x500U
static unsigned char *fixed_before,*fixed_after;
static struct stat fixed_source;

static int fixed_validate(int cp,const unsigned char *p){
    unsigned count=get32(p+4),mask=get32(p+8);
    if(count<6||count>18||mask>>count||get32(p)!=FIXED_BYTES||
       get32(p+12)!=X_STRIDE||FIXED_BYTES!=X_SLOTS+count*X_STRIDE||FIXED_BYTES>FIXED_CAPACITY)
        return bad("fixed-image-layout");
    unsigned char native[1400];
    if(transfer(cp,native,sizeof native,0x1209480-F_BASE,0)||memcmp(native,p+X_GAMMA,sizeof native))
        return bad("fixed-native-rows");
    if(memcmp(p+X_BASIS,fixed_native_basis,1792))return bad("fixed-native-basis");
    for(unsigned i=0;i<count;i++){
        const unsigned char *d=p+X_DIRECTORY+i*16;unsigned at=X_SLOTS+i*X_STRIDE;
        unsigned rec=at+X_RECORD,n=get32(d+8),kind=get32(d+12),encoded=kind==0?0:kind==1?90:2200;
        if(kind>2||get32(d)!=FIXED_BASE+at||get32(d+4)!=FIXED_BASE+rec||
           n!=F_FIXED+4+encoded||n>X_STRIDE-X_RECORD||get32(p+rec+F_FIXED)!=encoded)
            return bad("fixed-record-layout");
        for(unsigned j=0;j<1215;j++)if((signed char)p[at+j]<-64||(signed char)p[at+j]>63)
            return bad("fixed-grid-range");
        if(get32(p+X_MODES+i*8)!=50+i*2||get32(p+X_MODES+i*8+4)!=51+i*2)
            return bad("fixed-mode-row");
        for(unsigned j=0;j<14;j++)if(get32(p+X_GAMMA+1400+i*56+j*4)!=FIXED_BASE+rec+912+j*576)
            return bad("fixed-curve-pointer");
    }
    return 0;
}
static int fixed_read(int fd,unsigned char **data){
    unsigned char descriptor[8];
    if(transfer(fd,descriptor,8,FIXED_ROOT,0)||get32(descriptor)!=FIXED_BASE||get32(descriptor+4)!=FIXED_CAPACITY)
        return bad("fixed-source-incomplete");
    if(FIXED_SOURCE>cp_file_size||FIXED_BYTES>cp_file_size-FIXED_SOURCE)return bad("fixed-source-extent");
    *data=malloc(FIXED_BYTES);if(!*data)return bad("memory");
    return transfer(fd,*data,FIXED_BYTES,FIXED_SOURCE,0)||fixed_validate(fd,*data)?-1:0;
}
static int fixed_prepare(int slot,const unsigned char *data,size_t input_size){
    char p[640];path(p,sizeof p,"/cp/cpapp-b.bin");int fd=open(p,O_RDONLY|O_NOFOLLOW),result=-1;
    unsigned char *entry=NULL;unsigned kind=0,length=0;
    if(fd<0)return bad("cp-open");
    if(fstat(fd,&fixed_source)||!S_ISREG(fixed_source.st_mode)||fixed_source.st_nlink!=1||
       fixed_source.st_size!=cp_file_size){bad("fixed-source-file");goto done;}
    if(fixed_read(fd,&fixed_before)||full_entry(fd,fixed_before+X_BASIS,data,input_size,&entry,&kind,&length))goto done;
    fixed_after=malloc(FIXED_BYTES);if(!fixed_after){bad("memory");goto done;}
    memcpy(fixed_after,fixed_before,FIXED_BYTES);
    unsigned at=X_SLOTS+((unsigned)slot-1)*X_STRIDE,rec=at+X_RECORD;
    if(length>X_STRIDE-X_RECORD){bad("fixed-record-space");goto done;}
    memset(fixed_after+at,0,X_STRIDE);
    memcpy(fixed_after+at,full_frame(data,input_size)?data+8:data,1215);
    memcpy(fixed_after+rec,entry,length);
    put32(fixed_after+X_DIRECTORY+((unsigned)slot-1)*16+8,length);
    put32(fixed_after+X_DIRECTORY+((unsigned)slot-1)*16+12,kind);
    put32(fixed_after+8,get32(fixed_after+8)|(1U<<(slot-1)));
    if(fixed_validate(fd,fixed_after))goto done;result=0;
done:free(entry);close(fd);return result;
}
static int fixed_install(int slot){
    if(!fixed_before||!fixed_after||!undo_active)return bad("fixed-source-not-prepared");
    char p[640];path(p,sizeof p,"/cp/cpapp-b.bin");int fd=open(p,O_RDWR|O_NOFOLLOW),result=-1;
    if(fd<0)return bad("cp-open");struct stat file;unsigned char check[1024];
    if(fstat(fd,&file)||file.st_dev!=fixed_source.st_dev||file.st_ino!=fixed_source.st_ino||
       file.st_mode!=fixed_source.st_mode||file.st_nlink!=1||file.st_size!=fixed_source.st_size){bad("fixed-source-changed");goto done;}
    for(unsigned at=0;at<FIXED_BYTES;){unsigned n=FIXED_BYTES-at;if(n>sizeof check)n=sizeof check;
        if(transfer(fd,check,n,FIXED_SOURCE+at,0)||memcmp(check,fixed_before+at,n)){bad("fixed-source-changed");goto done;}at+=n;}
    /* The existing base word is the publication boundary for cold loading.
       Persist zero before touching any record. The running CP RAM is unchanged;
       a CP cold load after interruption takes its already reviewed native fallback. */
    unsigned char unpublished[4]={0};
    if(replace_bytes(fd,FIXED_ROOT,unpublished,4))goto done;
#ifdef CAMERA_API_TEST
    const char *stop=getenv("A7C2_API_EXIT_FIXED");if(stop&&!strcmp(stop,"root"))_exit(85);
#endif
    unsigned at=X_SLOTS+((unsigned)slot-1)*X_STRIDE,dir=X_DIRECTORY+((unsigned)slot-1)*16;
    if(replace_bytes(fd,FIXED_SOURCE+at,fixed_after+at,X_STRIDE)||
       replace_bytes(fd,FIXED_SOURCE+dir,fixed_after+dir,16)||
       replace_bytes(fd,FIXED_SOURCE+8,fixed_after+8,4))goto done;
#ifdef CAMERA_API_TEST
    if(stop&&!strcmp(stop,"data"))_exit(86);
#endif
    if(fstat(fd,&file)||file.st_size!=cp_file_size){bad("readback-size");goto done;}result=0;
done:close(fd);return result;
}
static int fixed_publish(void){
    char p[640];path(p,sizeof p,"/cp/cpapp-b.bin");int fd=open(p,O_RDWR|O_NOFOLLOW);
    if(fd<0)return bad("cp-open");struct stat file;unsigned char descriptor[8];int result=-1;
    if(fstat(fd,&file)||file.st_dev!=fixed_source.st_dev||file.st_ino!=fixed_source.st_ino||
       file.st_nlink!=1||file.st_size!=fixed_source.st_size||
       transfer(fd,descriptor,8,FIXED_ROOT,0)||get32(descriptor)||get32(descriptor+4)!=FIXED_CAPACITY){
        bad("fixed-source-changed");goto done;
    }
    put32(descriptor,FIXED_BASE);result=replace_bytes(fd,FIXED_ROOT,descriptor,4);
done:close(fd);return result;
}
static int fixed_status(void){
    char p[640];path(p,sizeof p,"/cp/cpapp-b.bin");int fd=open(p,O_RDONLY|O_NOFOLLOW),result=-1;
    unsigned char *data=NULL;if(fd<0)return bad("cp-open");
    if(!fixed_read(fd,&data)){
        printf("{\"state\":\"persisted\",\"look_storage\":\"cp-fixed-v1\",\"base\":%u,\"size\":%u,"
               "\"runtime_checked\":false,\"manual_reload_available\":false}\n",FIXED_BASE,FIXED_CAPACITY);result=0;
    }
    free(data);close(fd);return result;
}
static void fixed_close(void){free(fixed_before);free(fixed_after);fixed_before=NULL;fixed_after=NULL;}
#endif
