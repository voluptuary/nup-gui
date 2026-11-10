#pragma once
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>
namespace Common::FS {
enum class EdenPath{CacheDir};
inline std::filesystem::path GetEdenPath(EdenPath){return "/tmp/nup-consumer-audit/spill";}
inline std::string SanitizePath(std::string_view p){return std::string(p);}
inline std::string GetParentPath(std::string_view p){return std::filesystem::path(p).parent_path().string();}
inline std::string GetFilename(std::string_view p){return std::filesystem::path(p).filename().string();}
inline std::string GetExtensionFromFilename(std::string_view p){auto x=std::filesystem::path(p).extension().string();return x.empty()?x:x.substr(1);}
inline std::vector<std::string> SplitPathComponents(std::string_view p){std::vector<std::string> v;for(auto& part:std::filesystem::path(p)){auto s=part.string();if(!s.empty()&&s!="/")v.push_back(s);}return v;}
inline std::string GetPathWithoutTop(std::string_view p){auto x=p.find('/');return x==p.npos?"":std::string(p.substr(x+1));}
}
