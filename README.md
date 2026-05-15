# ZZU 教学评价自动提交程序

郑州大学本科教学质量管理平台（jxpj）自动评价工具，一键完成所有教师评价任务。

## 功能特点

- **自动登录**：通过 Playwright 浏览器自动化登录教学评价平台
- **自动填写**：选择题统一选择"非常同意"，自动生成正向评价文本
- **评分原因弹窗处理**：自动识别并填写高分评分原因
- **教师筛选**：支持白名单/黑名单模式，灵活指定评价范围
- **批量操作**：一键完成所有未评价任务，输出汇总报告
- **安全通信**：请求体使用 AES-ECB 加密，Token 自动管理

## 快速开始

### 安装依赖

```bash
pip install playwright
playwright install chromium
```

### 基本用法

```bash
python auto_evaluate.py -u 学号 -p 密码
```

### 显示浏览器窗口（调试模式）

```bash
python auto_evaluate.py -u 学号 -p 密码 --no-headless
```

### 教师筛选

```bash
# 白名单模式：仅评价指定教师的课程
python auto_evaluate.py -u 学号 -p 密码 --whitelist 张老师 李老师

# 黑名单模式：排除指定教师的课程
python auto_evaluate.py -u 学号 -p 密码 --blacklist 王老师
```

> 同时指定白名单和黑名单时，白名单优先生效。

## 运行示例

```
==================================================
  ZZU 教学评价自动提交程序
==================================================

[1/4] 获取未完成任务列表...
    共找到 1 个未完成任务
    1. 2025-2026-2学期期中学生评价（校级） (期中评价) [0/17]

[2/4] 逐个处理任务...

  任务: 2025-2026-2学期期中学生评价（校级） (期中评价) [0/17]
    导航到任务详情页...
    获取课程列表...
    共 17 门课程

[3/4] 开始评价 (17 门课程)...

    评价: 高等数学 - 张老师
      导航到任务详情页...
      点击课程 '高等数学' 的评价按钮...
      填写评价表单...
      已选择 16 个'非常同意'选项
      已填写评价文本
      提交评价...
      [✓] 提交成功

    ...

[4/4] 评价完成！
==================================================
  总计: 17 | 成功: 17 | 失败: 0
==================================================
```

## 参数说明

| 参数 | 缩写 | 必填 | 说明 |
|------|------|------|------|
| `--username` | `-u` | 是 | 学号 |
| `--password` | `-p` | 是 | 密码 |
| `--whitelist` | | 否 | 教师白名单，仅评价这些教师的课程 |
| `--blacklist` | | 否 | 教师黑名单，排除这些教师的课程 |
| `--no-headless` | | 否 | 显示浏览器窗口（调试用） |

## 代码调用

```python
from auto_evaluate import ZZUAutoEvaluate

evaluator = ZZUAutoEvaluate("学号", "密码", headless=True)
try:
    if evaluator.login():
        # 批量评价所有未完成任务
        report = evaluator.batch_evaluate()

        # 使用黑名单排除特定教师
        report = evaluator.batch_evaluate(blacklist=["某老师"])

        # 仅获取任务列表
        tasks = evaluator.get_unfinished_tasks()
        for t in tasks:
            print(t["QuestionnaireName"], t["AnsweredCount"], "/", t["TotalAnswerCount"])
finally:
    evaluator.close()
```

## 工作原理

1. **登录**：Playwright 打开评价平台 SPA，填写登录表单，从网络响应中捕获 Token
2. **获取任务列表**：调用 `GetMyTaskItemByAnswerStatus` API（AES-ECB 加密请求体）
3. **逐任务处理**：导航到任务详情页，获取课程列表
4. **填写评价**：点击"评价"按钮进入答题页面，自动选择"非常同意"、填写评价文本
5. **提交**：点击提交按钮，自动处理"评分原因"弹窗
6. **汇总报告**：输出每个课程的评价结果和统计数据

## 技术细节

- **加密方式**：AES-ECB，密钥 `nfZYwnW2ppQc3CXr`，盐值 `d^PrEK&c`，Base64 输出
- **Token 管理**：从网络响应体捕获，存入 localStorage，API 调用时自动更新
- **浏览器自动化**：Playwright Chromium，支持 headless 模式

## 文件说明

| 文件 | 说明 |
|------|------|
| `auto_evaluate.py` | 教学评价自动提交主程序 |
| `auto_login/` | CAS 自动登录模块（选课系统用，独立模块） |

## 注意事项

- 请确保网络连接稳定，程序运行期间不要手动操作浏览器窗口
- 如遇到验证码或其他人工验证，请使用 `--no-headless` 模式手动处理
- 本工具仅供学习交流使用，请合理使用

## License

MIT
