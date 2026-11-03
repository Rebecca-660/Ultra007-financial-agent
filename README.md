# Ultra 007 — Financial Analysis Agent

通用年报分析与估值系统，提供中文、English、Русский 界面及明暗主题。

## 功能

- 上传 PDF 年报，提取合并资产负债表、利润表、现金流量表。
- 单公司历史分析、多公司可比年度对比、财务比率和可视化。
- Excel 导出与来源追溯。
- 用户明确选择继续估值并确认参数后，使用代码中定义的公式计算 FCFF DCF。
- AI 负责取证及提取，历史指标和估值由确定性代码计算。系统校验不等同人工审计。

## 安装与运行

使用 64 位 Python 3.11–3.14；本项目曾在 Python 3.14.4 环境验证。

1. 下载并完整解压仓库。
2. 双击 `01_安装依赖.bat`，安装依赖（首次需要联网）。
3. 将 `.env.example` 复制为 `.env`，填写自己的 `DEEPSEEK_API_KEY`。
4. 本地模型未包含在 GitHub 仓库。首次分析时需联网下载 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，或将完整模型文件置于 `data/models/paraphrase-multilingual-MiniLM-L12-v2/`。
5. 双击 `03_启动程序.bat`，打开 http://127.0.0.1:8501/ ，保持启动窗口开启。

也可在已安装依赖的环境中执行 `python -m streamlit run streamlit_app.py`。
`02_检查环境.bat` 在本地模型尚未下载时会提示模型缺失。

## 数据与范围

仓库不包含 API 密钥、真实年报、原项目运行成果、本地模型、缓存或个人估值记录。使用时上传自己的年报；测试目录包含代码测试和模拟数据构造逻辑。
当前估值面向非金融企业 FCFF；不自动混用不同币种或不可比口径。扫描年报可能需要另行 OCR。

## 文档

设计文档、历史阶段说明和公式清单位于 `docs/`。部分文档反映历史阶段，请以当前代码和本说明为准。
第三方模型与依赖说明见 `THIRD_PARTY_NOTICES.md` 和 `licenses/`。

请勿提交 `.env` 或密钥，也不要在代码、截图和提交历史中放置密钥。
