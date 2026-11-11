/* Existing C2 records only. The wire carries masks, never paths/IDs/offsets. */
#define I_PACKET_MAX 4317U
#define I_MASK_BYTES 846U
#if API_MENU_ICONS
#if !API_FULL_NATIVE
typedef uint8_t u8;typedef uint32_t u32;typedef uint64_t u64;
#include "../fl23/native/sha256.h"
#endif
#define I_MAX_FILE (16U*1024U*1024U)
struct icon_bank {
    unsigned char *before,*after;size_t size,length;
    dev_t device;ino_t inode;unsigned windows[3],count;
};
static struct icon_bank icon_banks[4];
static const unsigned char *icon_masks;
static unsigned icon_growth;

static void i_hash(const unsigned char *p,size_t n,unsigned char out[32]) {
    SHA256 h;sha_init(&h);sha_add(&h,p,(u32)n);sha_end(&h,out);
}
static unsigned i_u16(const unsigned char *p){return (unsigned)p[0]|(unsigned)p[1]<<8;}

static int icon_unwrap(const unsigned char **data,size_t *size) {
    if(*size<8||memcmp(*data,"A7ICLOOK",8))return 0;
    if(*size<16+1324+I_MASK_BYTES+32)return bad("icon-packet-size");
    unsigned n=get32(*data+8),m=get32(*data+12);unsigned char hash[32];
    if((n!=1324&&n!=3423)||m!=I_MASK_BYTES||*size!=16U+n+m+32U)return bad("icon-packet-size");
    i_hash(*data,*size-32,hash);
    if(memcmp(hash,*data+*size-32,32))return bad("icon-packet-hash");
    icon_masks=*data+16+n;unsigned a=0,b=0;
    for(unsigned i=0;i<494;i++)a|=icon_masks[i];
    for(unsigned i=494;i<I_MASK_BYTES;i++)b|=icon_masks[i];
    if(!a||!b)return bad("icon-empty");
    *data+=16;*size=n;return 1;
}

static int i_decode(const unsigned char *p,size_t size,unsigned char *out,unsigned n) {
    static const unsigned lengths[]={3,4,5,6,7,8,9,10,11,12,13,14,15,16,32,64};
    size_t at=0;unsigned base=0;
    while(base<n){
        unsigned wanted=n-base;if(wanted>4096)wanted=4096;
        if(at>=size||p[at++]!=0xf0)return bad("icon-codec");
        unsigned used=0;int done=0;
        while(!done){
            if(at>=size)return bad("icon-codec");unsigned flags=p[at++];
            for(unsigned bit=0;bit<8;bit++){
                if(flags&(1U<<bit)){
                    if(size-at<2)return bad("icon-codec");
                    unsigned a=p[at++],b=p[at++];
                    if(!a&&!b){done=1;break;}
                    unsigned distance=((a&15)<<8)|b,count=lengths[a>>4];
                    if(!distance||distance>used||count>wanted-used)return bad("icon-codec");
                    for(unsigned j=0;j<count;j++){out[base+used]=out[base+used-distance];used++;}
                }else{
                    if(at>=size||used>=wanted)return bad("icon-codec");out[base+used++]=p[at++];
                }
            }
        }
        if(used!=wanted)return bad("icon-codec");base+=wanted;
    }
    return at==size?0:bad("icon-codec-tail");
}

/* Literal F0 is intentionally simple and bounded; native decoding is lossless. */
static size_t i_encode(const unsigned char *raw,unsigned n,unsigned char *out) {
    size_t at=0;
    for(unsigned base=0;base<n;){
        unsigned count=n-base;if(count>4096)count=4096;out[at++]=0xf0;
        unsigned pos=0;
        while(pos<count){
            unsigned take=count-pos;if(take>8)take=8;
            out[at++]=(take<8)?(unsigned char)(1U<<take):0;
            memcpy(out+at,raw+base+pos,take);at+=take;pos+=take;
            if(take<8){out[at++]=0;out[at++]=0;}
        }
        if(!(count%8)){out[at++]=1;out[at++]=0;out[at++]=0;}
        base+=count;
    }
    return at;
}

