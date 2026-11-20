# LangGraph SWE Agent

这个 Agent 用于修复可信的本地 Python 小仓库中的普通逻辑错误。模型通过 ACI 查看失败测试、搜索和阅读代码、提交修改请求，以及重跑测试。启动时选择在副本上做实验或直接修复原仓库。每次写入源码前，命令行会展示 diff 并等待人工决定。每次运行都有独立的 SQLite checkpoint。

## 在 PowerShell 运行

使用项目的 Python 3.12 虚拟环境。新环境可以用 `python -m venv .venv` 创建，再用 `uv pip install -r requirements.txt` 安装依赖。

模型配置沿用根目录 `.env` 中的三个变量。`LLM_MODEL` 指定支持工具调用的模型，`LLM_API_KEY` 是服务密钥，`LLM_BASE_URL` 是 OpenAI 兼容的 Chat Completions 服务地址。也可以在进程环境中提供这些变量。[DeepSeek 工具调用文档](https://api-docs.deepseek.com/guides/tool_calls/)

分页示例的三个文件在同一目录。`issue.md` 是题目，`pagination.py` 是带错误的代码，`test_pagination.py` 是验收测试。进入示例目录就可以直接跑分页测试，错误还没修复时应得到 `2 failed, 1 passed`。

```powershell
Push-Location .\examples\pagination
..\..\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
Pop-Location
```

回到项目根目录，用同一个示例启动 Agent。

```powershell
.\.venv\Scripts\python.exe .\run_agent.py start --repo .\examples\pagination --issue-file .\examples\pagination\issue.md
```

程序创建任务时会用仓库名和 UUID 生成编号，例如 `pagination-<UUID>`，并在调用模型前打印 `Run ID: ...`。模型提出写入后，命令会输出待审批的 diff 并退出。可在新的 PowerShell 窗口用打印出的完整 ID 查看题目和待审批修改，再决定是否批准。

在终端启动时，输入 `1` 或直接回车会使用副本，输入 `2` 会直接在原仓库修复。也可以在 `start` 命令上加 `--copy` 或 `--in-place` 跳过询问。脚本等非交互环境默认使用副本。`status` 显示实际的文件路径和模式，`resume` 按这次任务原先选择的位置继续。

```powershell
$runId = '粘贴程序打印的 Run ID'
.\.venv\Scripts\python.exe .\run_agent.py status $runId
.\.venv\Scripts\python.exe .\run_agent.py resume $runId --approve
```

需要退回时，改用 `resume $runId --reject --comment '请先核对页码的起始值'`，模型会收到拒绝和理由。如果是模型请求失败或进程退出，且状态中没有等待审批的操作，用 `resume $runId` 从最近的 checkpoint 继续。如果模型接着提出第二次修改，命令会再次暂停。再次执行 `start` 会生成新的 ID。也可以使用 `start pagination-01 ...` 手动指定编号，已使用的编号会被拒绝。

默认上限是 12 次工具调用，可用 `start ... --max-steps 12` 设置。失败或被拒绝的调用也占一步。`model_finished` 表示模型结束，`step_limit` 表示达到上限。核对是否修复时看 **最后一次源码修改后的 pytest 退出码**，`0` 表示测试通过。如果修改后还未跑测试，状态会显示结果未确认。

打开 [任务索引](runs/INDEX.md) 可以按题目找到原仓库、实际工作目录、运行模式和状态。每行最右侧链接会打开该任务的 Markdown 对话记录。日志导出时会更新索引。也可以运行 `run_agent.py history` 为已有任务重新生成索引和记录。

| 文件或目录 | 用途 |
|---|---|
| `run_agent.py` | 命令行入口，处理 `start`、`status`、`resume` 和 `history`。 |
| `experiment/__init__.py` | 声明 Python 包。 |
| `experiment/agent.py` | 定义 LangGraph 状态、工具循环和审批节点。 |
| `experiment/aci.py` | 定义模型可调用的本地仓库工具和执行逻辑。 |
| `experiment/model.py` | 将项目模型配置接到 LangGraph，向模型声明工具。 |
| `experiment/history.py` | 将本地运行记录整理成索引和可读的 Markdown。 |
| `examples/pagination/issue.md` | 分页用例的任务描述和验收期望。 |
| `examples/pagination/pagination.py` | 含分页错误的示例业务代码。 |
| `examples/pagination/test_pagination.py` | 验收第一页、第二页和无效输入。 |
| `tests/test_agent.py` | 用脚本模型验证审批、恢复、步数上限和 ACI 行为。 |
| `pytest.ini` | 项目根目录执行 pytest 时收集 Agent 自身的测试。 |
| `requirements.in`、`requirements.txt` | 分别保存直接依赖和固定版本，含 SQLite checkpoint 组件。 |
| `.gitignore`、`.env` | 忽略本地运行副本和密钥文件，模型配置保存在已有的 `.env`。 |
| `runs/<ID>/repo/` | 副本模式下可修改和测试的仓库副本。 |
| `runs/<ID>/target.json` | 保存所选模式和原仓库的路径，供恢复时使用。 |
| `runs/INDEX.md`、`runs/<ID>/conversation.md` | 任务总览和单次任务的对话记录。 |
| `runs/<ID>/checkpoint.sqlite3`、`invocation.lock` | 保存图状态，确保同一个运行 ID 的执行串行。 |
| `runs/.repository-locks/` | 协调同一个原仓库上的直接修复和复制操作。 |
| `results/logs/<ID>.jsonl` | 从 checkpoint 生成的任务描述、模型动作、工具结果和最终状态。 |
| `SWE_AGENT.md` | 本文。 |

## 每个函数的作用

### `run_agent.py`

| 函数 | 作用 |
|---|---|
| `parse_args` | 解析子命令、任务输入、步数上限和审批决定。 |
| `ignore_copy` | 从仓库副本中排除隐藏文件、本地缓存和符号链接。 |
| `choose_mode` | 读取启动参数，或在交互终端询问写入副本还是原仓库。 |
| `generate_run_id` | 用仓库目录名和 UUID 生成可辨识的编号。 |
| `exclusive_lock` | 在命令执行期间持有 SQLite 独占锁。 |
| `repository_lock` | 按原仓库路径选择共享锁，避免两个任务交错写入。 |
| `start_run` | 验证输入、建立运行目录，按所选模式复制仓库或登记原路径。 |
| `run_repository` | 读取运行的目标位置和模式，支持早期的副本存档。 |
| `resume_input` | 检查是否有待执行节点，按需把人工决定放入 `Command(resume=...)`。 |
| `write_trace` | 从当前 checkpoint 重建 JSONL 日志，再更新任务索引和对话记录。 |
| `show_status` | 显示题目首行、写入目标、待审批 diff、调用次数和测试退出码。 |
| `run_command` | 分配或读取运行 ID，获取互斥锁，打开 SQLite 并读取或执行 LangGraph。 |
| `main` | 调用 CLI，处理模型请求和本地运行错误，返回进程退出码。 |

### `experiment/agent.py`

`AgentState` 保存对话、工具计数、待修改内容、审批决定和测试结果。`build_agent` 把四个内部节点和路由编译成同一张图。

| 函数 | 作用 |
|---|---|
| `last_model_message`、`active_call` | 找到最近的模型消息及这条消息中当前要处理的工具调用。 |
| `after_model` | 根据模型是否结束，进入工具阶段或退出。 |
| `after_prepare` | 有有效的待写入 diff 就进入审批，其余动作直接交给执行节点。 |
| `after_action` | 处理同一批剩余的工具调用，或者把结果交回模型。 |
| `build_agent` | 接收 ACI、模型和 checkpointer，创建并编译 LangGraph。 |
| `call_model` | 检查工具预算，传入对话和反馈，接收下一批工具请求或最终答复。 |
| `prepare_action` | 校验写入请求，准备 diff 和文件校验值。 |
| `approve_edit` | 用 `interrupt()` 提交待审 diff，并把审批结果保存到图状态。 |
| `execute_action` | 调用 ACI，把结果作为 `ToolMessage` 交回图，并更新调用计数和测试状态。 |

审批和写入是独立节点。SQLite 保存了写入前的审批决定，恢复时仍使用该决定。若进程在写入完成后、结果保存前退出，下一次执行会检查文件内容是否已是批准后的版本。[LangGraph 检查点文档](https://docs.langchain.com/oss/python/langgraph/persistence) · [LangGraph 审批文档](https://docs.langchain.com/oss/python/langgraph/interrupts)

### `experiment/aci.py`

`RepositoryACI` 将工具限制在本次选定的仓库目录。四个模型工具名是 `search_repo`、`read_file`、`replace_text` 和 `run_tests`。编辑采用精确文本替换，现有测试文件可供读取和搜索。

| 函数或方法 | 作用 |
|---|---|
| `atomic_write` | 用同目录的临时文件完成整文件替换，用于写源码和 JSONL 日志。 |
| `RepositoryACI.__init__` | 解析仓库根目录并设置测试超时。 |
| `source_path` | 解析现有 Python 文件的相对路径，检查范围和大小。 |
| `search_repo` | 按关键词搜索 Python 文件路径或代码行，返回带位置的匹配。 |
| `read_file` | 读取指定行范围，返回带行号的内容。 |
| `prepare_edit` | 验证唯一匹配的旧文本，生成 `PreparedEdit`，包含 diff、更新内容和前后文件校验值。模型看到的工具名是 `replace_text`。 |
| `apply_edit` | 核对文件与审批时的版本一致后写入。已经写入同一份内容时，返回已应用。 |
| `run_tests` | 在所选仓库目录执行 `python -m pytest`，返回退出码、输出或超时结果。测试在本机执行，示例或目标仓库应来自可信来源。 |
| `model_tools` | 向模型提供四个工具的名称、说明和参数结构。 |

### 其他 Python 文件

| 文件 | 函数及作用 |
|---|---|
| `experiment/model.py` | `create_model` 创建模型适配器。内部 `invoke` 首次调用时读取模型配置、绑定工具，后续调用复用模型客户端。连接 DeepSeek 官方地址时使用非思考模式，以兼容 Chat Completions 工具循环。[DeepSeek 模式说明](https://api-docs.deepseek.com/guides/thinking_mode/) |
| `experiment/history.py` | `read_history` 读取单次运行的目录和日志，`RunHistory.title` 与 `RunHistory.status` 提取摘要。`table_text` 转义表格文字，`directory_link` 生成目录链接。`transcript` 渲染对话，`refresh_history` 更新各次记录和索引。 |
| `examples/pagination/pagination.py` | `paginate` 校验页码和每页数量后返回切片。示例原件将 1 起始的页码直接用于偏移量计算。 |
| `examples/pagination/test_pagination.py` | `test_first_page`、`test_second_page` 核对切片，`test_invalid_page` 核对无效页码仍抛出异常。 |
| `tests/test_agent.py` | `request_tool` 构造工具请求，`scripted_model` 根据工具反馈继续修复，`failing_model` 模拟模型中断。`cli` 启动独立进程，`trace` 读取持久化日志。 |
| `tests/test_agent.py` | `test_choose_mode_prompts_in_terminal` 验证启动询问。`test_approval_survives_process_exit` 验证两种模式下的批准、拒绝和恢复。`test_resume_after_provider_failure_preserves_completed_steps` 验证中断后续跑。`test_step_limit_ends_before_another_model_call` 核对工具预算。`test_aci_checks_edit_scope_and_replays_approved_write_safely` 检查编辑范围、过期 diff 和重复执行。 |
| `tests/test_agent.py` | `test_generated_ids_keep_tasks_separate_and_allow_resume` 验证自动编号、拒绝重复编号，以及按原编号恢复各自的任务。 |
| `tests/test_agent.py` | `test_history_backfills_existing_run_without_inventing_original_repository` 验证旧任务的索引与对话导出。 |
| `tests/test_agent.py` | `test_model_adapter_sends_tool_schemas_and_decodes_tool_calls` 使用模拟 HTTP 响应验证模型适配器。内部 `fake_provider` 检查请求并返回工具调用，`create_local_model` 建立使用该模拟服务的客户端。 |

## 本地验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

测试用脚本模型模拟工具请求，在独立进程之间验证 SQLite 恢复。实际模型运行使用前面的 `start` 命令，日志会出现在 `results/logs/`。
