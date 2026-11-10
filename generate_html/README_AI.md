# AI 维护指南

## 先看这里

这个项目只有三层，不要再拆层：

1. `core/`：Excel 读取、主体识别、通用组件数据结构、输出与校验。
2. `modules/`：一个业务标签一个文件，看板口径和排布都在这里。
3. `templates/`：页面外壳、样式和通用组件渲染。

`main.py` 只编排订单分析生成流程，`config.json` 放标签顺序和显示名称。不要直接修改 `output/` 中的生成文件。

## 常见修改

- 改某个看板：只改对应的 `modules/*.py`。
- 调整颜色、密度、布局：改 `templates/dashboard.css`。
- 新增一种已有组件组合：新建一个 `modules/*.py`，然后加到 `modules/registry.py` 和 `config.json`。
- 新增一种全新图形：先在业务模块输出新 `kind`，再在 `templates/dashboard.js` 增加一个同名渲染函数。
- 新增品牌或代际：不改代码，Sheet 名前缀符合现有命名即可。

## 模块契约

每个模块实现：

```python
class XxxModule:
    id = "unique_id"
    label = "页面标签"

    def build(self, store, subject):
        # 有数据返回 Dashboard，无数据返回 None。
        ...
```

返回 `None` 时顶部标签自动置灰。不要在页面中写死品牌、代际或周期。

## 业务约束

- 销量预测已迁至同级独立项目。订单入口仅构建订单模块，不注册销量预测、不刷新预测汇总、不输出预测 HTML 或 forecast_assets。两边使用独立文件，禁止跨项目 import、软链接或代码自动同步。
- 预测专属模块、工具、计算脚本、模板分支和回归测试已从本仓库移除，不保留停用副本。公共阶段身份读取仍用于小订、首销实际节奏；不得因整理表同时供预测使用而删除订单仍依赖的读取逻辑。
- 本仓库仅维护订单分析。旧 `销量规律/` 目录及其专属日历、测试引用已移除；维护和 Git 发布范围均为当前 `scripts` 仓库。
- 输入由 `core/data_paths.py` 相对项目位置选择同级 `共享数据/订单汇总`；显式 `SHARED_DATA_ROOT` 优先。共享输入只读。WorkbookStore 缓存必须显式传入本项目输出目录，不能写入或清理共享目录。
- `小订及首销数据整理.xlsx` 仍供公共阶段身份读取，但其 Sheet 和 `鸿蒙智行销量数据汇总.xlsx` 不参与订单主体发现、普通模块及底表中心。

- 集团固定为“鸿蒙智行”，品牌和代际动态识别。
- 主体类型不同，可用看板可以不同；不要强行补齐空看板。
- 大定、锁单、小订的趋势图统一读取“图表”Sheet 中的表数据生成。
- SKU、首销节奏、小订退订主要按单代际展示；如未来新增专门汇总 Sheet，按 Sheet 实际主体展示。
- 不添加“数据覆盖情况”、筛选区“数据口径”或自动管理建议。
- 底表统一在“底表中心”查看；看板来源抽屉只负责跳转定位，底表中心负责搜索与 CSV 导出。
- 原始数值、百分数和日期的显示必须读取单元格 `number_format`，不要在底表渲染中写死小数位或日期格式。
- SKU 的 TOP200 周度累计锁单占比、配置组合热力图保留全部历史列，首次显示时滚动到最右侧；切换组合后保留用户已拖动的位置。热力图本身负责横、竖滚动，横向滚动条始终位于卡片可见内容底部，不能放到200行之后再由外层裁切。主销 SKU 排行分列展示原表的版本中文名称、外饰、内饰和轮毂套件。
- 底表中心“导出当前数据”由后台导出当前筛选的全部 CSV；“导出整个 Excel”下载当前页面所属批次的原始 XLSX，保留全部 Sheet、格式和公式。生成阶段 raw_blocks 为中间表示，不再内嵌最终网页。动态运行、外置数据和发布契约见 SERVER.md。

## 修改后必做

内网从 GitHub 远端 `github` 的 `main` 分支下载或拉取代码。用户要求每次修改验证通过后自动提交并同步到 `github/main`，无需再次询问；若使用独立开发分支，交付前必须将本次已验证改动合入 `main` 并推送。保留无关修改，不强推或改写已有历史，并核对远端 `main` 已包含本次提交。

所有 Git 网络操作（包括 fetch、pull、push、ls-remote）必须使用与 Codex 软件当前连接相同的代理。执行前核对有效代理；代理不可用时停止并报告，禁止清空代理、通过 NO_PROXY 绕过或回退直连。本地 commit 不需要联网；代理地址按当前运行环境配置，不在共享代码中写死。

```powershell
python -m compileall core modules main.py server.py package_release.py
node --check templates\dashboard.js
python main.py --check --no-open
python -m unittest discover -s tests
```

检查本次 `generate_html_YYYYMMDD_HHMMSS.log` 中没有异常，并在浏览器测试主体切换、标签置灰、日/周/月和底表搜索。
