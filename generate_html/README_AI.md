# AI 维护指南

## 先看这里

这个项目只有三层，不要再拆层：

1. `core/`：Excel 读取、主体识别、通用组件数据结构、输出与校验。
2. `modules/`：一个业务标签一个文件，看板口径和排布都在这里。
3. `templates/`：页面外壳、样式和通用组件渲染。

`main.py` 只编排生成流程，`config.json` 放标签顺序、显示名称和可选的销量预测复盘日期。不要直接修改 `output/` 中的生成文件。

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

- 集团固定为“鸿蒙智行”，品牌和代际动态识别。
- 主体类型不同，可用看板可以不同；不要强行补齐空看板。
- 大定、锁单、小订的趋势图统一读取“图表”Sheet 中的表数据生成。
- SKU、首销节奏、小订退订主要按单代际展示；如未来新增专门汇总 Sheet，按 Sheet 实际主体展示。
- 小订及首销数据整理统一从项目根目录的 `output_file/小订及首销数据整理.xlsx` 读取（与 `scripts` 同级），刷新、车型属性和阶段识别共用 `core/model_identity.py` 的路径常量；业务输入不纳入Git。整理表和销量汇总在普通主体、模块构建后加入底表中心，避免其Sheet参与普通看板取数或生成额外主体。
- 不添加“数据覆盖情况”、筛选区“数据口径”或自动管理建议。
- 底表统一在“底表中心”查看；看板来源抽屉只负责跳转定位，底表中心负责搜索与 CSV 导出。
- 原始数值、百分数和日期的显示必须读取单元格 `number_format`，不要在底表渲染中写死小数位或日期格式。
- SKU 的周度累计锁单占比、配置组合热力图保留全部历史列，首次显示时滚动到最右侧；切换组合后保留用户已拖动的位置。主销 SKU 排行分列展示原表的版本中文名称、外饰、内饰和轮毂套件。
- 底表中心“导出当前数据”导出当前筛选结果的 CSV；“导出整个 Excel”下载生成看板时嵌入的完整原始 XLSX（所有 Sheet、格式和公式），不受筛选影响，也不依赖原文件路径或网络。`raw_blocks` 的数字 Sheet 键存储 gzip 行数据，`文件序号|xlsx` 键存储原文件的 base64 字节，仅供下载。

## 修改后必做

内网从 GitHub 远端 `github` 的 `main` 分支下载或拉取代码。用户要求每次修改验证通过后自动提交并同步到 `github/main`，无需再次询问；若使用独立开发分支，交付前必须将本次已验证改动合入 `main` 并推送。保留无关修改，不强推或改写已有历史，并核对远端 `main` 已包含本次提交。

所有 Git 网络操作（包括 fetch、pull、push、ls-remote）必须使用与 Codex 软件当前连接相同的代理。执行前核对有效代理；代理不可用时停止并报告，禁止清空代理、通过 NO_PROXY 绕过或回退直连。本地 commit 不需要联网；代理地址按当前运行环境配置，不在共享代码中写死。

```powershell
python -m compileall core modules main.py
node --check templates\dashboard.js
python main.py --check
python -m unittest discover -s tests
```

检查本次 `generate_html_YYYYMMDD_HHMMSS.log` 中没有异常，并在浏览器测试主体切换、标签置灰、日/周/月和底表搜索。