static void i_paint(unsigned char *raw,int compact,int selected) {
    unsigned width=compact?22:26,height=compact?16:19,stride=compact?64:80;
    unsigned ox=compact?22:27,oy=compact?8:10;
    const unsigned char *mask=icon_masks+(compact?494:0);
    unsigned palette[3];
    if(compact){palette[0]=10;palette[1]=selected?5:10;palette[2]=selected?1:10;}
    else{palette[0]=selected?13:15;palette[1]=selected?6:15;palette[2]=selected?3:15;}
    for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++){
        unsigned outline=0;
        for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++){
            int xx=(int)x+dx,yy=(int)y+dy;
            if(xx>=0&&yy>=0&&(unsigned)xx<width&&(unsigned)yy<height&&mask[yy*width+xx]>outline)
                outline=mask[yy*width+xx];
        }
        unsigned white=(mask[y*width+x]+8)/17,alpha=(outline+8)/17;
        unsigned word=(((white*palette[0]+7)/15)<<12)|(((white*palette[1]+7)/15)<<8)|
                      (((white*palette[2]+7)/15)<<4)|(alpha>white?alpha:white);
        size_t at=((y+oy)*stride+x+ox)*2;raw[at]=(unsigned char)word;raw[at+1]=(unsigned char)(word>>8);
    }
}

static int i_one(unsigned bank,unsigned slot) {
    struct icon_bank *v=&icon_banks[bank];unsigned group=bank&1;
    char p[640];snprintf(p,sizeof p,"%s/usr/share/app/%s",root,icon_names[bank]);
    int fd=open(p,O_RDONLY|O_NOFOLLOW);struct stat st;
    if(fd<0)return bad("icon-open");
    if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<16||st.st_size>I_MAX_FILE){close(fd);return bad("icon-file-size");}
    v->size=v->length=(size_t)st.st_size;v->device=st.st_dev;v->inode=st.st_ino;
    v->before=malloc(v->size);v->after=malloc(v->size+65536);
    if(!v->before||!v->after){close(fd);return bad("icon-memory");}
    if(transfer(fd,v->before,v->size,0,0)){close(fd);return -1;}close(fd);
    memcpy(v->after,v->before,v->size);
    const unsigned char *source=v->before;
    unsigned descriptor=get32(source+12),count=descriptor&8191,base=16+((descriptor>>11)&0x7ffc);
    if(memcmp(source,"uxd\7\0\0\0\0",8)||i_u16(source+8)!=8||i_u16(source+10)!=group||
       descriptor!=(count|(((count+1)&~1U)<<12))||base>v->size||16U+2U*count>v->size)
        return bad("icon-bank-layout");
    if(bank>=2){
        unsigned char hash[32];
        if(v->size<72||memcmp(source+v->size-8,"A7NP2301",8))return bad("icon-portrait-owner");
        i_hash(source,v->size-72,hash);
        if(memcmp(hash,source+v->size-40,32))return bad("icon-portrait-owner");
    }
    unsigned indices[3],selected[3],compact[3],families;
    if(!group){families=3;indices[0]=0x6c5+slot-1;indices[1]=0x8ef+13*(slot-1);indices[2]=0x181a+13*(slot-1);
        selected[0]=0;selected[1]=selected[2]=1;compact[0]=compact[1]=0;compact[2]=1;
    }else{families=1;indices[0]=0x13a3+slot-1;selected[0]=0;compact[0]=1;}
    for(unsigned i=0;i<families;i++){
        unsigned index=indices[i];if(index>=count)return bad("icon-record");
        unsigned pointer=i_u16(source+16+2*index);
        size_t at=(size_t)base+4U*pointer;
        if(pointer==65535||at>v->size||v->size-at<20)return bad("icon-record");
        unsigned width=compact[i]?58:70,height=compact[i]?30:35;
        if(get32(source+at)!=0x1a000000U+group*8192U+index||get32(source+at+4)!=0xc0000000U||
           i_u16(source+at+8)!=width||i_u16(source+at+10)!=height)return bad("icon-record-layout");
        unsigned size=get32(source+at+12),offset=get32(source+at+16);
        size_t start=at+4U+(size_t)offset;unsigned decoded=compact[i]?3840:5600;
        if(start<at+20||start>v->size||size>v->size-start||!size||size>decoded*2U)return bad("icon-payload-layout");
        unsigned char raw[5600],old[5600],encoded[11200];
        if(i_decode(source+start,size,raw,decoded))return -1;
        memcpy(old,raw,decoded);i_paint(raw,compact[i],selected[i]);
        if(!memcmp(old,raw,decoded))continue;
        size_t n=i_encode(raw,decoded,encoded);
        while(v->length%4)v->after[v->length++]=0;
        if(v->length+n+76>v->size+65536||v->length+n+76>I_MAX_FILE)return bad("icon-growth");
        put32(v->after+at+12,(uint32_t)n);put32(v->after+at+16,(uint32_t)(v->length-at-4));
        memcpy(v->after+v->length,encoded,n);v->length+=n;v->windows[v->count++]=(unsigned)at+12;
    }
    if(bank>=2){
        struct icon_bank *horizontal=&icon_banks[bank-2];unsigned char origin[32];
        i_hash(horizontal->after,horizontal->length,origin);
        if(v->count||memcmp(origin,source+v->size-72,32)){
            while(v->length%4)v->after[v->length++]=0;
            unsigned char hash[32];i_hash(v->after,v->length,hash);
            memcpy(v->after+v->length,origin,32);memcpy(v->after+v->length+32,hash,32);
            memcpy(v->after+v->length+64,"A7NP2301",8);v->length+=72;
        }
    }else while(v->length%4)v->after[v->length++]=0;
    icon_growth+=(unsigned)(v->length-v->size);return 0;
}

