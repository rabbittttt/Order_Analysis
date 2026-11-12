# 订单看板动态服务

数据来自当前汇总 Excel，默认输入为项目 `output_file`。后台自动检查文件变化，由独立低优先级进程复用现有业务模块，生成不可变数据批次；HTTP 请求只读取已完成数据，不解析 Excel。

## 本地使用

双击 `scripts/启动订单分析.cmd` 启动或复用后台服务，并通过浏览器打开看板。后台运行期间自动同步 Excel，无需反复运行 `main.py`。启动器检查 Excel 读取与动态服务依赖，使用共享 Python 或 `ORDER_ANALYSIS_PYTHON` 指定的解释器。

在 `generate_html` 目录执行（使用项目 Python 环境）：

```powershell
python -m pip install -r requirements.txt
python server.py --open
```

使用共享 `Project/.venv` 时，也在该环境中执行安装命令，以 `requirements.txt` 声明的服务依赖版本为准。

通过 `http://127.0.0.1:8767/` 打开页面。后台日志位于项目 `output_file/log/order_server.log`，自动处理日志为 `auto_sync.log` 及每批 `generate_html_*.log`。相同代码、输入/数据目录和同步间隔的运行服务会复用；升级代码后需先停止旧订单服务，再启动新版本。首次没有数据时页面自动等待，已有数据立即展示。

手动重建/检查（排错时使用）与直接运行：

```powershell
python main.py --check --no-open
python server.py --host 127.0.0.1 --port 8767
```

`--check` 遇到数据校验警告返回非零；无生成错误时仍发布完整数据。生成错误不会切换当前批次。Excel 更新后由后台自动处理；网页可见时，前台每 15 秒检查一次版本；隐藏时暂停，切回或聚焦时立即检查。发现新版本后，预加载当前看板成功后统一切换，看板、底表和导出保持同一批次。保留主体、标签、粒度、周期以及底表搜索和分页；批注编辑中延后切换，提交/取消后关闭编辑器即可同步。顶部不显示生成时间，异常时才显示简短状态。

网页需通过服务网址访问；不能再通过双击生成的 HTML 离线使用。保留的离线渲染函数仅供历史测试与明确的离线调用。

## 自动同步配置

- 空闲时每 **300 秒（5 分钟）**检查文件名、大小、修改时间等元数据；发现变化后等待 **60 秒（1 分钟）**复查，仍在变化则重新等待。稳定确认是额外的一次检查，无需再等 5 分钟。
- 启动时立即检查一次；无变化不解析 Excel。构建不设 30 秒或 5 分钟的完成时限；一个任务运行期间不再启动第二个，结束后检查最新输入，连续多次改动合并。
- 输入优先级：`--input` > `ORDER_DASHBOARD_INPUT` > 显式 `SHARED_DATA_ROOT/订单汇总` > 项目 `output_file`。不再因为同级共享目录存在而静默切换。使用共享目录时仍只读。
- 只检查输入目录顶层 `.xlsx`，忽略 `~$` 临时文件、已迁出销量汇总、日志及 runtime；阶段身份表随订单输入一起复制。
- 先复制独立输入快照，复制前后校验文件状态；文件损坏、被占用、读取不完整或计算失败都不切换当前批次，下个检查周期自动重试。
- 可选批次标记：输入目录存在 `orders.ready` 时，必须在本轮所有 Excel 保存/复制完成后最后更新此文件；标记时间早于任一 Excel 时等待。没有标记则按上述稳定窗口判断。
- `--check-seconds 300 --stable-seconds 60` 可调整间隔；`--no-sync` 只服务已有数据。后台停止或电脑关机期间不检查，重新启动后会检查当前文件。
- 每个 runtime 只允许一个自动调度器；自动处理和手动 `main.py` 共用跨进程构建锁。Windows 计算进程使用低于正常的优先级，仍需要足够内存容纳完整输入。
- 历史数据批次保留以供进行中的导出或旧页面读取；此版本不自动清理历史批次。

