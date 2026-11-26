# RA2AYRMB

**Red Alert 2 and Yuri's Revenge MIX Browser** 是一款桌面应用，用于浏览和管理 Westwood MIX 归档，以及普通游戏文件和文件夹。

版本：**1.2.1**

README： [English](README.md) | 简体中文  
界面语言：英语、简体中文

## 功能

- 浏览文件夹、MIX 归档及嵌套 MIX 归档。
- 创建和保存 MIX 归档；向归档添加、提取、替换、复制、重命名和删除条目。
- 从文件夹或归档根目录递归搜索，支持正则表达式并显示相对路径。
- 预览受支持的文本、图像、动画、模型、色盘、名称数据库、音频和视频格式。
- 使用内置的 XCC 名称表，也可按需下载 CnCNet 社区 MIX 名称数据库。
- 根据归档内容、INI 规则、自定义规则和可选的 RA2/YR 游戏目录自动选择色盘。
- 提供桌面界面、输出 JSON 的 CLI，以及本地 stdio MCP 服务器。
- 可选为 `.mix`、`.mmx` 和 `.yro` 容器注册 Windows 资源管理器上下文菜单及文件处理程序，仅作用于当前用户。

## 预览支持

桌面程序的 **帮助 > 预览支持...** 会列出以下格式及限制：

| 类别 | 格式 |
| --- | --- |
| 文本文档 | `.bat`、`.cfg`、`.csv`、`.glsl`、`.htm`、`.html`、`.ini`、`.json`、`.lcf`、`.log`、`.map`、`.md`、`.mpr`、`.txt`、`.xml`、`.yrm` |
| SHP 动画 | `.shp`、`.shp-ts` |
| PCX 图像 | `.pcx`、`.mmp`* |
| 色盘 | `.pal` |
| 体素模型 | `.vxl`、`.hva` |
| XCC 名称数据 | `.dat` |
| 音频 | `.wav` |
| 视频 | `.bik`、`.bk2`、`.bink` |
| 可浏览的 MIX 容器 | `.mix`、`.mmx`、`.yro` |

`*` 只有当 `.mmp` 文件内容具有有效的 PCX 签名时，程序才会将其作为 PCX 预览。`.dat` 仅支持可识别的 XCC MIX 名称数据库。PAL 预览支持 Westwood 原始色盘、JASC 和 RIFF 格式。选择 VXL 可预览静态几何；选择 HVA 时，程序会查找同一 MIX 或文件夹中的同名 VXL，并应用 HVA 姿态，也可手动选择 HVA 帧。没有有效配对文件的 HVA 无法预览。目录和 MIX 容器用于浏览，不作为文档预览。

预览限制：文本条目最多显示 2 MiB，超出部分会截断；大于 64 MiB 的 DAT 条目不预览；SHP 和 PCX 图像最多解码 33,554,432 个像素；大于 64 MiB 的 SHP、PCX 和 VXL 条目不预览；大于 16 MiB 或超过 1,024 帧的 HVA 不会应用；大于 128 MiB 的 WAV 和 Bink 条目不预览。

### Windows 下的 VLC 播放启动延迟

音视频预览使用 VLC。首次播放时，VLC 初始化媒体播放流程可能需要一些时间。Windows Defender 实时保护可能在首次访问 VLC 运行文件时扫描它们；扫描期间，程序界面可能短暂看起来像无响应。NVIDIA Instant Replay 也可能监测 VLC 播放并造成类似延迟，通常影响较轻。不同系统的情况会有差异；这些是可能的系统侧因素，并非每次延迟都能确定由它们造成，通常首次使用时最明显。

程序不会附带游戏文件。在 **编辑 > 首选项 > 色盘来源** 中选择现有 RA2/YR 游戏目录，可在预览时使用其中的色盘和 Art 规则。游戏目录作为设置保存，游戏文件会在原位置读取。

## 用户资料

可执行文件旁的便携式 `user-data` 文件夹用于存放用户专属数据：

- `RA2AYRMB.ini`：首选项和启动选项。
- `user-palettes/`：导入的 PAL 文件和自定义色盘规则。
- `name-sources/community/`：按需下载的社区数据库。
- `system-integration/default-app-samples/`：Windows 默认应用选择流程使用的常驻样例。
- `cache/palette-catalog/`：为已配置的游戏目录生成的色盘和 Art 规则缓存，可删除并重新生成。

程序只从 `user-data/` 读取用户资料，不会自动从可执行文件目录导入旧文件。若要从 1.0.0 beta 1 或更早版本迁移，请在首次启动前，将旧可执行文件目录中的项目复制到新可执行文件目录：

