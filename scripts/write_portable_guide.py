"""Write the portable handoff guide with Python's standard library only."""
from __future__ import annotations

import argparse
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re


PACKAGE_NAME = 'Ultra007_可迁移运行包_2026-10-28.zip'

GUIDE = r'''# Ultra 007：另一台电脑运行与使用指南

代码版本：2026-10-28。适用对象：接收压缩包后，第一次在自己电脑安装和使用的人。

> 这是一份带源码和本地模型的运行包，不是免安装 EXE。对方需要安装兼容的 Python，并首次联网安装依赖。包内保留了 `.env`，其中可能含有效 API 密钥，请仅在授权人员之间交接；接收方可以换成自己的密钥。

## 1. 先了解交接内容

Ultra 007 从公司年报出发，提取完整合并三表，计算历史指标与趋势，导出 Excel；也支持同项目内多公司比较，以及由使用者填写、确认参数后的 FCFF DCF 估值。

| 包内内容 | 作用 |
| --- | --- |
| `streamlit_app.py`、`financial_workbook/`、`rag_step1/` | 应用入口、财务计算、Agent 与 RAG 完整代码 |
| `assets/`、`.streamlit/` | 页面素材及明暗主题配置 |
| `requirements.txt`、`requirements-ui.txt`、安装辅助脚本 | 在接收方电脑建立独立运行环境 |
| `data/models/paraphrase-multilingual-MiniLM-L12-v2/` | 约 500 MB 的本地多语嵌入模型，不必再次从 Hugging Face 下载 |
| 立讯精密已完成研究 | 2021—2023 年，9 张主表、675 行、60 项年度指标、5 张图表 |
| 合成 A/B 多公司示例 | 用于练习公司比较、估值操作；不是真实公司投资结论 |
| 格力旧版正式结果及原年报 | 四年 12 张主表，保留原有历史记录 |
| `.env`、`.env.example` | 实际配置及空白配置参考；不要把真实密钥粘贴到群聊或截图中 |

包内不带 Python 解释器、`.venv` 虚拟环境、pip 离线安装包、RAG 索引缓存、个人估值草稿或旧后台任务。因此，第一次需要联网安装 Python 依赖；首次分析新报告时需要建立本机索引。

日常运行不需要 Codex、Node.js 或独立显卡。计算与导出使用普通 Python 程序；已有结果浏览和参数估值不需要调用大模型，新年报分析会调用配置的模型服务。

## 2. 先完整解压，再安装 Python

1. 收到 `Ultra007_可迁移运行包_2026-10-28.zip` 后，先完整解压。不要在 ZIP 浏览窗口里直接双击脚本。
2. 建议解压到较短的目录，例如 `D:\FinanceDemo`，然后进入里面的 `Ultra007` 文件夹。中文、空格和 `&` 路径经过辅助脚本检查，但短目录更有利于减少 Windows 长路径问题。
3. 以实际能看到 `streamlit_app.py` 和三个编号 `.bat` 的文件夹为“项目根目录”。不需要使用原电脑的用户名或桌面路径。
4. 如果电脑尚无 Python，打开 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/)，安装 **64 位 Python 3.14.x**。安装时启用 Python Launcher，或勾选 Add Python to PATH。
5. 辅助脚本支持 64 位 Python **3.11—3.14**；原电脑实际运行版本为 3.14.4。不要因为下载页显示更新的版本，就选择尚未在本项目验证的 3.15。

安装 Python 后，关闭并重新打开终端或脚本窗口，让系统识别新安装的程序。

## 3. 第一次启动：按三个文件的顺序操作

### 第一步：双击 `01_安装依赖.bat`

脚本会在当前项目里创建 `.venv`，安装应用和后端依赖，并使用包内的版本约束。它不会要求你先安装 Codex 或 Node。

第一次安装会下载 PyTorch 等较大的运行依赖，耗时和下载量明显大于普通小程序。请保持网络畅通，等待窗口显示结束，不要因为一段时间没有新文字就重复启动。包内约 500 MB 的模型不需要重新下载，但 pip 安装仍需联网。

如果出现安装错误，先保留最后几行错误信息，按下文故障表处理。不要把含密钥的 `.env` 内容一起截图。

### 第二步：双击 `02_检查环境.bat`

检查会关注 Python 版本与位数、依赖导入、本地模型文件、API 密钥是否存在、目录是否可写，以及默认端口是否可用。密钥检查只报告是否配置，不打印真实值，也不代表已在线验证密钥余额和服务权限。

根据检查结果补齐缺失项后，再进行下一步。只浏览随包的已完成结果不需要有效 API 密钥；新年报分析需要密钥和网络连接。

### 第三步：双击 `03_启动程序.bat`

看到服务已经运行后，在这台电脑的浏览器打开：

```text
http://127.0.0.1:8501
```

如果浏览器没有自动弹出，请手动输入这个地址。该地址指向“当前这台电脑”，只有对方先在自己的电脑启动程序后才能打开；直接转发原电脑上的地址不能代替安装和启动。

运行期间保持启动窗口开启。要停止服务，在窗口按 `Ctrl+C`。下次使用通常只需再次双击 `03_启动程序.bat`，不必每天重装依赖。

## 4. API 密钥与配置怎么处理

本包按交接要求保留了 `.env`，只应向获得授权的接收方提供。不要把整个运行包当作公开下载材料发布。接收方可以用记事本打开 `.env`，将 `DEEPSEEK_API_KEY` 改成自己的有效密钥。

下面只是字段示意，不能把中文占位文字当成真实密钥使用：

```text
DEEPSEEK_API_KEY=这里填写接收方自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
AIF_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

保存时保持文件名为 `.env`，不要变成 `.env.txt`。修改后停止并重新启动程序。如果资源管理器不显示扩展名，可开启“显示文件扩展名”；不要凭看起来相似的文件名反复创建配置文件。

本地模型已在 `data/models/` 中。不要把嵌入模型配置改成原电脑上的 `C:\Users\...` 绝对路径，也不要随意删除模型目录里的 tokenizer、权重或 `1_Pooling` 文件。

## 5. 先打开已有结果，确认交接正常

建议第一次先浏览随包结果，再尝试新上传，这样能把“环境或页面问题”与“新年报解析问题”区分开。

1. 默认中文界面下，在侧栏“研究项目”选择立讯精密研究。
2. 进入“财务概览”，查看 2021—2023 年的指标卡、收入利润、增长、盈利、负债和现金流图表。
3. 切换年份，打开“财务指标”“公式与来源”，可查看计算口径和原 PDF 页预览。
4. 点击“下载分析 Excel”，确认本机能下载并打开工作簿。
5. 在研究项目下拉框中选择合成 A/B 示例。A 含多个年度，B 为单年度，适合练习纵向分析和同项目公司比较。

查看旧格力成果时，回到“上传年报”首页，点击“打开已有年报分析”，再从“分析记录”选择格力旧记录。它保留原来的历史处理方式；少数不可计算指标按原说明展示，不会用零或猜测值补齐。

如果接收方只想看成果或练习估值，可以一直使用已保存结果。这些浏览、筛选和下载操作不会重新启动年报分析任务。

## 6. 上传自己的年报并分析

1. 进入“上传年报”，拖入或选择文本型 PDF 年报。单份最多 100 MB，合计最多 500 MB。
2. 每份报告都要分配公司与报告年度；填写行业、会计准则、财年末和金融／非金融企业类型。文件名推测的公司与年份只是提示，应由使用者确认归属。
3. 同公司多份报告可以先填写通用信息，再点击应用到清单；也可以逐行修改。每家公司同一年只选一份主报告版本。
4. “列报币种”可选填。原报已经明确币种时，系统从原文取证；如果报告只写“元”而无法确认列报币种，应明确填写 CNY、USD 等实际币种，系统不会把所有“元”都猜成人民币。
5. “公司英文名”“公司俄文名”为可选显示信息。原公司名仍保留，外文名称作为旁注；不要用译名建立第二个不同的公司身份。
6. 点击“按以上公司与年度开始分析”。选择文件或修改筛选本身不会调用模型；明确点击开始才提交后台任务。
7. 系统先检查主表范围、年度列、跨页版式、来源和单位，通过后才建立或复用 RAG 索引，再运行 Agent、固定公式与 Excel 导出。
8. 等待后台进度。大批量长年报首次索引可能较慢；刷新页面可以继续看同一任务，不要为了催进度重复上传或重复点开始。

本版取消逐表人工数据审核，不需要先填写审核栏。系统仍会检查可执行的来源与勾稽规则；无法可靠识别时停止并说明文件和物理页，不会让 AI 编造数值。

单份年报可得到单年三表、可计算指标和对应图表。同公司多年度报告可以展示跨年趋势；没有足够数据的指标按原因保留为空。扫描图片型 PDF、加密文件和未支持的复杂版式仍可能无法处理，本包不包含 OCR。

## 7. 单公司纵向与多公司横向比较

同一家公司的不同年份：上传时将多份报告归到同一公司，完成后在“财务概览”选择多个年份，即可看收入、利润、增长、盈利能力及现金流趋势。

多家公司：需要把各公司的报告放入**同一个研究项目**。新建时一次选入这些 PDF，分别填写公司归属；分析完成后进入“公司对比”，勾选需要比较的公司和共同年度，再点击生成比较。

程序只比较兼容的币种、会计准则与完整财年口径，不自动换汇或对齐不同财年。样本统计只代表所选公司，不能当作全行业均值。当前界面不是从不同研究项目任意合并公司；如果要比较分散在不同项目里的报告，请新建一个包含所需公司的研究。

## 8. 如何尝试估值

历史分析完成后，可以选择“填写参数，计算 DCF”，也可以“本次只看分析”。选择结束后仍能查看和下载历史结果；若以后需要重新开启估值研究，可从新建研究开始。

进入估值后填写判断与参数确认人，明确选择继续，再选择模型。当前 FCFF 适用于非金融企业；银行、保险等不适用该模型，但仍可使用已有的历史分析功能。

### 简易 FCFF 增长试算

简易模型由你提供基期 FCFF，假设按固定增长率推演。全部参数、确认人、预测年数和整体假设说明均为必填，空白不等于零。

金额使用原币**基本单位**，股数使用**股**。例如 CNY 金额 100 表示 100 元，不是 100 万元；百分比输入 5 表示 5%，不应填写 0.05 或带百分号的字符串。

建议先在合成 A/B 项目的**合成 B**上做一次功能测试。以下只用于测试程序，不是真实公司估值建议：

| 输入框 | 合成示例填写值 |
| --- | --- |
| 判断与参数确认人 | 填写你自己的姓名或团队名称 |
| 基准年度 | 选择合成 B 已有的 2020 年 |
| 已核实的基期 FCFF | 100 |
| 预测期 FCFF 增长率（%） | 5 |
| WACC（%） | 10 |
| 永续增长率（%） | 2 |
| 净债务 | 200 |
| 稀释股数（股） | 100 |
| 预测年数 | 5 |
| 整体假设与适用边界 | 由你填写“合成数据功能测试”，并说明这些数值仅用于试用 |

填写后勾选“我已核对当前全部估值参数”，点击计算。应看到经营资产价值、权益价值、每股价值、敏感性分析和 DCF Excel 下载入口。

### 完整经营预测模型

完整模型还需要基期经营性营运资本、逐年收入增长、EBIT 利润率、现金税、折旧摊销、资本支出与营运资本假设，以及终值、权益桥接和判断依据。

- 至少选择一个 Base／Bear／Bull 情景，不必把三个都选上。
- WACC 可以直接填写，也可以按组成项计算；只需填写当前选择方式所显示的必填字段。
- 参考股价为选填；其他当前适用字段按“必填”标示输入。不存在的桥接金额请明确填 0。
- 预测表中每个年度的参数和判断依据都要填写。整体依据、折现依据、终值依据和营运资本依据也不能留空。
- WACC 要大于长期增长率，长期 ROIC 要高于长期增长率；不满足时会显示对应红字。

缺项或数值不合法时，字段旁会显示红字，完整模型会展开相关板块并列出待修正位置。修正后请重新勾选确认。修改参数会使原来的确认失效；这是防止旧确认被用于新参数的正常行为。

任意试填的数值可能得到非正权益残值。此时计算仍可完成，但每股价值可能显示“—”，并解释原因；这不等于程序崩溃。真实公司估值的经验判断应由有相应专业能力的使用者提供，不能把合成测试值直接套到真实公司。

## 9. 语言、主题与来源原文

侧栏 `Language / 语言 / Язык` 可以切换中文、英文和俄语。页面标签、系统提示、图表、指标名称与金额单位随语言变化，财务数值、币种和公司身份不变。

右上角三点菜单中的 `Light / Dark / System` 分别表示浅色、深色和跟随系统。浏览器会保留主题偏好。

公司原名保留，已有外文名称显示在旁边；原 PDF 项目、原列头、原披露单位、文件名及你输入的判断依据保留原文。Streamlit 原生菜单和上传控件内部的部分系统文字由框架提供。

## 10. 文件保存、下载与备份

历史分析可从财务概览下载；公司比较可从比较页下载；估值结果可从估值页或摘要页下载。摘要页还可导出带数据版本和参数的 JSON。

程序生成的数据在项目下的 `outputs/`：

```text
outputs/
  research_projects/
    research_.../
      sources/          上传的源报告和清单
      runs/             提取、系统校验、历史分析与 Excel
      comparisons/      公司对比结果
      investment/       估值选择、参数草稿和已保存的估值版本
  agent_runs/           留存的旧版分析成果
```

退出程序后可备份整个 `Ultra007` 文件夹，包括新生成的 `outputs/`。备份或交接 `.env` 时，只提供给获授权人员。不要把 `.venv` 当作可跨电脑复制的环境；换电脑后应在新位置重新安装依赖。

## 11. 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 提示找不到 Python、`py` 或 `python` | 安装 64 位 Python 3.11—3.14，推荐 3.14.x；启用 Launcher 或 PATH 后重新打开脚本 |
| 安装脚本提示 Python 版本不支持 | 不使用 3.15；安装兼容版本，必要时按下一节用 `py -3.14` 明确指定 |
| 复制来的虚拟环境不能用 | 不从其他电脑复制 `.venv`。退出程序后，可把当前项目里的旧 `.venv` 改名备份，再执行安装脚本 |
| `ModuleNotFoundError` 或依赖安装失败 | 重新执行 `01_安装依赖.bat`，确保网络能访问 PyPI；保留安装错误末尾信息，检查是否选错 Python 或使用了不可写目录 |
| 首次下载和安装很慢 | PyTorch 等依赖较大，等待安装完成；本地模型随包，不必反复从 Hugging Face 下载。不要重复开多个安装窗口 |
| 8501 端口被占用 | 先看是否已有本应用在运行，可直接使用现有页面。若不是，用下一节命令改为 8502，不要随意结束不认识的程序 |
| 浏览器打不开 `127.0.0.1:8501` | 确认这台电脑的启动窗口仍开启、无报错，并且端口与启动命令一致。关闭窗口后页面就无法继续服务 |
| 密钥缺失、401／403、模型服务错误 | 检查 `.env` 文件名、有效 Key、服务权限、余额和网络；修改配置后重启。环境检查只确认 Key 是否存在，不测试所有在线权限 |
| 提示本地嵌入模型不完整 | 确认完整解压了 `data/models/paraphrase-multilingual-MiniLM-L12-v2/`，不要只复制权重或只保留快捷方式；可重新从原 ZIP 解压 |
| 上传扫描 PDF 失败 | 本版需要带可提取文字的 PDF，不支持扫描件 OCR；改用官方文本版年报 |
| 提示币种缺失或不明确 | 回上传页重新选择该批文件，在清单填写已确认的列报币种后再分析，不把“元”自动等同人民币 |
| 提示主表、续页或年度列无法验证 | 查看具体文件及 PDF 物理页；可能需要新的通用版式适配。换一份官方文本版，或把错误原因反馈给维护者，不能靠反复重试或让 AI 补数字解决 |
| 估值提示缺少必填参数 | 看对应红字，尤其是整体假设说明、逐年判断依据、折现和终值依据。没有的金额明确填 0；修正后重新确认 |
| 估值结果为负或每股值显示“—” | 检查单位是否把“元”误当“万元”，以及假设是否仅为试填；同时阅读结果解释，负权益本身不是程序异常 |
| 改参数后确认框自动取消 | 正常设计。重新核对新的参数，再勾选确认并计算 |
| 换电脑后已有记录找不到原 PDF | 确认复制的是完整运行包，包含原报告与成果目录，而不是只复制 Excel 或部分输出；不要手工改原始候选 JSON |

## 12. 命令行备用方法

### Windows CMD

先进入你实际解压后的项目根目录。下面的目录只是示例，要替换成自己的位置：

```bat
cd /d "D:\FinanceDemo\Ultra007"
py -3.14 scripts\portable\portable_runtime.py install
.venv\Scripts\python.exe scripts\portable\portable_runtime.py check
.venv\Scripts\python.exe scripts\portable\portable_runtime.py start
```

辅助安装会同时读取两份 requirements 和包内适用的版本约束。若只想直接启动已安装环境：

```bat
.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

端口冲突时可改为：

```bat
.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8502
```

然后打开 `http://127.0.0.1:8502`。如果使用 PowerShell，先用 `Set-Location -LiteralPath "你的项目根目录"` 进入文件夹，再执行相同的 Python 命令；路径含空格时保持引号完整。

### macOS／Linux 的简单替代

编号 `.bat` 只适用于 Windows。以下是其他系统的命令参考，尚未在另一操作系统完成本交接包的实机验证；原项目验证环境是 Windows。请先安装兼容的 Python 3.11—3.14 并进入解压后的项目根目录：

```sh
python3.14 scripts/portable/portable_runtime.py install
.venv/bin/python scripts/portable/portable_runtime.py check
.venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

不同操作系统的 Python 安装方式和依赖 wheel 可能不同；不能把 Windows 的 `.venv` 或可执行文件直接复制过去使用。

## 13. 交接验收清单

本包已在原电脑的另一个迁移目录完成验证：4 个已完成分析运行、30 张报表、1520 行和 10 份原 PDF 的来源复核与数据指纹一致；合成公司比较与简易 DCF 导出通过；本地模型在断网下载模式下使用 CPU 完成两段文本的 384 维编码。迁移检查、启动助手检查和页面回归也已通过。这证明文件可以在新目录重新定位，不等于已经在另一台实体电脑安装过依赖。

- 能完成环境检查，并在接收方电脑打开本机页面。
- 能查看立讯精密的历史指标、图表与来源，下载历史 Excel。
- 能在合成 A/B 项目生成公司比较。
- 能在合成 B 填写测试参数、看到必填提示，确认后计算并下载 DCF Excel。
- 能切换中文／英文／俄文和明暗主题，刷新后仍能恢复草稿。
- 如需新分析，确认自己的 API 配置有效，并用一份支持的文本年报完成上传测试。

完成以上步骤，才算这台接收电脑的环境验收通过。本包已经在原环境验证功能，但不承诺不安装依赖即可运行、完全离线处理新报告，或任意 PDF 版式都自动兼容。
'''

