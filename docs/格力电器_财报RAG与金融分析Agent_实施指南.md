# 格力电器财报 RAG 与金融分析 Agent：逐步实施指南

版本：2026-09-29  
依据：你们的 `Project_Design_Brief_Template(2).md`、课程 Week 1 PDF、老师指定的 [LlamaIndex RAG 入门](https://developers.llamaindex.ai/python/framework/understanding/rag/)。

## 0. 先明确最终要交付什么

**研究对象**：格力电器（000651），先使用 2023、2024、2025 三份年度报告全文。研究的是一家公司在家电制造业中的案例，不把单家公司的结果写成整个行业的结论。

**目标用户**：做公司基本面研究的初级分析师。系统帮助他核对历史数据、理解报告披露的经营与风险信息，并根据他自己输入的 Base/Bear/Bull 假设生成估值前的预测表。

**最终可运行的 Streamlit 原型包含两个连续模块**：

| 模块 | 用户得到什么 | 课程对应 |
|---|---|---|
| 财报问答与风险摘要 | 上传多份年报，自然语言问答、报告摘要、风险提取、文件和页码证据、连续追问 | Case 1 |
| 数据与情景准备 Agent | 经核对的历史指标、三个确定性计算工具、Base/Bear/Bull 情景、两张图、规则风险检查、结构化报告 | Case 2；也落实你们的 md |

课程要求 Case 1 的持续对话、自动报告摘要和报告风险提取；你们当前 md 尚未明确实现这些功能。课程要求 Case 2 至少三个确定性金融工具、两项可视化输出、规则检查和结构化报告；当前 md 的工具与图表也需要具体化。**改变行业不能代替补齐这些功能。**

### 范围约束

- 第一版只处理用户上传的**文本型 PDF/TXT**，不自动下载报告，不接股价、新闻或实时行情 API。
- 不自动设定预测增长率、毛利率或风险阈值；用户输入并确认。
- 不计算 DCF、公允价值或目标价，不给交易建议。
- 扫描件、提取失败的表格和没有来源的数字一律标记待核查。
- 每个历史数字的报告年份、数据年份、原单位和来源页码都要可见。

## 1. 取得资料，建立人工核对的答案集

下载年度报告**全文**，不要把摘要、业绩预告和正式年报混在一起：

1. [格力电器 2023 年年度报告全文](https://static.cninfo.com.cn/finalpage/2024-04-30/1219928418.PDF)
2. [格力电器 2024 年年度报告全文](https://static.cninfo.com.cn/finalpage/2025-04-28/1223330631.PDF)
3. [格力电器 2025 年年度报告全文](https://static.cninfo.com.cn/finalpage/2026-04-29/1225250396.PDF)

保存为 `data/reports/gree_2023.pdf` 等。记录下载地址、下载日、文件哈希、页数和报告版本。先人工翻阅每份报告的目录、主要会计数据、管理层讨论、风险描述、合并利润表、资产负债表和现金流量表。选取 20–30 道带标准答案的问题，涵盖数字、经营解释、风险、跨年比较、报告无法回答的问题。

**重要口径**：一份 2025 年报通常同时列示 2025、2024、2023 年数字。`report_year=2025` 表示证据来自 2025 年报，`value_year=2023` 表示这个数字对应 2023 年；两者不能混用。年度间若有重述，保留两个版本并提示人工选择。

验收：人工能在报告中找到每道标准题的原文或表格，以及 PDF 页码和报告印刷页码。

## 2. 环境与目录

在 PyCharm 新建项目或虚拟环境，建议 Python 3.11/3.12；保持与已完成的 LlamaIndex 课堂练习一致。Windows PowerShell 示例：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install llama-index-core llama-index-llms-deepseek llama-index-embeddings-huggingface pymupdf streamlit pandas plotly python-dotenv pydantic pytest
```

如果你们已经配置并测试了另一种 LLM，可以沿用；**LLM 与向量嵌入模型是两个独立配置**。这里的 DeepSeek 只是与先前课堂练习衔接的示例，不要求团队改用新服务。`.env` 存放 `DEEPSEEK_API_KEY=...`，加入 `.gitignore`，不要把密钥写进代码或提交仓库。首次下载本地嵌入模型需要可访问模型源；若下载失败，换用团队能稳定访问的中文嵌入服务，并在建索引和查询时保持同一个模型。

推荐目录：

```text
project/
├─ app.py                     # Streamlit 页面
├─ .env.example               # 只写变量名和示例，不含真实密钥
├─ requirements.txt           # 在可运行环境中锁定实际依赖
├─ data/
│  ├─ reports/                # 用户上传的正式年报
│  ├─ review/metrics.csv      # 人工核对后的历史数字
│  ├─ review/questions.csv    # 人工标注的标准问题
│  └─ index/                  # 保存的索引，不入版本控制
├─ src/
│  ├─ ingest.py               # 按页解析、元数据、质量检查
│  ├─ rag.py                  # 索引、检索、引用和拒答
│  ├─ extract.py              # 财务数据候选提取与审核状态
│  ├─ finance.py              # 三项确定性工具
│  ├─ agent.py                # 子 Agent / 主 Agent 调用
│  ├─ report.py               # 摘要和结构化输出
│  └─ store.py                # 会话和结果持久化
└─ tests/
   ├─ test_finance.py
   └─ evaluation_questions.csv
```

完成标准：能在干净环境中安装依赖，`python -c "import llama_index.core, fitz, streamlit"` 正常退出。把已经验证可运行的版本写入 `requirements.txt`。

## 3. 加载：按 PDF 物理页建立证据

老师的 RAG 教程把第一步称为 **Loading**。`SimpleDirectoryReader` 可快速验证文件能否读入，但你们必须给每个回答显示**准确页码**，建议首版直接用 PyMuPDF 按页提取，再创建 LlamaIndex `Document`。以下是实现要点的最小示意：

```python
from pathlib import Path
import fitz
from llama_index.core import Document

def load_report_pages(path: Path, report_year: int) -> list[Document]:
    documents = []
    with fitz.open(path) as pdf:
        for page_index in range(len(pdf)):
            text = pdf[page_index].get_text("text").strip()
            if not text:
                # 在数据质量清单中记录；不要编造这一页的内容。
                continue
            documents.append(Document(
                text=text,
                metadata={
                    "company_code": "000651",
                    "company_name": "格力电器",
                    "report_year": report_year,
                    "file_name": path.name,
                    "pdf_page": page_index + 1,
                },
            ))
    return documents
```

建议同时保存 `printed_page`（若报告正文印有页码，经人工抽查后映射）、`source_url` 和 `file_hash`。不要假设 `pdf_page` 与报告印刷页码相同。对空白页、乱码页、表格列错位页生成 `parse_warnings.csv`；扫描版 PDF 首版提示不支持。尽量不要让文本块跨越两个 PDF 页，否则引用会失准。

**抽查 15 页**：封面、目录、三张财务报表、风险段落以及随机页。逐页比对提取文本与原 PDF。通过后再建索引。

## 4. 建索引与存储：先做可查询的单年报告

老师的五步路线中，**Indexing** 负责把文档切成 Nodes 并建立检索结构，**Storing** 避免每次启动重复建立索引。初始配置建议为中文嵌入模型、按页输入、每块约 500–800 个字符的等效长度、少量重叠；实际切分参数需要用测试题调整。优先保留每个块的页码元数据。

```python
from dotenv import load_dotenv
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.deepseek import DeepSeek

load_dotenv()
Settings.llm = DeepSeek(model="deepseek-chat")  # 从 DEEPSEEK_API_KEY 读取密钥
Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-zh-v1.5")
Settings.text_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=80)
index = VectorStoreIndex.from_documents(documents, show_progress=True)
index.storage_context.persist(persist_dir="data/index/gree_2025")
```

上面是起始配置，不是已经针对格力年报调优的参数。把**嵌入模型名、切分设置、源文件哈希**写入索引清单；源报告或模型改变时重建索引。先仅载入 2025 年报跑通，再加入 2023、2024 年报；可按年建独立索引，或者使用一个索引加 `report_year` 过滤，团队只选一种并固定下来。

验收：程序重启后能从磁盘加载同一索引；检索“2025 年经营活动产生的现金流量净额”时，能看到正确的来源节点、文件和页码。索引保存与聊天记录保存是两件事。

## 5. 查询：先让 Query Engine 准确回答，再包装成子 Agent

老师教程的 **Querying** 包含检索、可选的过滤/重排、根据检索内容生成回答。先写一个没有 Agent 的 `ask_report(question, report_year)`：

```python
query_engine = index.as_query_engine(similarity_top_k=5)
response = query_engine.query("2025 年公司的经营活动现金流如何变化？")
print(response)
for item in response.source_nodes:
    print(item.node.metadata)
```

不能直接把 `source_nodes` 的列表当成“每句话都被证明”。实现 `rag.py` 时应：

1. 解析用户要求的年度和指标；限制或路由到相应年报。
2. 检索前五个候选节点，记录得分与元数据，检查来源是否同公司、同报告年度。
3. 把可核对的证据交给 LLM；要求回答事实时标注证据编号。
4. 程序逐项验证证据编号确实在检索结果里，再显示文件名、PDF 页码、简短证据文本。
5. 找不到充分证据时返回“上传的报告中未找到足够证据”，提示用户核查；不从通用知识补数。

报告摘要单独处理：分别对“主要会计数据”“管理层讨论”中检索到的内容归纳经营表现。风险摘要从年报实际披露的风险或经营不确定性中提取，区分“已发生事项”和“披露的潜在风险”，每一条均附页码。

**这里的 RAG 子 Agent** 叫 `ReportEvidenceAgent`。它只需要一到两个工具，例如 `search_report_evidence(question, report_year)` 和 `extract_report_risks(report_year)`。`FunctionAgent` 的职责是针对用户问题选择工具、必要时多步查询并整理证据；不要让它自己凭记忆编财务数字，也不要一开始搭多个互相转交任务的 Agent。LlamaIndex 文档允许把普通 Python 函数或 Query Engine 封装为 Agent 工具。

连续对话应保存同一会话的上下文，并支持“那上一年呢？”等追问。**Streamlit `session_state` 只解决当前会话的界面状态**；要满足课程的跨会话历史，需把会话 ID、消息、报告集合和时间戳保存到 SQLite，重开页面后选择会话并恢复。若使用 LlamaIndex Workflow `Context`，按官方序列化方法保存和恢复。

Case 1 完成标准：多文件上传、自由问答、报告层面表现摘要、风险摘要、可核对文件与页码、跨会话恢复、人工复核提示全部可演示。

## 6. 抽取历史数据：候选值和可计算值分开

年报中文表格会出现跨行表头、`元/万元/亿元`、负号、同比列、合并报表与母公司报表，以及一份年报含多个年度的情况。**RAG 负责定位和解释；计算从审核通过的结构化表读取。**

先选少量指标：`营业收入`、`营业成本`、`归母净利润`、`经营活动现金流量净额`、`存货`。不要把 md 测试题中的 `EBITDA margin` 作为第一版必需值；如果报告未直接披露，需要额外定义和核对折旧摊销口径。毛利率可以由同口径收入和成本确定性计算。

`metrics.csv` 推荐字段：

```text
company_code,metric,value_year,report_year,raw_value,raw_unit,
normalized_yuan,scope,file_name,pdf_page,printed_page,
evidence_text,review_status,reviewer,reviewed_at
```

`scope` 例如 `consolidated`；`review_status` 取 `candidate/approved/rejected/needs_review`。解析出的候选值**不能直接用于预测**；由一位组员对照原页核查，另一位抽查关键指标。若数字来自 2025 年报中的“2023 年”列，保留 `value_year=2023` 与 `report_year=2025`；若与 2023 原年报不一致，标记可能重述并报告两个来源。

可以先人工录入 3 年 × 5 项指标建立可信的 `approved` 基线，再逐项替换为自动提取加人工审核；这比让一个不稳定的表格解析器控制整个原型更可执行。

验收：每个 `approved` 值均能反查 PDF 页，单位转换有记录；未审核、重复、口径冲突或缺失的值不会进入 `finance.py`。

## 7. Case 2：三个确定性工具与两张图

编写纯 Python 函数；函数只接收已核查数据和用户参数，不让 LLM 算术。先实现**三个确定性金融工具和一项独立的规则检查**：

| 工具 | 输入 | 输出与检查 |
|---|---|---|
| `calculate_indicators` | 年度收入、成本 | 收入同比、毛利率；零分母时返回“不适用” |
| `calculate_cash_flow_quality` | 经营现金流、净利润、收入 | 现金流/净利润、经营现金流占收入比等；负利润或零分母时显示明确口径说明 |
| `forecast_scenarios` | 最新已审核收入、预测年数、逐情景增长率和毛利率 | Base/Bear/Bull 的收入、毛利；展示输入和公式 |
| `apply_risk_rules`（独立检查） | 历史指标、预测表、用户阈值 | 如收入增速低于阈值、现金流与利润背离、Bear 毛利率跌幅过大；每条显示阈值和触发依据 |

基本公式：

```text
营业收入同比 = 当年营业收入 / 上年营业收入 - 1
毛利率 = (营业收入 - 营业成本) / 营业收入
情景收入[t] = 情景收入[t-1] × (1 + 用户输入的增长率[t])
情景毛利[t] = 情景收入[t] × 用户输入的毛利率[t]
```

示例：用户输入预测 3 年，Base/Bear/Bull 每年的收入增长率和毛利率，系统显示三张表。**示例假设不是模型预测值**，必须标为“用户输入”，并在点击计算前确认。指标缺失、单位不一致或分母为零时停止该项计算并显示原因。

两张必备图：

1. 历史营业收入与毛利率趋势图（不同单位分图或双轴明确标识）。
2. Base/Bear/Bull 三条收入预测曲线，标出历史实际与预测起点。

结构化输出固定为：`数据范围 → 历史实际与出处 → 假设 → 指标与三情景结果 → 两张图 → 触发的规则 → 缺失值与人工复核说明`。这张结果页既能作为课程 Case 2 的标准化报告，也符合 md 所说的估值前准备材料。

## 8. Streamlit：按用户动作组织页面

建议做四个标签页，避免一页堆满功能：

1. **上传与检查**：`st.file_uploader(..., accept_multiple_files=True)`，展示每个文件的报告年份、页数、解析警告及建索引状态。
2. **财报问答**：`st.chat_input` 和 `st.chat_message`，回答下方有证据卡片和打开 PDF 对应页的入口；侧栏恢复历史会话。
3. **数据审核**：候选值、原单位、目标单位、原文、页码、接受/拒绝按钮；只允许 `approved` 数值流向计算工具。
4. **情景与报告**：历史窗口、预测期、三情景参数、阈值确认、计算按钮、表格、两张图与风险提示。

每个动作给用户明确状态：`上传完成 → 解析完成 → 索引完成 → 等待审核 → 可计算 → 报告生成`。一项失败时保留已有成果和错误原因；不要显示看似完整但缺少来源的报告。首次部署可以在本机运行：

```powershell
streamlit run app.py
```

## 9. 评估：按老师的第五步检验，而不是只看演示是否流畅

建立 `questions.csv`，每题含 `question,expected_answer,expected_report_year,expected_pdf_page,type`。建议至少：10 道数字题、5 道报告解释题、5 道风险题、5 道不可回答或混淆年份题。把检索结果与最终回答分开评估：

- **检索**：正确页是否出现在前五个候选节点中；记录命中率及误检页。
- **回答**：数字、单位、年份、结论是否与原文一致；每项引用是否真正支持该句。
- **拒答**：五道不可回答题是否拒绝猜测。
- **计算**：为每个函数准备手算或表格复算样例，包括零分母、缺失和负值；输出必须逐项相同。
- **产品**：重启后索引可用、历史会话可恢复、三份报告可上传、两张图正常显示。

可以使用 LlamaIndex 的检索评估与忠实度评估模块，但**人工核对真实 PDF 页仍是评分依据**。先跑基线，再逐个调整分块、检索过滤、提示词；每改一处用同一组题重测，记录版本与结果。

### 最终验收清单

- [ ] 一家公司三份年报全文能上传，无法解析的文件有提示。
- [ ] 自然语言问答、连续追问和跨会话恢复可演示。
- [ ] 报告表现摘要与披露风险摘要都附原报告页码。
- [ ] 历史数据表区分 `report_year`、`value_year`、单位及合并口径。
- [ ] 三个确定性金融工具和独立风险规则只使用审核通过的数据及用户假设。
- [ ] 两张图、规则触发条件和结构化结果页可演示。
- [ ] 对未披露问题拒答；对缺失、歧义和解析失败显式标记。
- [ ] 使用说明清楚写明人工审核点和估值前准备边界。

## 10. 四周推进表与分工建议

| 周 | 工作包 | 可验收产物 |
|---|---|---|
| 1 | 获取三份报告；标注问题和 15 项左右历史指标；搭环境、解析和页码核查 | `questions.csv`、`metrics.csv` 初版、解析警告表 |
| 2 | 建索引、保存与加载、Query Engine 问答、证据卡、摘要与风险提取 | Case 1 命令行演示与错误记录 |
| 3 | 接入子 Agent、跨会话历史、三个金融工具、独立风险规则、假设校验 | 可复算的三情景表和工具测试 |
| 4 | Streamlit、两张图、完整报告、人工测评和演示 | 可运行原型、结果截图、评估表、使用说明 |

你们 md 已列出产品流程、RAG、金融计算、前端和测试职责；现在需要把五类职责落实到具体组员，并指定一人负责数据口径与最终验收。RAG 组交付带元数据的证据，金融组只接收已审核的数值，前端组显示状态和出处，测试组维护标准问题与失败样例。

## 11. 常见阻塞与处理顺序

| 现象 | 先检查什么 | 处理 |
|---|---|---|
| PDF 检索不到数字 | 原页是否文本型；解析的行列是否错位 | 保留原页链接，用人工审核的 CSV 供计算；必要时换解析器 |
| 数字对了但引用错页 | 分块是否跨页、元数据是否继承 | 强制页内分块，抽查 PDF 页与印刷页 |
| 2024 数字在 2025 年报被当成 2025 | 报告年份与数值年份是否分开 | 增加 `report_year/value_year`，显式筛选 |
| 回答捏造来源 | 是否只显示了检索节点但未验证答案 | 逐条校验引用 ID；证据不足就拒答 |
| Agent 没有调用工具 | 工具说明、模型工具调用支持、运行日志 | 先单独测试工具，再测试 `FunctionAgent`；必要时关闭流式输出 |
| 重启后聊天丢失 | 是否只用了 `st.session_state` | 将消息和上下文按会话 ID 持久化到 SQLite |
| 预测结果不可信 | 输入是否来自 `approved` 数据、单位是否统一 | 阻止计算并提示复核；对公式做独立复算 |

## 12. 参考资料与推荐学习顺序

1. 老师指定：[Introduction to RAG](https://developers.llamaindex.ai/python/framework/understanding/rag/)：理解加载、建索引、存储、查询、评估。
2. [Loading Data](https://developers.llamaindex.ai/python/framework/understanding/rag/loading/) 与 [SimpleDirectoryReader](https://developers.llamaindex.ai/python/framework/module_guides/loading/simpledirectoryreader/)：先理解 Document、Node 和 metadata；本项目用逐页读取保证引用准确。
3. [Using VectorStoreIndex](https://developers.llamaindex.ai/python/framework/module_guides/indexing/vector_store_index/) 与 [Persisting & Loading Data](https://developers.llamaindex.ai/python/framework/module_guides/storing/save_load/)：完成索引与重启加载。
4. [Querying](https://developers.llamaindex.ai/python/framework/understanding/rag/querying/) 与 [Q&A patterns](https://developers.llamaindex.ai/python/framework/understanding/putting_it_all_together/q_and_a/)：完成检索、查询和证据检查。
5. [Building an agent](https://developers.llamaindex.ai/python/framework/understanding/agent/) 与 [Maintaining state](https://developers.llamaindex.ai/python/framework/understanding/agent/state/)：Query Engine 稳定后再接工具和历史。
6. [Evaluating](https://developers.llamaindex.ai/python/framework/understanding/evaluating/evaluating/)：检索与回答分别评估。
7. [LlamaIndex 的 DeepSeek 集成](https://developers.llamaindex.ai/python/framework/integrations/llm/deepseek/) 与 [本地 HuggingFace 嵌入](https://developers.llamaindex.ai/python/framework/integrations/embeddings/huggingface/)：选定并记录模型配置。
8. [Streamlit 聊天应用教程](https://docs.streamlit.io/develop/tutorials/chat-and-llm-apps/build-conversational-apps)：搭建问答界面；跨会话保存另行实现。

**开始时只做第一道纵向流程**：上传 2025 年报 → 检索一个问题 → 显示正确页码 → 将一个审核通过的营业收入读入计算器。这个流程跑通后，按上述步骤扩到多年、风险、情景和完整网页。
