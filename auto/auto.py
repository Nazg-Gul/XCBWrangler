#!/usr/bin/env python

from __future__ import print_function

from clang.cindex import *
import os
import sys

###############################################################################
# Parsing


def formatAndCleanType(type):
    """
    Format data type to code style closer to what we want.
    """
    type = type.replace(" *", "* ")
    type = type.strip()
    if type.startswith("struct ") and not type.endswith("*"):
        type = type[7:]
    return type


def mergeTypeAndVariable(type, variable):
    """
    Combines type and variable to a single line of code.
    """
    dimension = ""
    type = type.strip()
    while type.endswith(']'):
        index = type.rfind('[')
        dimension = type[index:] + dimension
        type = type[:index]
    return "{} {}{}". format(type.strip(), variable, dimension)

class Argument:
    """
    Function argument.
    """
    def __init__(self, cursor):
        """
        Construct higher level function argument declaration
        from CLang's cursor.
        """
        self.name = cursor.spelling
        self.type = formatAndCleanType(cursor.type.spelling)

    def __str__(self):
        return mergeTypeAndVariable(self.type, self.name)


class Function:
    """
    Function declaration.
    """
    def __init__(self, cursor):
        """
        Construct higher level function declaration from CLang's cursor.
        """
        self.return_type = "void"
        self.name = cursor.spelling
        self.return_type = formatAndCleanType(cursor.result_type.spelling)
        self.arguments = []
        for child in cursor.get_children():
            if child.kind == CursorKind.PARM_DECL:
                self.arguments.append(Argument(child))

    def __str__(self):
        result = "{} {}" . format(self.return_type, self.name)
        for argument in self.arguments:
            result += "\n" + str(argument)
        return result


def combine_struct_or_union_decl(cursor):
    """
    Combine structure/union definition to a code snippet.
    """
    code = cursor.spelling + " {\n"
    for child in cursor.get_children():
        if child.kind == CursorKind.FIELD_DECL:
            code += "  {};\n" . format(
                mergeTypeAndVariable(formatAndCleanType(child.type.spelling),
                                     child.spelling))
    return code + "}"


def combine_struct_decl(cursor):
    """
    Combine structure definition to a code snippet.
    """
    return "struct " + combine_struct_or_union_decl(cursor)


def combine_union_decl(cursor):
    """
    Combine structure definition to a code snippet.
    """
    return "union " + combine_struct_or_union_decl(cursor)


def combine_enum_decl(cursor):
    """
    Combine structure definition to a code snippet.
    """
    code = "enum "  + format(cursor.spelling) + " {\n"
    for child in cursor.get_children():
        if child.kind == CursorKind.ENUM_CONSTANT_DECL:
            code += "  {} = {},\n" . format(child.spelling, child.enum_value)
    code += "}"
    return code


class TypeDefinition:
    """
    Type definition.
    """
    def __init__(self, cursor):
        """
        Construct higher level function declaration from CLang's cursor.
        """
        self.name = cursor.spelling
        self.type = None
        for child in cursor.get_children():
            if child.kind == CursorKind.STRUCT_DECL:
                self.type = combine_struct_decl(child)
            elif child.kind == CursorKind.UNION_DECL:
                self.type = combine_union_decl(child)
            elif child.kind == CursorKind.ENUM_DECL:
                self.type = combine_enum_decl(child)
            elif child.kind == CursorKind.TYPE_REF:
                self.type = child.spelling
        if self.type is None:
            self.type = formatAndCleanType(cursor.type.get_canonical().spelling)

    def __str__(self):
        return "typedef {} {}" .format(self.type, self.name)


def collect_function_prototypes(tu):
    file_name = tu.cursor.spelling
    functions = []
    for cursor in tu.cursor.walk_preorder():
        # Skip all tokens which are coming from different file.
        if cursor.location.file is None:
            continue
        if cursor.location.file.name != file_name:
            continue
        if cursor.kind == CursorKind.FUNCTION_DECL:
            functions.append(Function(cursor))
    return functions


def collect_types(tu):
    file_name = tu.cursor.spelling
    types = []
    for cursor in tu.cursor.walk_preorder():
        # Skip all tokens which are coming from different file.
        if cursor.location.file is None:
            continue
        if cursor.location.file.name != file_name:
            continue
        if cursor.kind == CursorKind.TYPEDEF_DECL:
            types.append(TypeDefinition(cursor))
    return types