QUICKSTART = r'''Ultra 007 可迁移运行包——开始前先读我
代码版本：2026-10-28
压缩包：Ultra007_可迁移运行包_2026-10-28.zip

一、先解压
完整解压到较短目录，例如 D:\FinanceDemo，然后进入里面的 Ultra007。
项目根目录应能看到 streamlit_app.py 和三个编号 .bat。
不要在 ZIP 浏览窗口里直接运行，也不需要复制原电脑的用户目录。

二、先准备 Python
需要 64 位 Python 3.11—3.14，推荐 3.14.x（原环境为 3.14.4）。
官方下载：https://www.python.org/downloads/windows/
安装时启用 Python Launcher 或 Add Python to PATH。
不要选择尚未在本项目验证的 Python 3.15。

三、按顺序双击
1. 01_安装依赖.bat —— 首次联网安装较大的 Python 依赖，请等待完成。
2. 02_检查环境.bat —— 看是否缺 Python、依赖、模型或配置。
3. 03_启动程序.bat —— 保持窗口开启，浏览器打开 http://127.0.0.1:8501。
下次一般只需第 3 步。停止服务时在启动窗口按 Ctrl+C。
127.0.0.1 指当前电脑；接收方必须先在自己的电脑启动程序。

四、已有成果与试用
研究项目下拉框可打开立讯精密，或合成 A/B 多公司示例。
旧格力成果从首页“打开已有年报分析”进入。
先看图表并下载历史 Excel，再尝试上传自己的年报。
估值请先用合成 B：FCFF 100，增长率 5%，WACC 10%，永续增长 2%，
净债务 200，股数 100，预测 5 年；填写自己的确认人和“合成数据功能测试”依据。
示例只是测试，不是真实公司投资建议。金额单位为原币基本单位，股数为股；5 表示 5%。
缺项会显示红字；整体假设说明也是必填。完整模型中的参考股价为选填。

五、配置与交接范围
包内保留 .env，其中可能含有效密钥，只向获授权人员交接。
接收方可改成自己的 DEEPSEEK_API_KEY，不要把 Key 粘贴到群聊或截图中。
本地多语模型约 500 MB 已随包，首次 pip 安装仍需联网。
本包不含 Python 解释器、虚拟环境、离线 wheels、RAG 索引缓存、个人估值草稿或旧后台任务。
不需要 Codex、Node.js 或独立显卡。

六、详细说明
双击“操作指南.html”，可离线阅读和打印。
“操作指南.md”是同内容的 Markdown 版。
新 PDF 必须有可提取文本；扫描件、复杂未支持版式可能失败。
第一次分析长年报建立索引可能较慢，不要反复提交同一任务。
'''

