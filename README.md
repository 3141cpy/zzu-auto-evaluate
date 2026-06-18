# ZZU 教学评价自动提交程序

郑州大学本科教学质量管理平台（jxpj）自动评价工具，一键完成所有教师评价任务。

## 功能特点

- **API直连模式**：直接调用评价系统API提交评价，无需浏览器自动化，速度快、稳定性高
- **自动登录**：支持 Playwright 浏览器登录 + Cookie复用 + Chrome Cookie导入
- **全类型覆盖**：自动识别理论课、实验课等不同问卷类型，逐一提交
- **AuthKey加密**：RSA-1024加密生成AuthKey，确保提交合法性
- **教师筛选**：支持白名单/黑名单模式，灵活指定评价范围
- **批量操作**：一键完成所有未评价任务，输出汇总报告

## 快速开始

### 安装依赖

```bash
pip install playwright pycryptodome
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

[1] 登录中...
    登录成功: 张三

[2] 获取未完成任务列表...
    共找到 1 个未完成任务
    2025-2026-2学期期末学生评价（校级） [3/17]

[3] 开始自动填写评价...

  [1/1] 2025-2026-2学期期末学生评价（校级）
      子问卷课程: 物理实验 (QuestionnaireId=23)
      [1/1] 物理实验 - 李老师
      [1/16] 高等数学 - 王老师
      [2/16] 大学英语 - 赵老师
      ...
      [16/16] 思想道德修养 - 刘老师
  [✓] 成功提交14门课程评价

==================================================
  评价完成！
==================================================
```

## 参数说明

| 参数 | 缩写 | 必填 | 说明 |
|------|------|------|------|
| `--username` | `-u` | 是 | 学号 |
| `--password` | `-p` | 否 | 密码（Cookie复用/导入时可选） |
| `--whitelist` | | 否 | 教师白名单，仅评价这些教师的课程 |
| `--blacklist` | | 否 | 教师黑名单，排除这些教师的课程 |
| `--no-headless` | | 否 | 显示浏览器窗口（调试用） |
| `--api-only` | | 否 | 仅使用API模式，不回退到浏览器自动化 |

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

1. **登录**：Playwright 打开 CAS 统一认证平台，完成登录后从重定向中提取 Token
2. **获取任务列表**：调用 `GetMyTaskItemByAnswerStatus` API（AES-ECB 加密请求体）
3. **获取课程列表**：调用 `GetFinalQuestionnaireHeaderAsync` 获取教师列表（含DetailId和AnswerStatus）
4. **发现子问卷**：调用 `GetMyTaskItemDetailAsync` 发现使用不同问卷的课程（如实验课）
5. **生成AuthKey**：RSA-1024加密 `DetailId&PersonCode`，公钥来自 `Login/GetPublicKey`
6. **提交评价**：调用 `SaveAnswer` API，选择题选"非常同意"，文本题填正向评价
7. **汇总报告**：输出每个课程的评价结果和统计数据

## 技术细节

- **加密方式**：AES-ECB（与前端SPA保持协议兼容），Base64 输出
- **AuthKey**：RSA-1024 + PKCS1_v1_5，加密 `DetailId&PersonCode`，输出hex字符串
- **Token管理**：从CAS登录重定向提取，存入Cookie复用文件
- **Cookie存储**：`~/.zzu_eval_cookies.json`，权限0600

## 文件说明

| 文件 | 说明 |
|------|------|
| `auto_evaluate.py` | 教学评价自动提交主程序（单文件，包含所有功能） |

## 安全说明

- 密码通过RSA加密后传输，不会以明文形式发送
- Cookie文件存储在用户主目录，权限设为仅所有者可读
- AES加密密钥为前端SPA内置密钥，用于API协议兼容，非用户凭据
- 建议使用后及时清理Cookie文件

## 注意事项

- 请确保网络连接稳定，程序运行期间不要手动操作浏览器窗口
- 如遇到验证码或其他人工验证，请使用 `--no-headless` 模式手动处理
- 本工具仅供学习交流使用，请合理使用

## License

MIT
