#!/usr/bin/env python3

import os
import re
import sys

source_to_resource = {}
resource_to_source = {}
loader_map = {
    "": "resource://gre/modules/commonjs/",
    "main": "resource:///modules/devtools/main.js",
    "definitions": "resource:///modules/devtools/definitions.js",
    "devtools": "resource:///modules/devtools",
    "devtools/toolkit": "resource://gre/modules/devtools",
    "devtools/server": "resource://gre/modules/devtools/server",
    "devtools/toolkit/webconsole": "resource://gre/modules/devtools/toolkit/webconsole",
    "devtools/app-actor-front": "resource://gre/modules/devtools/app-actor-front.js",
    "devtools/styleinspector/css-logic": "resource://gre/modules/devtools/styleinspector/css-logic",
    "devtools/css-color": "resource://gre/modules/devtools/css-color",
    "devtools/output-parser": "resource://gre/modules/devtools/output-parser",
    "devtools/client": "resource://gre/modules/devtools/client",
    "devtools/pretty-fast": "resource://gre/modules/devtools/pretty-fast.js",
    "devtools/jsbeautify": "resource://gre/modules/devtools/jsbeautify/beautify.js",
    "devtools/async-utils": "resource://gre/modules/devtools/async-utils",
    "devtools/content-observer": "resource://gre/modules/devtools/content-observer",
    "gcli": "resource://gre/modules/devtools/gcli",
    "projecteditor": "resource:///modules/devtools/projecteditor",
    "promise": "resource://gre/modules/Promise-backend.js",
    "acorn": "resource://gre/modules/devtools/acorn",
    "acorn/util/walk": "resource://gre/modules/devtools/acorn/walk.js",
    "tern": "resource://gre/modules/devtools/tern",
    "source-map": "resource://gre/modules/devtools/sourcemap/source-map.js",
    "xpcshell-test": "resource://test"
}

# Allow libs from external repos to remain special for now
ignored_resource_prefixes = [
    "resource://gre/modules/devtools/acorn",
    "resource://gre/modules/devtools/tern",
    "resource://gre/modules/devtools/sourcemap",
    "resource://test"
]

# For some libs, we specify the files to ignore by source path
ignored_source_prefixes = [
    "devtools/shared/gcli/source"
]

def record_source_to_resource(path):
    print("Reading %s" % path)
    is_client = path.split("/")[1] == "client"
    module_base = None
    with open(path, 'r') as file:
        for line in file:
            if line.startswith("EXTRA_JS_MODULES"):
                # Replace ["foo"] with .foo
                module_base = re.sub(r"\[['\"]([\w-]+?)['\"]\]", r".\1", line)
                # Convert to resource://
                module_base = re.search(r"EXTRA_JS_MODULES(.*) \+= \[", module_base).group(1)
                module_base = module_base.replace(".", "/")
                if is_client:
                    module_base = "resource:///modules" + module_base
                else:
                    module_base = "resource://gre/modules" + module_base
            elif line == "]\n":
                module_base = None
            elif module_base is not None:
                # print("Line: %s, Base: %s" % (line, module_base))
                relative_source = re.search(r"[\"'](.*)[\"']", line).group(1)
                # Record mapping of source path to resource path
                source = os.path.join(os.path.dirname(path), relative_source)
                resource = module_base + "/" + os.path.basename(source)
                source_to_resource[source] = resource
                resource_to_source[resource] = source
                print("%s -> %s" % (source, resource))

resolve_map = list(loader_map.keys())
resolve_map.sort(key = len, reverse = True)
resolve_map = [[x, loader_map[x]] for x in resolve_map]
# print(resolve_map)

def is_relative(id):
    return id[0] == "."

def is_resource(id):
    return id.startswith("resource://")

def resolve(id):
    if is_resource(id):
        return normalize_ext(id)
    for id_base, resource_base in resolve_map:
        if id.startswith(id_base):
            return normalize_ext(id.replace(id_base, resource_base, 1))
    raise RuntimeError("No mapping found for %s" % id)

def normalize_ext(resource):
    ext = os.path.splitext(resource)[1]
    if ext:
        return resource
    return resource + '.js'

def rewrite_source(path):
    print("Updating %s" % path)
    with open(path, 'r') as file:
        contents = file.read()
        changed = False
        for match in re.finditer(r"(Components.utils.import|Cu.import|require|devtoolsRequire|loadFrameScript|importScripts|loadSubScript)\([\"']([^;]*?)[\"']", contents):
            current = match.group(0)
            id = match.group(2)
            is_import = match.group(1) != "require" and match.group(1) != "devtoolsRequire"
            rewritten = rewrite_block(current, id, is_import, path)
            if rewritten:
                contents = contents.replace(current, rewritten, 1)
                changed = True
        for match in re.finditer(r"(lazyImporter|lazyRequireGetter|defineLazyModuleGetter)\([^;]+?,[^;]+?,[^;]+?[\"']([^;]*?)[\"']", contents, re.DOTALL):
            current = match.group(0)
            id = match.group(2)
            is_import = match.group(1) != "lazyRequireGetter"
            rewritten = rewrite_block(current, id, is_import, path)
            if rewritten:
                contents = contents.replace(current, rewritten, 1)
                changed = True
        if changed:
            with open(path, 'w') as writable_file:
                writable_file.write(contents)

def rewrite_block(current, id, is_import, path):
    # Ignore empty IDs
    if len(id) == 0:
        return None
    # Ignore relative IDs, they should be okay
    if is_relative(id):
        return None
    # Ignore "main" used in addon-sdk files
    if path.startswith("./addon-sdk") and id == "main":
        return None
    print("Current: %s" % current)
    resource = resolve(id)
    # Allow libs from external repos to remain special for now
    for prefix in ignored_resource_prefixes:
        if resource.startswith(prefix):
            return None
    print("Resource: %s" % resource)
    # Ignore resources outside of devtools
    if not "devtools" in resource:
        return None
    try:
        source = resource_to_source[resource]
    except KeyError:
        if resource.startswith("resource:///"):
            resource = resource.replace("resource:///", "resource://gre/")
            source = resource_to_source[resource]
        else:
            print("WARNING! No mapping for: %s" % resource)
            return None
    # For some libs, we specify the files to ignore by source path
    for prefix in ignored_source_prefixes:
        if source.startswith(prefix):
            return None
    if is_import or is_resource(id):
        is_client = source.startswith("devtools/client")
        if is_client:
            updated_id = "resource:///modules/" + source
        else:
            updated_id = "resource://gre/modules/" + source
    else:
        base, ext = os.path.splitext(source)
        # require() calls don't need the .js extension
        if ext == ".js":
            source = base
        updated_id = source
    rewritten = current.replace(id, updated_id)
    print("Updated: %s" % rewritten)
    return rewritten

# Scan all devtools moz.build files to record the mapping of paths in the source
# tree to resource:// URIs.
for root, dirs, files in os.walk("devtools"):
    for file in files:
        if file == "moz.build":
            record_source_to_resource(os.path.join(root, file))

# Visit all files in the tree to update various require and import paths to be
# based on source tree locations instead of arbitrary names
for root, dirs, files in os.walk("."):
    for dir in dirs:
        if dir == ".hg" or dir == ".git" or dir.startswith("obj-"):
            dirs.remove(dir)
    for file in files:
        try:
            rewrite_source(os.path.join(root, file))
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            continue
