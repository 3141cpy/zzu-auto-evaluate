# ZZU 教学评价自动提交程序

郑州大学本科教学质量管理平台（jxpj）自动评价工具，一键完成所有教师评价任务。

## 功能特点

- **API直连模式**：直接调用评价系统API提交评价，无需浏览器自动化，速度快、稳定性高
- **多种登录策略**：Cookie复用 → Chrome Cookie导入 → API+MFA登录 → Playwright回退
- **多种MFA验证方式**：支持APP扫码（qrcode）、APP推送（appPush）、短信验证码（securephone）三种MFA验证方式，自动检测可用方式并支持用户手动选择
- **终端二维码展示**：APP扫码验证时，使用Pillow库下载二维码PNG图片并在终端直接渲染显示（Unicode方块字符双行高显示），无需手动打开图片
- **MFA可信客户端自动跳过**：使用fpVisitorId标识设备，CAS detect接口返回need=false时自动跳过MFA验证，无需用户干预
- **TGC复用**：有效TGC Cookie自动跳过整个登录流程
- **全类型覆盖**：自动识别理论课、实验课等不同问卷类型，逐一提交
- **AuthKey加密**：RSA-1024加密生成AuthKey，确保提交合法性
- **教师筛选**：支持白名单/黑名单模式，灵活指定评价范围
- **批量操作**：一键完成所有未评价任务，输出汇总报告

## 快速开始

### 安装依赖

```bash
pip install pycryptodome beautifulsoup4 requests Pillow
```

如需Playwright浏览器登录（回退方案）：
```bash
pip install playwright
playwright install chromium
```

### 基本用法

```bash
python auto_evaluate.py -u 学号 -p 密码
```

### 登录策略

```bash
# 自动策略（默认）：依次尝试 Cookie复用 → Chrome导入 → API+MFA → Playwright
python auto_evaluate.py -u 学号 -p 密码

# 仅API+MFA登录
python auto_evaluate.py -u 学号 -p 密码 --strategy api_mfa

# Cookie复用登录
python auto_evaluate.py -u 学号 --strategy cookie_reuse

# Chrome Cookie导入
python auto_evaluate.py -u 学号 --cookie-import

# Playwright浏览器登录
python auto_evaluate.py -u 学号 -p 密码 --strategy playwright
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

[1] 登录中... (策略: auto)
    [CAS] TGC有效，跳过登录直接签发ticket
[✓] 登录成功！用户: 张三

[2] 获取未完成任务列表...
    共找到 1 个未完成任务
    1. 2025-2026-2学期期末学生评价（校级） (期末评价) [3/17]

[3] 开始自动填写评价...

  [1/1] 2025-2026-2学期期末学生评价（校级） (期末评价) [3/17]
    [1/14] 高等数学 - 王老师
    [2/14] 大学英语 - 赵老师
    ...
    [14/14] 思想道德修养 - 刘老师
  [✓] 成功提交14门课程评价

==================================================
  评价完成！总计: 1 | 成功: 1 | 失败: 0
==================================================
```

### 首次登录（含MFA）

```
[1] 登录中... (策略: api_mfa)
    [MFA] 检测到多种验证方式可用:
    请选择验证方式 (1=APP扫码验证, 2=APP推送验证, 3=短信验证码，默认1): 1
    [MFA] 已选择: APP扫码验证
    [MFA] 二维码已生成，请使用APP扫描：
    ██████████████████████████████
    ██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀██
    ██▀▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▀▄██
    ...（终端直接显示二维码）
    [MFA] 等待APP扫码确认... (120秒超时)
    [MFA] 扫码验证成功！
    是否将当前设备设为可信客户端？后续登录可跳过安全验证 (y/n): y
    [✓] 已设为可信客户端
[✓] 登录成功！
```

### 短信验证方式

```
[1] 登录中... (策略: api_mfa)
    [MFA] 安全手机: 138****1234
    [MFA] 短信验证码已发送
    请输入收到的短信验证码: 1234
    [MFA] 短信验证成功！
    是否将当前设备设为可信客户端？后续登录可跳过安全验证 (y/n): y
    [✓] 已设为可信客户端
[✓] 登录成功！
```

### 可信设备再次登录

```
[1] 登录中... (策略: api_mfa)
    [MFA] CAS detect返回need=false，自动跳过MFA验证
    [✓] 登录成功！
```

## 参数说明

