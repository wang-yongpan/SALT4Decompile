#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
from os import path

addition_prefix = '''
static int failed_assertions = 0;
static int total_assertions = 0;
#include <assert.h>
#include <stdio.h>
#undef assert
#define assert(expr) \\
    do { \\
        total_assertions++; \\
        if (!(expr)) { \\
            failed_assertions++; \\
            fprintf(stderr, "Assertion failed: %s\\n", #expr); \\
        } \\
    } while (0)
'''

addition_after = '''
printf("Total assertions: %d\\n", total_assertions);
printf("Passed assertions: %d\\n", total_assertions - failed_assertions);
'''

def read_DecompileEval():
    path = "**/decompile-eval-executable-gcc-obj.json"
    with open(path,'r') as f:
        data = json.load(f)
    return data
import re


def find_main_function(c_code):
    """
    Find the start and end of the main function.
    """
    # Matches the start and end of the main function
    main_pattern = re.compile(r'int\s+main\s*\([^\)]*\)\s*\{([\s\S]*?)\n\}')
    match = main_pattern.search(c_code)
    if not match:
        raise ValueError("Could not find main function in the code.")

    # Returns the start and end position of the main function
    start = match.start(1)
    end = match.end(1)
    return start, end


def find_last_return_in_main(c_code, main_start, main_end):
    """
    Find the return statement on the last line of the main function.
    """
    # Extract the code of the main function
    main_code = c_code[main_start:main_end]

    # Matches all return statements
    return_pattern = re.compile(r'return\s*[^;]*;')
    return_matches = list(return_pattern.finditer(main_code))

    if not return_matches:
        raise ValueError("No return statement found in main function.")

    #Find the last return statement
    last_return = return_matches[-1]
    return main_start + last_return.start(), main_start + last_return.end()


def insert_printf_before_return(c_code, return_start, return_end):
    """
    Insert the printf statement before the return statement.
    """
    # Define the printf statements to be inserted
    printf_statements = """
    printf("Total assertions: %d\\n", total_assertions);
    printf("Passed assertions: %d\\n", total_assertions - failed_assertions);
    """

    # Insert a printf statement before the return statement
    modified_code = (
            c_code[:return_start] +
            printf_statements +
            c_code[return_start:]
    )

    return modified_code

def add_code(data):
    for d in data:
        c_test = d["c_test"].strip()
        c_test_new = addition_prefix + c_test
        # Find the start and end of the main function
        main_start, main_end = find_main_function(c_test_new)

        try:
        # Find the return statement on the last line of the main function
            return_start, return_end = find_last_return_in_main(c_test_new, main_start, main_end)
            # Insert a printf statement before the return statement
            modified_code = insert_printf_before_return(c_test_new, return_start, return_end)
        except:
            modified_code = c_test_new[:-1] + addition_after + "}"
        d["c_test_rate"] = modified_code
        if d["task_id"] == 6:
            print()
        if "int main" not in d["c_test"]:
            print()
        print()

    with open("**/decompile-eval_test_rate.json",'w') as f:
        json.dump(data,f)


add_code(read_DecompileEval())
