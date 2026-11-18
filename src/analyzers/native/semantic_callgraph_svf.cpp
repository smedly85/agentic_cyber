// Dedicated structured call-graph extractor for SVF 67efb774 (LLVM 21 line).
// Build this as an SVF tool; do not parse wpa's human-readable output.

#include "Graphs/ICFG.h"
#include "SVF-LLVM/LLVMModule.h"
#include "SVF-LLVM/LLVMUtil.h"
#include "SVF-LLVM/SVFIRBuilder.h"
#include "SVFIR/SVFVariables.h"
#include "Util/CommandLine.h"
#include "WPA/Andersen.h"

#include <llvm/IR/DebugInfoMetadata.h>
#include <llvm/IR/Function.h>
#include <llvm/IR/Instructions.h>
#include <llvm/Support/FormatVariadic.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/raw_ostream.h>

#include <algorithm>
#include <map>
#include <string>
#include <vector>

using namespace llvm;
using namespace SVF;

namespace {

struct SourceLocation {
    std::string file;
    unsigned line = 0;
    unsigned column = 0;
};

std::string normalizePath(std::string path) {
    std::replace(path.begin(), path.end(), '\\', '/');
    while (path.rfind("./", 0) == 0)
        path.erase(0, 2);
    // Absolute debug paths are intentionally not converted into identities.
    if ((!path.empty() && path.front() == '/') ||
        (path.size() > 1 && path[1] == ':'))
        return {};
    return path;
}

SourceLocation functionLocation(const Function *function) {
    SourceLocation result;
    if (const DISubprogram *subprogram = function->getSubprogram()) {
        result.file = normalizePath(subprogram->getFilename().str());
        result.line = subprogram->getLine();
    }
    return result;
}

SourceLocation valueLocation(const Value *value) {
    SourceLocation result;
    const auto *instruction = dyn_cast_or_null<Instruction>(value);
    if (!instruction)
        return result;
    const DebugLoc &debug = instruction->getDebugLoc();
    if (!debug)
        return result;
    result.file = normalizePath(debug->getFilename().str());
    result.line = debug.getLine();
    result.column = debug.getCol();
    return result;
}

json::Object locationJSON(const SourceLocation &location) {
    json::Object object;
    object["source_file"] = location.file.empty() ? json::Value(nullptr) : json::Value(location.file);
    object["line"] = location.line == 0 ? json::Value(nullptr) : json::Value(location.line);
    object["column"] = location.column == 0 ? json::Value(nullptr) : json::Value(location.column);
    return object;
}

std::string sourceName(const Function *function) {
    if (const DISubprogram *subprogram = function->getSubprogram()) {
        if (!subprogram->getName().empty())
            return subprogram->getName().str();
    }
    return function->getName().str();
}

std::string sourceQualifiedIdentity(const Function *function) {
    SourceLocation location = functionLocation(function);
    if (location.file.empty())
        return {};
    return location.file + "::" + sourceName(function);
}

std::string identity(const Function *function, bool sourceIdentityCollides) {
    std::string result = sourceQualifiedIdentity(function);
    if (result.empty())
        return result;
    // llvm-link renames colliding internal symbols when one source file is
    // compiled into more than one translation unit (for example xstrtol.c in
    // gnulib).  Preserve that compiler identity instead of conflating the
    // distinct functions.  Ordinary source identities remain concise.
    if (sourceIdentityCollides)
        result += "#llvm=" + function->getName().str();
    return result;
}

std::string linkage(const Function *function) {
    if (function->hasInternalLinkage()) return "internal";
    if (function->hasExternalLinkage()) return "external";
    if (function->hasWeakLinkage()) return "weak";
    return "other";
}

const Function *llvmFunction(LLVMModuleSet *modules, const FunObjVar *function) {
    if (!function || !function->hasLLVMValue()) return nullptr;
    return dyn_cast<Function>(modules->getLLVMValue(function));
}

} // namespace

