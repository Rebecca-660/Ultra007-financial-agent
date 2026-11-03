"""Deterministic metrics; unapproved source values cannot enter calculations."""
from __future__ import annotations

import ast
from decimal import Decimal
from .models import Dataset, Review, Statement, SystemValidation, digest

INPUTS = {
    "revenue": ("营业收入", "IS"), "cost_of_sales": ("营业成本", "IS"),
    "operating_profit": ("营业利润", "IS"), "net_income": ("合并净利润", "IS"),
    "parent_net_income": ("归母净利润", "IS"), "assets": ("总资产", "BS"),
    "liabilities": ("总负债", "BS"), "equity": ("全部股东权益", "BS"),
    "parent_equity": ("归母股东权益", "BS"), "current_assets": ("流动资产", "BS"),
    "current_liabilities": ("流动负债", "BS"), "inventory": ("存货", "BS"),
    "receivables": ("应收账款", "BS"), "cfo": ("经营活动现金流量净额", "CF"),
    "cfi": ("投资活动现金流量净额", "CF"), "cff": ("筹资活动现金流量净额", "CF"),
    "capex": ("购建长期资产支付现金", "CF"),
    "assets_opening": ("期初总资产", "BS"), "parent_equity_opening": ("期初归母权益", "BS"),
    "inventory_opening": ("期初存货", "BS"), "receivables_opening": ("期初应收账款", "BS"),
    "revenue_previous": ("上年营业收入", "IS"), "net_income_previous": ("上年合并净利润", "IS"),
}
# name, expression, display format, positive prerequisites, definition
RECIPES = [
    ("营业收入同比", "revenue/revenue_previous-1", "percent", ["revenue_previous"], "上年收入必须为正；优先引用上年原报主列。"),
    ("合并净利润同比", "net_income/net_income_previous-1", "percent", ["net_income_previous"], "亏损或零基数不显示普通同比。"),
    ("营业收入变动额", "revenue-revenue_previous", "amount", [], "本年营业收入减上年营业收入。"),
    ("合并净利润变动额", "net_income-net_income_previous", "amount", [], "负基数时仍可观察金额变化。"),
    ("毛利", "revenue-cost_of_sales", "amount", [], "营业收入减匹配的营业成本，不采用营业总成本。"),
    ("毛利率", "(revenue-cost_of_sales)/revenue", "percent", ["revenue"], "营业收入与成本采用相同业务口径。"),
    ("营业利润率", "operating_profit/revenue", "percent", ["revenue"], "年报营业利润/营业收入；营业利润可能包含投资等收益。"),
    ("净利率", "net_income/revenue", "percent", ["revenue"], "合并净利润/营业收入。"),
    ("ROA", "net_income/((assets+assets_opening)/2)", "percent", ["assets","assets_opening"], "合并净利润/期初期末平均总资产。"),
    ("ROE", "parent_net_income/((parent_equity+parent_equity_opening)/2)", "percent", ["parent_equity","parent_equity_opening"], "归母净利润/平均归母权益，不等同于加权平均 ROE。"),
    ("资产负债率", "liabilities/assets", "percent", ["assets"], "总负债/总资产，包含非付息经营性负债。"),
    ("负债权益比", "liabilities/equity", "multiple", ["equity"], "总负债/全部权益，区别于有息债务/权益。"),
    ("流动比率", "current_assets/current_liabilities", "multiple", ["current_liabilities"], "流动资产/流动负债。"),
    ("简化速动比率", "(current_assets-inventory)/current_liabilities", "multiple", ["current_liabilities"], "仅剔除存货，仍可能包含预付款、受限等非速动项目。"),
    ("存货周转率", "cost_of_sales/((inventory+inventory_opening)/2)", "multiple", ["inventory","inventory_opening"], "营业成本/期初期末平均存货，单位次/年。"),
    ("应收账款周转率", "revenue/((receivables+receivables_opening)/2)", "multiple", ["receivables","receivables_opening"], "营业收入代理赊销收入/平均应收账款，单位次/年。"),
    ("总资产周转率", "revenue/((assets+assets_opening)/2)", "multiple", ["assets","assets_opening"], "营业收入/平均总资产，单位次/年。"),
    ("经营现金流/净利润", "cfo/net_income", "multiple", ["net_income"], "净利润非正时不可作通常现金含量比较。"),
    ("经营现金流利润率", "cfo/revenue", "percent", ["revenue"], "经营现金流/营业收入。"),
    ("简化自由现金流", "cfo-capex", "amount", [], "经营现金流减购建长期资产现金支出，不等同于 FCFF。"),
]


