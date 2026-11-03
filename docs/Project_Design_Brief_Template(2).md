# AI & Finance Practice — AI Financial Analysis Agent Design Brief

## 1. Team
- Team name:Agent 007
- Members:张嘉敏 庞偌萱 Preobrazhenskaya Elizaveta 陈端阳
- Roles: Product and workflow design; RAG and document-processing development; financial calculation and validation; Streamlit interface development; testing and documentation. Specific role assignments will be confirmed after the team list is finalized.
- Project title: Pre-Valuation Financial Data and Scenario Preparation Agent

## 2. Target user
The target users are junior-to-mid-level fundamental equity research analysts, corporate finance specialists, buy-side research associates, and other finance professionals conducting single-company fundamental analysis.

Their main difficulty is the time required to search through lengthy annual reports, locate the correct financial tables, copy figures into a consistent historical dataset, and preserve evidence for later checking. Manual extraction is slow and error-prone, especially when metric names or table formats change across reporting years. Analysts also spend repetitive spreadsheet time applying their own Base, Bear, and Bull assumptions. The proposed tool prepares reliable inputs for valuation work; it does not perform the valuation itself.

## 3. Finance problem
The agent supports one bounded task: preparing auditable historical financial data and human-defined scenario forecasts for a single company before valuation begins.

In the current workflow, an analyst manually downloads the company's annual reports, identifies relevant income-statement and balance-sheet figures, copies several years of data into a spreadsheet, checks every number against the original report, enters scenario assumptions, and builds separate forecast tables. The resulting dataset is then used in analyst-managed valuation models such as DCF or relative-multiples models.

The agent reduces the mechanical part of this workflow. It retrieves and extracts selected financial metrics from reports uploaded by the user, organizes them into a historical time series, attaches report-and-page evidence, and applies numerical assumptions entered by the analyst to deterministic Base, Bear, and Bull forecast calculations. AI is useful because RAG can search long, unstructured reports and connect extracted figures to their source context, while Python tools can perform repeatable calculations. The analyst remains responsible for selecting assumptions, constructing the valuation model, interpreting results, and making any final judgement.

## 4. Inputs
- Documents or data: Annual reports, official annual filings, MD&A sections, and embedded financial tables manually downloaded and uploaded by the user; user-entered historical look-back period, forecast horizon, and Base/Bear/Bull numerical assumptions.
- Source and year: One company's user-supplied reports for the fiscal years selected by the user. The MVP does not obtain reports, prices, market data, or third-party datasets automatically.
- File type: Text-based PDF and TXT files for reports; numerical values entered through the Streamlit interface for analysis parameters and scenario assumptions.
- Expected data quality issues: Misaligned or poorly parsed PDF tables; inconsistent metric names across years; missing line items; duplicate values expressed in different units; restated prior-year figures; page-number or fiscal-year ambiguity; and image-only scanned PDFs that cannot be reliably extracted. The agent must flag these problems instead of filling gaps with invented values.

## 5. MVP definition
The MVP is a Streamlit-based AI Financial Analysis Agent that completes a useful pre-valuation preparation workflow for one company.

- **Starting input:** The user uploads multiple annual-report PDF or TXT files, selects the historical look-back period and forecast horizon, chooses the target financial metrics, and manually enters all Base, Bear, and Bull assumptions, such as revenue-growth or margin assumptions.
- **Main task supported:** Produce a traceable historical dataset and deterministic three-scenario projections that the analyst can review before transferring them into a separately managed valuation model.
- **Agent workflow:**
  1. Ingest the uploaded files and build a LlamaIndex RAG index while retaining source-file and page metadata.
  2. Retrieve relevant report sections and extract the requested core income-statement and balance-sheet metrics for each fiscal year.
  3. Normalize labels, years, and units into a historical time-series table without changing the underlying source figures.
  4. Mark missing or ambiguous values and show parsing or consistency warnings.
  5. Read the analyst's Base, Bear, and Bull assumptions and validate basic input format and completeness.
  6. Call deterministic Python functions to calculate multi-year scenario projections.
  7. Present historical actuals, forecasts, assumptions, citations, and uncertainty notes in one reviewable result.
- **Python functions and financial tools:** A LlamaIndex-based RAG metric-extraction tool; a deterministic scenario forecast calculator using explicit arithmetic formulas; input-validation and unit-consistency checks; and a table-rendering function for the Streamlit interface. The LLM may plan retrieval and explain results, but it must not perform unverified arithmetic or invent missing values.
- **Expected result:** A combined table containing historical actual figures and separate Base, Bear, and Bull forecast columns; a visible assumptions table; report-name and page-number citations for every historical value; a short narrative summary; and explicit warnings for missing data, low-confidence extraction, unit inconsistencies, and unsupported files. The output is preparation material for later human-led valuation, not a DCF, fair value, or price target.
- **Trust and review:** The user can inspect every extracted figure, follow its source reference, compare the table with the uploaded report, review all scenario inputs, and spot-check forecast calculations. Values without adequate evidence are labelled for review rather than silently accepted.

## 6. Scope boundary
The MVP will:

