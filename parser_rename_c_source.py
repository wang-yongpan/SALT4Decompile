#!/usr/bin/env python
# -*- coding: utf-8 -*-


import sys
import clang.cindex
import itertools
import string
import os

# Set the path to libclang. Please adjust this path according to your system.
clang.cindex.Config.set_library_file('/usr/lib/llvm-10/lib/libclang.so.1')

C_KEYWORDS = {
    'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do',
    'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if',
    'inline', 'int', 'long', 'register', 'restrict', 'return', 'short',
    'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union',
    'unsigned', 'void', 'volatile', 'while', '_Alignas', '_Alignof',
    '_Atomic', '_Bool', '_Complex', '_Generic', '_Imaginary', '_Noreturn',
    '_Static_assert', '_Thread_local', '__func__'
}


def generate_variable_names(existing_identifiers):
    """Generate variable names that do not conflict with existing identifiers or C keywords."""
    index = 1
    while True:
        name = f'var{index}'
        if name not in existing_identifiers and name not in C_KEYWORDS:
            yield name
        index += 1

def generate_variable_names_():
    """Generate variable names such as a, b, c, ..., aa, ab, etc."""
    alphabet = string.ascii_lowercase
    for size in range(1, 10):  # Adjust the length of the generated variable name as needed
        for s in itertools.product(alphabet, repeat=size):
            yield ''.join(s)

def collect_identifiers(node, identifiers):
    """Recursively collect all identifiers, including variables, functions, types, etc."""
    if node.spelling:
        identifiers.add(node.spelling)
    for child in node.get_children():
        collect_identifiers(child, identifiers)


def collect_variables(node, variables):
    """Recursively collect all variable declarations and references."""
    if node.kind == clang.cindex.CursorKind.VAR_DECL:
        if node.spelling:
            variables[node.spelling] = node
    elif node.kind == clang.cindex.CursorKind.PARM_DECL:
        if node.spelling:
            variables[node.spelling] = node
    elif node.kind == clang.cindex.CursorKind.DECL_REF_EXPR:
        referenced = node.referenced
        if referenced and referenced.kind == clang.cindex.CursorKind.VAR_DECL:
            if referenced.spelling:
                variables[referenced.spelling] = referenced
    # Regardless of the node type, continue recursively traversing child nodes
    for child in node.get_children():
        collect_variables(child, variables)


def rename_variables(code, tmp_dir):
    """Rename all variables in the C code to non-meaningful names."""
    index = clang.cindex.Index.create()
    # Writing to a temporary file
    with open(os.path.join(tmp_dir, 'tmp.c'), 'w', encoding='utf-8') as f:
        f.write(code)
    tu = index.parse(os.path.join(tmp_dir, 'tmp.c'), args=['-std=c99'])

    # Collect all existing identifiers
    existing_identifiers = set()
    collect_identifiers(tu.cursor, existing_identifiers)
    existing_identifiers.update(C_KEYWORDS)

    # Collect variables that need to be renamed
    variables = {}
    collect_variables(tu.cursor, variables)

    # Generate new variable names
    name_generator = generate_variable_names(existing_identifiers)
    new_names = {}
    for var_name in variables:
        new_name = next(name_generator)
        new_names[var_name] = new_name
        existing_identifiers.add(new_name)

    # Collect all tokens
    tokens = list(tu.get_tokens(extent=tu.cursor.extent))

    # Rebuild the code and replace the variable name
    new_code_parts = []
    last_token_end = 0
    for token in tokens:
        token_start = token.extent.start.offset
        token_end = token.extent.end.offset

        # Add the code between the previous token and the current token (including whitespace and comments)
        new_code_parts.append(code[last_token_end:token_start])

        # If token is a variable name that needs to be replaced, replace
        if token.spelling in new_names:
            new_token_spelling = new_names[token.spelling]
        else:
            new_token_spelling = token.spelling

        new_code_parts.append(new_token_spelling)
        last_token_end = token_end

    # Add the code after the last token
    new_code_parts.append(code[last_token_end:])

    new_code = ''.join(new_code_parts)

    # remove tmp file
    os.remove(os.path.join(tmp_dir, 'tmp.c'))

    return new_code

# Example usage
if __name__ == "__main__":
    code = '''

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

    transformed_code = rename_variables(code, "/tmp_dir")
    print("Original code:")
    print(code)
    print("Transformed code:")
    print(transformed_code)
