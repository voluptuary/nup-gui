#include <fstream>
#include <iterator>
#include <iostream>
#include <iomanip>
#include "core/file_sys/nup_container.h"
int main(int argc,char**argv){
 if(argc<2)return 2;
 std::ifstream input(argv[1],std::ios::binary);std::vector<u8> data((std::istreambuf_iterator<char>(input)),{});
 auto backing=std::make_shared<FileSys::VectorVfsFile>(std::move(data),argv[1]);
 for(auto cap:{size_t(512*1024*1024),size_t(4096)}){
 FileSys::NupContainer container(backing,cap,std::filesystem::path(argv[1]).parent_path()/"spill");
 if(container.GetStatus()!=Loader::ResultStatus::Success){std::cerr<<"parse rejected\n";return 3;}
 if(argc>=4){const auto& p=container.GetPackages().front();if(p.title_name!=argv[2]||p.publisher!=argv[3]||p.icon.empty()){std::cerr<<"metadata mismatch\n";return 6;}}
 if(container.VerifyIntegrity({})!=Loader::ResultStatus::Success){std::cerr<<"integrity failed\n";return 4;}
 for(size_t i=0;i<container.GetFileCount();i++){
  auto file=container.OpenFile(i);if(!file || file->ReadAllBytes().size()!=file->GetSize())return 5;
 }
 std::cout<<"OK files="<<container.GetFileCount()<<" packages="<<container.GetPackages().size()<<" cap="<<cap<<"\n";
 if(cap>4096)for(const auto&p:container.GetPackages())std::cout<<"META "<<p.title_id<<" "<<p.version<<" "<<int(p.kind)<<" "<<std::quoted(p.title_name)<<" "<<std::quoted(p.publisher)<<" "<<std::quoted(p.display_version)<<" "<<p.icon.size()<<"\n";
 }
}
