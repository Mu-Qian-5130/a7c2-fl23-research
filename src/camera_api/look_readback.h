/* Root-only SSH diagnostics over the same fixed file set as look publication. */
#if API_MENU_ICONS
static int rb_path(unsigned id,char *out,size_t size,char *logical,size_t logical_size) {
    if(id==0)snprintf(logical,logical_size,"/cp/cpapp-b.bin");
    else if(id<=name_count)snprintf(logical,logical_size,"/usr/share/app/%s",name_files[id-1]);
    else if(id<=name_count+4)snprintf(logical,logical_size,"/usr/share/app/%s",icon_names[id-name_count-1]);
    else return bad("readback-file");
    snprintf(out,size,"%s%s",root,logical);return 0;
}
static void rb_hex(const unsigned char *p,size_t n){for(size_t i=0;i<n;i++)printf("%02x",p[i]);}
static int rb_files(void) {
    struct row {char logical[256];struct stat info;unsigned char digest[32];};
    if(name_count>128)return bad("readback-bound");
    struct row *rows=calloc(name_count+5,sizeof *rows);
    if(!rows)return bad("readback-memory");
    for(unsigned id=0;id<name_count+5;id++){
        char p[640],logical[256];if(rb_path(id,p,sizeof p,logical,sizeof logical)){free(rows);return -1;}
        int fd=open(p,O_RDONLY|O_NOFOLLOW);struct stat before,after;
        if(fd<0){free(rows);return bad("readback-open");}
        if(fstat(fd,&before)||!S_ISREG(before.st_mode)||before.st_size<0||before.st_size>64*1024*1024){close(fd);free(rows);return bad("readback-size");}
#if !API_FIXED_BANK
        SHA256 hash;sha_init(&hash);unsigned char data[16384],digest[32];
        for(off_t at=0;at<before.st_size;){
            size_t n=(size_t)(before.st_size-at);if(n>sizeof data)n=sizeof data;
            if(transfer(fd,data,n,at,0)){close(fd);free(rows);return -1;}sha_add(&hash,data,(u32)n);at+=(off_t)n;
        }
        sha_end(&hash,digest);
#endif
        int changed=fstat(fd,&after)||after.st_size!=before.st_size||
                    after.st_mtim.tv_sec!=before.st_mtim.tv_sec||after.st_mtim.tv_nsec!=before.st_mtim.tv_nsec;
        close(fd);if(changed){free(rows);return bad("readback-source-changed");}
        strcpy(rows[id].logical,logical);rows[id].info=before;
#if !API_FIXED_BANK
        memcpy(rows[id].digest,digest,32);
#endif
    }
    puts("{\"files\":[");
    for(unsigned id=0;id<name_count+5;id++){
        struct stat before=rows[id].info;
        printf("%s{\"id\":%u,\"path\":\"%s\",\"bytes\":%llu,\"inode\":%llu,\"mode\":%u",
               id?",":"",id,rows[id].logical,(unsigned long long)before.st_size,(unsigned long long)before.st_ino,(unsigned)(before.st_mode&07777));
#if !API_FIXED_BANK
        printf(",\"sha256\":\"");rb_hex(rows[id].digest,32);putchar('"');
#endif
        puts("}");
    }
    free(rows);puts("]}");return 0;
}
static int rb_number(const char *s,uint64_t *out) {
    if(!*s)return bad("readback-arguments");
    for(const char *p=s;*p;p++)if(*p<'0'||*p>'9')return bad("readback-arguments");
    errno=0;char *end;unsigned long long value=strtoull(s,&end,10);
    if(errno||*end)return bad("readback-arguments");*out=value;return 0;
}
static int rb_chunk(int fd,uint64_t id,uint64_t at,uint64_t count) {
    struct stat before,after;
    if(fstat(fd,&before)||!S_ISREG(before.st_mode)||before.st_size<0||
       at>(uint64_t)before.st_size||count>(uint64_t)before.st_size-at)return bad("readback-bound");
    unsigned char *data=malloc((size_t)count);char *encoded=malloc(((size_t)count+2)/3*4+1);
    if(!data||!encoded){free(data);free(encoded);return bad("readback-memory");}
    int result=-1;if(transfer(fd,data,(size_t)count,(off_t)at,0))goto done;
    if(fstat(fd,&after)||after.st_size!=before.st_size||after.st_mtim.tv_sec!=before.st_mtim.tv_sec||
       after.st_mtim.tv_nsec!=before.st_mtim.tv_nsec){bad("readback-source-changed");goto done;}
    static const char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t n=0;
    for(size_t i=0;i<count;i+=3){
        unsigned v=(unsigned)data[i]<<16;
        if(i+1<count)v|=(unsigned)data[i+1]<<8;if(i+2<count)v|=data[i+2];
        encoded[n++]=alphabet[v>>18];encoded[n++]=alphabet[(v>>12)&63];
        encoded[n++]=i+1<count?alphabet[(v>>6)&63]:'=';encoded[n++]=i+2<count?alphabet[v&63]:'=';
    }
    encoded[n]=0;
    printf("{\"file\":%llu,\"offset\":%llu,\"bytes\":%llu,\"file_size\":%llu",
        (unsigned long long)id,(unsigned long long)at,(unsigned long long)count,(unsigned long long)before.st_size);
#if !API_FIXED_BANK
    unsigned char digest[32];i_hash(data,(size_t)count,digest);printf(",\"sha256\":\"");rb_hex(digest,32);putchar('"');
#endif
    printf(",\"data\":\"%s\"}\n",encoded);result=0;
done:free(data);free(encoded);return result;
}
static int rb_read(char **args) {
    uint64_t id,at,count;
    if(rb_number(args[0],&id)||rb_number(args[1],&at)||rb_number(args[2],&count))return -1;
    if(id>name_count+4||count==0||count>131072)return bad("readback-bound");
    char p[640],logical[256];if(rb_path((unsigned)id,p,sizeof p,logical,sizeof logical))return -1;
    int fd=open(p,O_RDONLY|O_NOFOLLOW);if(fd<0)return bad("readback-open");
    int result=rb_chunk(fd,id,at,count);close(fd);return result;
}
static int rb_undo(const char *name) {
    const char *prefix="a7c2-api.undo.";size_t n=strlen(prefix);
    if(strlen(name)!=n+6||memcmp(name,prefix,n)||strspn(name+n,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")!=6)
        return bad("undo-name");
    char p[640];snprintf(p,sizeof p,"%s/setting/%s",root,name);
    int fd=open(p,O_RDONLY|O_NOFOLLOW);struct stat st;
    if(fd<0)return bad("undo-open");
    if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<8||st.st_size>200000){close(fd);return bad("undo-size");}
    int result=rb_chunk(fd,4294967295U,0,(uint64_t)st.st_size);close(fd);return result;
}
static int rb_result(const char *identifier) {
    if(strlen(identifier)!=32||strspn(identifier,"0123456789abcdef")!=32)return bad("result-id");
    char p[640];snprintf(p,sizeof p,"%s/tmp/a7c2-api-%s.response",root,identifier);
    int fd=open(p,O_RDONLY|O_NOFOLLOW);struct stat st;
    if(fd<0)return bad("result-open");
    if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<2||st.st_size>262144){close(fd);return bad("result-size");}
    int result=rb_chunk(fd,4294967294U,0,(uint64_t)st.st_size);close(fd);return result;
}
#else
static int rb_files(void){return bad("readback-unavailable");}
static int rb_read(char **args){(void)args;return bad("readback-unavailable");}
static int rb_undo(const char *name){(void)name;return bad("readback-unavailable");}
static int rb_result(const char *identifier){(void)identifier;return bad("readback-unavailable");}
#endif
