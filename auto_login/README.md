# 郑州大学CAS自动登录模块

模拟浏览器登录郑州大学CAS系统，自动获取选课系统认证信息。

## 功能特点

- **自动登录**：模拟CAS登录流程，自动获取JWT Token和Student ID
- **RSA加密**：密码使用RSA+PKCS1_v1_5加密传输
- **自动更新配置**：登录成功后自动更新配置文件

## 快速开始

### 安装依赖

```bash
pip install requests beautifulsoup4 pycryptodome
```

### 运行登录

```bash
python auto_login.py
```

按提示输入学号和密码：

```
==================================================
郑州大学CAS自动登录工具
==================================================
请输入学号: REDACTED
请输入密码: ********

登录成功！config.json 已更新
```

## 代码调用

```python
from auto_login import auto_login

# 登录并更新config.json
success = auto_login('学号', '密码')

# 指定配置文件路径
success = auto_login('学号', '密码', 'path/to/config.json')

if success:
    print("登录成功")
```

## 输出说明

登录成功后，`config.json` 会更新：

```json
{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "student_id": "123220"
}
```

## 登录流程

1. 访问CAS登录页 `cas.s.zzu.edu.cn/cas/a/login`
2. 提取表单 `execution` 参数
3. 获取RSA公钥
4. 使用PKCS1_v1_5填充加密密码
5. 提交登录表单，获取ticket
6. 跟随ticket重定向
7. 访问选课页面获取JWT token
8. 调用API获取student_id

## 文件说明

| 文件 | 说明 |
|------|------|
| `auto_login.py` | 自动登录模块 |
| `config.json` | 配置文件（存储token和student_id） |
| `example.txt` | 测试账号示例 |

## 注意事项

- Token有效期较短，，过期后需重新运行
- 密码使用RSA加密传输，安全性有保障