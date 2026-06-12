# 抖音号明细 Edge 自动导出

当前抖音来客后台的“抖音号明细 / 子机构经营号”没有可用开放 API 时，可以用 Edge 浏览器自动化完成后台导出，再接入现有 XML 解析脚本。

## 0. 云端生产方案

生产环境建议部署在 Windows 云服务器或带桌面能力的受控服务器上。浏览器下载文件只作为任务临时文件，不作为长期主数据源；任务成功后将“抖音号明细”写入数据库表 `raw_aweme_bindings`，并删除临时 Excel、CSV 和解压目录。

生产链路：

```text
服务器定时任务
  -> Edge 复用已登录用户目录
  -> 抖音来客后台点击导出
  -> 临时下载 Excel
  -> 解析 sheet1.xml
  -> 写入数据库 raw_aweme_bindings
  -> 清理临时文件
```

数据库连接通过环境变量配置，不提交到 Git：

```powershell
$env:DY_DATA_DATABASE_URL = "postgresql+psycopg://USER:PASS@HOST:5432/dy_data"
```

MySQL 也可以使用：

```powershell
$env:DY_DATA_DATABASE_URL = "mysql+pymysql://USER:PASS@HOST:3306/dy_data?charset=utf8mb4"
```

服务器自动导出并入库：

```powershell
python scripts\exports\auto_export_backend_aweme_edge.py --import-db --delete-local-after-db
```

注册为 Windows 云服务器每日任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\tasks\setup_backend_aweme_cloud_export_task.ps1 -RunAt 08:30 -DatabaseUrl "postgresql+psycopg://USER:PASS@HOST:5432/dy_data"
```

如果不想在命令历史中出现数据库密码，也可以先在服务器环境变量里配置 `DY_DATA_DATABASE_URL`，再注册任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\tasks\setup_backend_aweme_cloud_export_task.ps1 -RunAt 08:30
```

也可以用环境变量固定为服务器模式：

```powershell
$env:DY_DATA_IMPORT_BACKEND_AWEME_TO_DB = "1"
$env:DY_DATA_DELETE_BACKEND_AWEME_FILES_AFTER_DB = "1"
python scripts\exports\auto_export_backend_aweme_edge.py
```

入库表：

```text
raw_aweme_bindings
job_runs
```

`raw_aweme_bindings.binding_key` 会按“抖音 id + 所属账户 id + POI id + 抖音昵称”生成，重复导出会先删除同 key 旧行再写入新行，避免重复插入。`job_runs` 记录每次任务状态和成功条数。

## 1. 首次登录与页面定位

自动化脚本使用独立 Edge 用户目录，首次需要人工登录一次：

```powershell
python scripts\exports\auto_export_backend_aweme_edge.py --setup-only --manual-wait-seconds 180
```

运行后会打开 Edge。请在窗口中登录抖音来客后台，并手动进入“抖音号明细 / 子机构经营号”页面。脚本会保存最终 URL 到配置项 `field_probe_dir` 下：

```text
<field_probe_dir>/backend_aweme_page_url.txt
```

后续运行会优先使用这个 URL。

## 2. 自动点击导出并解析

页面 URL 保存后，运行：

```powershell
python scripts\exports\auto_export_backend_aweme_edge.py
```

脚本会尝试查找“导出 / 下载”按钮，等待 Excel 下载完成，并保存到：

```text
<field_probe_dir>/抖音号明细-自动导出.xlsx
```

随后会解压 Excel，调用现有脚本生成：

```text
<field_probe_dir>/来客后台抖音号明细_XML解析.csv
```

## 3. 如果按钮识别失败

脚本会输出调试文件到：

```text
<field_probe_dir>/browser_export_debug/
```

其中包含页面截图和可点击元素文本。根据这些信息可以通过环境变量指定更精确的按钮选择器：

```powershell
$env:DOUYIN_AWEME_EXPORT_SELECTOR = "button:has-text('导出')"
python scripts\exports\auto_export_backend_aweme_edge.py
```

## 4. 关于已打开的 Edge 登录态

普通 Edge 已经打开时，Playwright 不能直接接管这个窗口，除非该 Edge 是用远程调试端口启动的。因此推荐使用脚本自带的独立自动化用户目录，并在里面登录一次。后续只要登录态未过期，就可以定时复用。

如果必须复用默认 Edge 用户目录，需要先完全关闭 Edge，再用自动化方式启动默认目录；这个方式对日常使用干扰更大，不作为默认方案。
