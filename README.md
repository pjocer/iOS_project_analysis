# iOS工程检查工具

实用脚本：分析项目文件，使用gitignore过滤dev文件，检测未使用的类。识别和分类资源，突出显示未使用的资源。保存结果以提高项目管理效率。

# 一、分析iOS工程中开发者创建的文件以及其中的类和结构体。
- 目前支持检索的文件类型为`[".h", ".m", ".swift", ".xib", ".nib", ".storyboard"]`
- 检索后的文件路径将保存在输出路径下的`filtered_files.json`中，格式为：

  ```
  [
  	#绝对路径
  }
  ```
  
	> 支持应用`gitignore`的过滤规则，可通过`-gi`指令开启，详见脚本说明(`python3 project_static_analysis -h`)

- 检索后的类和结构体信息将保存在输出路径下的`filtered_objects.json`中，格式为:

  ```
  {
    "Objective-C": [
      ... #OC声明类
    ],
    "Swift": [
      "classes": [
        ...#Swift声明的类
      ],
      "structs": [
        ...#Swift声明的结构体
      ]
    ]
  }
  ```
  
  > 可通过`-p`指定工程路径，默认为脚本当前的路径。通过`-o`指定过滤后的输出路径，默认为脚本当前的路径。详见脚本说明(`python3 project_static_analysis -h`)
  
  
  # 二、分析iOS工程中的资源文件以及未被使用过的资源文件。
  
- 检索后的资源将保存在输出路径下的`filtered_resources.json`中，格式为：

	```
	{
		"imagesets": [ # Assets.xcassets中的资源
			... # 资源名称
		],
		"others": [ # 其它自定义文件夹中的资源
			"资源类型": [
				... # 资源名称
			],
			"资源类型": [
				... # 资源名称
			]
			...
		]
	}
	```

	> 可通过`-arp`添加`Assets.xcassets`以外的自定义资源文件夹。详见脚本说明(`python3 project_static_analysis -h`)

- 检索未被使用的资源将保存在输出路径下的`unused_assets.json`中，格式为：

	```
	[
		... # 资源名称
	]
	```
  > 支持检测工程中未被使用到的资源列表，可通过`-r`指令开启。详见脚本说明(`python3 project_static_analysis -h`)
