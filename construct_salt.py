#!/usr/bin/env python
# -*- coding: utf-8 -*-

import shutil
import time
import angr
import sys
import capstone
from collections import defaultdict
import random
random.seed(123456789)

class LogicalBlock:
    def __init__(self, name):
        self.name = name
        self.assembly = []
        self.children = []
        self.all_asm = []
        self.block_num = 0
        self.logical_block = []
        self.start_addr = None
        self.end_addr = None
        self.path = ""
        self.already_address = set()
        self.all_address = set()

    def add_instruction(self, instruction, addr):
        if (addr, instruction) not in self.assembly:
            self.assembly.append((addr, instruction))
        if self.start_addr is None or addr < self.start_addr:
            self.start_addr = addr
        if self.end_addr is None or addr > self.end_addr:
            self.end_addr = addr

    def add_child(self, child):
        self.children.append(child)

    def check_is_suitable(self):
        if len(self.already_address) == len(self.all_address) and len(self.already_address - self.all_address) == 0:
            return True
        return False
        pass

    def __str__(self, level=0):
        indent = "  " * level
        ret = f"{indent}<<{self.name}>> : {{\n"
        for addr, instr in sorted(self.assembly):
            self.already_address.add(addr)
            ret += f"{indent}  {hex(addr)} :\t {instr}\n"
        for child in self.children:
            ret += child.__str__(level + 1)
            self.already_address = self.already_address.union(child.already_address)
            #child.already_address = []
        ret += f"{indent}}}\n"
        return ret

    def sort_asm(self, asms):
        body_addrs = {addr: asm for addr, asm in asms}
        return [(key, body_addrs[key]) for key in sorted(body_addrs.keys())]

    def to_json(self):
        return {
            "name": self.name,
            "assembly": self.sort_asm(self.assembly),
            # "assembly": self.assembly,
            "children": [child.to_json() for child in self.children],
            "logical_block": self.logical_block#,
            #"all_asm": self.all_asm
        }

def analyze_binary(binary_path, funcName):
    # Loading binary files
    proj = angr.Project(binary_path, arch="x86_64", auto_load_libs=False, main_opts={'base_addr': 0})
    # Generate CFG
    cfg = proj.analyses.CFGFast(normalize=True, resolve_indirect_jumps=True, collect_data_references=True)

    # Get all functions
    functions = cfg.kb.functions.values()

    for func in functions:
        if func.is_plt or func.is_simprocedure or func.is_syscall:
            continue  # # Skip library functions and system calls

        if func.name != funcName:
            continue
        # Create a root logical block
        root_block = LogicalBlock(func.name)

        # Analyze functions and build a logical block tree
        obj_ams = objdump(binary_path, binary_path + ".s", funcName)
        root_block.path = binary_path
        root_block.start_addr = func.addr
        analyze_function(proj, cfg, func, root_block, obj_ams)

        # Output logic block tree
        root_block.__str__()
        if root_block.check_is_suitable():
            return root_block.to_json(), 1
        else:
            return {
                "name": root_block.name,
                "assembly": root_block.sort_asm(root_block.all_asm),
                "children": [],
                "logical_block": root_block.logical_block
            }, 0
        #print("\n" + "="*50 + "\n")

def analyze_function(proj, cfg, func, parent_block, obj_ams):
    # Get all nodes within the function
    function_nodes = [n for n in cfg.graph.nodes() if n.function_address == func.addr]

    block_dict = {}
    predecessors = defaultdict(list)
    successors = defaultdict(list)

    # Construct basic block dictionary and predecessor and successor relationships
    for node in function_nodes:
        addr = node.addr
        block_dict[addr] = node

        for succ in cfg.graph.successors(node):
            if succ.function_address == func.addr:
                successors[addr].append(succ.addr)
                predecessors[succ.addr].append(addr)

        for insn in proj.factory.block(node.addr).capstone.insns:
            parent_block.all_address.add(insn.address)
            parent_block.all_asm.append((addr, f"{insn.mnemonic}\t{insn.op_str}"))

    # Detection cycle
    loops = detect_loops(cfg, func, proj)

    # Processed basic blocks
    visited_blocks = set()

    # Start processing from the function entry
    entry_node = block_dict.get(func.addr)
    if entry_node:
        block_num = 0
        process_block(proj, cfg, entry_node, parent_block, visited_blocks, loops, block_dict, successors, parent_block, predecessors, block_num, obj_ams)
    else:
        print(f"function {func.name} Entry address {hex(func.addr)} No corresponding basic block was found.")

