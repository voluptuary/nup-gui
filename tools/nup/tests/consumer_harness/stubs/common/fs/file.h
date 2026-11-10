#pragma once
#include <cstdio>
#include <span>
#include <filesystem>
#include "common/common_types.h"
namespace Common::FS {
enum class FileAccessMode { Read, Write };
class IOFile { FILE* f{};
public:
 IOFile()=default; IOFile(const std::filesystem::path& p, FileAccessMode m){Open(p,m);} ~IOFile(){Close();}
 IOFile(const IOFile&)=delete; IOFile& operator=(const IOFile&)=delete;
 void Open(const std::filesystem::path& p,FileAccessMode m){Close();f=fopen(p.c_str(),m==FileAccessMode::Read?"rb":"wb");}
 void Close(){if(f){fclose(f);f=nullptr;}} bool IsOpen() const{return f;}
 bool Seek(s64 p){return f && fseeko(f,p,SEEK_SET)==0;}
 template<class T> size_t ReadSpan(std::span<T> p){return f?fread(p.data(),sizeof(T),p.size(),f):0;}
 template<class T> size_t WriteSpan(std::span<T> p){return f?fwrite(p.data(),sizeof(T),p.size(),f):0;}
}; }
