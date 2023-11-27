import os
import json
import re
import subprocess
import sys
import tty
import termios
import concurrent.futures
import threading
import glob
import argparse
import logging

try:
    # 尝试导入模块
    from gitignore_parser import parse_gitignore
    from tqdm import tqdm
except ImportError:
    # 如果导入失败，说明模块未安装
    print("正在安装依赖...")
    
    try:
        # 使用pip安装模块
        import subprocess
        subprocess.check_call(['/usr/bin/python3', '-m', 'pip', 'install', 'gitignore_parser', 'tqdm'])
        
        # 安装成功后导入模块
        from gitignore_parser import parse_gitignore
        from tqdm import tqdm
        print("安装成功！")
    except Exception as e:
        # 安装失败，输出错误信息
        print(f"安装失败: {e}")
        exit(1)

input_path = None
output_path = None
exclude_paths = None
additional_resource_folders = None
apply_gitignore_filter = None
apply_filtered_files = None
analyze_resources = None

def getch():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

def get_colored__description_and_object(description, obj = None):
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    colored_description = description
    colored_object = obj
    if obj:
        colored_description = f"{RED}{description}{RESET}"
        colored_object = f"{BLUE}{obj}{RESET}"
    else:
        colored_object = ""
    return f"{colored_description}{colored_object}"

def filter_files_by_type(all_files, filter_file_types):
    print(get_colored__description_and_object(f"正在过滤指定类型{filter_file_types}的文件..."))
    filtered_files = [file for file in all_files if any(file.endswith(file_type) for file_type in filter_file_types)]
    print(get_colored__description_and_object("过滤完成💩"))
    return filtered_files