int main(int argc, char **argv) {
    std::vector<std::string> modules = OptionBase::parseOptions(
        argc, argv, "Structured semantic may-call graph", "[options] <input-bitcode...>");
    LLVMModuleSet::preProcessBCs(modules);
    LLVMModuleSet::buildSVFModule(modules);
    SVFIRBuilder builder;
    SVFIR *pag = builder.build();
    Andersen *andersen = AndersenWaveDiff::createAndersenWaveDiff(pag);
    LLVMModuleSet *moduleSet = LLVMModuleSet::getLLVMModuleSet();

    std::map<std::string, unsigned> sourceIdentityCounts;
    for (const Function *function : moduleSet->getFunctionSet()) {
        if (function->isDeclaration() || function->isIntrinsic())
            continue;
        const std::string sourceIdentity = sourceQualifiedIdentity(function);
        if (!sourceIdentity.empty())
            ++sourceIdentityCounts[sourceIdentity];
    }
    std::map<const Function *, std::string> identities;
    json::Array functions;
    for (const Function *function : moduleSet->getFunctionSet()) {
        if (function->isDeclaration() || function->isIntrinsic())
            continue;
        const std::string sourceIdentity = sourceQualifiedIdentity(function);
        const std::string id = identity(function, sourceIdentityCounts[sourceIdentity] > 1);
        if (id.empty())
            continue;
        identities[function] = id;
        SourceLocation definition = functionLocation(function);
        json::Object row;
        row["identity"] = id;
        row["source_qualified_identity"] = sourceIdentity;
        row["llvm_symbol"] = function->getName().str();
        row["name"] = sourceName(function);
        row["source_file"] = definition.file;
        row["definition"] = locationJSON(definition);
        row["linkage"] = linkage(function);
        const FunObjVar *svfFunction = moduleSet->getFunObjVar(function);
        row["address_taken"] = svfFunction && svfFunction->hasAddressTaken();
        functions.push_back(std::move(row));
    }

    json::Array edges;
    json::Array unresolved;
    json::Array external;
    for (const auto &item : *pag->getICFG()) {
        const auto *call = SVFUtil::dyn_cast<CallICFGNode>(item.second);
        if (!call)
            continue;
        const Function *callerFunction = llvmFunction(moduleSet, call->getCaller());
        auto caller = identities.find(callerFunction);
        if (caller == identities.end())
            continue;
        const Value *callValue = call->hasLLVMValue() ? moduleSet->getLLVMValue(call) : nullptr;
        SourceLocation callsite = valueLocation(callValue);
        if (!call->isIndirectCall()) {
            const Function *calleeFunction = llvmFunction(moduleSet, call->getCalledFunction());
            auto callee = identities.find(calleeFunction);
            if (callee == identities.end()) {
                json::Object row;
                row["caller"] = caller->second;
                row["callee_name"] = calleeFunction ? sourceName(calleeFunction) : std::string("<unknown>");
                row["callsite"] = locationJSON(callsite);
                row["status"] = "external_or_unavailable_definition";
                external.push_back(std::move(row));
                continue;
            }
            json::Object row;
            row["caller"] = caller->second;
            row["callee"] = callee->second;
            row["edge_type"] = "direct";
            row["callsite"] = locationJSON(callsite);
            row["indirect_target_count"] = nullptr;
            row["indirect_target_set"] = nullptr;
            edges.push_back(std::move(row));
            continue;
        }

        std::vector<const Function *> targets;
        if (andersen->hasIndCSCallees(call)) {
            for (const FunObjVar *target : andersen->getIndCSCallees(call)) {
                const Function *function = llvmFunction(moduleSet, target);
                if (function && identities.count(function))
                    targets.push_back(function);
            }
        }
        std::sort(targets.begin(), targets.end(), [&](const Function *left, const Function *right) {
            return identities[left] < identities[right];
        });
        targets.erase(std::unique(targets.begin(), targets.end()), targets.end());
        if (targets.empty()) {
            json::Object row;
            row["caller"] = caller->second;
            row["callsite"] = locationJSON(callsite);
            row["status"] = "unresolved_indirect_callsite";
            unresolved.push_back(std::move(row));
            continue;
        }
        for (const Function *target : targets) {
            json::Object row;
            row["caller"] = caller->second;
            row["callee"] = identities[target];
            row["edge_type"] = "indirect_resolved";
            row["callsite"] = locationJSON(callsite);
            row["indirect_target_count"] = static_cast<int64_t>(targets.size());
            json::Array targetSet;
            for (const Function *possibleTarget : targets)
                targetSet.push_back(identities[possibleTarget]);
            row["indirect_target_set"] = std::move(targetSet);
            row["pointer_analysis_backend"] = "SVF";
            row["pointer_analysis"] = "andersen_wave_diff";
            edges.push_back(std::move(row));
        }
    }

    json::Object root;
    root["functions"] = std::move(functions);
    root["call_edges"] = std::move(edges);
    root["unresolved_indirect_callsites"] = std::move(unresolved);
    root["external_calls"] = std::move(external);
    root["failures"] = json::Array();
    outs() << formatv("{0:2}\n", json::Value(std::move(root)));

    AndersenWaveDiff::releaseAndersenWaveDiff();
    SVFIR::releaseSVFIR();
    LLVMModuleSet::releaseLLVMModuleSet();
    return 0;
}
