# CAS自动登录模块使用说明

## 目录

1. [安装依赖](#安装依赖)
2. [使用方法](#使用方法)
3. [配置文件](#配置文件)
4. [登录流程](#登录流程)
5. [API说明](#api说明)
6. [常见问题](#常见问题)

---

## 安装依赖

```bash
pip install requests beautifulsoup4 pycryptodome
```

| 依赖包 | 用途 |
|--------|------|
| `requests` | HTTP请求库 |
| `beautifulsoup4` | HTML解析，提取表单参数 |
| `pycryptodome` | RSA加密密码 |

---

## 使用方法

### 命令行方式

```bash
python auto_login.py
```

交互式输入学号密码：

```
==================================================
郑州大学CAS自动登录工具
==================================================
请输入学号: 202500000000
请输入密码: ********

==================================================
登录成功！config.json 已更新
student_id: 123220
token: eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
==================================================
```

### 代码调用方式

```python
from auto_login import auto_login

# 基本用法
success = auto_login('学号', '密码')

# 指定配置文件路径
success = auto_login('学号', '密码', 'my_config.json')

if success:
    print("登录成功")
else:
    print("登录失败")
```

### 获取登录结果

```python
from auto_login import ZZUCASLogin

login = ZZUCASLogin()

# 执行登录流程
execution, _ = login.get_execution_value()
public_key = login.get_public_key()
encrypted_pwd = login.encrypt_password('密码', public_key)
success, ticket_url = login.submit_login('学号', encrypted_pwd, execution)
success, student_id, token = login.follow_redirect_and_get_cookies(ticket_url)

print(f"student_id: {student_id}")
print(f"token: {token}")
```

---

## 配置文件

配置文件 `config.json` 结构：

```json
{
  "token": "JWT认证令牌",
  "student_id": "学生ID"
}
```

登录成功后自动更新 `token` 和 `student_id` 字段。

---

## 登录流程

### 完整流程

```
┌─────────────────────────────────────────────────────────────┐
│  1. GET /cas/a/login?service=选课系统URL                    │
│     → 获取 execution 参数                                   │
├─────────────────────────────────────────────────────────────┤
│  2. GET /cas/jwt/publicKey                                  │
│     → 获取 RSA 公钥 (PEM格式)                               │
├─────────────────────────────────────────────────────────────┤
│  3. POST /cas/a/login                                       │
│     → 提交加密密码和表单数据                                 │
│     → 获取 ticket 重定向URL                                 │
├─────────────────────────────────────────────────────────────┤
│  4. GET ticket重定向URL                                     │
│     → 建立教务系统会话                                      │
├─────────────────────────────────────────────────────────────┤
│  5. GET /student/for-std/course-select                      │
│     → 提取页面中的 JWT token                                │
├─────────────────────────────────────────────────────────────┤
│  6. GET /course-selection-api/.../students                  │
│     → 使用 JWT token 获取 student_id                        │
└─────────────────────────────────────────────────────────────┘
```

### 关键参数

| 参数 | 来源 | 用途 |
|------|------|------|
| `execution` | 登录表单隐藏字段 | 防止CSRF攻击 |
| `RSA公钥` | `/cas/jwt/publicKey` | 加密密码 |
| `ticket` | 登录成功重定向 | CAS单点登录凭证 |
| `JWT token` | 选课页面 | API认证令牌 |
| `student_id` | API响应 | 学生标识 |

### 密码加密格式

```
__RSA__ + Base64(RSA_PKCS1_v1_5_Encrypt(密码))
```

---

## API说明

### ZZUCASLogin 类

```python
class ZZUCASLogin:
    """郑州大学CAS登录类"""
    
    # URL常量
    CAS_LOGIN_PAGE_URL = "https://cas.s.zzu.edu.cn/cas/a/login"
    PUBLIC_KEY_URL = "https://cas.s.zzu.edu.cn/cas/jwt/publicKey"
    SERVICE_URL = "https://jwxt.zzu.edu.cn/student/sso/login"
    COURSE_SELECT_PAGE_URL = "https://jwxt.zzu.edu.cn/student/for-std/course-select"
    STUDENT_INFO_API = "https://jwxt.zzu.edu.cn/course-selection-api/api/v1/student/course-select/students"
```

### 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `get_execution_value()` | 无 | `(execution, event_id)` | 获取表单execution参数 |
| `get_public_key()` | 无 | `public_key_str` | 获取RSA公钥 |
| `encrypt_password(password, public_key)` | 密码, 公钥 | `encrypted_password` | RSA加密密码 |
| `submit_login(username, password, execution)` | 学号, 加密密码, execution | `(success, ticket_url)` | 提交登录 |
| `follow_redirect_and_get_cookies(ticket_url)` | ticket URL | `(success, student_id, token)` | 获取认证信息 |
| `update_config(student_id, token, config_path)` | 认证信息, 配置路径 | `success` | 更新配置文件 |

### auto_login 函数

```python
def auto_login(username: str, password: str, config_path: str = 'config.json') -> bool:
    """
    自动登录主函数
    
    Args:
        username: 学号
        password: 密码
        config_path: 配置文件路径
        
    Returns:
        是否成功
    """
```

---

## 常见问题

### Q: Token有效期多久？

A: JWT Token有效期约24小时，过期后重新运行 `python auto_login.py` 即可。

### Q: 登录失败提示"账号密码错误"？

A: 
1. 确认学号密码正确
2. 检查网络是否能访问 `cas.s.zzu.edu.cn`
3. 确认账号未被锁定

### Q: 如何处理验证码？

A: 当前系统登录通常不需要验证码。如果出现验证码，需要手动登录后获取token。

### Q: 支持多账号吗？

A: 支持。可以指定不同的配置文件：

```python
auto_login('学号1', '密码1', 'config1.json')
auto_login('学号2', '密码2', 'config2.json')
```

### Q: Token可以用于哪些API？

A: Token用于教务系统选课相关API，在请求头中添加：
```
Authorization: <token>
```