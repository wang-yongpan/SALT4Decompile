#!/usr/bin/env python
# -*- coding: utf-8 -*-

from openai import OpenAI
import json
import os
from tqdm import tqdm


def read_DecompileEval(path):
    with open(path, "r") as f:
        data = json.load(f)
    return data

prompts = {
    "repair_prompt": "Analyze the following code to identify any possible boundary condition errors (The judgment statement of the loop is wrong, such as n is changed to n-1, the index overflow of the array is not reinitialized, such as i++ is not initialized to the original 0 in time, the variable i of the loop is initialized incorrectly, and so on), and ensure that the execution logic of the code is correct. If found, modify only the necessary parts and output the modified code. Do not modify any unrelated sections. No explanation. \n{func_code}\n",
    "rename_variable_names_prompt":"Please follow these rules when renaming variables: 1. Only Modify Variable Names: Do not modify function names, macro definitions, struct names, type names, or other non-variable identifiers. 2. Variable Names Should Reflect Logic: Variable names should clearly express their purpose and align with the code's context and logic. 3. High Readability: Variable names should be concise, easy to read, and avoid overly complex or obscure naming. 4. Follow Common Naming Conventions: 4.1 Use widely accepted naming conventions in software development, such as: Use snake_case or camelCase style (choose based on the code context). 4.2 Loop variables can use simple names like i, j, or k. 4.3 Boolean variables should start with prefixes like is_, has_, or can. 4.4 Pointer variables can start with p_ or ptr_ (optional). 4.5 Array variables can use arr_ or plural forms. 4.6 Temporary variables can start with tmp_ or temp_ (optional). 5. Preserve Comments and Formatting: Do not modify comments, code formatting, or logic structure. Please rename the variables in the following C code and provide the modified code. No explanation. ", #Output the old and new names in JSON format like {‘old name’: ‘new name’}.
    "add_comment_prompt":"Please follow these rules when adding comments: 1. Only Add Comments: Do not modify any code logic, variable names, function names, or other content. 2. Comments Should Reflect Logic: Comments Should Reflect Logic: Comments should clearly explain the purpose and logic of the code, especially for complex or non-obvious sections. 3. High Readability: Comments should be concise and clear, avoiding lengthy or obscure descriptions. 4. Avoid Over-Commenting: Do not add comments to obvious code lines, such as: 4.1 Simple assignments (e.g., int x = 10;). 4.2 Loop variable initialization (e.g., for (int i = 0; ...)). 4.3 Basic loop iterations (e.g., i++). 4.4 Simple expressions (e.g., sum = a + b;). 4.5 Return statements (e.g., return result;). 5. Function Summary Comment: Add a comment block before the function definition to describe the function's main purpose, inputs, outputs, and key logic. 6. Comment Style: Use // or /* */ comment styles, consistent with the code's style. Please add comments to the following C code and provide the modified code. No explanation. \n{func_code}\n",
    "fix_compile_prompt":"Please fix the following code based on the error messages provided by the GCC compiler to ensure successful compilation. The fix should minimize changes to the original code while ensuring the correctness of its logic. error messages: \n{error_messages}\n function code: \n{func_code}\n"
}

def response(client, model, content):
    ms = [
        {'role': 'system',
         'content': 'You are a programming expert, good at c code, especially algorithmic problems. You can mimic answering them in the background five times and provide me with the most frequently appearing answer. Furthermore, please strictly adhere to the output format specified in the question; there is no need to explain your answer.'},
        {'role': 'user',
         'content': content}]

    completion = client.chat.completions.create(
        model=model,
        messages=ms,
        temperature=0
    )
    output1 = completion.choices[0].message.content
    return output1


from multiprocessing import Process

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

def post_processing(client, model, func_code, c_test):
    ans = {}
    c_test_include = ""
    for line in c_test.split("\n"):
        if "#include" in line:
            c_test_include += line + "\n"
            c_test = c_test.replace(line, "")
    # 1: fix_compile
    MAX_ITERS = 3
    returncode, error_messages = compile(func_code)
    if returncode != 0:
        content = prompts["fix_compile_prompt"].format(error_messages=error_messages, func_code=func_code)
        output = response(client, model, content).replace("}\n```", "}\n").replace("```c\n", "")
        for i in range(MAX_ITERS - 1):
            returncode, error_messages = compile(output)
            if returncode == 0:
                break
            output = response(client, model, content).replace("}\n```", "}\n").replace("```c\n", "")
        func_code = output
        flag_compile, flag_run = eval_compile_and_run(c_test_include + "\n" + func_code + "\n" + c_test)
        ans["fix_compile_flag_compile"] = flag_compile
        ans["fix_compile_flag_run"] = flag_run
        ans["fix_compile_output"] = func_code

    #
    # # 2: repair_prompt
    func_code = response(client, model, prompts["repair_prompt"].format(func_code=func_code)).replace("}\n```", "}\n").replace("```c\n", "")
    flag_compile, flag_run = eval_compile_and_run(c_test_include + "\n" + func_code + "\n" + c_test)
    ans["repair_flag_compile"] = flag_compile
    ans["repair_flag_run"] = flag_run
    ans["repair_flag_output"] = func_code


    # 3: rename_variables
    func_code = response(client, model, prompts["rename_variable_names_prompt"] + "\n" + func_code + "\n").replace("}\n```", "}\n").replace("```c\n", "")
    flag_compile, flag_run = eval_compile_and_run(c_test_include + "\n" + func_code + "\n" + c_test)
    ans["rename_flag_compile"] = flag_compile
    ans["rename_flag_run"] = flag_run
    ans["rename_flag_output"] = func_code

    # 4: add_comment
    func_code = response(client, model, prompts["add_comment_prompt"].format(func_code=func_code)).replace("}\n```", "}\n").replace("```c\n", "")
    flag_compile, flag_run = eval_compile_and_run(c_test_include + "\n" + func_code + "\n" + c_test)
    ans["add_comment_flag_compile"] = flag_compile
    ans["add_comment_flag_run"] = flag_run
    ans["add_comment_flag_output"] = func_code
    return func_code, ans