def obtain_loop_nodes(loop, successors):
    body_nodes, body_nodes_addr = obtain_loop_nodes_addr(loop, successors)
    body_addrs = {node.addr: node for node in body_nodes}
    loop_nodes = {key: body_addrs[key] for key in sorted(body_addrs)}
    # loop_nodes = body_addrs
    return loop_nodes.values()
    pass

def process_block(proj, cfg, node, parent_block, visited_blocks, loops, block_dict, successors, root_node, predecessors, block_num, obj_ams):
    addr = node.addr
    if addr in visited_blocks:
        return
    visited_blocks.add(addr)

    # Check if you are in a loop
    loop = in_loop(addr, loops, successors)
    if loop and loop.entry.addr == addr and not loop.processed:
        loop.processed = True
        loop_block = LogicalBlock(f"<<BLOCK_{str(root_node.block_num)}>>")
        parent_block.add_child(loop_block)

        instrs = get_node_instructions(proj, node, root_node, cfg, obj_ams)
        for instr_addr, instr in instrs:
            loop_block.add_instruction(instr, instr_addr)

        parent_block.add_instruction(f"<<BLOCK_{str(root_node.block_num)}>>", addr)
        root_node.logical_block.append((f"<<BLOCK_{str(root_node.block_num)}>>", addr))#{root_node.name} #BLOCK
        root_node.block_num += 1
        # Collect all basic blocks in the loop body
        for sub_loop in loop.subloops:
            process_block(proj, cfg, block_dict[sub_loop.entry.addr], loop_block, visited_blocks, loops, block_dict, successors, root_node, predecessors, block_num, obj_ams)
        out_nodes = []
        in_nodes = []
        for in_edge in loop.entry_edges:
            if in_edge[0] not in in_nodes:
                in_nodes.append(in_edge[0])
        for out_edge in loop.break_edges:
            if out_edge[1] not in out_nodes and len(successors[out_edge[1].addr]) != 0:
                out_nodes.append(out_edge[1])
        loop_nodes = obtain_loop_nodes(loop, successors)
        loop_nodes_addr = []
        for node in loop.graph.nodes():
            if node not in loop.subloops and node not in out_nodes and node not in in_nodes:
                loop_nodes_addr.append(node.addr)
        for loop_node in loop_nodes:
            if loop_node.addr in visited_blocks:
                continue
            visited_blocks.add(loop_node.addr)
            instrs = get_node_instructions(proj, block_dict[loop_node.addr], root_node, cfg, obj_ams)

            for instr_addr, instr in instrs:

                loop_block.add_instruction(instr, instr_addr)
        # Continue processing the subsequent block
        for out_node in out_nodes:
            if out_node.addr not in visited_blocks and out_node.addr in block_dict:
                succ_node = block_dict[out_node.addr]
                process_block(proj, cfg, succ_node, parent_block, visited_blocks, loops, block_dict, successors, # should [FIX]: parent_block -> ? root_node
                              root_node, predecessors, block_num, obj_ams)
    else:
        # Check if it is a conditional jump
        # block = proj.factory.block(addr)
        # if is_conditional_jump(block):
        #     cond_block = LogicalBlock(f"{parent_block.name}_if_{addr:x}")
        #     parent_block.add_child(cond_block)
        #
        #     instrs = get_node_instructions(proj, node)
        #     for instr_addr, instr in instrs:
        #         cond_block.add_instruction(instr, instr_addr)
        #
        #     true_branch, false_branch = get_true_false_branch(block, node, successors)
        #
        #     # Processing the True branch
        #     if true_branch and true_branch not in visited_blocks and true_branch in block_dict:
        #         true_node = block_dict[true_branch]
        #         true_block = LogicalBlock(f"{cond_block.name}_true")
        #         cond_block.add_child(true_block)
        #         process_block(proj, cfg, true_node, true_block, visited_blocks, loops, block_dict, successors)
        #
        #     # Handling False Branches
        #     if false_branch and false_branch not in visited_blocks and false_branch in block_dict:
        #         false_node = block_dict[false_branch]
        #         false_block = LogicalBlock(f"{cond_block.name}_false")
        #         cond_block.add_child(false_block)
        #         process_block(proj, cfg, false_node, false_block, visited_blocks, loops, block_dict, successors)
        # else:
        # Common basic blocks
        # if loop and addr in [bn.addr for bn in loop.body_nodes]:
        #     return
        instrs = get_node_instructions(proj, node, root_node, cfg, obj_ams)
        for instr_addr, instr in instrs:
            parent_block.add_instruction(instr, instr_addr)

        # Continue processing the subsequent block
        for succ_addr in successors.get(addr, []):
            if succ_addr not in visited_blocks and succ_addr in block_dict:
                succ_node = block_dict[succ_addr]
                # If the current basic block is connected to the subsequent basic block through a call instruction, then merge
                last_instr = instrs[-1][1] if instrs else None
                if last_instr and is_call_instruction(last_instr):
                    merge_blocks(proj, cfg, succ_node, parent_block, visited_blocks, loops, block_dict, successors, root_node, predecessors, block_num, obj_ams)
                else:
                    process_block(proj, cfg, succ_node, parent_block, visited_blocks, loops, block_dict, successors, root_node, predecessors, block_num, obj_ams)

