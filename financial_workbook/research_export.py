"""Portable XLSX artifacts for peers and user-confirmed valuation models."""
from decimal import Decimal
from pathlib import Path
import json


def _workbook(output):
    import xlsxwriter
    output=Path(output)
    if output.exists(): raise ValueError('输出已存在，不能覆盖历史结果。')
    output.parent.mkdir(parents=True,exist_ok=True)
    book=xlsxwriter.Workbook(output,{'strings_to_formulas':False,'strings_to_urls':False})
    formats={'header':book.add_format({'bold':True,'bg_color':'#203B58','font_color':'white','text_wrap':True}),
             'number':book.add_format({'num_format':'#,##0.00;(#,##0.00);0.00'}),
             'percent':book.add_format({'num_format':'0.00%'}),
             'text':book.add_format({'text_wrap':True,'valign':'top'})}
    return book,formats


def _sheet(book,formats,name,headers,rows):
    sheet=book.add_worksheet(name); sheet.freeze_panes(1,0)
    sheet.set_column(0,len(headers)-1,23); sheet.set_default_row(22)
    sheet.write_row(0,0,headers,formats['header']); sheet.set_row(0,30)
    for row_index,row in enumerate(rows,1):
        for col,value in enumerate(row):
            if isinstance(value,(dict,list)): value=json.dumps(value,ensure_ascii=False)
            if isinstance(value,Decimal): sheet.write_number(row_index,col,float(value),formats['number'])
            elif value is not None: sheet.write(row_index,col,value,formats['text'])
    if rows: sheet.autofilter(0,0,len(rows),len(headers)-1)
    return sheet


def export_comparison(result: dict, output: Path):
    book,fmt=_workbook(output)
    try:
        _sheet(book,fmt,'可比数据',['公司','年度','项目','原币基本单位或小数比率','类型','缺失原因'],
            [[r['company_id'],r['year'],r['metric'],Decimal(r['value']) if r['value'] is not None else None,
              r['format'],r['reason']] for r in result['rows']])
        chart_data=book.add_worksheet('图表数据'); chart_data.freeze_panes(1,1)
        overview=book.add_worksheet('横向比较'); overview.set_column('A:N',13)
        overview.write('A1','仅比较所选公司共同年度；金额为亿 '+result['currency'])
        chart_row=0
        definitions=[('revenue','营业收入趋势',False),('net_income','合并净利润趋势',False),
                     ('净利率','净利率',True),('资产负债率','资产负债率',True)]
        for metric,title,percent in definitions:
            chart_data.write_row(chart_row,0,['年度',*result['company_ids']],fmt['header'])
            for index,year in enumerate(result['years'],chart_row+1):
                chart_data.write(index,0,year)
                for col,company in enumerate(result['company_ids'],1):
                    row=next(r for r in result['rows'] if r['company_id']==company and r['year']==year and r['metric']==metric)
                    if row['value'] is not None:
                        value=Decimal(row['value'])/(1 if percent else Decimal(10**8))
                        chart_data.write_number(index,col,float(value),fmt['percent' if percent else 'number'])
            chart=book.add_chart({'type':'line'})
            for col,company in enumerate(result['company_ids'],1):
                chart.add_series({'name':company,'categories':['图表数据',chart_row+1,0,chart_row+len(result['years']),0],
                    'values':['图表数据',chart_row+1,col,chart_row+len(result['years']),col],'marker':{'type':'circle','size':5}})
            chart.set_title({'name':title}); chart.set_y_axis({'num_format':'0%' if percent else '#,##0.0'})
            chart.set_legend({'position':'bottom'}); chart.show_blanks_as('gap')
            overview.insert_chart(3+definitions.index((metric,title,percent))//2*17,
                                  definitions.index((metric,title,percent))%2*7,chart,{'x_scale':.86,'y_scale':.9})
            chart_row+=len(result['years'])+3
        _sheet(book,fmt,'收入指数',['公司','年度','基准年','收入指数 基准100','缺失原因'],
            [[r['company_id'],r['year'],r['base_year'],Decimal(r['revenue_index']) if r['revenue_index'] is not None else None,r['reason']] for r in result['revenue_index']])
        _sheet(book,fmt,'样本统计',['年度','项目','有效样本数','选择公司数','中位数','说明'],
            [[r['year'],r['metric'],r['count'],r['selected_count'],Decimal(r['median']) if r['median'] is not None else None,r['label']] for r in result['sample_statistics']])
        _sheet(book,fmt,'来源与口径',['项目','记录'],[['限制',x] for x in result['limitations']]+[['来源快照',r] for r in result['snapshots']])
    finally: book.close()


