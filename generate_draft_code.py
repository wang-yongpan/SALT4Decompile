#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import multiprocessing
import tempfile

from transformers import AutoTokenizer
import torch
import os
from tqdm import tqdm
import gc
import subprocess
os.environ["TOKENIZERS_PARALLELISM"] = "true"

def evaluate_func(params):
    c_func, c_test, c_func_decompile = (
        params["c_func"],
        params["c_test"],
        params["c_func_decompile"],
    )

    timeout = 10
    flag_compile = 0
    flag_run = 0
    c_include = ""
    for line in c_func.split("\n"):
        if "#include" in line:
            c_include += line + "\n"
            c_func = c_func.replace(line, "")
    for line in c_test.split("\n"):
        if "#include" in line:
            c_include += line + "\n"
            c_test = c_test.replace(line, "")
    c_combine = c_include + "\n" + c_func_decompile + "\n" + c_test
    c_onlyfunc = c_include + "\n" + c_func_decompile

    with tempfile.TemporaryDirectory() as temp_dir:
        pid = os.getpid()
        c_file = os.path.join(temp_dir, f"combine_{pid}.c")
        executable = os.path.join(temp_dir, f"combine_{pid}")
        c_file_onlyfunc = os.path.join(temp_dir, f"onlyfunc_{pid}.c")
        executable_onlyfunc = os.path.join(temp_dir, f"onlyfunc_{pid}")
        if os.path.exists(executable):
            os.remove(executable)
        if os.path.exists(executable_onlyfunc):
            os.remove(executable_onlyfunc)

        with open(c_file, "w") as f:
            f.write(c_combine)
        with open(c_file_onlyfunc, "w") as f:
            f.write(c_onlyfunc)

        # Compile the C program to an assembly
        compile_command = [
            "gcc",
            "-S",
            c_file_onlyfunc,
            "-o",
            executable_onlyfunc,
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
            subprocess.run(compile_command, check=True, timeout=timeout)
            flag_compile = 1
        except:
            return flag_compile, flag_run

        # Run the compiled executable
        run_command = [executable]
        try:
            process = subprocess.run(
                run_command, timeout=timeout, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            flag_run = 1
        except:
            if "process" in locals() and process:
                process.kill()
                process.wait()
            return flag_compile, flag_run

    return flag_compile, flag_run

def decompile_pass_rate(testsets, gen_results_repeat, opts):
    all_stats = []

    for gen_index, gen_results in enumerate(gen_results_repeat):
        results_save = []
        with multiprocessing.Pool(16) as pool:
            tasks = [
                {
                    "c_func": testset["c_func"],
                    "c_test": testset["c_test"],
                    "c_func_decompile": output[0],
                }
                for testset, output in zip(testsets, gen_results)
            ]
            eval_results = list(tqdm(pool.imap(evaluate_func, tasks), total=len(tasks)))

        pool.terminate()
        pool.join()

        stats = {opt: {"compile": 0, "run": 0, "total": 0} for opt in opts}
        for idx, (testset, output, flag) in enumerate(
            tqdm(
                zip(testsets, gen_results, eval_results),
                total=len(testsets),
                desc="Evaluating",
            )
        ):
            c_func_decompile = output[0]
            c_func = testset["c_func"]
            c_test = testset["c_test"]
            flag_compile, flag_run = flag[0], flag[1]

            try:
                results_save.append({
                    "task_id": testset["task_id"],
                    "type": testset["type"],
                    "c_func": c_func,
                    "c_test": c_test,
                    "SALT4Decompile_output": c_func_decompile,
                    "SALT4Decompile_run_flag": flag_run,
                    "SALT4Decompile_compile_flag": flag_compile
                })
            except:

                results_save.append({
                    "task_id": testset["task_id"],
                    "type": testset["type"],
                    "c_func": c_func,
                    "c_test": c_test,
                    "SALT4Decompile_output": c_func_decompile,
                    "SALT4Decompile_run_flag": flag_run,
                    "SALT4Decompile_compile_flag": flag_compile
                })
            opt = testset["type"]

            stats[opt]["total"] += 1
            if flag_compile:
                stats[opt]["compile"] += 1
            if flag_run:
                stats[opt]["run"] += 1

        all_stats.append(stats)

    # average
    avg_stats = {opt: {"compile": 0, "run": 0, "total": 0} for opt in opts}
    for stats in all_stats:
        for opt in opts:
            avg_stats[opt]["compile"] += stats[opt]["compile"]
            avg_stats[opt]["run"] += stats[opt]["run"]
            avg_stats[opt]["total"] += stats[opt]["total"]

    for opt in opts:
        avg_stats[opt]["compile"] /= len(gen_results_repeat)
        avg_stats[opt]["run"] /= len(gen_results_repeat)
        avg_stats[opt]["total"] /= len(gen_results_repeat)

    all_ = 0
    for opt, data in avg_stats.items():
        compile_rate = data["compile"] / data["total"] if data["total"] > 0 else 0
        run_rate = data["run"] / data["total"] if data["total"] > 0 else 0
        all_ += run_rate
        print(
            f"Optimization {opt}: Compile Rate: {compile_rate:.4f}, Run Rate: {run_rate:.4f}"
        )
    print(f"run_rate:{all_/4.0:.4f}")
    return all_/4.0, results_save

from vllm import LLM, SamplingParams
def Eval_vllm(model_path, data_path, output_path):
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    stop_sequences = [tokenizer.eos_token]
    llm = LLM(
        model=model_path,
        tensor_parallel_size=1,
        max_model_len=4096,
        # max_num_seqs=args.max_num_seqs,
        gpu_memory_utilization=0.82,
    )

    sampling_params = SamplingParams(
        temperature=0,
        max_tokens=512,
        stop=stop_sequences,
    )
    print('Model Loaded!')
    repeat_num = 1
    data_name = data_path
    with open(data_name, 'r') as f:
        data = json.load(f)
    model_name = model_path.split("/")[-2] + "_" + model_path.split("/")[-1]
    inputs = []
    c_tests = []
    c_funcs = []
    for idx in tqdm(range(len(data))):
        func = data[idx]
        input_asm_prompt = func["instruction"]
        inputs.append(input_asm_prompt)
        c_tests.append(func["c_test"])
        c_funcs.append(func["c_func"])
    gen_results_repeat = []
    opts = {
        "-O0": "# This is the assembly code:\n",
        "-O1": "# This is the assembly code:\n",
        "-O2": "# This is the assembly code:\n",
        "-O3": "# This is the assembly code:\n",
    }
    for i in range(repeat_num):
        with torch.no_grad():
            gen_results = llm.generate(inputs, sampling_params)
            gen_results = [[output.outputs[0].text] for output in gen_results]
            gen_results_repeat.append(gen_results)
    ret, results_save = decompile_pass_rate(data, gen_results_repeat, opts)
    with open(os.path.join(output_path, "DecompileEval_output_" + model_name + ".json"), 'w') as f:
        json.dump(results_save, f, indent=4)
    return ret

if __name__ == '__main__':
    import sys
    model_path = str(sys.argv[1])
    data_path = str(sys.argv[2])
    output_path = str(sys.argv[3])
    result = Eval_vllm(model_path, data_path, output_path)
    print(model_path + str(result))