def expression_inputs(expression: str) -> set[str]:
    return {node.id for node in ast.walk(ast.parse(expression, mode="eval")) if isinstance(node, ast.Name)}


def evaluate(expression: str, values: dict[str, Decimal]) -> Decimal:
    def visit(node):
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Name): return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int,float): return Decimal(str(node.value))
        if isinstance(node, ast.BinOp):
            a,b = visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Add): return a+b
            if isinstance(node.op,ast.Sub): return a-b
            if isinstance(node.op,ast.Mult): return a*b
            if isinstance(node.op,ast.Div): return a/b
        raise ValueError("Unsupported expression")
    return visit(ast.parse(expression,mode="eval"))


def effective_statements(dataset: Dataset, review: Review | SystemValidation | None) -> dict[str,Statement]:
    if review is None:
        return {}
    if isinstance(review,SystemValidation):
        from .automatic import assert_validation
        assert_validation(dataset,review)
        return {s.statement_id:s.model_copy(deep=True) for s in dataset.statements}
    if review.dataset_fingerprint != dataset.fingerprint or review.report_set_id != dataset.report_set_id:
        raise ValueError("审核属于旧版或其他报告集合，请重新审核。")
    by_id = {s.statement_id:s for s in dataset.statements}
    effective = {}
    seen = set()
    for decision in review.decisions:
        if decision.statement_id in seen or decision.statement_id not in by_id:
            raise ValueError("Duplicate or unknown review identity")
        seen.add(decision.statement_id)
        original = by_id[decision.statement_id]
        if decision.statement_digest != digest(original):
            raise ValueError("Statement changed after review")
        if decision.decision != "approved":
            continue
        if not decision.reviewer.strip():
            raise ValueError("人工审核人不能为空")
        conflicting = any(original.statement_id in (c['current_statement_id'],c['comparison_statement_id']) for c in dataset.conflicts)
        if conflicting and decision.conflict_resolution != "as_reported":
            raise ValueError("比较栏差异未处理；请明确选择 as_reported 并核对原报。")
        current = original.model_copy(deep=True)
        corrections_seen = set()
        for correction in decision.corrections:
            record_key = (correction.row_id,correction.column_id)
            if record_key in corrections_seen:
                raise ValueError("Duplicate correction")
            corrections_seen.add(record_key)
            rows = [r for r in current.rows if r.row_id == correction.row_id]
            cols = [i for i,c in enumerate(current.columns) if c.column_id == correction.column_id]
            if len(rows)!=1 or len(cols)!=1 or rows[0].values[cols[0]] != correction.original:
                raise ValueError("Correction does not match original source cell")
            rows[0].values[cols[0]] = correction.corrected
        # Validate the effective input itself, including human corrections.
        # The Excel audit view is terminal and is never used as a formula input.
        equations=([('assets',['liabilities','equity'])] if current.kind=='BS' else
                   [('cash_closing',['cash_opening','cash_change'])] if current.kind=='CF' else [])
        for total,parts in equations:
            indexed={}
            for r in current.rows:
                if r.canonical_metric in [total,*parts]:
                    if r.canonical_metric in indexed:
                        raise ValueError('自动勾稽输入映射不唯一')
                    indexed[r.canonical_metric]=r
            for col in range(len(current.columns)):
                if all(k in indexed and indexed[k].values[col] is not None for k in [total,*parts]):
                    difference=indexed[total].values[col]-sum(indexed[k].values[col] for k in parts)
                    if abs(difference)>Decimal('.05'):
                        raise ValueError('人工修正后基础勾稽不成立，请重新核对：'+current.statement_id)
        effective[current.statement_id] = current
    return effective