def merge_blocks(proj, cfg, node, parent_block, visited_blocks, loops, block_dict, successors, root_node, predecessors, block_num, obj_ams):
    # Merge the current node into the parent logic block
    instrs = get_node_instructions(proj, node, root_node, cfg, obj_ams)
    for instr_addr, instr in instrs:
        parent_block.add_instruction(instr, instr_addr)

    # Mark this node as visited
    visited_blocks.add(node.addr)
    for succ_addr in successors.get(node.addr, []):
        if succ_addr not in visited_blocks and succ_addr in block_dict:
            succ_node = block_dict[succ_addr]
            process_block(proj, cfg, succ_node, parent_block, visited_blocks, loops, block_dict, successors, root_node, predecessors, block_num, obj_ams)

def obtain_all_loops(loop):
    loops = [loop]
    for sub_loop in loop.subloops:
        loops += obtain_all_loops(sub_loop)
    return loops

from loop_location import LoopLocation


def detect_loops(cfg, func, proj):
    '''

    '''
    loop_finder = LoopLocation(proj, cfg, normalize=True)
    loops = []
    all_loops = []
    for loop in loop_finder.loops:
        loop_node = cfg.get_any_node(loop.entry.addr)
        if loop_node and loop_node.function_address:# and loop not in all_loops:
            if loop_node.function_address == func.addr:
                loop.processed = False
                loops.append(loop)
                all_loops.extend(obtain_all_loops(loop))
    return loops

def obtain_loop_nodes_addr(loop, successors):
    out_nodes = []
    in_nodes = []
    for in_edge in loop.entry_edges:
        if in_edge[0] not in in_nodes:
            in_nodes.append(in_edge[0])
    for out_edge in loop.break_edges:
        if out_edge[1] not in out_nodes and len(successors[out_edge[1].addr]) != 0:
            out_nodes.append(out_edge[1])
    loop_nodes = []
    loop_nodes_addr = []
    for node in loop.graph.nodes():
        if node not in loop.subloops and node not in out_nodes and node not in in_nodes:
            loop_nodes.append(node)
            loop_nodes_addr.append(node.addr)
    return loop_nodes, loop_nodes_addr

def in_loop(addr, loops, successors):
    for loop in loops:
        _, loop_nodes_addrs = obtain_loop_nodes_addr(loop, successors)
        if addr in loop_nodes_addrs:
            return loop
    return None

def is_call_instruction(instr):
    # Check if the instruction is a call
    return instr.startswith('call')

def is_jump(insn):
    # Use Capstone to determine whether it is a conditional jump instruction
    if insn.mnemonic.startswith('j'):
        return True
    return False

def get_true_false_branch(block, node, successors):
    last_insn = block.capstone.insns[-1]
    succ_addrs = []
    for succ_addr in successors.get(node.addr, []):
        if succ_addr not in succ_addrs:
            succ_addrs.append(succ_addr)
    true_branch = None
    false_branch = None

    # Get the target address of the jump instruction (true branch)
    if last_insn.operands and last_insn.operands[0].type == capstone.CS_OP_IMM:
        true_branch = last_insn.operands[0].imm
        if true_branch not in succ_addrs:
            true_branch = None

    # False branches are other successor nodes
    for addr in succ_addrs:
        if addr != true_branch:
            false_branch = addr
            break

    return true_branch, false_branch

