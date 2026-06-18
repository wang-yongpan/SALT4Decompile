#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import shutil
import subprocess
import os

from tqdm import tqdm
import random

from construct_salt import analyze_binary
import re
from func_timeout import func_set_timeout
from parser_rename_c_source import rename_variables

SEED_RANDOM = 123456789
random.seed(SEED_RANDOM)

def extract_comments(code):
    # Regular expressions that recognize both strings and various types of comments
    pattern = (
        r'(?P<string>"(\\.|[^"\\])*"|\'(\\.|[^\'\\])*\'|"(\\.|[^"\\])*")'
        r'|(?P<comment>//.*|/\*[\s\S]*?\*/|#.*)'
    )
    comments = []

    def is_within_string(index, text):
        """ Helper function to check if an index is within a quoted string """
        in_quote = False
        escape = False
        for i, char in enumerate(text):
            if i > index:
                break
            if char == '"' and not escape:
                in_quote = not in_quote
            if char in ("'", '"') and not escape:
                in_quote = not in_quote
            escape = (char == '\\') and not escape

        return in_quote

    # Use re.finditer to iterate over all matches
    for match in re.finditer(pattern, code):
        if match.lastgroup == 'comment':
            # Checks if this match is a comment
            if not is_within_string(match.start(), code):
                comments.append(match.group('comment'))

    return comments

def find_loops(text):
    pattern = r"""
        # Matches do-while loops, supports cross-line content and code within curly braces
        \bdo\s*{[\s\S]*?}\s*while\s*\([^\)]*\)\s*;  # Matching do-while loops
        |
        \bfor\s*\([^)]*\)\s*{[^}]*}      # Matching for loops
        |
        \bwhile\s*\([^)]*\)\s*{[^}]*}    # Matching while loops
    """

    # Use the re.VERBOSE and re.DOTALL flags to support line breaks and enhance readability
    matches = re.finditer(pattern, text, re.VERBOSE | re.DOTALL)
    results = [match.group() for match in matches]
    return len(results)

def load_data(base_path, save_name):
    train_path = os.path.join(base_path, save_name + ".json")
    test_file = os.path.join(base_path, "1.c")
    test_exe = os.path.join(base_path, "1")
    normal_func_num = 0
    if not os.path.exists(train_path):
        from datasets import load_dataset
        dataset = load_dataset('jordiae/exebench', split='train_real_compilable')
        dataset = dataset.shuffle(seed=SEED_RANDOM)
        func_sets = []
        for idx, item in tqdm(enumerate(dataset), total=len(dataset), ncols=50):
            if item['synth_deps'] is None or len(item['synth_deps']) == 0:
                ans = {}
                line_num = len(item['func_def'].split("\n"))
                if line_num < 5 or line_num > 500:
                    continue
                comments = extract_comments(item['func_def'])
                loop_count = find_loops(item['func_def'])
                if loop_count > 0:
                    if int(line_num / loop_count) <= 200:
                        func_code = item['func_def']
                        for comment in comments:
                            func_code = func_code.replace(comment, '')
                        with open(test_file, "w") as f:
                            f.write(func_code)
                        ans["func_def"] = func_code
                        ans["path"] = item['path']
                        ans['fname'] = item['fname']
                        ans['type'] = 'loop'
                        try:
                            proc_compile = subprocess.run(
                                ["gcc",
                                 "-shared",
                                 "-fPIC",
                                 "-g3",
                                 "-O2",
                                 "-o",
                                 test_exe,
                                 test_file],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=True,
                                encoding="utf-8",
                                timeout=12)
                        except:
                            continue
                        func_sets.append(ans)
                else:
                    if normal_func_num < 40000:
                        func_code = item['func_def']
                        for comment in comments:
                            func_code = func_code.replace(comment, '')
                        with open(test_file, "w") as f:
                            f.write(func_code)
                        ans["func_def"] = func_code
                        ans["path"] = item['path']
                        ans['fname'] = item['fname']
                        ans['type'] = 'normal'
                        try:
                            proc_compile = subprocess.run(
                                ["gcc",
                                 "-shared",
                                 "-fPIC",
                                 "-g3",
                                 "-O2",
                                 "-o",
                                 test_exe,
                                 test_file],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=True,
                                encoding="utf-8",
                                timeout=12)
                        except:
                            continue
                        func_sets.append(ans)
                        normal_func_num += 1
        random.shuffle(func_sets)
        for i in range(5):
            print(func_sets[i])
        with open(train_path, "w") as f:
            json.dump(func_sets, f)
        os.remove(test_file)
        os.remove(test_exe)
        print(len(func_sets))
    else:
        with open(train_path, "r") as f:
            func_sets = json.load(f)

    loop_num = 0
    normal_num = 0
    for func in func_sets:
        if func["type"] == "loop":
            loop_num += 1
        if func["type"] == "normal":
            normal_num += 1
    print(loop_num)
    print(normal_num)
    return func_sets