# Raw document literals keep Windows examples readable in this source; collapse
# paired backslashes once so recipients see normal paths, not Python escapes.
GUIDE = GUIDE.replace(chr(92) * 2, chr(92))
QUICKSTART = QUICKSTART.replace(chr(92) * 2, chr(92))

README = '''# Ultra 007 可迁移运行包

代码版本：2026-10-28。请先完整解压，再运行。

**首先打开 [00_先读我.txt](00_先读我.txt)，详细操作见 [操作指南.html](操作指南.html) 或 [操作指南.md](操作指南.md)。**

Windows 首次使用依次双击：

1. `01_安装依赖.bat`
2. `02_检查环境.bat`
3. `03_启动程序.bat`

需要 64 位 Python 3.11—3.14，推荐 3.14.x。首次安装 Python 依赖需要联网；约 500 MB 的本地多语模型已随包。启动后在本机打开 `http://127.0.0.1:8501`，保持启动窗口开启。

包内有完整源码、页面素材、配置、本地模型、立讯已完成研究、合成 A/B 示例及旧格力成果。不含 Python 解释器、虚拟环境、离线依赖安装包、索引缓存、个人估值草稿或旧后台任务。不需要 Codex、Node 或独立显卡。

`.env` 按交接要求保留，其中可能包含有效密钥；请只向获得授权的人提供。接收方可以改用自己的 Key。不要公开上传整个运行包。

先浏览已有成果，再在合成 B 试用估值。新报告上传会调用配置的模型服务，历史指标与 DCF 由代码中的固定公式计算。具体必填项、单位、比较范围和故障处理都在操作指南中。
'''

