"""Real FastAPI + browser coverage; Browser plugin not available, use Playwright."""
from test_visual_smoke import browser, live_admin_fastapi_base_url, vite_live_admin_api_base_url
from playwright.sync_api import expect
from pathlib import Path
import pytest


@pytest.mark.parametrize('width', [390, 1440])
def test_store_search_multi_select_import_and_save(browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, width):
    context = browser.new_context(viewport={'width': width, 'height': 900})
    context.add_cookies([{'name': 'dy_e2e_role', 'value': 'highest_admin', 'url': live_admin_fastapi_base_url}])
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(vite_live_admin_api_base_url + '/admin/accounts')
        expect(page.get_by_role('heading', name='新建账号', exact=True)).to_be_visible()
        page.get_by_role('button', name='门店权限 · 已选 0 家').click()
        dialog = page.get_by_role('dialog')
        search = dialog.get_by_placeholder('输入名称关键词或部分 ID')
        search.fill('深圳')
        expect(dialog.locator('.account-scope-row')).to_have_count(1)
        dialog.locator('.account-scope-row input').check()
        search.fill('store-')
        expect(dialog.locator('.account-scope-row')).to_have_count(2)
        dialog.get_by_role('button', name='全选搜索结果').click()
        expect(dialog.locator('.account-scope-row input:checked')).to_have_count(2)
        search.fill('杭州')
        expect(dialog.locator('.account-scope-row input')).to_be_checked()
        output = Path('output/account-scope'); output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f'stores-{width}.png'), full_page=True)
        dialog.get_by_role('button', name='完成选择（2 家）').click()
        page.get_by_label('批量导入门店', exact=True).set_input_files({'name': 'stores.csv', 'mimeType': 'text/csv', 'buffer': '门店ID,门店名称\nstore-1,深圳临港认证服务店\nstore-1,深圳临港认证服务店\nmissing,错误\n'.encode('utf-8-sig')})
        expect(page.get_by_text('匹配 1 家 · 去重 1 行 · 错误 1 行')).to_be_visible()
        expect(page.get_by_role('button', name='确认加入已选门店')).to_be_disabled()
        page.get_by_label('批量导入门店', exact=True).set_input_files({'name': 'stores.csv', 'mimeType': 'text/csv', 'buffer': b'storeId\nstore-1\n'})
        expect(page.get_by_role('button', name='确认加入已选门店')).to_be_enabled()
        page.get_by_role('button', name='确认加入已选门店').click()
        page.get_by_label('显示名称', exact=True).fill(f'多选验证{width}')
        page.get_by_label('密码', exact=True).fill('AccountTest123!')
        page.get_by_label('确认密码', exact=True).fill('AccountTest123!')
        page.locator('form.account-form button[type=submit]').click()
        with page.expect_response(lambda response: response.url.endswith('/admin/accounts') and response.request.method == 'POST') as saved:
            page.get_by_role('button', name='确认创建', exact=True).click()
        assert saved.value.status == 200, saved.value.text()
        assert len(saved.value.json()['data']['stores']) == 2
        rows = context.request.get(live_admin_fastapi_base_url + '/api/v1/admin/accounts').json()['data']['rows']
        assert len(next(row for row in rows if row['display_name'] == f'多选验证{width}')['stores']) == 2
        assert not errors
    finally:
        context.close()


def test_bulk_account_import_real_api(browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url):
    from test_account_bulk_import import workbook
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    context.add_cookies([{'name': 'dy_e2e_role', 'value': 'highest_admin', 'url': live_admin_fastapi_base_url}])
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + '/admin/accounts')
        expect(page.get_by_role('heading', name='批量开通账号', exact=True)).to_be_visible()
        content = workbook([['bulk-browser-001', '批量开通验证', '门店账号', '', '', '', '', 'store-1;store-2']])
        page.get_by_label('上传账号开通表', exact=True).set_input_files({'name': 'accounts.xlsx', 'mimeType': 'application/octet-stream', 'buffer': content})
        expect(page.get_by_text('可开通 1 个 · 错误 0 行。确认前不会创建账号。')).to_be_visible()
        page.get_by_role('button', name='确认批量创建 1 个账号').click()
        link = page.get_by_role('link', name='下载第 1 批开通结果（1 个账号，含初始密码）')
        expect(link).to_be_visible()
        with page.expect_download() as download:
            link.click()
        assert download.value.suggested_filename.endswith('.xlsx')
        rows = context.request.get(live_admin_fastapi_base_url + '/api/v1/admin/accounts').json()['data']['rows']
        assert len(next(row for row in rows if row['username'] == 'bulk-browser-001')['stores']) == 2
    finally:
        context.close()


def test_org_picker_does_not_require_group_for_service_hierarchy(browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url):
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    context.add_cookies([{'name': 'dy_e2e_role', 'value': 'highest_admin', 'url': live_admin_fastapi_base_url}])
    page = context.new_page()
    catalog = [{'store_id': f'org-{i}', 'store_name': f'门店{i}', 'group_name': group, 'service_center_name': '共同中心', 'district_name': '共同大区', 'area_name': '共同区域'} for i, group in enumerate(['集团甲', '集团乙'])]
    page.route('**/api/v1/admin/account-store-catalog', lambda route: route.fulfill(json={'data': {'stores': catalog}}))
    try:
        page.goto(vite_live_admin_api_base_url + '/admin/accounts')
        def choose(label, option):
            page.get_by_label(label, exact=True).click()
            page.get_by_role('option', name=option, exact=True).click()
        choose('角色', '管理员')
        choose('数据可见范围', '区域')
        expect(page.get_by_label('集团', exact=True)).to_have_count(0)
        choose('服务中心', '共同中心')
        choose('大区', '共同大区')
        choose('区域', '共同区域')
        expect(page.get_by_text('当前覆盖 2 家门店，门店归属调整后自动更新。')).to_be_visible()
        choose('数据可见范围', '集团')
        expect(page.get_by_label('服务中心', exact=True)).to_have_count(0)
        choose('集团', '集团甲')
        expect(page.get_by_text('当前覆盖 1 家门店，门店归属调整后自动更新。')).to_be_visible()
    finally:
        context.close()