def preprocess_c(c_code):
    function_def, remain = c_code.split("{", maxsplit=1)
    function_def = (
        function_def.replace("static", "")
        .replace("inline", "")
        #.replace("\n", " ")
        #.strip()
    )
    remain, right_bracket = remain.rsplit("}", maxsplit=1)
    # remain comments such as # 1 "filename.c"
    remain = re.sub(r"#\s+\d+\s+\"[^\"]+\"", "", remain)
    function_def += " {" + remain + "\n}"

    # replace multiple \n to one \n
    function_def = re.sub("\n+", "\n", function_def)

    full_code = function_def.strip() + "\n\n"
    return full_code

def get_bin_blocks(bin_blocks):
    bin_blocks_all = {}
    asms = ""
    for asm in bin_blocks["assembly"]:
        asms += asm[1].strip() + "\n"
    bin_blocks_all[bin_blocks["name"]] = asms
    for child in bin_blocks["children"]:
        for name, asms in get_bin_blocks(child).items():
            bin_blocks_all[name] = asms
    return bin_blocks_all

def get_block_str_type1(bin_blocks_all, type=""):
    if type == "json":
        block_str = {}
        for block_name, block in bin_blocks_all.items():
            block_str[block_name] = block.strip()
    else:
        block_str = ""
        for block_name, block in bin_blocks_all.items():
            block_str += block_name + ":\n"
            block_str += block.strip() + "\n"
    return block_str#.strip()


def get_all_bin_asms(bin_blocks):
    bin_blocks_all = {}
    asms_ = []
    for asm in bin_blocks["assembly"]:
        asms_.append(asm)
    bin_blocks_all[bin_blocks["name"]] = asms_
    for child in bin_blocks["children"]:
        for name, asms in get_all_bin_asms(child).items():
            bin_blocks_all[name] = asms
    return bin_blocks_all

def get_text_type1(bin_blocks_all):
    all_bin_blocks = get_all_bin_asms(bin_blocks_all)
    asms = []
    for k, blocks in all_bin_blocks.items():
        asms.extend(blocks)
    body_addrs = {addr: asm for addr, asm in asms if "BLOCK_" not in asm}
    ams = [body_addrs[key].strip() for key in sorted(body_addrs.keys())]
    return "\n".join(ams)

def get_block_str_type2_3(bin_blocks_all):
    block_type_start = "[B]\n"
    block_type_end = "[/B]\n"
    block_str = ""
    i = 0
    for block_name, block in bin_blocks_all.items():
        block_name = block_type_start + block_name
        if i == 0:
            block_name = block_name.replace("<<", "<").replace(">>", ">")
            i += 1
        block_str += block_name + ":{\n"
        block_str += block.strip() + "\n}\n" + block_type_end
    return block_str