STYLE = '''
:root{color-scheme:light;--ink:#202621;--muted:#5c675f;--accent:#c46c22;--line:#dce2dc;--paper:#fff;--wash:#f5f7f2}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:16px/1.85 "Segoe UI","Microsoft YaHei",Arial,sans-serif}
.shell{max-width:1020px;margin:36px auto;background:var(--paper);padding:44px 58px 54px;border:1px solid var(--line);border-radius:16px}
.brand{font-weight:750;letter-spacing:.04em;color:var(--accent);margin-bottom:8px}.meta{color:var(--muted);font-size:14px}
h1{font-size:32px;line-height:1.35;margin:10px 0 18px}h2{font-size:23px;line-height:1.5;margin:42px 0 14px;padding-top:14px;border-top:1px solid var(--line);scroll-margin-top:22px}
h3{font-size:18px;margin:26px 0 12px}p{margin:12px 0}a{color:#965219;text-decoration-thickness:1px;text-underline-offset:3px}
nav{padding:18px 24px;margin:26px 0;background:#fbf6ed;border:1px solid #eadac3;border-radius:10px}nav strong{display:block;margin-bottom:6px}nav a{display:block;margin:2px 0;font-size:14px}
ul,ol{padding-left:26px}li{padding:3px 0}code{font:13px/1.7 Consolas,"Courier New",monospace;background:#f1f3ef;border-radius:4px;padding:2px 5px;overflow-wrap:anywhere}
pre{padding:16px 20px;margin:16px 0;border-radius:8px;border:1px solid var(--line);background:#f5f7f3;overflow:auto}pre code{padding:0;background:none;white-space:pre-wrap;word-break:break-word}
table{border-collapse:collapse;width:100%;margin:18px 0;font-size:14px}th,td{padding:11px 13px;border:1px solid var(--line);text-align:left;vertical-align:top}th{background:#f4f6ef;font-weight:650}td:first-child{min-width:26%}
blockquote{margin:20px 0;padding:14px 20px;border-left:4px solid #dc9a47;background:#fff8eb;border-radius:0 8px 8px 0;font-size:14px}
.footer{margin-top:42px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
@media(max-width:700px){body{font-size:15px}.shell{margin:0;padding:24px 20px;border:0;border-radius:0}h1{font-size:26px}h2{font-size:21px}table{font-size:13px}th,td{padding:8px}pre{padding:12px}}
@media print{body{background:white;font-size:10.5pt;line-height:1.65}.shell{max-width:none;margin:0;padding:0;border:0;border-radius:0}nav{break-inside:avoid}h1{font-size:23pt}h2{font-size:16pt;break-after:avoid}h3{font-size:12pt;break-after:avoid}tr,pre,blockquote{break-inside:avoid}a{color:inherit}thead{display:table-header-group}.footer{font-size:9pt}@page{margin:18mm 16mm}}
'''


