"""Standard account onboarding workbook: parse, validate and export credentials."""
from io import BytesIO
from itertools import islice
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule

HEADERS = ['登录账号', '显示名称', '账号类型', '集团', '服务中心', '大区', '区域', '门店ID（多个用英文分号分隔）', '所属账户编号（选填）']
INITIAL_ACCOUNT_PASSWORD = '123456'
TYPES = {'最高管理员': None, '管理员': None, '集团账号': 'group', '服务中心账号': 'service_center', '大区账号': 'district', '区域账号': 'area', '门店账号': 'store'}


def _save(book):
    for sheet in book:
        sheet.freeze_panes = 'A2'
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='9B461C')
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        for column in 'ABCDEFGHI':
            sheet.column_dimensions[column].width = 25
        sheet.row_dimensions[1].height = 36
        if sheet.title == '填写说明':
            for column in 'ABCDEFGH':
                sheet.column_dimensions[column].width = 17
            sheet.column_dimensions['A'].width = 22
            for number in range(1, sheet.max_row + 1):
                sheet.row_dimensions[number].height = 40
    output = BytesIO(); book.save(output)
    return output.getvalue()


def account_template(catalog=None):
    book = Workbook(); sheet = book.active; sheet.title = '账号开通'
    sheet.append(HEADERS)
    for row in range(2, 202):
        for column in (1, 8, 9):
            sheet.cell(row, column).number_format = '@'
    choices = DataValidation(type='list', formula1='"' + ','.join(TYPES) + '"', allow_blank=False)
    choices.errorTitle = '请选择账号类型'; choices.error = '请使用下拉列表中的账号类型'; choices.showErrorMessage = True
    sheet.add_data_validation(choices); choices.add('C2:C201')
    guide = book.create_sheet('填写说明')
    guide.append(['账号类型', '登录账号', '显示名称', '集团', '服务中心', '大区', '区域', '门店ID'])
    required = {
        '集团账号': {'集团'}, '服务中心账号': {'服务中心'}, '大区账号': {'服务中心', '大区'},
        '区域账号': {'服务中心', '大区', '区域'}, '门店账号': {'门店ID'}, '管理员': set(), '最高管理员': set(),
    }
    for kind, names in required.items():
        guide.append([kind, '必填', '必填', *['必填' if name in names else '留空' for name in ['集团', '服务中心', '大区', '区域', '门店ID']]])
        for cell in guide[guide.max_row][1:]:
            cell.fill = PatternFill('solid', fgColor='E9F3E7' if cell.value == '必填' else 'F2F2F2')
    notes = [
        ('填写顺序', '先看上方必填表，再打开“账号开通”填写；每行一人，最多200人。账号类型从下拉列表选择。'),
        ('组织关系', '集团与服务中心互不隶属。大区、区域属于“服务中心→大区→区域”这条路径。'),
        ('登录账号 / 名称', '建议登录账号用手机号或英文账号；显示名称填真实姓名或岗位名称。账号必须唯一。'),
        ('组织名称', '填写系统完整名称，可从“可选门店”复制。区域账号须同时填服务中心、大区，避免同名区域混淆。'),
        ('门店ID', '仅门店账号填写；多个ID用英文分号分隔，如00123;00456。不要填门店名称，ID按文本填写。'),
        ('所属账户编号', '所有类型都可留空。不清楚含义就留空；它不是登录账号，也不是门店ID。填写时必须唯一。'),
        ('密码', f'无需填写。初始密码统一为{INITIAL_ACCOUNT_PASSWORD}；开通后在“我的→修改密码”自行修改。'),
        ('怎么交表', '填完后把原xlsx发回管理员。只导入“账号开通”；示例表不导入，不要改表头或工作表名称。'),
        ('发现错误', '先校验再开通；错误按行号和原因提示。任一行有误整批不创建，修正后再上传，不覆盖已有账号。'),
        ('权限提醒', '管理员及最高管理员是全局权限；组织管理人员请选对应组织账号类型。三个打榜指标始终全量可见。'),
        ('先看示例', '“示例（不导入）”展示各类型正确填法，请替换示例名称。创建成功后可下载含初始密码的开通结果。'),
    ]
    for number, (label, note) in enumerate(notes, 10):
        guide.cell(number, 1, label)
        guide.merge_cells(start_row=number, start_column=2, end_row=number, end_column=8)
        guide.cell(number, 2, note)
    for column, formula in {
        'D': '$C2="集团账号"', 'E': 'OR($C2="服务中心账号",$C2="大区账号",$C2="区域账号")',
        'F': 'OR($C2="大区账号",$C2="区域账号")', 'G': '$C2="区域账号"', 'H': '$C2="门店账号"',
    }.items():
        sheet.conditional_formatting.add(f'{column}2:{column}201', FormulaRule(formula=[f'AND($C2<>"",{formula})'], fill=PatternFill('solid', fgColor='E9F3E7')))
        sheet.conditional_formatting.add(f'{column}2:{column}201', FormulaRule(formula=[f'AND($C2<>"",NOT({formula}))'], fill=PatternFill('solid', fgColor='F2F2F2')))
    examples = book.create_sheet('示例（不导入）'); examples.append(HEADERS)
    for values in [
        ['group_zhang', '张经理', '集团账号', '示例集团', '', '', '', '', ''],
        ['center_li', '李经理', '服务中心账号', '', '示例中心', '', '', '', ''],
        ['district_wang', '王经理', '大区账号', '', '示例中心', '示例大区', '', '', ''],
        ['area_zhao', '赵经理', '区域账号', '', '示例中心', '示例大区', '示例区域', '', ''],
        ['store_qian', '钱店长', '门店账号', '', '', '', '', '00123;00456', ''],
    ]: examples.append(values)
    options = book.create_sheet('可选门店'); options.append(['门店ID', '门店名称', '集团', '服务中心', '大区', '区域'])
    for store in catalog or []:
        options.append([store.get(key, '') for key in ['store_id', 'store_name', 'group_name', 'service_center_name', 'district_name', 'area_name']])
    data = _save(book)
    return data


def read_account_rows(content: bytes, filename: str):
    if len(content) > 5 * 1024 * 1024 or not filename.lower().endswith('.xlsx'):
        raise ValueError('请上传不超过5MB的xlsx账号开通模板')
    try:
        with ZipFile(BytesIO(content)) as archive:
            if sum(row.file_size for row in archive.infolist()) > 30 * 1024 * 1024:
                raise ValueError('Excel内容过大，请使用标准模板')
        book = load_workbook(BytesIO(content), read_only=True, data_only=False)
        try:
            sheet = book['账号开通']; sheet.reset_dimensions()
            rows = list(islice(sheet.iter_rows(min_col=1, max_col=9, values_only=True), 202))
        finally: book.close()
    except (BadZipFile, KeyError, OSError, ParseError, TypeError) as exc:
        raise ValueError('无法读取“账号开通”工作表，请使用标准xlsx模板') from exc
    if not rows or list(rows[0]) != HEADERS:
        raise ValueError('表头不匹配，请使用最新账号开通模板，不要修改表头')
    if len(rows) > 201:
        raise ValueError('每批最多200个账号，请拆分表格')
    return [(number, row) for number, row in enumerate(rows[1:], 2) if any(value is not None and str(value).strip() for value in row)]


def credential_workbook(rows):
    book = Workbook(); sheet = book.active; sheet.title = '账号开通结果'
    sheet.append(['登录账号', '显示名称', '账号类型', '初始密码', '数据可见范围'])
    for row in rows: sheet.append(row)
    return _save(book)