def get_section_name(proj, addr):
    """Get the name of the section where the given address is located"""
    data_segs = ['.rodata', '.bss', '.data', '.idata']
    for section in proj.loader.main_object.sections:
        if section.contains_addr(addr):
            seg_name = section.name.lower()
            if seg_name in data_segs:
                return section.name
    return None

def tran_digit_to_hex(op_str):
    if "$" not in op_str:
        return op_str
    op_str_new = op_str.replace("$", "")
    try:
        op_str_new = "$" + str(hex(int(op_str_new, 10)))
        return op_str_new
    except:
        return op_str

def objdump(obj_output, asm_output, fname):
    subprocess.run(
        f"objdump -d {obj_output} > {asm_output}",
        shell=True,  # Use shell to handle redirection
        check=True,
    )

    with open(asm_output) as f:
        asm = str(f.read())
        ##### start of clean up

        function_name_chk = "<" + fname + ">:"
        # IMPORTANT replace func0 with the function name
        if function_name_chk not in asm:
            raise ValueError("Function not found in asm!")

        # IMPORTANT replace func0 with the function name
        asm = function_name_chk + asm.split(function_name_chk)[-1].split("\n\n")[0]
        asm_sp = asm.split("\n")

        asm_blocks = {}
        for tmp in asm_sp[1:]:
            if len(tmp.split("\t")) < 3 and "00" in tmp:
                continue
            idx = min(len(tmp.split("\t")) - 1, 2)
            tmp_asm = "\t".join(tmp.split("\t")[idx:])  # remove the binary code
            tmp_asm = tmp_asm.split("#")[0].strip()  # remove the comments
            tmp_asm = "\t".join([ta for ta in tmp_asm.split(" ") if len(ta) != 0])
            tmp_addr = int(tmp.split("\t")[0].lstrip().split(":")[0], 16)
            if tmp_addr not in asm_blocks: #and "nop" not in tmp_asm.split("\t")[0]
                asm_blocks[tmp_addr] = tmp_asm
        return asm_blocks

def get_node_instructions(proj, node, root_node, cfg, obj_asms):
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.syntax = capstone.CS_OPT_SYNTAX_ATT
    block = proj.factory.block(node.addr)
    instrs = []
    for insn in cs.disasm(block.bytes, block.addr):
        if insn.address >= node.addr and insn.address < node.addr + node.size:
            data_comment = ""
            if insn.address in cfg.insn_addr_to_memory_data:
                memory_data = cfg.insn_addr_to_memory_data[insn.address]
                if isinstance(memory_data, list):
                    data_list = []
                    data_seg = ""
                    for mem_data in memory_data:
                        if mem_data is not None:
                            mem_data_str = process_data_reference(mem_data.addr, proj)
                            if mem_data_str is not None:
                                if get_section_name(proj, mem_data.addr):
                                    data_list.append(mem_data_str)
                    data_comment = ", ".join(data_list)
                else:
                    if memory_data is not None:
                        mem_data_str = process_data_reference(memory_data.addr, proj)
                        if mem_data_str is not None:
                            # print("find data:" + data_comment + "----" + get_section_name(proj, memory_data.addr) )
                            if get_section_name(proj, memory_data.addr):
                                data_comment = mem_data_str
            mnemonic = insn.mnemonic
            op_str = insn.op_str
            ops_new = []
            for ops in str(op_str).split(","):
                ops = tran_digit_to_hex(ops.lstrip().rstrip())
                ops_new.append(ops)
            op_str = ",".join(ops_new)
            if is_jump(insn):
                offset = hex(int(op_str, 16) - root_node.start_addr)
                new_op_str = "" + str(op_str).replace("0x", "") + " <" + root_node.name + "+" + str(offset) + ">"
                op_str = new_op_str
            if data_comment != "":
                # data_comment = '"' + data_comment + '"'
                op_str = op_str + "\t;" + data_comment

            if is_call_instruction(mnemonic):
                fn = proj.kb.functions.get(int(op_str, 16)).name
                ins_call = "call\t" + str(op_str).replace("0x", "") + " <" + fn + "@plt>"
                instrs.append((insn.address, ins_call))
                continue
            if len(op_str) != 0:
                instrs.append((insn.address, f"{mnemonic}\t{op_str}"))
            else:
                instrs.append((insn.address, mnemonic))
    return instrs

import os
import subprocess