static int icons_prepare(unsigned slot) {
    if(!icon_masks)return 0;
    for(unsigned i=0;i<4;i++)if(i_one(i,slot))return -1;
    return 0;
}

static int icons_publish(void) {
    if(!icon_masks)return 0;
    for(unsigned i=0;i<4;i++){
        struct icon_bank *v=&icon_banks[i];if(v->length==v->size&&!v->count)continue;
        char p[640];snprintf(p,sizeof p,"%s/usr/share/app/%s",root,icon_names[i]);
        int fd=open(p,O_RDWR|O_NOFOLLOW);struct stat st;int result=-1;unsigned char check[1024];
        if(fd<0)return bad("icon-publish-open");
        if(fstat(fd,&st)||st.st_dev!=v->device||st.st_ino!=v->inode||st.st_size!=(off_t)v->size){bad("icon-source-changed");goto done;}
        for(size_t at=0;at<v->size;){
            size_t n=v->size-at;if(n>sizeof check)n=sizeof check;
            if(transfer(fd,check,n,(off_t)at,0)||memcmp(check,v->before+at,n)){bad("icon-source-changed");goto done;}at+=n;
        }
        if(v->length>v->size&&replace_bytes(fd,(off_t)v->size,v->after+v->size,v->length-v->size))goto done;
        for(unsigned j=0;j<v->count;j++)if(replace_bytes(fd,v->windows[j],v->after+v->windows[j],8))goto done;
        for(size_t at=0;at<v->length;){
            size_t n=v->length-at;if(n>sizeof check)n=sizeof check;
            if(transfer(fd,check,n,(off_t)at,0)||memcmp(check,v->after+at,n)){bad("icon-readback");goto done;}at+=n;
        }
        result=0;
done:close(fd);if(result)return result;
    }
    return 0;
}

static void icons_close(void){for(unsigned i=0;i<4;i++){free(icon_banks[i].before);free(icon_banks[i].after);}}
#else
static const unsigned char *icon_masks;
static unsigned icon_growth;
static int icon_unwrap(const unsigned char **data,size_t *size){
    return *size>=8&&!memcmp(*data,"A7ICLOOK",8)?bad("icon-api-unavailable"):0;
}
static int icons_prepare(unsigned slot){(void)slot;return 0;}
static int icons_publish(void){return 0;}
static void icons_close(void){}
#endif
