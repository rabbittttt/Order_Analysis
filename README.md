# 订单分析代码

本仓库保存 `generate_html`（订单看板与销量预测）和 `销量规律`（销量规律分析与预测辅助）的程序代码。两个文件夹直接位于仓库根目录。运行所需的原始 Excel 和生成的报告留在各自电脑，不上传到公开仓库。

## 在另一台 Windows 电脑下载

先安装 Git 和 Python 3.10 或更新版本，然后在 PowerShell 中运行：

```powershell
git clone https://github.com/rabbittttt/Order_Analysis.git
cd Order_Analysis
python -m pip install -r generate_html/requirements.txt
```

在仓库根目录准备自己的数据：历史及车型 Excel 放入 `input_file/销量预测输入文件`，当前订单汇总报表放入 `output_file`。生成的汇总 Excel、网页和销量规律报告也写入 `output_file`。具体文件要求见 [看板说明](generate_html/README.md) 与 [销量规律说明](销量规律/README.md)。所有默认路径按代码所在仓库定位，无需使用旧电脑的 D 盘路径。

在仓库根目录运行：

```powershell
python generate_html/main.py
python 销量规律/analyze_sales_patterns.py
```

第二条命令需要第一步准备好的 `output_file/鸿蒙智行销量数据汇总.xlsx`。

此仓库不含真实订单 Excel。只下载代码无法重现旧电脑的分析结果；业务数据需另行安全迁移。

## 更新版本

在这个 Git 仓库里修改代码，然后运行：

```powershell
git status
git add generate_html 销量规律 README.md .gitignore
git diff --cached --stat
git commit -m "描述这次修改"
git push
```

开始修改前，在干净的仓库目录运行 `git pull --ff-only` 获取最新代码。另一台电脑也用这条命令更新。如果提示本地有未提交修改或分支已分叉，先保留本地修改并处理差异，不要强制覆盖。
