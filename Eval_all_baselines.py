#!/usr/bin/env python
# -*- coding: utf-8 -*-

baselines = {"llm-based": ["deepseek_V3", "GPT_4o", "Claude_35_sonnet", "o1-mini"], "Ctools": ["Angr", "RetDec", "Ghidra", "Hex-Rays"], "ExWork": ["LLM4Decompile", "nova", "SALT", "SccDec"]}

import os
import tempfile
import subprocess
def compile(func_code):
    with tempfile.TemporaryDirectory() as temp_dir:
        pid = os.getpid()
        c_file = os.path.join(temp_dir, f"func_{pid}.c")
        executable = os.path.join(temp_dir, f"func_{pid}")
        if os.path.exists(executable):
            os.remove(executable)
        with open(c_file, "w") as f:
            f.write(func_code)
        compile_command = [
            "gcc",
            "-S",
            c_file,
            "-o",
            executable,
            "-lm",
        ]
        result = subprocess.run(compile_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.returncode, result.stderr

def eval_compile_and_run(func_code):
    flag_compile, flag_run = 0, 0
    with tempfile.TemporaryDirectory() as temp_dir:
        pid = os.getpid()
        c_file = os.path.join(temp_dir, f"func_{pid}.c")
        executable = os.path.join(temp_dir, f"func_{pid}")
        if os.path.exists(executable):
            os.remove(executable)
        with open(c_file, "w") as f:
            f.write(func_code)
        # Compile the C program to an assembly
        compile_command = [
            "gcc",
            "-S",
            c_file,
            "-o",
            executable,
            "-lm",
        ]
        try:
            subprocess.run(compile_command, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            flag_compile = 1
        except:
            return flag_compile, flag_run

        # Compile the C program to an executable
        compile_command = ["gcc", c_file, "-o", executable, "-lm"]
        try:
            subprocess.run(compile_command, check=True, timeout=10)
            flag_compile = 1
        except:
            return flag_compile, flag_run

        # Run the compiled executable
        run_command = [executable]
        try:
            process = subprocess.run(
                run_command, timeout=10, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            flag_run = 1
        except:
            if "process" in locals() and process:
                process.kill()
                process.wait()
            return flag_compile, flag_run
    return flag_compile, flag_run

def eval_test_case_pass_rate(func_code, fname):
    total, passed = 0, 0
    with tempfile.TemporaryDirectory() as temp_dir:
        pid = os.getpid()
        c_file = os.path.join(temp_dir, f"func_{pid}.c")
        executable = os.path.join(temp_dir, f"func_{pid}")
        if os.path.exists(executable):
            os.remove(executable)
        with open(c_file, "w") as f:
            f.write(func_code)
        # Compile the C program to an assembly
        compile_command = [
            "gcc",
            "-S",
            c_file,
            "-o",
            executable,
            "-lm",
        ]

        try:
            subprocess.run(compile_command, check=True, timeout=10, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
        except:
            print(func_code)
            with open("error.txt", "a") as f:
                f.write(fname + "\n" + func_code)
            return passed, total


        # Compile the C program to an executable
        compile_command = ["gcc", c_file, "-o", executable, "-lm"]
        try:
            subprocess.run(compile_command, check=True, timeout=10)
        except:
            return passed, total

        # Run the compiled executable
        run_command = [executable]

        try:
            result = subprocess.run(run_command, timeout=10, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout
            if "assertions" not in result:
                raise "None assertions output"
            total = eval(result.split("Total assertions: ")[-1].split("\n")[0])
            passed = eval(result.split("Passed assertions: ")[-1].split("\n")[0])
        except:
            return passed, total
    return passed, total

import json
def read_json(path):
    with open(path, "r") as f:
        data = json.load(f)
    return data

def get_ctools_output(filepath):
    data = read_json(filepath)
    ans = {}
    for d in data:
        fname = str(d["task_id"]) + "_" + str(d["type"])
        ans[fname] = d["pseudo_code"]
    return ans

def get_llm_base_output(filepath):
    data = read_json(filepath)
    ans = {}
    for d in data:
        fname = str(d["task_id"]) + "_" + str(d["type"])
        ans[fname] = d["LLM_output"]
    return ans

def get_SccDec_output(filepath):
    data = read_json(filepath)
    ans = {}
    for d in data:
        fname = str(d["task_id"]) + "_" + str(d["opt_state"])
        ans[fname] = d["c_func_decompile"]
    return ans

def get_nova_output(filepath):
    data = read_json(filepath)
    ans = {}
    for d in data:
        fname = str(d["task_id"]) + "_" + str(d["type"])
        ans[fname] = d["infer_c_func"][0]["c_func"]
    return ans

def get_llm4decompile_output(filepath):
    data = read_json(filepath)
    ans = {}
    for d in data:
        fname = str(d["task_id"]) + "_" + str(d["type"])
        ans[fname] = d["output"]
    return ans

def get_SALT_output(filepath):
    data = read_json(filepath)
    ans = {}
    for d in data:
        fname = d["task_id"] + "_" + d["type"].replace("-", "")
        ans[fname] = d["SALT4Decompile_output"]
    return ans

def get_all_results(TEST_FILE_PATH, SAVE_PATH, DATA_PATH):
    eval_path = TEST_FILE_PATH
    savepath = os.path.join(SAVE_PATH, "DecompileEval.json")
    eval_data = read_json(eval_path)
    test_data = {}
    for ed in eval_data:
        test_data[str(ed["task_id"]) + "_" + str(ed["type"])] = ed
    path = DATA_PATH
    for file in os.listdir(path):
        ans = {}
        filepath = os.path.join(path, file)
        if file.split(".json")[0] in baselines["llm-based"]:
            ans = get_llm_base_output(filepath)
        if file.split(".json")[0] in baselines["Ctools"]:
            ans = get_ctools_output(filepath)
        if "nova" in file:
            ans = get_nova_output(filepath)
        if "SccDec" in file:
            ans = get_SccDec_output(filepath)
        if "LLM4Decompile" in file:
            ans = get_llm4decompile_output(filepath)
        if "SALT" in file:
            ans = get_SALT_output(filepath)
        for a, output in ans.items():
            test_data[a][file.split(".json")[0] + "_outputResult"] = output
    with open(savepath, "w") as f:
        json.dump(test_data, f)
    return savepath

def eval_all_baselines(DATA_PATH, SAVE_PATH):
    path = DATA_PATH
    savepath = os.path.join(SAVE_PATH, "DecompileEval_decompiled_output.json")
    data = read_json(path)
    for fname, d in data.items():
        c_test = d["c_test"]
        c_test_pass = d["c_test_rate"]
        c_func = d["c_func"]
        c_include = ""
        for line in c_func.split("\n"):
            if "#include" in line:
                c_include += line + "\n"
        c_test_include = ""
        for line in c_test.split("\n"):
            if "#include" in line:
                c_test_include += line + "\n"
                c_test = c_test.replace(line, "")
        c_test_pass_include = ""
        for line in c_test_pass.split("\n"):
            if "#include" in line:
                c_test_pass_include += line + "\n"
                c_test_pass = c_test_pass.replace(line, "")
        for t, c in d.items():
            if "outputResult" in t:
                output = c_include + c
                output_test = c_test_include + "\n" + output + "\n" + c_test
                flag_compile, flag_run = eval_compile_and_run(output_test)
                passed, total = 0, 0
                if flag_run == 0 and flag_compile == 1:
                    output_test_rate = c_test_pass_include + "\n" + output + "\n" + c_test_pass
                    passed, total = eval_test_case_pass_rate(output_test_rate, fname)
                if flag_run == 1:
                    total = -1
                d[t] = [c, flag_compile, flag_run, passed, total]

    with open(savepath, "w") as f:
        json.dump(data, f)
    return savepath

def print_all_results(DATA_PATH, SAVE_PATH):
    path = DATA_PATH
    savepath = os.path.join(SAVE_PATH, "DecompileEval_results_mean.json")
    data = read_json(path)
    ans = {}
    total_assertions = {}
    for fname, content in data.items():
        for k, v in content.items():
            if "outputResult" in k:
                total = v[4]
                if fname not in total_assertions:
                    total_assertions[fname] = total
                else:
                    total_assertions[fname] = total if total > total_assertions[fname] else total_assertions[fname]
    for fname, content in data.items():
        for k, v in content.items():
            if "outputResult" in k:
                if k not in ans:
                    if v[4] == -1:
                        addition = 1.0
                    elif total_assertions[fname] == 0:
                        addition = 0.0
                    else:
                        addition = float((v[3]) / total_assertions[fname])
                    ans[k] = [v[0], v[1], v[2], v[3], total_assertions[fname], addition]
                else:
                    compile_rate = v[1]
                    run_rate = v[2]
                    passed = v[3]
                    if v[4] == -1:
                        addition = 1.0
                    elif total_assertions[fname] == 0:
                        addition = 0.0
                    else:
                        addition = float((passed) / total_assertions[fname])
                    ans[k] = [ans[k][0], ans[k][1] + compile_rate, ans[k][2] + run_rate, ans[k][3] + passed, total_assertions[fname] + ans[k][4], addition + ans[k][5]]
    results = {}
    for model_name, metrics in ans.items():
        re_com_rate = metrics[1] / 656.0
        re_exe_rate = metrics[2] / 656.0
        pass_rate_mean = metrics[5] / 656.0
        results[model_name] = {}
        results[model_name]['re_com_rate'] = re_com_rate
        results[model_name]['re_exe_rate'] = re_exe_rate
        results[model_name]['pass_rate_mean'] = pass_rate_mean
        #results[model_name]['results'] = metrics

    with open(savepath, "w") as f:
        json.dump(results, f, indent=2)

def print_each_o(DATA_PATH, SAVE_PATH):
    path = DATA_PATH
    savepath = os.path.join(SAVE_PATH, "DecompileEval_results_each_options.json")
    data = read_json(path)
    ans = {}
    total_assertions = {}
    for fname, content in data.items():
        for k, v in content.items():
            if "outputResult" in k:
                total = v[4]
                if fname not in total_assertions:
                    total_assertions[fname] = total
                else:
                    total_assertions[fname] = total if total > total_assertions[fname] else total_assertions[fname]
    for fname, content in data.items():
        type = fname.split("_")[1]
        for k, v in content.items():
            if "outputResult" in k:
                if k not in ans:
                    if v[4] == -1:
                        addition = 1.0
                    elif total_assertions[fname] == 0:
                        addition = 0.0
                    else:
                        addition = float((v[3]) / total_assertions[fname])
                    ans[k] = {type: [v[0], v[1], v[2], v[3], total_assertions[fname], addition]}
                else:
                    compile_rate = v[1]
                    run_rate = v[2]
                    passed = v[3]
                    if v[4] == -1:
                        addition = 1.0
                    elif total_assertions[fname] == 0:
                        addition = 0.0
                    else:
                        addition = float((passed) / total_assertions[fname])
                    if type in ans[k]:
                        res = [ans[k][type][0], ans[k][type][1] + compile_rate, ans[k][type][2] + run_rate, ans[k][type][3] + passed,
                                  total_assertions[fname] + ans[k][type][4], addition + ans[k][type][5]]
                        ans[k][type] = res
                    else:
                        ans[k][type] = [v[0], compile_rate, run_rate, passed, total_assertions[fname], addition]
    results = {}
    for model_name, metrics in ans.items():
        results[model_name] = {}
        for o, od in metrics.items():
            re_com_rate = od[1] / 164.0
            re_exe_rate = od[2] / 164.0
            pass_rate_mean = od[5] / 164.0
            results[model_name][o] = {}
            results[model_name][o]['re_com_rate'] = re_com_rate
            results[model_name][o]['re_exe_rate'] = re_exe_rate
            results[model_name][o]['pass_rate_mean'] = pass_rate_mean
            # results[model_name]['results'] = metrics

    with open(savepath, "w") as f:
        json.dump(results, f, indent=2)
    pass

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("-t", "--test_path", help="the path of test file")
    parser.add_argument("-s", "--save_path", help="the save path")
    parser.add_argument("-d", "--input_path", help="the data path of all baselines")
    args = parser.parse_args()
    TEST_FILE_PATH = args.test_path
    SAVE_PATH = args.save_path
    DATA_PATH = args.input_path
    DP1 = get_all_results(TEST_FILE_PATH, SAVE_PATH, DATA_PATH)
    DP2 = eval_all_baselines(DP1, SAVE_PATH)
    print_all_results(DP2, SAVE_PATH)
    print_each_o(DP2, SAVE_PATH)