- `RA2AYRMB.ini` 复制到 `user-data/RA2AYRMB.ini`。
- `user-palettes/` 复制到 `user-data/user-palettes/`。
- `name-sources/` 复制到 `user-data/name-sources/`。
- `system-integration/` 复制到 `user-data/system-integration/`。

以后更新时，把整个 `user-data/` 文件夹复制到新可执行文件旁即可。Windows 资源管理器注册信息单独保存在当前用户的注册表中；如果可执行文件位置改变，请到 **首选项 > 系统集成** 重新注册。

如果程序内下载社区数据库失败，点击下载按钮旁的超链接获取 `global_mix_database.dat.zip`。将文件复制到可执行文件旁的 `user-data/name-sources/community/global_mix_database.dat.zip`；如有需要请创建目录，然后重启 RA2AYRMB。

## 从源码运行

要求：Python 3.10 或更高版本。受支持的 Windows 桌面版本需要 Windows 10 或更高版本。在 Windows 上创建虚拟环境并安装项目：

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .
```

使用以下命令启动桌面程序：

```powershell
run.bat
```

## Windows 打包

如果 `.runtime\vlc` 中仍没有 VLC runtime，请先准备一次：

```powershell
tools\prepare_vlc_runtime.bat
```

已有运行时可跳过此步。然后在项目虚拟环境中安装 PyInstaller，再运行打包脚本：

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
package.bat
```

打包结果位于 `dist/RA2AYRMB/RA2AYRMB.exe`。设置、导入的色盘，以及用户选择下载的社区数据库保存在 `dist/RA2AYRMB/user-data/` 中。

## CLI

CLI 成功时输出结构化 JSON，失败时向 stderr 输出稳定格式的错误对象。完整命令说明见 [CLI 和 MCP 文档](docs/cli_mcp.md)。

```powershell
.venv\Scripts\python.exe -m mix_browser.cli --help
.venv\Scripts\python.exe -m mix_browser.cli archive inspect "C:\Games\RA2\ra2.mix"
.venv\Scripts\python.exe -m mix_browser.cli search "C:\Games\RA2" "^unit.*\.shp$" --regex
.venv\Scripts\python.exe -m mix_browser.cli preview .\asset.shp --game-directory "C:\Games\RA2" --output .\asset.png
.venv\Scripts\python.exe -m mix_browser.cli name-source download-community
```

## MCP

RA2AYRMB 提供基于本地 stdio 的 MCP（Model Context Protocol）服务器，不会开启网络监听。将 MCP 客户端配置为启动以下命令：

```text
命令：C:\path\to\RA2AYRMB\.venv\Scripts\python.exe
参数：-m mix_browser.mcp_server
工作目录：C:\path\to\RA2AYRMB
```

可用工具和客户端配置详情见 [CLI 和 MCP 文档](docs/cli_mcp.md)。

## 文档

- [CLI 和 MCP 参考](docs/cli_mcp.md)
- [预览和色盘选择规则](docs/mix_browser_previews.md)
- [MIX 名称数据来源](docs/mix_name_data_sources.md)
- [许可说明](docs/licensing.md)

## 许可

随附的 Windows 可执行版组合程序选择 GPL-3.0，这是项目 GPL-2.0-or-later 授权允许的版本；该可执行版不采用项目代码的 MIT 选项。由于其中包含 GPL-3.0 的 XCC 数据，组合发行不声明可升级到后续 GPL 版本。其他第三方组件仍按各自许可发布，详见可执行版发行声明和第三方声明。

项目原创应用源代码采用 [MIT 许可证](LICENSE)或 [GPL-2.0-or-later](LICENSE-GPL-2.0-or-later.txt)。额外的 GPL 授权用于随附并集成 GPL 许可 VLC runtime 的 Windows 应用分发。项目原创文档和素材（包括手绘的 `MIX-EXE.ico`、`MIX-FILE.ico`、`MMX-FILE.ico` 和 `YRO-FILE.ico` 图标）采用 MIT 许可。仓库和发布包还包含其他单独许可的材料；GitHub 上的 MIT 标记不代表所有文件均采用 MIT。详见[第三方声明](THIRD_PARTY_NOTICES.md)。

随包附带的 XCC 名称表涵盖泰伯利亚黎明、泰伯利亚之日和红色警戒 2/尤里的复仇，单独采用 GPL-3.0 并附有相应许可文本。可选的 CnCNet 社区 Global MIX Database 由用户按需从原论坛附件下载，不随源码仓库或应用程序版本发布；其中还包含红色警戒名称表。各组件的许可范围和源码要约见[许可说明](docs/licensing.md)。