def inline(source: str) -> str:
    """Render the small, controlled Markdown subset used by this document."""
    tokens: list[str] = []

    def keep_code(match: re.Match) -> str:
        tokens.append('<code>' + escape(match.group(1)) + '</code>')
        return f'\x00{len(tokens)-1}\x00'

    value = re.sub(r'`([^`]+)`', keep_code, source)
    value = escape(value)
    value = re.sub(r'\[([^\]]+)\]\((https://[^\s)]+|[^\s)]+\.(?:html|md|txt))\)',
                   lambda m: '<a href="' + escape(m.group(2), quote=True) + '">' + m.group(1) + '</a>', value)
    value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
    for index, token in enumerate(tokens):
        value = value.replace(f'\x00{index}\x00', token)
    return value


def render_markdown(source: str) -> tuple[str, list[tuple[str, str]]]:
    lines = source.splitlines()
    output: list[str] = []
    sections: list[tuple[str, str]] = []
    index = 0
    list_type: str | None = None

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f'</{list_type}>')
            list_type = None

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            close_list()
            index += 1
            continue
        if line.startswith('```'):
            close_list()
            buffer = []
            index += 1
            while index < len(lines) and not lines[index].startswith('```'):
                buffer.append(lines[index])
                index += 1
            output.append('<pre><code>' + escape('\n'.join(buffer)) + '</code></pre>')
            index += 1
            continue
        heading = re.match(r'^(#{1,3})\s+(.+)$', line)
        if heading:
            close_list()
            level = len(heading.group(1))
            title = heading.group(2)
            anchor = f'section-{len(sections)+1}' if level == 2 else None
            if anchor:
                sections.append((anchor, title))
            identifier = f' id="{anchor}"' if anchor else ''
            output.append(f'<h{level}{identifier}>{inline(title)}</h{level}>')
            index += 1
            continue
        if line.startswith('|') and index + 1 < len(lines) and re.fullmatch(r'[\s|:\-]+', lines[index + 1]):
            close_list()
            cells = lambda row: [cell.strip() for cell in row.strip().strip('|').split('|')]
            output.append('<table><thead><tr>' + ''.join('<th>' + inline(cell) + '</th>' for cell in cells(line)) + '</tr></thead><tbody>')
            index += 2
            while index < len(lines) and lines[index].startswith('|'):
                output.append('<tr>' + ''.join('<td>' + inline(cell) + '</td>' for cell in cells(lines[index])) + '</tr>')
                index += 1
            output.append('</tbody></table>')
            continue
        if line.startswith('> '):
            close_list()
            output.append('<blockquote>' + inline(line[2:]) + '</blockquote>')
            index += 1
            continue
        item = re.match(r'^(?:([-])\s+|(\d+)\.\s+)(.+)$', line)
        if item:
            kind = 'ul' if item.group(1) else 'ol'
            if list_type != kind:
                close_list()
                output.append(f'<{kind}>')
                list_type = kind
            output.append('<li>' + inline(item.group(3)) + '</li>')
            index += 1
            continue
        close_list()
        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not re.match(r'^(?:#{1,3}\s|```|\||> |[-]\s|\d+\.\s)', lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        output.append('<p>' + inline(' '.join(paragraph)) + '</p>')
    close_list()
    return '\n'.join(output), sections


def html_document(source: str) -> str:
    body, sections = render_markdown(source)
    contents = ''.join(f'<a href="#{anchor}">{escape(title)}</a>' for anchor, title in sections)
    # Insert navigation after the introductory version paragraph and handoff note.
    marker = '<h2 id="section-1">'
    body = body.replace(marker, '<nav aria-label="指南目录"><strong>操作目录</strong>' + contents + '</nav>\n' + marker, 1)
    return '<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Ultra 007 · 另一台电脑运行与使用指南</title>\n<style>' + STYLE + '</style>\n</head>\n<body><main class="shell"><div class="brand">ULTRA 007</div>\n' + body + '\n<p class="footer">Ultra 007 · 代码版本 2026-10-28 · 本页可以离线阅读和通过浏览器打印。</p></main></body></html>\n'


class GuideInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.anchors: list[str] = []
        self.external_resources: list[str] = []
        self.headings = 0
        self.tables = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get('id'):
            self.ids.add(values['id'])
        if tag == 'a' and values.get('href', '').startswith('#'):
            self.anchors.append(values['href'][1:])
        if tag in ('script', 'link', 'img', 'iframe'):
            self.external_resources.append(tag)
        if tag == 'h2':
            self.headings += 1
        if tag == 'table':
            self.tables += 1


def write_guides(target: Path) -> list[Path]:
    target = Path(target).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    html = html_document(GUIDE)
    inspector = GuideInspector()
    inspector.feed(html)
    if inspector.external_resources or inspector.headings != 13 or inspector.tables < 3:
        raise RuntimeError('Guide HTML structural check failed')
    if any(anchor not in inspector.ids for anchor in inspector.anchors):
        raise RuntimeError('Guide HTML has a broken contents link')
    if ('C:' + chr(92) + 'Users' + chr(92) + 'Lenovo') in GUIDE or 'DEEPSEEK_API_KEY=sk-' in GUIDE:
        raise RuntimeError('Guide contains a machine-specific path or credential')
    documents = {'00_先读我.txt': QUICKSTART, '操作指南.md': GUIDE, '操作指南.html': html, 'README.md': README}
    outputs = []
    for name, content in documents.items():
        path = target / name
        path.write_text(content.rstrip() + '\n', encoding='utf-8')
        if path.read_text(encoding='utf-8') != content.rstrip() + '\n':
            raise RuntimeError('Guide UTF-8 round-trip failed')
        outputs.append(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True, help='Destination folder for the four guide files')
    args = parser.parse_args()
    outputs = write_guides(args.target)
    for path in outputs:
        print(path)
    print('Guide checks passed: UTF-8, 13 sections, valid contents links, no external rendering resources.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
