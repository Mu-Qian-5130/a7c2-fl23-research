/* Full C2 native records for the invocation-only look command. No offsets in input. */
#if API_FULL_NATIVE
typedef uint8_t u8;typedef uint32_t u32;typedef uint64_t u64;
#include "../fl23/native/sha256.h"
#define F_PREFIX 0xa000U
#define F_CAPACITY (0x20000U-F_PREFIX)
#define F_BASE 0x108000U
#define F_MAGIC 0x33465041U
#define F_TABLE 0xb27590U
#define F_MASK 0x1101ae8U
#define F_MATRIX 864U
#define F_CHROMA 48U
#define F_FIXED (F_MATRIX+F_CHROMA+14U*576U)
#define F_EDIT 2200U
#define F_FRAME (8U+1215U+F_EDIT)
static uint32_t full_fnv(const unsigned char *p,size_t n){uint32_t v=2166136261U;for(size_t i=0;i<n;i++)v=(v^p[i])*16777619U;return v;}
static uint32_t full_crc(const unsigned char *p,size_t n){uint32_t v=~0U;for(size_t i=0;i<n;i++){v^=p[i];for(int j=0;j<8;j++)v=(v>>1)^((v&1)?0xedb88320U:0);}return ~v;}
static void full_put16(unsigned char *p,int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static int full_edit_valid(const unsigned char *p){
    unsigned char digest[32];SHA256 hash;
    if(memcmp(p,"A7C2ED02",8)||get32(p+8)!=2152||get32(p+12)!=full_crc(p+48,2152))return bad("full-edit-integrity");
    sha_init(&hash);sha_add(&hash,p+48,2152);sha_end(&hash,digest);if(memcmp(digest,p+16,32))return bad("full-edit-integrity");
    const unsigned char *axis=p+80,*base=p+592,*fit=p+1396;
    if(get32(axis)||get32(axis+127*4)!=65535U*32)return bad("full-edit-axis");
    for(int i=1;i<128;i++)if(get32(axis+i*4)<=get32(axis+(i-1)*4))return bad("full-edit-axis");
    if(memcmp(base,fit,24)||memcmp(base+216,fit+216,60))return bad("full-edit-common");
    for(int k=0;k<2;k++){
        const unsigned char *q=k?fit:base;const unsigned char *gamma=q+292;
        if(get32(gamma))return bad("full-edit-gamma");
        for(int i=0;i<128;i++){uint32_t y=get32(gamma+i*4);if(y>0x3ffffU||(i&&y<get32(gamma+(i-1)*4)))return bad("full-edit-gamma");if(k&&(y&1))return bad("full-edit-gamma-precision");}
    }
    for(int i=4;i<8;i++){int v=get16(fit+276+i*2);if(v<0||v>2046||(v&1))return bad("full-edit-cc1-precision");}
    return 0;
}
static int full_frame(const unsigned char *data,size_t size){return size==F_FRAME&&!memcmp(data,"A7F2LOOK",8);}
static int full_axis(const unsigned char *record,uint32_t *nodes){
    static const uint32_t widths[]={32,32,64,128,256,512,1024,2048,4096,8192,16384,32768};
    static const uint32_t bases[]={0,32,64,128,256,512,1024,2048,4096,8192,16384,32768};
    unsigned count=0;nodes[0]=0;
    for(int i=0;i<12;i++){
        unsigned shift=record[0x204+i];if(shift>15)return bad("full-native-axis");unsigned step=widths[i]>>shift;if(!step)return bad("full-native-axis");
        unsigned n=widths[i]/step;for(unsigned j=1;j<=n&&count<128;j++){uint32_t x=bases[i]+j*step;if(x>65535)x=65535;nodes[++count]=x;}
    }
    if(count!=128||nodes[128]!=65535)return bad("full-native-axis");
    for(int i=1;i<129;i++)if(nodes[i]<=nodes[i-1])return bad("full-native-axis");return 0;
}
static int full_curve(unsigned char *record,const unsigned char *edit,const int *tone){
    uint32_t nodes[129];if(full_axis(record,nodes))return -1;uint32_t old_top=get32(record+512),top=old_top;
    if(!old_top||old_top>0x3ffffU||get32(record+0x220)!=old_top)return bad("full-native-endpoint");
    if(edit){
        const unsigned char *axis=edit+80,*y=edit+1688;
        for(int i=0;i<128;i++){uint32_t x=(i==127?nodes[128]:nodes[i])*32U;if(get32(axis+i*4)!=x)return bad("full-native-axis");put32(record+i*4,get32(y+i*4)/2U);}
        uint32_t last=get32(record+127*4);if(last>top)top=last;put32(record+128*4,top);
    }else if(tone){
        for(int i=0;i<129;i++){
            int64_t y=get32(record+i*4),x=(y<<12)/old_top,v=4096-x;
            int64_t a=(y*tone[0])>>10,b=(((((y*tone[1])>>10)*v)>>12)*v)>>12;
            int64_t c=(((((y*tone[2])>>10)*x)>>12)*v)>>12,value=y+a+b+c;
            if(value<0)value=0;if(value>0x3ffff)value=0x3ffff;put32(record+i*4,(uint32_t)value);
        }top=get32(record+512);
    }
    for(int i=1;i<129;i++)if(get32(record+i*4)<get32(record+(i-1)*4))return bad("full-native-monotone");put32(record+0x220,top);return 0;
}
static int full_expand(unsigned char *out,const int *v){
    int a[9]={v[0]+v[1],-v[0],-v[1],-v[2],v[2]+v[3],-v[3],-v[4],-v[5],v[4]+v[5]};
    for(int i=0;i<9;i++){if(a[i]<-32768||a[i]>32767)return bad("full-matrix-overflow");full_put16(out+i*2,a[i]);}return 0;
}
static int full_entry(int fd,const unsigned char *bank,const unsigned char *data,size_t size,unsigned char **result,unsigned *kind,unsigned *length){
    const unsigned char *edit=NULL;int present=0,tone[3]={0},mat[3][6]={{0}},chroma[24]={0};unsigned char encoded[90];unsigned encoded_size=0;
    if(full_frame(data,size)){edit=data+8+1215;if(full_edit_valid(edit))return -1;*kind=2;encoded_size=F_EDIT;}
    else{
        if(size!=1324||data[1215]>1)return bad("look-size");present=data[1215];*kind=present?1:0;
        if(present){
            for(int i=0;i<3;i++){tone[i]=get16(data+1216+i*2);if(tone[i]<-1024||tone[i]>1024)return bad("look-range");full_put16(encoded+i*2,tone[i]);}
            static const int select[]={1,2,3,5,6,7};
            for(int p=0;p<3;p++){
                int v[9];for(int i=0;i<9;i++)v[i]=get16(data+1216+(3+p*9+i)*2);
                for(int i=0;i<3;i++)if(v[i*3]+v[i*3+1]+v[i*3+2])return bad("look-matrix");
                for(int j=0;j<6;j++){mat[p][j]=-v[select[j]];if(mat[p][j]<-1024||mat[p][j]>1024)return bad("look-range");full_put16(encoded+6+(p*6+j)*2,mat[p][j]);}
            }
            for(int i=0;i<24;i++){chroma[i]=get16(data+1216+(30+i)*2);if(chroma[i]<-1024||chroma[i]>1024)return bad("look-range");full_put16(encoded+42+i*2,chroma[i]);}encoded_size=90;
        }
    }
    *length=F_FIXED+4+encoded_size;unsigned char *out=calloc(1,*length);if(!out)return bad("memory");
    const unsigned char *fit=edit?edit+1396:NULL;
    for(int s=0;s<16;s++)for(int p=0;p<3;p++){
        int values[6];for(int j=0;j<6;j++)values[j]=edit?(get16(fit+24+2*(16*j+(s^1)))>>2)-get16(bank+1152+(p*96+s*6+j)*2):mat[p][j];
        if(full_expand(out+s*54+p*18,values))goto fail;
    }
    static const int order[]={1,2,3,0,5,6,7,4};
    for(int p=0;p<3;p++)for(int j=0;j<8;j++){
        int d=chroma[p*8+j];if(edit){int desired=get16(fit+276+order[j]*2);if(j>=4)desired/=2;int original=get16(bank+1728+j*2);if(p)original=(int16_t)(original+get16(bank+1728+p*16+j*2));d=desired-original;}
        if(d<-32768||d>32767){bad("full-chroma-overflow");goto fail;}full_put16(out+F_MATRIX+(p*8+j)*2,d);
    }
    for(int domain=0;domain<2;domain++)for(int col=0;col<7;col++){
        unsigned char pointer[4];unsigned row=domain?10:0;
        if(transfer(fd,pointer,4,0x1209480-F_BASE+row*28+col*4,0))goto fail;
        uint32_t p=get32(pointer);if(!p){if(transfer(fd,pointer,4,0x1209480-F_BASE+24,0))goto fail;p=get32(pointer);}
        if(p<F_BASE||p-F_BASE>cp_file_size-576){bad("full-native-pointer");goto fail;}
        unsigned char *record=out+F_MATRIX+F_CHROMA+(domain*7+col)*576;
        if(transfer(fd,record,576,p-F_BASE,0)||full_curve(record,edit,present?tone:NULL))goto fail;
    }
    put32(out+F_FIXED,encoded_size);if(edit)memcpy(out+F_FIXED+4,edit,encoded_size);else if(encoded_size)memcpy(out+F_FIXED+4,encoded,encoded_size);
    *result=out;return 0;
fail:free(out);return -1;
}
static int full_prepare(int fd,int slot,const unsigned char *data,size_t size,unsigned char **prepared,unsigned char *gamma_table,unsigned char *mask){
    unsigned char *old=malloc(F_CAPACITY),*next=NULL,*entry=NULL;if(!old)return bad("memory");int result=-1;
    if(transfer(fd,old,F_CAPACITY,F_PREFIX,0))goto done;
    unsigned total=get32(old+8),active=get32(old+12);unsigned char installed_mask[4];
    if(transfer(fd,installed_mask,4,F_MASK,0))goto done;
    if(get32(old)!=F_MAGIC||get32(old+4)!=1||get32(old+20)!=1792||active>63||get32(installed_mask)!=active||total<1920||total>F_CAPACITY||get32(old+16)!=full_fnv(old+128,total-128)){bad("full-prefix");goto done;}
    unsigned kind,length;if(full_entry(fd,old+128,data,size,&entry,&kind,&length))goto done;
    next=calloc(1,F_CAPACITY);if(!next){bad("memory");goto done;}memcpy(next,old,1920);unsigned at=1920;
    unsigned char live_table[50*28];
    if(transfer(fd,gamma_table,50*28,F_TABLE,0)||transfer(fd,live_table,sizeof(live_table),0x1209480-F_BASE,0))goto done;
    if(memcmp(live_table,gamma_table,sizeof(live_table))){bad("full-gamma-table");goto done;}
    for(int i=0;i<6;i++){
        const unsigned char *body=entry;unsigned n=length,k=kind;
        if(i!=slot-1){unsigned offset=get32(old+32+i*16);n=get32(old+36+i*16);k=get32(old+44+i*16);
            if(offset<1920||n<F_FIXED+4||n>F_FIXED+4+F_EDIT||offset>total||n>total-offset||k>2||!!k!=!!(active&(1U<<i))||full_fnv(old+offset,n)!=get32(old+40+i*16)){bad("full-prefix-slot");goto done;}
            body=old+offset;
        }
        at=(at+3)&~3U;if(n>F_CAPACITY-at){bad("full-prefix-space");goto done;}memcpy(next+at,body,n);
        put32(next+32+i*16,at);put32(next+36+i*16,n);put32(next+40+i*16,full_fnv(body,n));put32(next+44+i*16,k);
        for(int d=0;d<2;d++)for(int col=0;col<7;col++)put32(gamma_table+(50+i*2+d)*28+col*4,F_BASE+F_PREFIX+at+F_MATRIX+F_CHROMA+(d*7+col)*576);
        if(k)active|=1U<<i;else active&=~(1U<<i);at+=n;
    }
    put32(next+8,at);put32(next+12,active);put32(next+16,full_fnv(next+128,at-128));put32(mask,active);
    *prepared=next;next=NULL;result=0;
done:free(next);free(entry);free(old);return result;
}
#endif