def export_valuation(result: dict, assumptions: dict, output: Path):
    book,fmt=_workbook(output)
    try:
        summary=_sheet(book,fmt,'估值汇总',['情景','WACC','经营资产价值','权益价值','每股模型价值','终值占比'],[
            [s['name'],Decimal(s['discount_rate']['wacc']),Decimal(s['valuation']['operating_value']),
             Decimal(s['valuation']['equity_value']),Decimal(s['valuation']['per_share_value']) if s['valuation']['per_share_value'] is not None else None,
             Decimal(s['valuation']['terminal_share_of_operating_value']) if s['valuation']['terminal_share_of_operating_value'] is not None else None]
            for s in result['scenarios']])
        summary.set_column('B:B',18,fmt['percent']); summary.set_column('F:F',18,fmt['percent'])
        heads=['情景','年度','收入','EBIT','现金税','NOPAT','折旧摊销','资本支出','期初经营NWC','期末经营NWC','NWC变动','FCFF','折现因子','FCFF现值']
        keys=['year','revenue','ebit','cash_tax','nopat','depreciation','capex','opening_operating_nwc',
              'operating_nwc','change_in_operating_nwc','fcff','discount_factor','pv_fcff']
        forecast=_sheet(book,fmt,'预测明细',heads,
            [[s['name'],*[r[k] if k=='year' else Decimal(r[k]) for k in keys]] for s in result['scenarios'] for r in s['forecast']])
        chart=book.add_chart({'type':'line'}); row=1
        for s in result['scenarios']:
            last=row+len(s['forecast'])-1
            chart.add_series({'name':s['name'],'categories':['预测明细',row,1,last,1],
                              'values':['预测明细',row,11,last,11],'marker':{'type':'circle','size':5}})
            row=last+1
        chart.set_title({'name':'用户假设下的预测 FCFF'}); chart.set_y_axis({'name':result['currency']+' 基本单位'})
        summary.insert_chart('A8',chart)
        _sheet(book,fmt,'终值与桥接',['情景','项目','值'],
            [[s['name'],k,Decimal(v) if v is not None else None] for s in result['scenarios'] for k,v in s['valuation'].items()]+
            [['共享桥接',k,v] for k,v in assumptions['bridge'].items()])
        sensitivity=_sheet(book,fmt,'敏感性',['情景','WACC','长期增长率','权益价值','每股模型价值','原因'],
            [[s['name'],Decimal(r['wacc']),Decimal(r['growth']),Decimal(r['equity_value']) if r['equity_value'] is not None else None,
              Decimal(r['per_share_value']) if r['per_share_value'] is not None else None,r['reason']]
             for s in result['scenarios'] for r in s['sensitivity']])
        sensitivity.conditional_format(1,4,sum(len(s['sensitivity']) for s in result['scenarios']),4,{'type':'3_color_scale'})
        _sheet(book,fmt,'用户确认参数',['字段','已确认值'],list(assumptions.items()))
        _sheet(book,fmt,'公式与依据',['项目','内容'],list(result['formulas'].items())+
            [['方法来源',s] for s in result['method_sources']]+[['适用限制',x] for x in result['limitations']])
        _sheet(book,fmt,'条件性结论',['情景','说明'],[[s['name'],x] for s in result['scenarios'] for x in s['observations']])
        _sheet(book,fmt,'情景区间',['说明'],[[x] for x in result.get('conclusions',[])])
    finally: book.close()
