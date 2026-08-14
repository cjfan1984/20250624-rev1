# LEMON PROFIT Python Cloud V0.2

LEMON PROFIT 的配置驱动利润核验程序。手机和电脑都不需要安装 Python。

## 直接使用

- 工作副本：[LEMON PROFIT Python自动化 V0.1](https://docs.google.com/spreadsheets/d/1y4UIifDu1WaRQSLPxMFdBhsXwrfCyt_Kmu555q4mea0/edit)
- 正式原表默认受保护，不被 Python 覆盖。
- 修改 `06_跨境SKU核价` 或 `07_本土SKU核价` 的输入后，查看 `PY_测试结果`。
- 字段开关、必填、数据类型在 `PY_字段配置` 修改。
- 计算逻辑在 `PY_公式配置` 修改，字段用 `[字段名称]` 引用。
- `PY_系统设置` 默认是 `audit`，只核验，不覆盖 06/07 既有公式。

## V0.2 做了什么

- Python 按字段名称定位，不依赖 A/B/C 固定列号。
- 新增、删除或移动字段后，只要同步修改配置即可。
- 公式从 Google Sheet 读取，不写死在程序里。
- 支持 `IF`、`ROUNDUP10`、四则运算、比较和安全白名单函数。
- 空白成本保持空白并标记“待补充”，不会按 0。
- 每次运行写入 `PY_测试结果` 并追加 `PY_运行日志`。
- `apply` 写回有双开关和原表保护，默认关闭。

## 云端运行状态

GitHub Actions 每小时自检一次。Google 直连需要仓库 Secret `GOOGLE_SERVICE_ACCOUNT_JSON`，并将工作副本共享给该服务账号。Secret 未配置时，工作流会明确显示“Google直连尚未接通”，不会伪装成已经写表。

服务账号 JSON 只能放在 GitHub Actions Secret 中，禁止提交到仓库或粘贴到公开文件。
