# 订单看板动态服务

数据仍来自当前共享汇总 Excel。`main.py` 复用现有业务模块，生成不可变数据批次。服务读取生成结果，不在浏览器请求中读取 Excel。

## 本地使用

在 `generate_html` 目录执行（使用项目 Python 环境）：

```powershell
python -m pip install -r requirements.txt
python main.py
```

使用共享 `Project/.venv` 时，也在该环境中执行安装命令，以 `requirements.txt` 声明的服务依赖版本为准。

默认生成后启动后台服务，并通过 `http://127.0.0.1:8766/` 打开页面。后台日志位于项目 `output_file/log/order_server.log`。已运行相同数据目录的服务会复用。

分开生成与运行：

```powershell
python main.py --check --no-open
python server.py --host 127.0.0.1 --port 8766
```

`--check` 遇到数据校验警告返回非零；无生成错误时仍发布完整数据。生成错误不会切换当前批次。更新 Excel 后重新运行生成命令；服务无需重启，刷新网页获取新批次。已经打开的网页继续使用原批次，确保看板、底表和导出一致。

网页需通过服务网址访问；不能再通过双击生成的 HTML 离线使用。保留的离线渲染函数仅供历史测试与明确的离线调用。

## 数据和接口

- `output_file/runtime/current.json`：已完成批次指针，最后原子替换。
- `output_file/runtime/datasets/<dataset_id>/`：看板、底表与原始 XLSX 快照。旧批次保留供已打开的网页读取。
- `output_file/runtime/index.html`、`assets/`：服务读取的页面入口和资源，资源文件名带内容哈希。生成器只在 runtime 中输出入口，根目录与旧入口内容完全一致的重复 HTML 会在成功发布后清理。
- `data/order_dashboard/annotations.sqlite3`：共享批注，服务重启和生成 Excel 批次不会覆盖；可用 `--state-dir` 指向持久目录。备份应在停止服务后复制数据库。

HTTP 仅公开页面、资源和业务接口，不挂载整个数据目录。看板按主体和模块请求；底表后台搜索分页；CSV 导出当前搜索的全部匹配记录；Excel 下载该批次的原始文件，保留格式、公式和全部 Sheet。

批注的集团范围作用到所有品牌和车型，品牌范围作用到自身及所属车型；车型范围仅作用到自身。数据库保存修改时间、版本和连接来源，同一条批注并发修改返回冲突，避免后保存者覆盖前一次修改。显示/隐藏偏好仍属于本地浏览器。服务不提供实名登录，来源记录不等于个人身份；部门访问控制由部署入口提供，不能直接信任浏览器自报的用户头。

接口均在应用前缀内：`api/catalog`、`api/dashboard`、`api/raw`、`api/export/csv`、`api/workbook`、`api/annotations`。健康检查为 `health`，含 `application=order-dashboard` 和数据批次。允许同源 iframe，页面与接口支持 HEAD。

## 门户与正式发布

门户公共入口保持 `/orderiq/`，代理转发到独立订单服务，并剥除该前缀。页面资源、请求及下载使用相对路径，不抢占站点根 `/api/`。反代须保留公共 Host/Origin；服务使用 `--allowed-host` 显式允许门户域名。默认允许 localhost 和 127.0.0.1。HTTPS 反代同时显式设置 `--allowed-origin https://<门户域名>`，不要信任客户端传入的代理身份头。本地服务没有 Windows 身份认证。

生成经过验证的服务发布目录：

```powershell
python package_release.py --output ../../releases/order-dashboard-v1
```

发布目录含服务代码、依赖清单及同版前端，拒绝覆盖已有目录，不包含原始业务数据、数据快照或批注数据库。可交给门户的 `New-AppRelease.ps1` 封装，类型 service、入口 server.py、dataMode external、healthPath /health。

从发布目录启动时显式传入绝对持久路径与当前版本 web 目录：

```powershell
python server.py --data-dir <持久数据目录/runtime> --state-dir <持久批注目录> --web-dir ./web --allowed-host <门户域名> --host 127.0.0.1 --port 8766
```

服务默认路径仅方便开发，发布运行必须显式配置。持久数据目录不得放入发布版本目录或静态站点根。首次部署从已验证输出复制完整数据快照目录；升级复用原持久路径，不用新包覆盖批注数据。停止旧订单服务，切换同版前后端，使用相同持久路径启动并验收。门户、其他应用不需要随之停止。此仓库不自动安装 Windows 服务或修改 IIS。

验收包括主体/模块/粒度切换、来源跳转、底表搜索分页、CSV/XLSX 下载、两个浏览器间共享批注、继承范围、重启持久化及旧批次查询。业务数据、数据库、发布产物与日志不得提交 Git。