- Process user-uploaded text-based PDF and TXT annual reports for one company.
- Extract selected core income-statement and balance-sheet metrics and organize them into a historical time series.
- Preserve report-name and page-number traceability for historical figures.
- Run simple deterministic Base, Bear, and Bull projections using assumptions entered entirely by the user.
- Display historical data, forecasts, assumptions, citations, missing-data flags, and parsing warnings in Streamlit.
- Support a user-selected historical window and forecast horizon based on the available historical data and manually supplied assumptions.

The MVP will deliberately not:

- Download annual reports or retrieve external market data, stock prices, news, or third-party API data.
- Generate scenario assumptions automatically or replace industry judgement.
- Perform DCF, relative-multiples valuation, fair-value estimation, price-target calculation, or any other end-to-end valuation.
- Produce investment recommendations, buy/sell signals, trading actions, or completed equity-research reports.
- Compare multiple companies, manage portfolios, or use advanced stochastic forecasting.
- Correct factual errors in source reports; it will reproduce sourced figures and flag apparent inconsistencies.
- Reliably process image-only scanned PDFs in the MVP.
- Provide user-access control, permission management, or automated model export/integration in the MVP.

All outputs are analytical preparation materials. The user retains responsibility for source verification, forecast assumptions, valuation design, and final decisions.

## 7. Success criteria
The MVP succeeds when the following criteria are observable in an end-to-end test:

1. **Task usefulness:** A first-time target user can upload reports, select metrics, enter scenario parameters, and obtain a complete historical-plus-forecast table suitable for use as an input to later valuation work.
2. **Analysis quality:** Every historical number displayed has a report-name and page-number citation, or is explicitly marked as missing or requiring review. Units and fiscal years are shown consistently. Forecast outputs match an independent recalculation using the same user-entered assumptions.
3. **Agent behavior:** The agent uses document retrieval for source-grounded extraction and the Python calculator for arithmetic. It does not fabricate unavailable metrics, auto-generate scenario assumptions, or drift into valuation and investment advice. When evidence is insufficient, it gives a clear data-missing or low-confidence warning.
4. **Product usability:** A first-time user can complete the upload → parameter entry → analysis → evidence review workflow in Streamlit without reading the source code. Assumptions, citations, warnings, and the pre-valuation scope are visible on the result page.

## 8. Test questions

1. **A document-grounded question:**  
   “Extract historical revenue and gross profit for the past five fiscal years from these uploaded annual reports.”  
   **Expected behavior:** The agent uses RAG retrieval, returns a year-by-year table, identifies units, and attaches the exact report name and page number to every extracted value. If a year or metric is absent or ambiguous, it labels the cell as missing or requiring review rather than estimating it.

2. **A calculation or financial-indicator task:**  
   “Using my assumptions of 6% Base revenue growth, -3% Bear revenue growth, and 12% Bull revenue growth, generate three-year revenue projections.”  
   **Expected behavior:** The agent takes the latest verified historical revenue as the starting value, passes the three user-provided rates and forecast horizon to the deterministic Python calculator, displays the assumptions beside the output, and produces reproducible Base/Bear/Bull tables. It does not choose or revise the rates itself.

3. **A multi-step analysis or risk-assessment task:**  
   “Extract four years of EBITDA margin data with sources, apply my Base/Bear/Bull margin assumptions, and flag large negative margin shifts in the Bear case.”  
   **Expected behavior:** The agent first retrieves and cites historical values, then uses the calculation tool to apply the user's assumptions, compares projected Bear-case margins with historical margins, and highlights material deterioration according to a user-provided threshold. The summary links the warning to the relevant input assumption and does not translate it into a valuation or investment recommendation.

## 9. Risk and human review
- **Data and parsing risk:** Complex tables, inconsistent units, restatements, and low-quality PDFs may cause incorrect extraction. Image-only scanned PDFs are unsupported. The UI must show: “PDF parsing may be incomplete; cross-check every figure with the original source document.”
- **Retrieval risk:** RAG may select an irrelevant passage, confuse consolidated and segment figures, or mix fiscal years. Each historical value therefore requires a visible citation, and unclear matches must be marked for review.
- **Tool-selection and calculation risk:** The agent may attempt free-form LLM arithmetic or may apply the wrong scenario input. Forecast calculations must run through the deterministic Python function, and inputs and formulas must remain visible for spot-checking.
- **Input risk:** Users may enter incomplete, conflicting, or implausible assumptions. The interface should reject invalid formats, identify missing fields, and warn about inconsistent scenario ordering without replacing the user's judgement.
- **Model-reasoning risk:** The model may infer a missing value or overstate what the data supports. If evidence is unavailable, the required message is: “Data missing from uploaded source reports.”
- **Interface risk:** Broken table rendering or citations could remove audit traceability. A result should not be treated as complete if its source reference cannot be displayed.
- **Scope and interpretation risk:** Users may mistake forecast preparation for valuation or investment advice. The result page must state: “This agent prepares historical data and scenario projections for human-led valuation. It does not perform valuation or provide investment advice.”

Mandatory human review is required at three points:

1. After extraction, the user checks key historical figures against the cited report pages.
2. Before forecasting, the user confirms all Base, Bear, and Bull assumptions, thresholds, units, and the forecast horizon.
3. After forecasting, the user spot-checks representative calculations and reviews all missing-data, parsing, and consistency warnings before using the output in any downstream model.

All extracted figures, scenario tables, and narrative observations require human validation. Unsupported cases must stop with a clear warning rather than produce a confident answer.