@func_set_timeout(120)
def compile(func_def, function_name, tmp_dir, t="train"):
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
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
    c_include = ''
    for line in formatted_code.split('\n'):
        if '#include' in line:
            c_include += line + '\n'

    # rename
    if t == "train":
        formatted_code = formatted_code.replace(c_include, "")
        formatted_code = c_include + rename_variables(formatted_code, tmp_dir)
        pass
    with open(formatted_code_file, "w") as f:
        f.write(formatted_code)
    ans = {}
    compile_error = 0
    block_error = 0
    for optimization in ["-O0", "-O1", "-O2", "-O3"]:
        binary_file = os.path.join(tmp_dir, f"code{optimization}")
        try:
            proc_compile = subprocess.run(
                ["gcc",
                 "-shared",
                 "-fPIC",
                 "-lm",
                 "-fno-builtin",
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
        except:
            compile_error += 1
            continue
        bin_block, status = analyze_binary(binary_file, function_name)
        if status == 0:
            print("logical block is error!")
            block_error += 1
        asm_blocks = get_bin_blocks(bin_block)
        block_str = get_block_str_type1(asm_blocks)

        ans[optimization] = block_str
    return ans, formatted_code, compile_error, block_error

@func_set_timeout(10)
def addr2line(addresses, binary_file):
    if len(addresses) == 0:
        return {}
    results = {}
    executable = binary_file
    cmd_addr = subprocess.run(['addr2line', '-e', executable, *addresses], stdout=subprocess.PIPE,stderr=subprocess.PIPE, text=True, check=True, encoding="utf-8", timeout=12)
    line_info = cmd_addr.stdout.strip()
    if line_info:
        i = 0
        for line in line_info.split("\n"):
            source_line = line.split(".c:")[-1]
            try:
                source_line_num = int(source_line.split("(discriminator ")[0])
            except:
                i += 1
                continue
            address = addresses[i]
            if address not in results:
                results[address] = source_line_num
            else:
                print("bad logical block! multiple same source line number.")
            i += 1
    return results

def process_data(train_func_sets, base_path, process_id, al_funcs, save_name, tmp_name="tmp", t="train"):
    idx = process_id * len(train_func_sets)
    optimizations = ["-O0", "-O1", "-O2", "-O3"]
    tq = tqdm(train_func_sets, ncols=80)
    ce = 0
    be = 0
    for func in tq:
        func_def = func["func_def"]
        fid = str(func['path']+func["fname"])
        if fid in al_funcs:
            continue
        func_def = "\n".join(line for line in func_def.splitlines() if line.strip())
        func_def = preprocess_c(func_def)
        try:
            ans, code_format, c_error, b_error = compile(func_def, func["fname"], tmp_dir=os.path.join(os.path.join(base_path, tmp_name), str(process_id)), t=t)
            c_include = ''
            for line in code_format.split('\n'):
                if '#include' in line:
                    c_include += line + '\n'
            ce += c_error
            be += b_error
        except:
            continue
        if len(ans) == 0 and len(ans) != 4:
            continue
        for optim, block_str in ans.items():
            if optim in optimizations:
                func_text = {}
                func_text['task_id'] = idx
                if t != "train":
                    func_text['task_id'] = func["task_id"]
                func_text['type'] = optim
                func_text['func_def'] = code_format
                func_text['fid'] = str(fid)
                func_text['input'] = block_str
                if t != "train":
                    func_text['c_test'] = func["c_test"] # DecompileEval
                func_text['output'] = code_format#.replace(c_include, "").lstrip().strip()
                with open(os.path.join(base_path, save_name.split(".json")[0] + "_" + str(process_id) + ".json"), "a") as f:
                    f.write(str(func_text) + "\n")
                tq.set_description(f"Processing {func['fname']} success!")
        idx += 1
        tq.set_description(f"Finished processing {idx - process_id * len(train_func_sets)} functions")
    # with open(os.path.join(base_path, "error" + str(process_id)), "w") as f:
    #     f.write(str(ce) + "\n")
    #     f.write(str(be) + "\n")
    return

from multiprocessing import Process
import multiprocessing

def multi_process_train_DecompileEval(base_path, name, DecompileEval_path):
    path = DecompileEval_path
    with open(path, 'r') as f:
        data = list(json.load(f))
    new_data = []
    for d in data:
        new_d = {}
        new_d["path"] = "1"
        new_d["fname"] = "func0"
        new_d["func_def"] = d["c_func"]
        new_d["c_test"] = d["c_test"]
        new_d["task_id"] = d["task_id"]
        if new_d not in new_data:
            new_data.append(new_d)
    data = new_data
    save_name = name + "_DecompileEval.json"
    save_path = os.path.join(base_path, save_name)
    process_num = 10
    p_list = []
    # multiprocessing.set_start_method('spawn')
    for i in range(process_num):
        train_func_set = data[int((i) / process_num * len(data)): int((i + 1) / process_num * len(data))]
        p = Process(target=process_data, args=(train_func_set, base_path, i, {}, save_name, "tmp_" + name, "eval"))
        p_list.append(p)
    for p in p_list:
        p.start()
    for p in p_list:
        p.join()
    trains = []
    for i in range(process_num):
        if os.path.exists(os.path.join(base_path, save_name.split(".json")[0] + "_" + str(i) + ".json")):
            with open(os.path.join(base_path, save_name.split(".json")[0] + "_" + str(i) + ".json"), "r") as f:
                for line in f.readlines():
                    line = eval(line)
                    trains.append(line)
            os.remove(os.path.join(base_path, save_name.split(".json")[0] + "_" + str(i) + ".json"))
    print("ALL DecompileEval samples number: " + str(len(trains)))
    before = "# This is the assembly code:\n"
    after = "\n# What is the source code?\n"
    train_funcs = []
    for func in trains:
        new_func = {}
        new_func["instruction"] = before + str(func['input']).strip() + after
        new_func["c_func"] = str(func['output'])
        new_func["c_test"] = str(func['c_test'])
        new_func["task_id"] = str(func['task_id'])
        new_func["type"] = str(func["type"])
        train_funcs.append(new_func)
    with open(save_path, 'w') as f:
        json.dump(train_funcs, f)

def data_sample(base_path, save_name, trains):
    sample_num = 40000 if len(trains) >= 40000 else len(trains)
    save_path = os.path.join(base_path, save_name.split(".json")[0] + "_" + str(int(sample_num / 1000)) + "K.json")
    save_path_llama = os.path.join(base_path, save_name.split(".json")[0] + "_" + str(int(sample_num / 1000)) + "K_llama_factory.json")
    before = "# This is the assembly code:\n"
    after = "\n# What is the source code?\n"
    train_keys = list(trains.keys())
    random.shuffle(train_keys)
    func_sets = random.sample(train_keys, k=sample_num)
    func_sets = [trains[key] for key in func_sets]
    train_funcs = []
    llama_data = []
    for funcs in func_sets:
        for func in funcs:
            new_func = {}
            new_func["instruction"] = str(func['input'])
            new_func["output"] = str(func['output'])
            train_funcs.append(new_func)
            nds = []
            nd = {}
            nd["role"] = "user"
            nd["content"] = before + new_func["instruction"].strip() + after
            nds.append(nd)
            nd = {}
            nd["role"] = "assistant"
            nd["content"] = new_func["output"]
            nds.append(nd)
            llama_data.append({"messages": nds})
    random.shuffle(llama_data)
    random.shuffle(train_funcs)
    with open(save_path, 'w') as f:
        json.dump(train_funcs, f, indent=4)
    # with open(save_path_llama, 'w') as f:
    #     json.dump(llama_data, f, indent=4)


def multi_process_train(base_path, name):
    """
    Args:
        base_path:
        name:

    Returns:

    """
    save_name = name + "_SFT.json"
    train_func_sets = load_data(base_path, "exebench_4w")
    process_num = 20
    p_list = []
    # multiprocessing.get_context("spawn").set_start_method('spawn')
    multiprocessing.set_start_method('spawn')
    al_funcs = {}
    trains = {}
    if os.path.exists(os.path.join(base_path, save_name)):
        with open(os.path.join(base_path, save_name), "r") as f:
            trains = json.load(f)
            al_funcs = {key: 1 for key in trains.keys()}
    for i in range(process_num):
        train_func_set = train_func_sets[int((i) / process_num * len(train_func_sets)): int((i + 1) / process_num * len(train_func_sets))]
        p = Process(target=process_data, args=(train_func_set, base_path, i, al_funcs, save_name, "tmp_train_" + name))
        p_list.append(p)
    for p in p_list:
        p.start()
    for p in p_list:
        p.join()
    for i in range(process_num):
        if os.path.exists(os.path.join(base_path, save_name.split(".json")[0] + "_" + str(i) + ".json")):
            with open(os.path.join(base_path, save_name.split(".json")[0] + "_" + str(i) + ".json"), "r") as f:
                for line in f.readlines():
                    try:
                        line = eval(line)
                        if line['fid'] not in al_funcs:
                            trains[line['fid']] = [line]
                            al_funcs[line['fid']] = 1
                        else:
                            trains[line['fid']].append(line)
                    except:
                        continue
            os.remove(os.path.join(base_path, save_name.split(".json")[0] + "_" + str(i) + ".json"))
    print("ALL train samples number: " + str(len(trains)))
    with open(os.path.join(base_path, save_name), "w") as f:
        json.dump(trains, f, indent=4)
    data_sample(base_path, save_name, trains)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("-p", "--base_path", help="the base path of dataset")
    parser.add_argument("-n", "--name", help="the name of save")
    parser.add_argument("-h", "--DecompileEval_path", help="the path of DecompileEval")
    args = parser.parse_args()
    base_path = args.base_path
    DecompileEval_path = args.DecompileEval_path
    name = args.name
    multi_process_train(base_path, name)
    multi_process_train_DecompileEval(base_path, name, DecompileEval_path)