| 参数 | 缩写 | 必填 | 说明 |
|------|------|------|------|
| `--username` | `-u` | 是 | 学号 |
| `--password` | `-p` | 否 | 密码（Cookie复用/导入时可选） |
| `--strategy` | | 否 | 登录策略：auto(默认)、cookie_reuse、api_mfa、playwright、cookie_import |
| `--cookie-import` | | 否 | 启用Chrome Cookie导入 |
| `--whitelist` | | 否 | 教师白名单，仅评价这些教师的课程 |
| `--blacklist` | | 否 | 教师黑名单，排除指定教师的课程 |
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

### 登录流程

1. **Cookie复用**：加载已保存的TGC Cookie，如有效则直接签发ticket，跳过整个登录流程
2. **Chrome Cookie导入**：从本地Chrome浏览器导入CAS Cookie
3. **API+MFA登录**：
   - 访问CAS登录页，获取execution参数
   - RSA加密密码，提交登录表单（failN="-1"避免CAS误判触发验证码）
   - 如需MFA：调用detect接口检查设备是否已信任
     - 已信任设备（`need=false`）：自动跳过MFA，提交trustAgent="true"
     - 未信任设备：检测可用MFA验证方式（qrcode/appPush/securephone）
       - 单种方式：直接使用该方式验证
       - 多种方式：用户手动选择验证方式
       - qrcode（APP扫码）：下载二维码PNG → 终端渲染显示 → 用户APP扫码 → 轮询状态
       - appPush（APP推送）：发起推送 → 轮询状态 → 用户APP确认
       - securephone（短信验证码）：发送短信 → 用户输入验证码 → 验证
       - qrcode/appPush失败时自动回退securephone
       - 验证成功后可选设为可信客户端
   - fpVisitorId默认值为"00000000000000000000000000000000"（已注册的信任设备标识）
   - 跟随SSO重定向获取Token
4. **Playwright回退**：以上方式均失败时，使用浏览器自动化登录

### 评价流程

1. **获取任务列表**：调用 `GetMyTaskItemByAnswerStatus` API（AES-ECB 加密请求体）
2. **获取课程列表**：调用 `GetFinalQuestionnaireHeaderAsync` 获取教师列表
3. **发现子问卷**：调用 `GetMyTaskItemDetailAsync` 发现使用不同问卷的课程（如实验课）
4. **生成AuthKey**：RSA-1024加密 `DetailId&PersonCode`
5. **提交评价**：调用 `SaveAnswer` API，选择题选"非常同意"，文本题填正向评价
6. **汇总报告**：输出每个课程的评价结果和统计数据

## 技术细节

- **加密方式**：AES-ECB（与前端SPA保持协议兼容），Base64 输出
- **AuthKey**：RSA-1024 + PKCS1_v1_5，加密 `DetailId&PersonCode`，输出hex字符串
- **Token管理**：从CAS登录重定向提取，存入Cookie复用文件
- **Cookie存储**：`~/.zzu_eval_cookies.json`，权限0600，包含cookies和fp_visitor_id
- **MFA验证方式**：支持三种验证方式 - qrcode（APP扫码，下载PNG二维码并用Pillow库渲染到终端）、appPush（APP推送，轮询状态SENT→SCAND→VALID）、securephone（短信验证码），qrcode/appPush失败时自动回退securephone
- **可信客户端**：基于fpVisitorId标识设备，默认值"00000000000000000000000000000000"（已注册的信任设备标识），CAS detect接口返回`need=false`时自动跳过MFA，同时提交trustAgent="true"
- **验证码规避**：failN="-1"参数避免CAS误判触发图像验证码，已移除图像验证码识别功能

## 文件说明

| 文件 | 说明 |
|------|------|
| `auto_evaluate.py` | 教学评价自动提交主程序（单文件，包含所有功能） |

## 安全说明

- 密码通过RSA加密后传输，不会以明文形式发送
- Cookie文件存储在用户主目录，权限设为仅所有者可读
- AES加密密钥为前端SPA内置密钥，用于API协议兼容，非用户凭据
- fpVisitorId默认为"00000000000000000000000000000000"（已注册的信任设备标识），用于可信客户端功能
- 建议使用后及时清理Cookie文件

## 注意事项

- 请确保网络连接稳定
- 首次登录需输入短信验证码，建议选择"设为可信客户端"以便后续自动登录
- 登录成功后如选课系统未开放，程序会给出明确提示
- failN="-1"参数可避免CAS误判触发图像验证码，已移除图像验证码识别功能（ddddocr依赖已移除）
- 本工具仅供学习交流使用，请合理使用

## License

MIT
