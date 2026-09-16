# Copy this directory below svf-llvm/tools in the pinned SVF checkout and add
# add_subdirectory(SemanticCallGraph) to svf-llvm/tools/CMakeLists.txt.
add_llvm_executable(semantic-callgraph-svf semantic_callgraph_svf.cpp)

# The upstream tools directory links its built-in executables to these targets
# from a fixed ALL_TOOLS list.  This repository-added target is intentionally
# outside that list, so declare the dependencies here.  Their PUBLIC
# build-interface include directories provide svf/include and svf-llvm/include
# without embedding checkout-specific absolute paths.
target_link_libraries(semantic-callgraph-svf PRIVATE SvfCore SvfLLVM)
