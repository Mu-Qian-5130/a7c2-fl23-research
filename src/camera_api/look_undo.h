/* Internal bounded undo records. Input never selects a file or an offset. */
#define UNDO_LIMIT 256
struct undo_row { int fd; off_t at, size; size_t count; unsigned char *before; };
static struct undo_row undo_rows[UNDO_LIMIT];
static unsigned undo_count;
static int undo_fd=-1,undo_active,undo_rolled_back;
static char undo_path[640];
static const char *icon_names[]={"image_00_32_IPSX.uxc","image_01_32_IPSX.uxc",
                               "image_00_23_IPSX.uxc","image_01_23_IPSX.uxc"};

static int undo_id(int fd) {
    char link[64],actual[640],expected[640];
    snprintf(link,sizeof link,"/proc/self/fd/%d",fd);
    ssize_t n=readlink(link,actual,sizeof(actual)-1);
    if(n<0||(size_t)n>=sizeof(actual)-1)return bad("undo-descriptor");
    actual[n]=0;path(expected,sizeof expected,"/cp/cpapp-b.bin");
    if(!strcmp(actual,expected))return 0;
    for(unsigned i=0;i<name_count;i++){
        snprintf(expected,sizeof expected,"%s/usr/share/app/%s",root,name_files[i]);
        if(!strcmp(actual,expected))return (int)i+1;
    }
    for(unsigned i=0;i<4;i++){
        snprintf(expected,sizeof expected,"%s/usr/share/app/%s",root,icon_names[i]);
        if(!strcmp(actual,expected))return (int)name_count+1+(int)i;
    }
    return bad("undo-target");
}

static int undo_begin(void) {
    path(undo_path,sizeof undo_path,"/setting/a7c2-api.undo.XXXXXX");
    undo_fd=mkstemp(undo_path);
    if(undo_fd<0)return bad("undo-create");
    if(transfer(undo_fd,"A7IUNDO1",8,0,1)||fsync(undo_fd))return bad("undo-create");
    undo_active=1;return 0;
}

static int undo_record(int fd,off_t at,size_t count) {
    if(!undo_active)return 0;
    if(undo_count>=UNDO_LIMIT||at<0||count>1024*1024)return bad("undo-bound");
    int id=undo_id(fd);struct stat file,journal;
    if(id<0)return -1;
    if(fstat(fd,&file)||!S_ISREG(file.st_mode)||fstat(undo_fd,&journal))return bad("undo-stat");
    size_t keep=at<file.st_size?(size_t)(file.st_size-at):0;
    if(keep>count)keep=count;
    unsigned char *old=malloc(keep?keep:1);
    if(!old)return bad("undo-memory");
    if(keep&&transfer(fd,old,keep,at,0)){free(old);return -1;}
    int copy=dup(fd);
    if(copy<0){free(old);return bad("undo-descriptor");}
    uint64_t header[4]={(uint64_t)id,(uint64_t)at,(uint64_t)file.st_size,(uint64_t)keep};
    if(transfer(undo_fd,header,sizeof header,journal.st_size,1)||
       (keep&&transfer(undo_fd,old,keep,journal.st_size+sizeof header,1))||fsync(undo_fd)){
        close(copy);free(old);return bad("undo-write");
    }
    undo_rows[undo_count++]=(struct undo_row){copy,at,file.st_size,keep,old};
#ifdef CAMERA_API_TEST
    const char *fail=getenv("A7C2_API_FAIL_WRITE");
    if(fail&&strtoul(fail,NULL,10)==undo_count)return bad("injected-write-failure");
#endif
    return 0;
}

static int undo_mark(const char *marker) {
    struct stat s;
    if(undo_fd<0||fstat(undo_fd,&s)||transfer(undo_fd,(void*)marker,8,s.st_size,1)||fsync(undo_fd))
        return bad("undo-finish");
    return 0;
}

static int undo_abort(void) {
    int failed=0;
    for(unsigned i=undo_count;i;i--){
        struct undo_row *r=&undo_rows[i-1];
        if((r->count&&transfer(r->fd,r->before,r->count,r->at,1))||ftruncate(r->fd,r->size)||fsync(r->fd))failed=1;
        unsigned char check[1024];
        for(size_t at=0;at<r->count&&!failed;){
            size_t n=r->count-at;if(n>sizeof check)n=sizeof check;
            if(transfer(r->fd,check,n,r->at+(off_t)at,0)||memcmp(check,r->before+at,n))failed=1;
            at+=n;
        }
        struct stat s;if(fstat(r->fd,&s)||s.st_size!=r->size)failed=1;
    }
    if(undo_mark(failed?"RBFAIL01":"ROLLBK01"))failed=1;
    undo_rolled_back=!failed;
    return failed?bad("rollback-incomplete"):0;
}

static void undo_close(void) {
    for(unsigned i=0;i<undo_count;i++){close(undo_rows[i].fd);free(undo_rows[i].before);}
    if(undo_fd>=0)close(undo_fd);
    undo_active=0;
}