def analyze(dataset: Dataset, review: Review | SystemValidation | None = None) -> dict:
    effective = effective_statements(dataset,review)
    years = sorted({s.report_year for s in dataset.statements})
    raw = {(s.report_year,s.kind):s for s in dataset.statements}
    approved = {(s.report_year,s.kind):s for s in effective.values()}
    inputs,results = {},[]
    for year in years:
        annual = {}
        for metric,(label,kind) in INPUTS.items():
            source_year = year
            canonical, column = metric,None
            selection = 'current'
            if metric.endswith('_opening'):
                canonical,selection = metric[:-8],'opening'
            if metric.endswith('_previous'):
                canonical = metric[:-9]
                if (year-1,kind) in raw:
                    source_year = year-1
                else:
                    selection='prior'
            statement = approved.get((source_year,kind))
            item = {"label":label,"value":None,"reason":"来源报表未获人工批准","source":None}
            if statement:
                choices=[i for i,c in enumerate(statement.columns) if
                         (selection=='current' and c.role=='current' and c.value_year==source_year) or
                         (selection=='opening' and ((c.role=='opening' and c.value_year==year) or
                                                   (c.role=='prior' and c.value_year==year-1))) or
                         (selection=='prior' and c.role=='prior' and c.value_year==year-1)]
                column=choices[0] if len(choices)==1 else None
                rows = [r for r in statement.rows if r.canonical_metric == canonical]
                item['reason'] = "原表缺少该指标、映射或期间列不唯一"
                if len(rows)==1 and column is not None:
                    col = statement.columns[column]
                    row = rows[0]
                    if row.values[column] is not None and statement.currency and statement.scale:
                        sign=-1 if canonical in ('cost_of_sales','capex') and dataset.extraction_profile.get('outflow_signs',{}).get(canonical)=='negative' else 1
                        amount=row.values[column]*statement.scale*sign
                        if canonical in ('cost_of_sales','capex') and amount<0:
                            item['reason']='支出为负且与配置口径不符；请核实 outflow_signs 后重新提取并审核，不直接猜取绝对值'
                        else:
                            item.update(value=str(amount),reason="",
                                source={"statement_id":statement.statement_id,"row_id":row.row_id,
                                        "column":column,"currency":statement.currency,"scale":str(statement.scale),"sign":sign})
                    else:
                        item['reason']="原单元格空白、单位缺失或期初/比较年度不匹配"
            annual[metric]=item
        inputs[str(year)]=annual
        for name,expr,fmt,positive,definition in RECIPES:
            required=expression_inputs(expr)
            missing=[annual[k]['label']+"："+annual[k]['reason'] for k in sorted(required) if annual[k]['value'] is None]
            value=None
            reasons=missing
            if not missing:
                currencies={annual[k]['source']['currency'] for k in required}
                vals={k:Decimal(annual[k]['value']) for k in required}
                bad=[annual[k]['label'] for k in positive if vals[k]<=0]
                if len(currencies)>1: reasons=["输入币种不同，未进行外汇换算"]
                elif bad: reasons=["分母或同比基数非正："+"、".join(bad)]
                else:
                    try: value=str(evaluate(expr,vals))
                    except (ArithmeticError,ValueError): reasons=["分母为零或计算输入无效"]
            results.append({"year":year,"name":name,"expression":expr,"format":fmt,
                "definition":definition,"value":value,"reason":"；".join(reasons),"positive":positive})
    cagr={"name":"营业收入 CAGR","value":None,"reason":"需要全部连续年度收入已批准且起止收入为正"}
    if len(years)>1 and years==list(range(min(years),max(years)+1)):
        relevant=[inputs[str(y)]['revenue'] for y in years]
        if all(x['value'] is not None for x in relevant) and len({x['source']['currency'] for x in relevant})==1:
            first,last=Decimal(relevant[0]['value']),Decimal(relevant[-1]['value'])
            if first>0 and last>0:
                cagr.update(value=str((last/first)**(Decimal(1)/(years[-1]-years[0]))-1),reason="")
    result={"dataset_fingerprint":dataset.fingerprint,"status":"approved" if len(effective)==len(dataset.statements) else "needs_human_review",
        "approved_statements":len(effective),"total_statements":len(dataset.statements),
        "years":years,"inputs":inputs,"results":results,"cagr":cagr,
        "unavailable":[{"name":n,"reason":r} for n,r in [
            ("EBITDA margin","尚未从附注核实完整折旧、摊销及 EBITDA 定义。"),
            ("利息保障倍数","财务费用净额和金融子公司利息支出不能替代统一口径的利息费用。"),
            ("有息负债率","仅保留资产负债率；尚未核实全部有息负债组成项和租赁口径。"),
            ("PE / PB / EV multiples","仅输入年报，缺少估值日股价与市场价值。")]]}
    if isinstance(review,SystemValidation):
        result.update(status='validated',validation_method='system',validated_statements=len(effective),approved_statements=0)
        result['cagr']['reason']=result['cagr']['reason'].replace('已批准','通过系统校验')
    return result
