/* Guest test utility; excluded from the camera/product payload. */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
int main(int argc,char **argv){
 if(argc==2&&!strcmp(argv[1],"setup")){
  int image=open("/tmp/native.updater",O_RDWR),loop=open("/dev/loop1",O_RDWR);
  int result=image<0||loop<0?-1:ioctl(loop,0x4c00,image);
  if(image>=0)close(image);if(loop>=0)close(loop);return result?1:0;
 }
 if(argc==3&&!strcmp(argv[1],"hex")){
  FILE *input=fopen(argv[2],"rb");if(!input)return 1;
  int value;unsigned count=0;while((value=fgetc(input))!=EOF&&count++<512)printf("%02x",value);
  int failed=ferror(input);fclose(input);return failed?1:0;
 }
 if(argc==4&&!strcmp(argv[1],"compare")){
  FILE *a=fopen(argv[2],"rb"),*b=fopen(argv[3],"rb");if(!a||!b)return 1;
  unsigned char x[16384],y[16384];size_t n,m;
  do{n=fread(x,1,sizeof(x),a);m=fread(y,1,sizeof(y),b);if(n!=m||memcmp(x,y,n))return 1;}while(n);
  int failed=ferror(a)||ferror(b);fclose(a);fclose(b);return failed?1:0;
 }
 return 2;
}