def collect_defines(file_name):
    """
    Collect all XCB defines from file.
    """
    defines = []
    with open(file_name, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line.startswith("#define XCB"):
                continue
            defines.append(line)
    return defines

def parse_file(file_name):
    idx = Index.create()
    args = ('-x', 'c-header')
    tu = idx.parse(file_name, args=args)
    functions = collect_function_prototypes(tu)
    types = collect_types(tu)
    defines = collect_defines(file_name)
    return functions, types, defines


###############################################################################
# Wrangler generation

def generate_function_typedefs(functions):
    """
    Generate typedef for functions:
      typedef return_type (*tMyFunction)(arguments).
    """
    lines = []
    for function in functions:
        line = "typedef {} (*t{}) ({});" . format(
                function.return_type,
                function.name,
                ",".join(str(arg) for arg in function.arguments))
        lines.append(line)
    return lines


def generate_extern_function_declarations(functions):
    """
    Generate lines "extern tFoo foo_impl;"
    """
    lines = []
    for function in functions:
        line = "extern t{} {}_impl;" . format(
                function.name,
                function.name,
                ",".join(str(arg) for arg in function.arguments))
        lines.append(line)
    return lines


def generate_extern_function_definitions(functions):
    """
    Generate lines "tFoo foo_impl;"
    """
    lines = []
    for function in functions:
        line = "t{} {}_impl;" . format(
                function.name,
                function.name,
                ",".join(str(arg) for arg in function.arguments))
        lines.append(line)
    return lines


def generate_dynload_calls(header, functions):
    """
    Generate lines which reads all functions from dynamic library.
    """
    macro_prefix = os.path.basename(header).replace(".h", "").upper()
    lines = []
    for function in functions:
        line = "  {}_LIBRARY_FIND({});" . format(
                macro_prefix,
                function.name)
        lines.append(line)
    return lines


def generate_extern_function_wrappers(functions):
    """
    Genrate function wrappers, which passes call to a dynload symbol.
    """
    lines = []
    for function in functions:
        line = ""
        line += "{} {}" . format(formatAndCleanType(function.return_type),
                                 function.name)
        arguments = []
        argument_names = []
        for argument in function.arguments:
            arguments.append(str(argument))
            argument_names.append(argument.name)
        line += "({})" . format(", " . join(arguments)) + " {\n"
        line += "  return {}_impl({});\n" . format(
                function.name,
                ", " . join(argument_names))
        line += "}\n"
        lines.append(line)
    return lines


def generate_wrapper_declarations(functions):
    """
    Generate wrapper function declarations.
    Those declarations actually matches functions from xcb headers.
    """
    lines = []
    for function in functions:
        line = ""
        line += "{} {}" . format(formatAndCleanType(function.return_type),
                                 function.name)
        arguments = []
        argument_names = []
        for argument in function.arguments:
            arguments.append(str(argument))
            argument_names.append(argument.name)
        line += "({})" . format(", " . join(arguments)) + ";"
        lines.append(line)
    return lines


def add_functions_to_wrangler(header, wrangler, functions):
    section = ["/* " + os.path.basename(header) + " */"]
    typedefs = section + generate_function_typedefs(functions)
    externs = section + generate_extern_function_declarations(functions)
    definitions = section + generate_extern_function_definitions(functions)
    dynload = ["  " + section[0]] + generate_dynload_calls(header, functions)
    wrappers = section + generate_extern_function_wrappers(functions)
    wrapper_declarations = generate_wrapper_declarations(functions)
    wrangler["functions"]["typedefs"].extend(typedefs)
    wrangler["functions"]["wrapper_declarations"].extend(wrapper_declarations)
    wrangler["functions"]["declarations"].extend(externs)
    wrangler["functions"]["definitions"].extend(definitions)
    wrangler["functions"]["dynload"].extend(dynload)
    wrangler["functions"]["wrappers"].extend(wrappers)


def add_types_to_wrangler(header, wrangler, types):
    typedefs = ["/* " + os.path.basename(header) + " */"]
    for type in types:
        typedefs.append(str(type) + ";\n")
    wrangler["types"]["definitions"].extend(typedefs)


def add_definitions_to_wrangler(header, wrangler, definitions):
    wrangler["definitions"]["all"].extend(definitions)

def replace_template_variables(wrangler, data):
    """
    Replace variables like %foo% in template data with actual code.
    """
    for group in wrangler:
        for variable in wrangler[group]:
            template_variable = "%{}_{}%" . format(group, variable)
            data = data.replace(template_variable,
                                "\n" . join(wrangler[group][variable]))
    return data


def write_wrangler_to_file(wrangler, template, destination):
    """
    Write wrangler symbols to a template.
    """
    with open(template, "r") as input:
        data = input.read()
        data = replace_template_variables(wrangler, data)
        with open(destination, "w") as output:
            output.write(data)


def write_wrangler_to_files(wrangler):
    """
    Write generated data from wrangler context to actual source files.
    """
    path = os.path.dirname(os.path.realpath(__file__))
    write_wrangler_to_file(
            wrangler,
            os.path.join(path, "xcbew.template.h"),
            os.path.join(path, "..", "include", "xcbew.h"))
    write_wrangler_to_file(
            wrangler,
            os.path.join(path, "xcbew.template.c"),
            os.path.join(path, "..", "source", "xcbew.c"))

###############################################################################
# Main logic


if __name__ == "__main__":
    headers = ("/usr/include/xcb/xcb.h",
               "/usr/include/xcb/xproto.h",
              )
    if len(sys.argv) == 2:
        headers = [sys.argv[1]]
    wrangler = {
        "functions": {
            "typedefs": [],
            "wrapper_declarations": [],
            "declarations": [],
            "definitions": [],
            "dynload": [],
            "wrappers": [],
        },
        "types": {
            "definitions": [],
        },
        "definitions": {
            "all": []
        },
    }
    for header in headers:
        functions, types, definitions = parse_file(header)
        add_functions_to_wrangler(header, wrangler, functions)
        add_types_to_wrangler(header, wrangler, types)
        add_definitions_to_wrangler(header, wrangler, definitions)
        write_wrangler_to_files(wrangler)