def compile(func_def, tmp_dir, function_name):
    code_file = os.path.join(tmp_dir, "code.c")
    with open(code_file, "w") as f:
        f.write(func_def)
    formatted_code_file = os.path.join(tmp_dir, "formatted_code.c")
    proc_compile = subprocess.run(
        ["clang-format", code_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        encoding="utf-8")
    formatted_code = proc_compile.stdout.strip()

    with open(formatted_code_file, "w") as f:
        f.write(formatted_code)
    ans = {}
    for optimization in ["-O0", "-O1", "-O2", "-O3"]:
        binary_file = os.path.join(tmp_dir, f"code{optimization}")
        try:
            proc_compile = subprocess.run(
                ["gcc",
                 "-shared",
                 "-fPIC",
                 optimization,
                 "-o",
                 binary_file,
                 formatted_code_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                encoding="utf-8",
                timeout=12)
            data, status = analyze_binary(binary_file, function_name)
            ans[optimization] = data
            if status == 0:
                print("logical block is error!")
        except:
            print("gcc compile error!")
            continue
    return ans

def get_all_addrs(asms):
    addrs = []
    asm_ins = []
    for asm in asms:
        addrs.append(int(asm[0]))
        asm_ins.append(asm[1])
    return addrs, asm_ins

def analyse_logical_tree_child(child, block_addrs):
    deps_names = set()
    for block_name, block_addr in block_addrs.items():
        # [should FIX]: pass the bro block
        if len(set(block_addr).intersection(child["dep_addrs"])) != 0:
            deps_names.add(block_name)
    child["deps_names"] = list(deps_names)
    childs_new = []
    for child_new in child["children"]:
        childs_new.append(analyse_logical_tree_child(child_new, block_addrs))
    child["children"] = childs_new
    return child

def process_data_reference(addr, p):
    try:
        # try to read string
        string_at = p.loader.memory.load(addr, 500)  # Maximum read 500 bytes
        null_term = string_at.find(b'\x00')
        if null_term != -1:
            string_at = string_at[:null_term]
        try:
            # try to decode string
            decoded = string_at.decode('utf-8')
            if decoded.isprintable() and len(decoded) > 0:
                return decoded
            raise UnicodeDecodeError("Not a valid string")
        except UnicodeDecodeError:
            # only string
            return None

            # [FIX]: If not a string, read as an integer
            # try:
            #     return str(p.loader.memory.unpack_word(addr))
            # except:
            #     return None
    except:
        return None

def analyse_logical_tree(block_addrs, logical_block_dict):
    # blocks, block_addrs = get_bin_blocks(logical_tree)
    childs_new = []
    for child in logical_block_dict["children"]:
        childs_new.append(analyse_logical_tree_child(child, block_addrs))
    logical_block_dict["children"] = childs_new
    return logical_block_dict

import json
import tqdm

def get_bin_blocks(bin_blocks):
    bin_blocks_all = {}
    bin_blocks_all_addrs = {}
    asms = ""
    addrs = []
    for asm in bin_blocks["assembly"]:
        asms += asm[1].strip() + "\n"
        addrs.append(asm[0])
    bin_blocks_all[bin_blocks["name"]] = asms
    bin_blocks_all_addrs[bin_blocks["name"]] = addrs
    for child in bin_blocks["children"]:
        child_blocks, child_block_addrs = get_bin_blocks(child)
        for name, asms in child_blocks.items():
            bin_blocks_all[name] = asms
            bin_blocks_all_addrs[name] = child_block_addrs[name]
    return bin_blocks_all, bin_blocks_all_addrs

def extract_DecompileEval():
    base_path = "**"
    path = "**"
    with open(path, 'r') as f:
        data = json.load(f)
    save_path = os.path.join(base_path, "DecompileEval.json")
    tmp_dir = os.path.join(base_path, "tmp")
    results = []
    for idx in tqdm.tqdm(range(len(data))):
        func = data[idx]
        func_def = func["c_func"]
        fid = func["task_id"]
        ans = compile(func_def, tmp_dir, "func0")
        for o, d in ans.items():
            results.append({
                "task_id": fid,
                "type": o,
                "func_def": func_def,
                "logical_blocks": get_bin_blocks(d)
            })
    with open(save_path, 'w') as f:
        json.dump(results, f, indent=4)

if __name__ == "__main__":
    binary_path = "**/code-O1"
    logical_tree, status = analyze_binary(binary_path, "func0")
    # logical_tree = obtain_data_dep(binary_path, logical_tree)
    print(status)

    # extract_DecompileEval()