def filter_files_by_gitignore(all_files):
    print(get_colored__description_and_object("正在应用.gitignore规则过滤文件..."))
    gitignore_file = os.path.join(input_path, ".gitignore")
    ignored_patterns = []
    if os.path.exists(gitignore_file):
        print("检索到.gitignore文件:", gitignore_file)
        with open(gitignore_file, "r") as f:
            ignored_patterns = f.read().splitlines()
            print(*ignored_patterns, sep="\n")
    
    gitignore_parser = parse_gitignore(gitignore_file)
    filtered_files = []

    # 应用.gitignore规则过滤
    with tqdm(total=len(all_files), desc="应用.gitignore规则", unit="file", leave=False, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
        pbar.set_description(get_colored__description_and_object("正在应用.gitignore规则过滤"))
        for file in all_files:
            name = os.path.basename(file)
            if not gitignore_parser(os.path.relpath(file, input_path)):
                filtered_files.append(file)
            else:
                RED = "\033[91m"
                BLUE = "\033[94m"
                RESET = "\033[0m"
                pbar.write(f"已过滤文件：{BLUE}{name}{RESET}({RED}{file}{RESET})")
            pbar.update(1)
    print(get_colored__description_and_object("应用.gitignore规则过滤文件完成💩"))
    return filtered_files

def extract_classes(content, file_type):
    oc_class_pattern = r"@interface\s+(\w+)\s*:\s*\w+"
    swift_class_pattern = r"class\s+(\w+)\s*:\s*\w+"
    swift_struct_pattern = r"struct\s+(\w+)\s*(?:\{|\(|<)"
    classes = []
    if file_type == ".h" or file_type == ".m":
        classes = re.findall(oc_class_pattern, content)
    elif file_type == ".swift":
        swift_classes = re.findall(swift_class_pattern, content)
        swift_structs = re.findall(swift_struct_pattern, content)
        classes = {"classes": swift_classes, "structs": swift_structs}

    return classes

def apply_classes_json(filtered_files):
    print(get_colored__description_and_object("正在提取文件中声明的class/struct..."))
    all_files = filter_files_by_type(filtered_files, [".h", ".m", ".swift"])
    filtered_oc_classes = []
    filtered_swift_classes = []
    filtered_swift_structs = []
    for file_path in all_files:
        with open(file_path, "r") as file:
            content = file.read()
        file_type = os.path.splitext(file_path)[1]
        if file_type == ".h" or file_type == ".m":
            oc_classes = extract_classes(content, file_type)
            filtered_oc_classes.extend(oc_classes)
        elif file_type == ".swift":
            swift_classes_and_structs = extract_classes(content, file_type)
            filtered_swift_classes.extend(swift_classes_and_structs["classes"])
            filtered_swift_structs.extend(swift_classes_and_structs["structs"])
    filtered_oc_classes = list(set(filtered_oc_classes))
    filtered_swift_classes = list(set(filtered_swift_classes))
    filtered_swift_structs = list(set(filtered_swift_structs))
    classes_json = {
        "Objective-C": filtered_oc_classes,
        "Swift": {
            "classes": filtered_swift_classes,
            "structs": filtered_swift_structs
        }
    }
    print(get_colored__description_and_object("提取class/struct完成💩"))
    return classes_json

def apply_resources():
    print(get_colored__description_and_object("正在检索项目中的资源信息..."))
    def extract_imageset_name(path):
        # 提取imageset名称
        imageset_path = os.path.dirname(path)
        imageset_name = os.path.basename(imageset_path)
        if imageset_name.endswith('.imageset'):
            imageset_name = imageset_name[:-9]
        return imageset_name

    imagesets = []
    others = {} 

    # 检索imageset
    imageset_files = glob.glob(os.path.join(input_path, "**/*.imageset/**/*.*"), recursive=True)
    for imageset_file in imageset_files:
        imageset_name = extract_imageset_name(imageset_file)
        imagesets.append(imageset_name)
    deduplicated_imagesets = list(set(imagesets))
    # 在 input_path 下检索 additional_resource_folders 中所有文件夹内的资源文件
    resource_files = []
    for folder_name in additional_resource_folders:
        folder_path = os.path.join(input_path, folder_name)
        # 如果连接后的路径是一个文件而不是目录，获取其所在的目录
        if not os.path.isdir(folder_path):
            folder_path = os.path.dirname(folder_path)
        # 检索文件夹内的所有资源文件
        folder_files = glob.glob(os.path.join(folder_path, "**/*.*"), recursive=True)
        folder_files = [file for file in folder_files if os.path.isfile(file)]
        resource_files.extend(folder_files)
    def remove_duplicate_suffix(name):
        if name.endswith('@2x'):
            return name[:-3]
        elif name.endswith('@3x'):
            return name[:-3]
        return name
    for resource_file in resource_files:
        full_name = os.path.basename(resource_file)
        name, format = full_name.rsplit(".", 1)
        name = remove_duplicate_suffix(name)
        if format in others:
            others[format].append(name)
        else:
            others[format] = [name]

    for format, names_list in others.items():
         others[format] = list(set(names_list))
    resources = {
        "imagesets": deduplicated_imagesets,
        "others": others
    }
    print(get_colored__description_and_object("检索完成💩"))
    resources_path = os.path.join(output_path, "filtered_resources.json")
    with open(resources_path, "w") as resources_file:
        json.dump(resources, resources_file, indent=4)
    print("是否要输出检索到的资源文件信息:(y/n)", end='', flush=True)
    user_input = getch()
    if user_input.lower() == "y":
        formatted_json = json.dumps(resources, indent=4)
        print(get_colored__description_and_object("检索到的资源文件信息:", formatted_json))
    print(get_colored__description_and_object("已保存检索到的资源文件至:", resources_path))
    return resources

def apply_dev_files(all_files):
    filter_file_types = [".h", ".m", ".swift", ".xib", ".nib", ".storyboard"]
    filtered_files = filter_files_by_type(all_files, filter_file_types)
    print(get_colored__description_and_object("过滤指定文件类型后的文件数量:",  len(filtered_files)))
    print("是否要输出过滤后的文件信息:(y/n)", end='', flush=True)
    user_input = getch()
    if user_input.lower() == "y":
        formatted_json = json.dumps(filtered_files, indent=4)
        print(get_colored__description_and_object("过滤后的文件信息:",  formatted_json))
    output_directory = os.path.join(output_path, "filtered_files.json")
    with open(output_directory, "w") as json_file:
        json.dump(filtered_files, json_file, indent=4)
    print(get_colored__description_and_object(f"已保存{filter_file_types}过滤后的文件路径至:",  output_directory))
    

    classes_json = apply_classes_json(filtered_files) 
    filtered_classes_path = os.path.join(output_path, "filtered_objects.json")
    with open(filtered_classes_path, "w") as classes_file:
        json.dump(classes_json, classes_file, indent=4)
    
    print("是否要输出提取的类信息:(y/n)", end='', flush=True)
    user_input = getch()
    if user_input.lower() == "y":
        formatted_json = json.dumps(classes_json, indent=4)
        print(get_colored__description_and_object("检索到的类信息:",  formatted_json))
    print(get_colored__description_and_object("已保存提取的类至:",  filtered_classes_path))
    return filtered_files

def contains_digit(input_string):
    pattern = r'\d'  # 正则表达式模式，匹配任意数字字符
    match = re.search(pattern, input_string)
    return match is not None

def check_resource_usage(resource, all_files, pbar, count_unuse, lock):
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    if contains_digit(resource): # TODO: 暂时忽略掉带有数字的资源
        return resource
    resource_used = False  # 添加一个标记来表示资源是否已经被使用
    pbar.set_description(f"正在检索资源{BLUE}{resource}{RESET}[已检测到的未使用资源数量:{RED}{count_unuse}{RESET}]")
    for file_path in all_files:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            if resource in content:
                resource_used = True  # 标记资源已经被使用
                break  # 终止循环
    if resource_used:
        return resource  # 返回资源，表示已使用
    else:
        with lock:
            count_unuse[0] += 1
        pbar.write(f"{BLUE}检测到未使用的资源：{RESET}{RED}{resource}{RESET}")
        return None  # 返回 None，表示未使用

def fetch_unused_resources(all_files, resources):
    print(get_colored__description_and_object("正在检索项目中未使用到的资源文件..."))
    all_resources = []
    for imageset in resources.get("imagesets", []):
        all_resources.append(imageset)
    for _, names in resources.get("others", {}).items():
        all_resources.extend(names)

    unused_resources = set(all_resources)
    total = len(unused_resources)
    lock = threading.Lock()
    resources_to_remove = set()
    count_unuse = [0]
    bar_format = '{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
    with concurrent.futures.ThreadPoolExecutor() as executor, \
            tqdm(total=total, desc="检索未使用的资源", unit="file", leave=False, bar_format=bar_format) as pbar:
        futures = [executor.submit(check_resource_usage, resource, all_files, pbar, count_unuse, lock) for resource in unused_resources]
        for future in concurrent.futures.as_completed(futures):
            with lock:
                r = future.result()
                if r:
                    resources_to_remove.add(r)
                pbar.update(1)
    executor.shutdown(wait=True)
    unused_resources -= resources_to_remove
    unused_resources = list(unused_resources)
    result_path = os.path.join(output_path, "unused_assets.json")
    with open(result_path, 'w') as result_file:
        json.dump(unused_resources, result_file, indent=4)

    print("是否要输出未使用的资源信息:(y/n)", end='', flush=True)
    user_input = getch()
    if user_input.lower() == "y":
        unused_resources_json = json.dumps(unused_resources, indent=4)
        print(get_colored__description_and_object("检索到的未使用的资源信息:", unused_resources_json))
    print(get_colored__description_and_object("检索完成💩，未使用的资源数量:", count_unuse))
    print(get_colored__description_and_object("已保存未使用的资源至:", result_path))

def fetch_filtered_files():
    print(get_colored__description_and_object("检索文件夹:", input_path))
    all_files = [os.path.join(root, filename) for root, _, files in os.walk(input_path) for filename in files]
    print(get_colored__description_and_object("检索文件数:", len(all_files)))
    filtered_files = all_files
    if apply_gitignore_filter:
        filtered_files = filter_files_by_gitignore(all_files)
    print(get_colored__description_and_object("应用gitignore规则过滤后的文件数量:", len(filtered_files)))
    return filtered_files

def create_arg_parser():
    parser = argparse.ArgumentParser(description="Utility script: analyze project files, filter dev files using gitignore, and detect unused classes. Identify and categorize resources, highlighting unused ones. Save results for efficient project management.")

    # 是否使用缓存文件代替全量文件过滤，默认为False
    parser.add_argument(
        "-t", 
        "--apply_filtered_files", 
        action="store_true", 
        help="Use cached 'filtered_files.json' instead of fetching files. Default is False.(e.g. -t or not)"
    )

    # 是否分析资源文件并提取出未使用的资源文件，默认为False
    parser.add_argument(
        "-r", 
        "--analyze_resources", 
        action="store_true", 
        help="Analyze resources and extract unused resources. Default is False.(e.g. -r or not)"
    )

    # 是否应用gitignore规则进行文件过滤，默认为True
    parser.add_argument(
        "-gi", 
        "--apply_gitignore_filter", 
        action="store_true", 
        default=True, 
        help="Apply gitignore rules for filtering files during script execution. Default is True.(e.g. -gi or not)"
    )

    # 外部输入分析路径，默认为当前脚本文件夹
    parser.add_argument(
        "-p", 
        "--input_path", 
        default=os.path.dirname(os.path.abspath(__file__)), 
        help="Specify the input path. Default is the current script folder.(e.g. -p={your_project_root_path})"
    )

    # 过滤后的文件输出地址，默认为当前脚本文件夹
    parser.add_argument(
        "-o",
        "--output_path", 
        default=os.path.dirname(os.path.abspath(__file__)), 
        help="Specify the output path. Default is the current script folder.(e.g. -o={your_project_root_path})"
    )

    # 默认只检测Assets.xcassets中的资源，通过该指令接受额外的一个或多个文件夹
    parser.add_argument(
        "-arp", 
        "--additional_resource_folders", 
        nargs='+', 
        help="Specify additional folder to search for resources. By default, only resources within 'Assets.xcassets' are checked. This option allows you to include one or more custom folder for resource detection.(e.g. -arp=Folder1,Folder2... or -arp Folder1 Folder2 ...)"
    )

    return parser

def inititalizeGlobalVariable(args):
    global input_path, output_path, apply_gitignore_filter, apply_filtered_files, analyze_resources, additional_resource_folders
    input_path = args.input_path
    output_path = args.output_path
    apply_filtered_files = args.apply_filtered_files
    apply_gitignore_filter = args.apply_gitignore_filter
    analyze_resources = args.analyze_resources
    additional_resource_folders = args.additional_resource_folders if args.additional_resource_folders else []

if __name__ == "__main__":
    arg_parser = create_arg_parser()
    args = arg_parser.parse_args()
    inititalizeGlobalVariable(args)
    # 切换工作目录
    try:
        os.chdir(input_path)
        print(f"Changed working directory to: {input_path}")
        logging.info(f"Changed working directory to: {input_path}")
        if apply_filtered_files:
            with open(os.path.join(output_path, "filtered_files.json"), "r") as filtered_files_file:
                filtered_files = json.load(filtered_files_file)
        else:
            filtered_files = fetch_filtered_files()
            filtered_files = apply_dev_files(filtered_files)

        if analyze_resources:
            resources = apply_resources()
            fetch_unused_resources(filtered_files, resources)
    except FileNotFoundError:
        print(f"The specified directory does not exist: {input_path}")
    except PermissionError:
        print(f"Permission error while trying to change to: {input_path}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")