#pragma once
#include <sstream>
#include <string>
namespace fmt { template<class... T> std::string format(const char*, T... args) { std::ostringstream s; ((s << args << '_'),...); return s.str()+".tmp"; } }
