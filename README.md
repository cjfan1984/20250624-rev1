# LEMON PROFIT Python Cloud

LEMON PROFIT 的云端 Python 自动化运行仓库。

- Google Sheet：经营控制台
- `10_Python设置`：可见、可编辑的公式配置
- `lemon_profit_cloud.py`：Python 计算与校验内核
- `PY_利润校验`：Python 与现有表格公式的并行校验结果
- GitHub Actions：云端定时运行

安全原则：未知成本不按 0；佣金只扣一次；第一阶段只校验，不覆盖现有 06/07 主公式。

当前 Google Sheet ID 已绑定到程序默认值；真正写入 Google Sheet 需要仓库 Secret：`GOOGLE_SERVICE_ACCOUNT_JSON`。