def main():
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("-p", "--data_path", help="the data path of the results from SALT4EXE")
    parser.add_argument("-o", "--output_path", help="the output path")
    parser.add_argument("-s", "--save_path", help="the savepath")
    args = parser.parse_args()
    select_llm = "DeepSeek-Coder-V3"
    additional_name = "V3"
    output_path = args.output + additional_name
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    data_path = args.data_path
    save_path = args.save_path
    data = read_DecompileEval(data_path)
    process_num = 20
    # multi_process(data, select_llm, additional_name, output_path)
    p_list = []
    # multi_process(data, select_llm, additional_name, output_path, 0)
    # return
    for i in range(process_num):
        func_set = data[int((i) / process_num * len(data)): int((i + 1) / process_num * len(data))]
        p = Process(target=multi_process, args=(func_set, select_llm, additional_name, output_path, i))
        p_list.append(p)
    for p in p_list:
        p.start()
    for p in p_list:
        p.join()
    results = []
    for pid in range(process_num):
        file = str(pid) + "_" + str(select_llm) + "_" + str(additional_name) + ".json"
        filepath = os.path.join(output_path, file)
        with open(filepath, "r") as f:
            func = json.load(f)
        results.extend(func)
    results = sorted(results, key=lambda x: x["task_id"])
    with open(save_path, "w") as f:
        json.dump(results, f, indent=4)
    return output_path

def multi_process(data, select_llm, additional_name, output_path, pid):
    api_keys = {
        "DeepSeek-Coder-V3": ["sk-***", "https://api.deepseek.com", ["deepseek-chat"]],
    }
    client = OpenAI(
        api_key=api_keys[select_llm][0],
        base_url=api_keys[select_llm][1]
    )

    model = api_keys[select_llm][2][0]
    results = []
    i = 0
    tq = tqdm(data, ncols=50, desc="it is processing...", total=len(data))
    for inr in tq:
        mod_output = inr["SALT4Decompile_output"]
        if str(inr["task_id"]) + "_" + str(inr["type"]) + ".json" in os.listdir(output_path):
            continue
        c_test = inr["c_test"]
        c_func = inr["c_func"]
        c_include = ""
        for line in c_func.split("\n"):
            if "#include" in line:
                c_include += line + "\n"
        mod_output = c_include + mod_output
        mod_output, mod_ans = post_processing(client, model, mod_output, c_test)
        for k, v in mod_ans.items():
            inr["ModDecompile_" + k] = v
        inr["SALT4Decompile_output_final"] = mod_output
        tq.set_description(str(inr["task_id"]).split("/")[-1] + " preprocessed !")
        results.append(inr)
    with open(os.path.join(output_path, str(pid) + "_" + str(select_llm) + "_" + str(additional_name) + ".json"), "w") as f:
        json.dump(results, f, indent=4)
    return additional_name

def print_results(data_path, save_path):
    path = data_path
    ans = {"repair_flag_run":0, "repair_flag_compile":0,"add_comment_flag_run":0,"add_comment_flag_compile":0,"rename_flag_run":0,"rename_flag_compile":0,"fix_compile_flag_run":0,"fix_compile_flag_compile":0,
           "simplify_flag_run":0, "simplify_flag_compile":0, "run_flag":0,"compile_flag":0}
    mod_ans = {"ModDecompile_" + k:v for k, v in ans.items()}
    for file in os.listdir(path):
        file_path = os.path.join(path, file)
        with open(file_path, "r") as f:
            data = json.load(f)
        for d in data:
            for k, v in mod_ans.items():
                if k in d:
                    mod_ans[k] = v + d[k]
                else:
                    if "fix_compile_flag_compile" in k:
                        mod_ans[k] += d["ModDecompile_compile_flag"]
                    if "fix_compile_flag_run" in k:
                        mod_ans[k] += d["ModDecompile_run_flag"]
    mod_ans = {k: v/656.0 for k, v in mod_ans.items()}
    ans = [mod_ans]
    with open(os.path.join(save_path, "decompiled_salt_eval.json"), "w") as f:
        json.dump(ans, f, indent=4)

if __name__ == '__main__':
    func_code = '''
    char **func0(const char *s, int n, int *returnSize)  {
    const char *vowels = "aeiouAEIOU";
    char **out = NULL;
    int numc = 0, word_count = 0, begin = 0;
    size_t length = strlen(s);
    char *current = (char *)malloc(length + 1);
    for (int i = 0; i <= length; i++) {
        if (isspace(s[i]) || s[i] == '\0') {
            if (numc == n) {
                current[i - begin] = '\0';
                out = (char **)realloc(out, sizeof(char *) * (word_count + 1));
                out[word_count] = (char *)malloc(strlen(current) + 1);
                strcpy(out[word_count], current);
                word_count++;
            }
            begin = i + 1;
            numc = 0;
        } else {
            current[i - begin] = s[i];
            if (strchr(vowels, s[i]) == NULL && isalpha((unsigned char)s[i])) {
                numc++;
            }
        }
    }
    free(current);
    *returnSize = word_count;
    return out;
}
    '''
    main()
    # print_results(main(), "save_path")
