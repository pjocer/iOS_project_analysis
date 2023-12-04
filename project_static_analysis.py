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
import fnmatch
import shutil

try:
    from gitignore_parser import parse_gitignore
    from tqdm import tqdm
except ImportError:
    print("正在安装依赖...")
    try:
        subprocess.check_call(['/usr/bin/python3', '-m', 'pip', 'install', 'gitignore_parser', 'tqdm'])
        from gitignore_parser import parse_gitignore
        from tqdm import tqdm
        print("安装成功！")
    except Exception as e:
        print(f"安装失败: {e}")
        exit(1)

input_path = None
output_path = None
additional_exclude_file_folder = None
additional_resource_folders = None
disable_gitignore = None
apply_filtered_files = None
analyze_resources = None
exclude_resource_folders = None

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

def find_gitignore():
    for root, dirs, files in os.walk(input_path):
        if '.gitignore' in files:
            ignore_path = os.path.join(root, '.gitignore')
            print(get_colored__description_and_object("检索到.gitignore文件:", ignore_path))
            return ignore_path
    return None

def filter_files_by_gitignore(all_files):
    gitignore_file = find_gitignore()
    ignored_patterns = []
    if os.path.exists(gitignore_file):
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
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    def find_matching_folders(base_path, folders):
        if not folders:
            return None
        matching_folders = set()
        for folder in folders:
            for root, dirs, files in os.walk(base_path):
                if folder in dirs:
                    matching_folders.add(os.path.join(root, folder))
        return list(matching_folders)
    # 检索imageset
    def apply_imageset(imageset_files, pbar):
        def extract_imageset_name(path):
            imageset_path = os.path.dirname(path)
            imageset_name = os.path.basename(imageset_path)
            if imageset_name.endswith('.imageset'):
                imageset_name = imageset_name[:-9]
            return imageset_name

        result = {}
        for imageset_file in imageset_files:
            imageset_name = extract_imageset_name(imageset_file)
            result[imageset_name] = imageset_file
            pbar.write(f"已检索到资源文件：{BLUE}{imageset_name}{RESET}")
            pbar.update(1)

        return result

    # 在 input_path 下检索 additional_resource_folders 中所有文件夹内的资源文件
    def apply_addtional_resouces(additional_resource_files, pbar):
        def remove_duplicate_suffix(name):
            if name.endswith('@2x'):
                return name[:-3]
            elif name.endswith('@3x'):
                return name[:-3]
            return name

        resource_files = set()
        exclude_resource_paths = find_matching_folders(input_path, exclude_resource_folders)
        for file_path in additional_resource_files:
            exclude = False
            file_name = os.path.basename(file_path)
            if exclude_resource_paths:
                is_under_exclude_path = any(
                    os.path.commonpath([file_path, exclude_path]) == exclude_path
                    for exclude_path in exclude_resource_paths
                )
                if is_under_exclude_path:
                    pbar.write(f"已排除资源文件：{RED}{file_name}{RESET}")
                    exclude = True
            if not exclude:
                pbar.write(f"已检索资源文件：{BLUE}{file_name}{RESET}")
                resource_files.add(file_path)
            pbar.update(1)
  
        result = {}
        for resource_file in resource_files:
            full_name = os.path.basename(resource_file)
            name, format = full_name.rsplit(".", 1)
            name = remove_duplicate_suffix(name)
            if format not in result:
                result[format] = {}
            result[format][name] = resource_file
        pbar.update(1)
        return result
        
    imageset_files = glob.glob(os.path.join(input_path, "**/*.imageset/**/*.*"), recursive=True)
    additional_resource_files = list()
    additional_resource_folder_paths = find_matching_folders(input_path, additional_resource_folders)
    for path in additional_resource_folder_paths:
        if os.path.isdir(path):
            directory_path = path
        else:
            directory_path = os.path.dirname(path)
        folder_files = glob.glob(os.path.join(directory_path, "**/*.*"), recursive=True)
        folder_files = [file for file in folder_files if os.path.isfile(file)]
        additional_resource_files.extend(folder_files)

    with tqdm(total=len(imageset_files) + len(additional_resource_files) + 1, desc=f"检索资源文件", unit="asset", leave=False, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
        pbar.set_description(get_colored__description_and_object(f"正在检索Assets.xcassets"))
        deduplicated_imagesets = apply_imageset(imageset_files, pbar)
        pbar.set_description(get_colored__description_and_object(f"正在检索扩展资源：{additional_resource_folders}"))
        others = apply_addtional_resouces(additional_resource_files, pbar)

    resources = {
        "imagesets": deduplicated_imagesets,
        "others": others
    }
    print(get_colored__description_and_object("检索完成💩"))
    resources_path = os.path.join(output_path, "filtered_resources.json")
    with open(resources_path, "w") as resources_file:
        json.dump(resources, resources_file, indent=4)
    print(get_colored__description_and_object("已保存检索到的资源文件至:", resources_path))
    return resources

def apply_dev_files(all_files):
    filter_file_types = [".h", ".m", ".swift", ".xib", ".nib", ".storyboard"]
    filtered_files = filter_files_by_type(all_files, filter_file_types)
    print(get_colored__description_and_object("过滤指定文件类型后的文件数量:",  len(filtered_files)))
    output_directory = os.path.join(output_path, "filtered_files.json")
    with open(output_directory, "w") as json_file:
        json.dump(filtered_files, json_file, indent=4)
    print(get_colored__description_and_object(f"已保存{filter_file_types}过滤后的文件路径至:",  output_directory))
    

    classes_json = apply_classes_json(filtered_files) 
    filtered_classes_path = os.path.join(output_path, "filtered_objects.json")
    with open(filtered_classes_path, "w") as classes_file:
        json.dump(classes_json, classes_file, indent=4)
    
    print(get_colored__description_and_object("已保存提取的类至:",  filtered_classes_path))
    return filtered_files

def check_resource_usage(resource, all_files, pbar, count_unuse, lock):

    def contains_digit(input_string):
        pattern = r'\d'
        match = re.search(pattern, input_string)
        return match is not None

    def is_content_matching_resource(resource, file_content):
        splited_string_arr = re.compile(r'([^_?-?\d]+)').findall(resource)
        if splited_string_arr:
            return all(s in file_content for s in splited_string_arr)
        else:
            return resource in file_content

    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    resource_used = False
    pbar.set_description(f"正在检索资源{BLUE}{resource}{RESET}[已检测到的未使用资源数量:{RED}{count_unuse}{RESET}]")
    for file_path in all_files:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            if content:
                try:
                    value = int(resource)
                    is_full_digit = True
                except ValueError:
                    is_full_digit = False

                if resource in content:
                    resource_used = True
                    break
                elif contains_digit(resource) and is_content_matching_resource(resource, content):
                    resource_used = True
                    break

    if resource_used:
        return resource
    else:
        with lock:
            count_unuse[0] += 1
        pbar.write(f"{BLUE}检测到未使用的资源：{RESET}{RED}{resource}{RESET}")
        return None

def fetch_unused_resources(all_files, resources):
    print(get_colored__description_and_object("正在检索项目中未使用到的资源文件..."))
    all_resources = []
    imageset_keys = set(resources.get("imagesets", {}).keys())
    all_resources.extend(imageset_keys)
    for item in resources.get("others", {}).values():
        all_resources.extend(set(item.keys()))
    total = len(all_resources)
    lock = threading.Lock()
    used_resources = []
    count_unuse = [0]
    bar_format = '{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
    with concurrent.futures.ThreadPoolExecutor() as executor, \
            tqdm(total=total, desc="检索未使用的资源", unit="file", leave=False, bar_format=bar_format) as pbar:
        futures = [executor.submit(check_resource_usage, resource, all_files, pbar, count_unuse, lock) for resource in all_resources]
        for future in concurrent.futures.as_completed(futures):
            with lock:
                r = future.result()
                if r and r not in used_resources:
                    used_resources.append(r)
                pbar.update(1)

    executor.shutdown(wait=True)
    unused_resources = list(set(all_resources).difference(set(used_resources)))
    result_path = os.path.join(output_path, "unused_assets.json")
    
    with open(result_path, 'w') as result_file:
        json.dump(unused_resources, result_file, indent=4)

    print(get_colored__description_and_object("检索完成💩，未使用的资源数量:", count_unuse))
    print(get_colored__description_and_object("已保存未使用的资源至:", result_path))
    return unused_resources

def clear_unused_resources(unused_resources, resources):
    def delete_imageset_or_file(file_path):
        nonlocal total_size_bytes
        try:
            size_bytes = os.path.getsize(file_path)
            total_size_bytes += size_bytes
        except FileNotFoundError:
            print(f"File not found: {file_path}")
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")
        
        parent_dir = os.path.dirname(file_path)
        if parent_dir.endswith('.imageset'):
            shutil.rmtree(parent_dir)
        else:
            os.remove(file_path)

    imageset_obj = resources["imagesets"]
    other_objs = resources["others"]
    unused_dict = {key: imageset_obj[key] for key in unused_resources if key in imageset_obj}
    unused_dict.update({key: format_dict[key] for key in unused_resources for format_dict in other_objs.values() if key in format_dict})
    total_size_bytes = 0
    with tqdm(total=len(unused_dict), desc="正在清理资源文件", unit="file", leave=False, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
        RED = "\033[91m"
        BLUE = "\033[94m"
        RESET = "\033[0m"
        for name, file_path in unused_dict.items():
            delete_imageset_or_file(file_path)
            pbar.write(f"已清理资源：{BLUE}{name}{RESET}({RED}{file_path}{RESET})")
            pbar.update(1)
    total_size_mb = round(total_size_bytes / (1024 * 1024), 2)
    print(f"清理资源完成💩，共清理文件{RED}{len(unused_dict)}{RESET}个，总计大小{RED}{total_size_mb}MB{RESET}")

def filter_additional_exclude_files(all_files):
    print(get_colored__description_and_object(f"正在应用扩展规则{additional_exclude_file_folder}过滤"))
    assert isinstance(all_files, list), "all_files should be a list of file paths"
    assert isinstance(additional_exclude_file_folder, list), "additional_exclude_file_folder should be a list of patterns"
    filtered_paths = []
    with tqdm(total=len(all_files), desc=f"应用扩展规则过滤{additional_exclude_file_folder}", unit="file", leave=False, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
        pbar.set_description(get_colored__description_and_object(f"正在应用扩展规则{additional_exclude_file_folder}过滤"))
        for file_path in all_files:
            for pattern in additional_exclude_file_folder:
                if not fnmatch.fnmatchcase(file_path, pattern):
                    filtered_paths.append(file_path)
                else:
                    name = os.path.basename(file_path)
                    RED = "\033[91m"
                    BLUE = "\033[94m"
                    RESET = "\033[0m"
                    pbar.write(f"已过滤文件：{BLUE}{name}{RESET}({RED}{file_path}{RESET})")

                pbar.update(1)
    print(get_colored__description_and_object(f"应用扩展规则过滤{additional_exclude_file_folder}文件完成💩"))
    return filtered_paths

def fetch_filtered_files():
    print(get_colored__description_and_object("检索文件夹:", input_path))
    all_files = [os.path.join(root, filename) for root, _, files in os.walk(input_path) for filename in files]
    print(get_colored__description_and_object("检索文件数:", len(all_files)))
    filtered_files = all_files
    if not disable_gitignore:
        filtered_files = filter_files_by_gitignore(all_files)
    print(get_colored__description_and_object("应用gitignore规则过滤后的文件数量:", len(filtered_files)))
    if additional_exclude_file_folder:
        filtered_files = filter_additional_exclude_files(filtered_files)
        print(get_colored__description_and_object("应用扩展规则过滤后的文件数量:", len(filtered_files)))
    return filtered_files

def create_arg_parser():
    parser = argparse.ArgumentParser(
        description="This script serves as a static analysis tool for iOS projects, designed to perform two main functions:\n"
                    "1. Analysis of developer-created files: It identifies and filters out Objective-C classes and Swift classes/structs created by developers. Further refinement distinguishes which classes or structs are unused and can be safely removed.\n"
                    "2. Analysis of resource files: The script examines 'Assets.xcassets' and other custom directories (refer to the '--additional_resource_folders' option) within the project. It categorizes resource files based on their types and refines the list to identify files that can be safely cleaned—those not referenced in filtered developer files.\n\n"
                    "Usage Example:\n"
                    "   ```python your_script.py -p /path/to/your/project -o /output/folder -r -arp CustomResources```\n"
                    "   Analyzes the specified iOS project, outputs results to the designated folder, performs resource analysis, and includes the 'CustomResources' directory for additional resource detection."
    )

    # 是否使用缓存文件代替全量文件过滤，默认为False
    parser.add_argument(
        "-t",
        "--apply_filtered_files",
        action="store_true",
        help="Enable the use of cached files instead of full file filtering. By default, full filtering based on Gitignore rules and additional exclusions is applied. When this option is activated, it disregards the '--additional_exclude_file_folder' and '--disable_gitignore' options, directly retrieving the file list from the specified '--output_path'.\n\n"
            "This option is useful when you have a pre-defined file list and want to bypass Gitignore rules for a specific operation, improving efficiency.\n\n"
            "Usage Example:\n"
            "   ```python3 project_static_analysis.py -t --output_path cached_file_list.txt```\n"
            "   Activates the use of cached files specified in 'cached_file_list.txt', ignoring Gitignore rules and additional exclusions.\n\n"
            "Note: Ensure the provided file list is accurate and relevant to the operation you are performing."
    )

    # 是否分析资源文件并提取出未使用的资源文件，默认为False
    parser.add_argument(
        "-r",
        "--analyze_resources",
        action="store_true",
        help="Enable resource file analysis to identify and extract unused resources. By default, this analysis is disabled.\n\n"
            "Example:\n"
            "   ```python3 project_static_analysis.py -r```\n"
            "   Enables resource analysis to identify and extract unused resources in the project. Use this option to optimize your application's resource usage."
    )
    
    # 是否禁用gitignore规则进行文件过滤，默认为开启
    parser.add_argument(
        "-dg",
        "--disable_gitignore",
        action="store_true",
        help="Whether to disable .gitignore rules for file filtering. By default, .gitignore rules are enabled."
    )

    # 默认只应用gitignore规则过滤工程中创建的开发者文件，可通过此参数添加额外的过滤文件夹或文件
    parser.add_argument(
        "-afp", 
        "--additional_exclude_file_folder", 
        nargs='+', 
        help="Exclude extra folders or files from version control, supplementing Gitignore rules. By default, the command filters developer-created files. Use this option to add more exclusions, supporting wildcards.\n\n"
         "Examples:\n"
         "1. Exclude a folder:\n"
         "   ```python3 project_static_analysis.py -afp folder_to_exclude```\n"
         "2. Exclude files with wildcards:\n"
         "   ```python3 project_static_analysis.py -afp folder/*.log```\n"
         "3. Exclude multiple items:\n"
         "   ```python3 project_static_analysis.py -afp folder1 folder2 file_to_exclude.txt```\n"
         "Ensure paths are relative to the project root. Added items follow Gitignore-like rules, refining version control for specific project needs."
    )

    # 外部输入分析路径，默认为当前脚本文件夹
    parser.add_argument(
        "-p",
        "--input_path",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="Specify the input analysis path from external sources. By default, it is set to the current directory of the script.\n\n"
            "Example:\n"
            "   ```python3 project_static_analysis.py -p /path/to/your/project```\n"
            "   Sets the input path to '/path/to/your/project', allowing analysis of resources or files within that specified directory."
    )

    # 过滤后的文件输出地址，默认为当前脚本文件夹
    parser.add_argument(
        "-o",
        "--output_path",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="Specify the output path for filtered files from external input. By default, it is set to the current directory of the script.\n\n"
            "Example:\n"
            "   ```python3 project_static_analysis.py -o /path/to/output/folder```\n"
            "   Sets the output path to '/path/to/output/folder', where the filtered files will be stored. Use this option to control the destination of the analysis results."
    )
    # 默认只检测Assets.xcassets中的资源，通过该指令接收额外的一个或多个文件夹
    parser.add_argument(
        "-arp",
        "--additional_resource_folders",
        nargs='+',
        help="Specify additional folders for resource detection, supplementing the default search limited to 'Assets.xcassets'. This option allows you to include one or more extra folders, supporting the use of wildcards.\n\n"
            "Usage Example:\n"
            "   ```python3 project_static_analysis.py -arp Resources CustomAssets/*```\n"
            "   Adds 'Resources' and all subdirectories matching the 'CustomAssets' pattern to the resource detection process. Use this option to broaden the scope of resource analysis beyond the default 'Assets.xcassets'."
    )

    # 排除的资源检测，通过该指令排除一个或多个文件夹
    parser.add_argument(
        "-erp",
        "--exclude_resource_folders",
        nargs='+',
        help="Exclude specified folders when detecting resource files in the project. "
            "Use this option to ignore specific directories containing resources that "
            "should not be processed. Provide a space-separated list of folder names. "
            "Example: -arp folder1 folder2"
    )
    return parser

def recreate_output_directory():
    if os.path.exists(output_path):
        shutil.rmtree(output_path)

    os.makedirs(output_path)

def inititalize_global_variable(args):
    global input_path, output_path, disable_gitignore, apply_filtered_files, analyze_resources, additional_resource_folders, additional_exclude_file_folder, exclude_resource_folders
    input_path = args.input_path
    output_path = args.output_path
    apply_filtered_files = args.apply_filtered_files
    disable_gitignore = args.disable_gitignore
    analyze_resources = args.analyze_resources
    additional_resource_folders = args.additional_resource_folders
    additional_exclude_file_folder = args.additional_exclude_file_folder
    exclude_resource_folders = args.exclude_resource_folders

if __name__ == "__main__":
    arg_parser = create_arg_parser()
    args = arg_parser.parse_args()
    inititalize_global_variable(args)
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
            if apply_filtered_files:
                with open(os.path.join(output_path, "filtered_resources.json"), "r") as filtered_resources_file:
                    resources = json.load(filtered_resources_file)
                with open(os.path.join(output_path, "unused_assets.json"), "r") as filtered_files_file:
                    unused_resources = json.load(filtered_files_file)
            else:
                resources = apply_resources()
                unused_resources = fetch_unused_resources(filtered_files, resources)
            clear_unused_resources(unused_resources, resources)
    except FileNotFoundError:
        print(f"The specified directory does not exist: {input_path}")
    except PermissionError:
        print(f"Permission error while trying to change to: {input_path}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")