## 数据和接口

- `output_file/runtime/current.json`：已完成批次指针，最后原子替换。
- `output_file/runtime/datasets/<dataset_id>/`：每次写入唯一目录，保存看板、底表与原始 XLSX 快照。全部文件和页面完成后原子写入 catalog.json，再切换 current.json；发布过程使用文件替换，兼容 Windows 拒绝重命名非空目录的环境。旧批次保留供已打开的网页读取。
- `output_file/runtime/index.html`、`assets/`：服务读取的页面入口和资源，资源文件名带内容哈希。生成器只在 runtime 中输出入口，根目录与旧入口内容完全一致的重复 HTML 会在成功发布后清理。
- `data/order_dashboard/annotations.sqlite3`：共享批注，服务重启和生成 Excel 批次不会覆盖；可用 `--state-dir` 指向持久目录。备份应在停止服务后复制数据库。

HTTP 仅公开页面、资源和业务接口，不挂载整个数据目录。看板按主体和模块请求；底表后台搜索分页；CSV 导出当前搜索的全部匹配记录；Excel 下载该批次的原始文件，保留格式、公式和全部 Sheet。

批注的集团范围作用到所有品牌和车型，品牌范围作用到自身及所属车型；车型范围仅作用到自身。数据库保存修改时间、版本和连接来源，同一条批注并发修改返回冲突，避免后保存者覆盖前一次修改。显示/隐藏偏好仍属于本地浏览器。服务不提供实名登录，来源记录不等于个人身份；部门访问控制由部署入口提供，不能直接信任浏览器自报的用户头。

接口均在应用前缀内：`api/catalog`、`api/dashboard`、`api/raw`、`api/export/csv`、`api/workbook`、`api/annotations`、`api/sync`。健康检查为 `health`，含 `application=order-dashboard` 和数据批次。允许同源 iframe，页面与接口支持 HEAD。

## 门户与正式发布

门户公共入口保持 `/orderiq/`，代理转发到独立订单服务，并剥除该前缀。页面资源、请求及下载使用相对路径，不抢占站点根 `/api/`。反代须保留公共 Host/Origin；服务使用 `--allowed-host` 显式允许门户域名。默认允许 localhost 和 127.0.0.1。HTTPS 反代同时显式设置 `--allowed-origin https://<门户域名>`，不要信任客户端传入的代理身份头。本地服务没有 Windows 身份认证。

生成经过验证的服务发布目录：

```powershell
python package_release.py --output ../../releases/order-dashboard-v1
```

发布目录含服务代码、Excel 读取和计算模块、模板、配置、依赖清单及同版前端，拒绝覆盖已有目录，不包含原始业务数据、数据快照或批注数据库。可交给门户的 `New-AppRelease.ps1` 封装，类型 service、入口 server.py、dataMode external、healthPath /health。

从发布目录启动时显式传入绝对持久路径与当前版本 web 目录：

```powershell
python server.py --input <汇总Excel目录> --data-dir <持久数据目录/runtime> --state-dir <持久批注目录> --web-dir ./web --allowed-host <门户域名> --host 127.0.0.1 --port 8767
```

服务默认路径仅方便开发，发布运行必须显式配置。持久数据目录不得放入发布版本目录或静态站点根。首次部署可直接从 Excel 自动构建，也可复制已验证的完整数据快照目录；升级复用原持久路径，不用新包覆盖批注数据。停止旧订单服务，切换同版前后端，使用相同持久路径启动并验收。门户、其他应用不需要随之停止。此仓库不自动安装 Windows 服务或修改 IIS。

验收包括主体/模块/粒度切换、来源跳转、底表搜索分页、CSV/XLSX 下载、两个浏览器间共享批注、继承范围、重启持久化及旧批次查询。业务数据、数据库、发布产物与日志不得提交 Git。
