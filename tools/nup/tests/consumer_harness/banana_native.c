#include <openssl/sha.h>
#define LOG(...) ((void)0)
#define DM_NUP_ZSTD 1
#include "nup_image.h"
int main(int argc, char**argv){
 if(argc!=2)return 2;char why[512]={0};romfs_img*m=nup_image_open(argv[1],why,sizeof why);
 if(!m){fprintf(stderr,"%s\n",why);return 3;}
 char **paths=calloc(m->n,sizeof(char*));paths[0]=strdup("");
 for(uint64_t k=0;k<m->n;k++){
  img_ent*x=&m->e[k];if(!x->type){for(uint64_t j=x->a;j<x->a+x->b;j++){
   img_ent*c=&m->e[j];size_t len=strlen(paths[k])+c->nlen+2;paths[j]=malloc(len);
   snprintf(paths[j],len,"%s%s%.*s",paths[k],*paths[k]?"/":"",c->nlen,m->names+c->name);
  }}else{
   const uint8_t*data;uint8_t*owned=NULL;
   if(x->flags&IMG_ENT_ZSTD){data=nup_z_get(m,x->a,why,sizeof why);if(!data){fprintf(stderr,"%s\n",why);return 4;}}
   else{owned=malloc(x->b?x->b:1);if(x->b&&!romfs_image_read(m->fd,owned,x->b,x->a))return 5;data=owned;}
   unsigned char hash[32];SHA256(data,x->b,hash);printf("FILE\t%s\t",paths[k]);for(int i=0;i<32;i++)printf("%02x",hash[i]);puts("");
   if(x->flags&IMG_ENT_ZSTD)nup_z_put(m,x->a);free(owned);
  }
 }
 for(uint64_t i=0;i<m->n;i++)free(paths[i]);free(paths);romfs_image_close(m);return 0;
}
