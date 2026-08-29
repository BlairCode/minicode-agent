# MiniCode Agent

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Qwen](https://img.shields.io/badge/Model-Qwen-6C5CE7)](https://www.alibabacloud.com/help/en/model-studio/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

MiniCode Agent 是一个轻量、本地运行的编程智能体。模型负责选择下一步动作，本地 Runtime 负责读取和修改文件、执行命令、回填真实结果，并在安全策略允许的范围内继续处理任务。

项目默认通过 DashScope 的 OpenAI-compatible 接口调用 Qwen。Agent Loop、上下文管理、工具注册、停止条件、命令审批和工作区隔离均由项目自身实现，不依赖 Agent 框架。

## 功能

- Coding 与 LeetCode 两类 Agent，共用同一套 Runtime。
- 读取、写入、精确补丁、目录查看、文本搜索、命令执行六个本地工具。
- 模型原生 Tool Calling，工具结果以 `tool` 消息回填下一轮上下文。
- 同一对话支持连续追问，并复用原上下文和独立工作区。
- 本地网页界面显示步骤、工具调用、命令输出、Markdown 回答和生成文件。
- 历史对话恢复、运行中取消、模型重试和危险操作确认。
- 路径越界防护、命令风险分级、无 Shell 执行、超时和输出限长。
- API Key 使用操作系统凭据库保存，不写入项目配置或会话文件。
- 无图形环境可使用终端界面。

## 环境要求

- Python 3.11 或更高版本
- 可用的 Qwen / DashScope API Key
- Windows、macOS 或 Linux

## 安装

克隆项目并进入目录：

```bash
git clone https://github.com/<YOUR_ACCOUNT>/minicode-agent.git
cd minicode-agent
```

创建虚拟环境：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 配置 Qwen

推荐启动应用后在左下角“设置”中保存 API Key。凭据会进入操作系统的安全存储，不会写入仓库。

也可以只为当前终端设置环境变量。

Windows PowerShell：

```powershell
$env:DASHSCOPE_API_KEY = "your-api-key"
```

macOS / Linux：

```bash
export DASHSCOPE_API_KEY="your-api-key"
```

默认模型配置位于 `config/default.yaml`：

```yaml
model:
  provider: qwen
  model: qwen-plus
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  api_key_env: DASHSCOPE_API_KEY
```

需要更换模型或工作区时，复制公开模板后修改：

```bash
cp config/user.example.yaml config/user.yaml
python main.py --config config/user.yaml
```

Windows PowerShell 可使用：

```powershell
Copy-Item config\user.example.yaml config\user.yaml
python main.py --config config\user.yaml
```

`config/user.yaml` 已被 `.gitignore` 排除。不要在任何 YAML、`.env.example` 或提交记录中填写真实 API Key。

## 运行

启动本地网页：

```bash
python main.py
```

服务只监听 `127.0.0.1`，默认自动打开浏览器。只启动服务、不自动打开浏览器：

```bash
python main.py --no-browser
```

使用终端界面：

```bash
python main.py --cli
```

指定工作区或初始 Agent：

```bash
python main.py --workspace ./workspace --agent coding
python main.py --workspace ./workspace --agent leetcode
```

## 使用示例

在网页输入框中描述任务即可：

```text
检查当前项目的文件结构，为缺失的功能补充实现和测试，并运行相关测试直到通过。
```

任务完成后可以继续追问：

```text
继续沿用当前实现，补充错误输入的边界测试，并整理最终说明。
```

终端界面支持以下命令：

```text
/help
/agent coding
/agent leetcode
/mode solve
/mode hint
/mode interview
/mode review
/workspace ./workspace
/settings
/skills
/clear
/history
/exit
```

## 工作方式

一次完整循环如下：

1. Runtime 把上下文和当前 Agent 可用的工具 Schema 发送给模型。
2. 模型返回文本或 Tool Call。
3. Dispatcher 校验工具名、参数和 Agent 权限。
4. Safety Layer 检查路径与命令风险，必要时等待用户确认。
5. 工具在本地执行，并返回退出码、stdout、stderr 或文件结果。
6. Runtime 将结果作为 `tool` 消息加入上下文，再决定是否进入下一步。
7. 模型给出最终回答，或 Runtime 因取消、步数上限、错误上限而停止。

网页中的步骤只展示可审计的动作、工具和结果，不展示模型隐藏思维链。

## 项目结构

```text
minicode-agent/
├── config/                 # 默认配置与公开用户模板
├── minicode_agent/
│   ├── agent/              # Runtime、上下文、状态与角色规格
│   ├── cli/                # 终端交互
│   ├── llm/                # Qwen 与兼容模型客户端
│   ├── safety/             # 路径、命令和审批策略
│   ├── skills/             # Skill 加载器
│   ├── tools/              # 文件与命令工具
│   └── web/                # 本地 HTTP 服务与网页资源
├── prompts/                # 基础、Coding、LeetCode 提示词
├── skills/                 # Python、C++、测试、调试和算法规则
├── tests/                  # 离线测试
├── workspace/              # 本地任务目录，内容默认不入库
├── main.py                 # 程序入口
├── pyproject.toml
└── requirements.txt
```

## 安全边界

文件工具默认只能访问当前对话的工作区。路径会解析为真实绝对路径，`../`、绝对路径越界和指向外部的符号链接默认被拒绝。写文件使用同目录临时文件和原子替换。

命令以 `shell=False` 执行，管道、重定向、命令拼接和命令替换会被拒绝。命令按以下等级处理：

- `SAFE`：测试、编译、只读 Git 等常规开发命令。
- `MEDIUM`：安装依赖、网络访问、切换分支等操作。
- `HIGH`：递归删除、强制 Git 操作等，需要确认。
- `BLOCKED`：系统级破坏命令，始终拒绝。

运行项目测试仍意味着执行本地代码。本项目能降低误操作风险，但不提供操作系统级沙箱。处理不可信代码时，请在容器或虚拟机内运行。

## 本地数据

API Key 由系统凭据库管理。个人设置和历史会话默认写入仓库外的用户数据目录：

- Windows：`%LOCALAPPDATA%\MiniCodeAgent`
- macOS：`~/Library/Application Support/MiniCodeAgent`
- Linux：`$XDG_DATA_HOME/minicode-agent`，未设置时使用 `~/.local/share/minicode-agent`

仓库中的 `workspace/` 只作为任务目录父级。每个网页对话会创建独立子目录，这些运行产物不会提交 Git。

## 测试

安装开发依赖并运行测试：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

测试不需要真实 API，覆盖 Agent Loop、上下文裁剪、Qwen Tool Calling、文件边界、命令风险、审批、超时、会话脱敏、多轮对话和本地 HTTP 安全头。

## License

[MIT](LICENSE)
