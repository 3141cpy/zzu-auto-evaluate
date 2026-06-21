#!/usr/bin/env python3
"""ZZU 教学评价自动提交程序 - 增强版

支持: Cookie复用(TGC跳过MFA)、MFA短信验证、Chrome Cookie导入、API直连、Playwright回退
"""

import random
import json
import time
import argparse
import os
import re
import shutil
import tempfile
import secrets
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote

import requests
from bs4 import BeautifulSoup

# ─── 可选依赖 ───────────────────────────────────────────────
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    import base64
    _HAS_PYCRYPTODOME = True
except ImportError:
    _HAS_PYCRYPTODOME = False

try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

# Windows DPAPI
try:
    import win32crypt
    _HAS_WIN32CRYPT = True
except ImportError:
    _HAS_WIN32CRYPT = False

# sqlite3 for Chrome cookie DB
try:
    import sqlite3
    _HAS_SQLITE3 = True
except ImportError:
    _HAS_SQLITE3 = False


# ═══════════════════════════════════════════════════════════════
# 1. Custom Exception Hierarchy
# ═══════════════════════════════════════════════════════════════

class EvalError(Exception):
    """评价系统基础异常"""
    pass


class EvalAuthError(EvalError):
    """认证相关异常"""
    pass


class EvalTokenExpiredError(EvalAuthError):
    """Token过期异常"""
    pass


class EvalAPIError(EvalError):
    """API调用异常"""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class EvalNetworkError(EvalError):
    """网络连接异常"""
    pass


# ═══════════════════════════════════════════════════════════════
# 2. AES Encryption Module
# ═══════════════════════════════════════════════════════════════

AES_KEY = "nfZYwnW2ppQc3CXr"
AES_SALT = "d^PrEK&c"


def _pkcs7_pad(data, block_size=16):
    """PKCS7填充"""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _pkcs7_unpad(data):
    """PKCS7去填充"""
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 16:
        return data
    return data[:-pad_len]


def _encrypt_aes(plaintext):
    """AES-ECB加密，PKCS7填充，Base64输出"""
    if not _HAS_PYCRYPTODOME:
        raise EvalError("pycryptodome未安装，无法进行AES加密。请运行: pip install pycryptodome")
    cipher = AES.new(AES_KEY.encode('utf-8'), AES.MODE_ECB)
    padded = _pkcs7_pad(plaintext.encode('utf-8'))
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode('utf-8')


def _decrypt_aes(ciphertext):
    """AES-ECB解密，Base64输入"""
    if not _HAS_PYCRYPTODOME:
        raise EvalError("pycryptodome未安装，无法进行AES解密。请运行: pip install pycryptodome")
    cipher = AES.new(AES_KEY.encode('utf-8'), AES.MODE_ECB)
    encrypted = base64.b64decode(ciphertext)
    decrypted = cipher.decrypt(encrypted)
    unpadded = _pkcs7_unpad(decrypted)
    return unpadded.decode('utf-8')


def _clean_nulls(text):
    """清理字符串中的null字符"""
    return text.replace('\x00', '')


# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

BASE_URL = "https://jxpj.v.zzu.edu.cn"
LOGIN_URL = f"{BASE_URL}/index.html?v=3.41.0"

CAS_BASE = "https://cas.s.zzu.edu.cn/cas"
CAS_LOGIN_URL = f"{CAS_BASE}/a/login"
CAS_PUBLIC_KEY_URL = f"{CAS_BASE}/jwt/publicKey"
DEAL_SSO_URL = f"{BASE_URL}/DealSSO.ashx/?universitycode=10459_1"
CAS_SERVICE_URL = DEAL_SSO_URL

POSITIVE_COMMENTS = [
    "老师教学认真负责，课堂内容丰富充实，能够很好地将理论知识与实际案例相结合，让学生在理解概念的同时也能掌握实际应用的方法，教学效果非常显著。",
    "教学方式生动有趣，能够很好地调动学生积极性，课堂氛围活跃，学生参与度高，老师善于用幽默风趣的语言讲解枯燥的知识点，让学习变得轻松愉快。",
    "老师备课充分，讲解清晰易懂，对课程内容有深入的理解和把握，能够将复杂的概念用简单明了的方式表达出来，让学生能够快速理解和掌握重点内容。",
    "课堂互动性强，注重培养学生的思考能力，老师经常提出有启发性的问题，引导学生主动思考和讨论，培养了我们的批判性思维和独立分析问题的能力。",
    "老师耐心解答学生疑问，关心学生学习进度，课后也愿意花时间帮助学生解决学习中的困难，对每一个学生都很负责，让人感到温暖和鼓舞。",
    "教学内容与时俱进，理论与实践结合紧密，老师能够将最新的行业动态和研究成果融入课堂，让我们不仅学到了书本知识，也了解了前沿发展。",
    "老师教学经验丰富，能够深入浅出地讲解难点，对于学生容易混淆的概念会进行对比分析，帮助我们建立清晰的知识体系，受益匪浅。",
    "课堂氛围活跃，学生参与度高，老师善于组织小组讨论和课堂活动，让每位同学都有机会表达自己的观点，极大地提升了学习效果和团队协作能力。",
]

RATING_REASON_COMMENTS = [
    "该教师教学态度认真，备课充分，课堂讲解清晰，能够很好地解答学生疑问，教学效果优秀。",
    "老师教学水平很高，课堂内容丰富，注重理论与实践结合，对学生负责，值得高度评价。",
    "教师教学经验丰富，课堂互动性强，能够深入浅出地讲解重点难点，学生收获很大。",
]


# ═══════════════════════════════════════════════════════════════
# 3. API Client Class
# ═══════════════════════════════════════════════════════════════

class EvalAPIClient:
    """评价系统API客户端 - 使用requests直接调用"""

    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0',
            'Accept': 'application/json, text/plain, */*',
            'sec-ch-ua': '"Microsoft Edge";v="144", "Chromium";v="144", "Not)A;Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        })
        self.token = None
        self.user_code = None
        self.university_code = None
        self.semester = None
        self._client_id = secrets.token_hex(16)
        self._fp_visitor_id = None

    def set_token(self, token):
        self.token = token

    def set_user_info(self, user_code, university_code, semester=None):
        self.user_code = user_code
        self.university_code = university_code
        if semester:
            self.semester = semester

    @property
    def fp_visitor_id(self):
        """获取fpVisitorId（持久化的浏览器指纹）"""
        return self._fp_visitor_id

    @fp_visitor_id.setter
    def fp_visitor_id(self, value):
        """设置fpVisitorId"""
        self._fp_visitor_id = value

    @staticmethod
    def _clean_nulls(obj, recursive=True):
        """清理字典中的null值和空字符串（前端JS逻辑）"""
        if not isinstance(obj, dict):
            return obj
        cleaned = {}
        for k, v in obj.items():
            if v is None or v == "":
                continue
            if recursive and isinstance(v, dict):
                v = EvalAPIClient._clean_nulls(v, True)
            cleaned[k] = v
        return cleaned

    def _build_system_params(self, api_name, token=None, user_code=None, university_code=None,
                              service_type=None, page_context=None):
        """构建统一的SystemParams（SPA实际格式）"""
        _token = token or self.token
        _user_code = user_code or self.user_code
        _university_code = university_code or self.university_code or "10459"

        system_params = {
            "DegreeLevel": 0,
            "Token": _token or "",
            "UserCode": _user_code or "",
            "UniversityCode": _university_code,
            "ApiName": api_name,
            "ClientTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ClientId": self._client_id,
            "ClientType": 0,
            "Semester": self.semester or "",
            "RequestOriginPageAddress": f"{LOGIN_URL}#/my-task/main/UnFinished",
        }

        if service_type:
            system_params["SERVICE_TYPE"] = service_type

        if page_context is not None:
            system_params["PageContext"] = page_context

        return system_params

    def _build_and_encrypt_body(self, api_name, request_params=None, token=None,
                                 user_code=None, university_code=None,
                                 service_type=None, page_context=None):
        """构建请求体并加密"""
        system_params = self._build_system_params(
            api_name, token, user_code, university_code, service_type, page_context
        )

        body = {
            "SystemParams": system_params,
            "RequestParams": request_params if request_params is not None else {},
        }

        # 清理null值和空字符串（前端JS逻辑）
        body = self._clean_nulls(body)

        body_str = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
        encrypted_body = _encrypt_aes(body_str + AES_SALT)
        return encrypted_body

    def call_old_api(self, api_name, request_params=None, token=None, user_code=None, university_code=None):
        """调用旧版API: POST /service/apis.do?ApiName={api_name}

        所有API统一使用SPA的SystemParams格式（ClientType=0, ClientId等）
        分页API额外包含PageContext字段
        """
        # 判断是否为分页API（需要PageContext）
        paginated_apis = [
            "GetMyTaskItemByAnswerStatus",
        ]
        is_paginated = any(api_name.endswith(p) for p in paginated_apis)

        page_context = None
        if is_paginated:
            page_context = {
                "PageIndex": 1,
                "PageSize": 10,
                "SortBy": "QuestionnaireName",
                "Direction": "asc",
                "IsGBKSort": False,
            }

        encrypted_body = self._build_and_encrypt_body(
            api_name, request_params, token, user_code, university_code,
            page_context=page_context,
        )

        url = f"{self.base_url}/service/apis.do?ApiName={api_name}"
        try:
            resp = self.session.post(url, data=encrypted_body, headers={
                'Content-Type': 'application/json; charset=utf-8',
            }, timeout=30, allow_redirects=False)
        except requests.RequestException as e:
            raise EvalNetworkError(f"网络请求失败: {e}")

        return self._parse_old_response(resp, api_name)

    def call_apiservice(self, api_name, request_params=None, token=None, encrypted=True):
        """调用新版API: POST /apiservice/{api_name}

        SPA实际格式：发送加密的 {SystemParams, RequestParams}，SystemParams包含SERVICE_TYPE="apiservice"
        """
        _token = token or self.token
        url = f"{self.base_url}/apiservice/{api_name}"

        encrypted_body = self._build_and_encrypt_body(
            api_name, request_params, _token,
            service_type="apiservice",
        )

        headers = {
            'Content-Type': 'application/json; charset=utf-8',
        }

        try:
            resp = self.session.post(url, data=encrypted_body, headers=headers, timeout=30, allow_redirects=False)
        except requests.RequestException as e:
            raise EvalNetworkError(f"网络请求失败: {e}")

        return self._parse_apiservice_response(resp, api_name)

    def call_questionnaire(self, api_name, request_params=None, token=None, encrypted=True):
        """调用问卷API: POST /questionnaire/{api_name}

        SPA实际格式：发送加密的 {SystemParams, RequestParams}，SystemParams包含SERVICE_TYPE="questionnaire"
        """
        _token = token or self.token
        url = f"{self.base_url}/questionnaire/{api_name}"

        encrypted_body = self._build_and_encrypt_body(
            api_name, request_params, _token,
            service_type="questionnaire",
        )

        headers = {
            'Content-Type': 'application/json; charset=utf-8',
        }

        try:
            resp = self.session.post(url, data=encrypted_body, headers=headers, timeout=30, allow_redirects=False)
        except requests.RequestException as e:
            raise EvalNetworkError(f"网络请求失败: {e}")

        return self._parse_apiservice_response(resp, api_name)

    def _parse_old_response(self, resp, api_name=""):
        """解析旧版API响应"""
        if resp.status_code != 200:
            raise EvalAPIError(f"API返回HTTP {resp.status_code}", status_code=resp.status_code)

        text = resp.text.strip()
        data = None

        # 先尝试直接JSON解析
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # 尝试AES解密
            try:
                decrypted = _decrypt_aes(text)
                decrypted = _clean_nulls(decrypted)
                # 去掉salt
                if decrypted.endswith(AES_SALT):
                    decrypted = decrypted[:-len(AES_SALT)]
                data = json.loads(decrypted)
            except Exception:
                raise EvalAPIError(f"无法解析API响应: {text[:200]}", status_code=resp.status_code)

        if not isinstance(data, dict):
            return data

        code = data.get("Code")
        # -3 = token过期
        if str(code) == "-3":
            raise EvalTokenExpiredError(f"Token已过期 (API: {api_name})")

        # 自动更新token
        if data.get("Token"):
            self.token = data["Token"]

        return data

    def _parse_apiservice_response(self, resp, api_name=""):
        """解析新版API响应"""
        if resp.status_code == 422:
            raise EvalTokenExpiredError(f"Token已过期或无效 (API: {api_name})")

        if resp.status_code != 200:
            raise EvalAPIError(f"API返回HTTP {resp.status_code}", status_code=resp.status_code)

        text = resp.text.strip()
        data = None

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            try:
                decrypted = _decrypt_aes(text)
                decrypted = _clean_nulls(decrypted)
                if decrypted.endswith(AES_SALT):
                    decrypted = decrypted[:-len(AES_SALT)]
                data = json.loads(decrypted)
            except Exception:
                raise EvalAPIError(f"无法解析API响应: {text[:200]}", status_code=resp.status_code)

        if not isinstance(data, dict):
            return data

        # 检查token/session过期
        success = data.get("Success", data.get("success"))
        message = str(data.get("Message", data.get("message", ""))).lower()
        if success is False and ("token" in message or "session" in message):
            raise EvalTokenExpiredError(f"Token/Session已过期 (API: {api_name}): {message}")

        # 自动更新token
        if data.get("Token"):
            self.token = data["Token"]

        return data


# ═══════════════════════════════════════════════════════════════
# 4. Cookie Manager Class
# ═══════════════════════════════════════════════════════════════

class CookieManager:
    """Cookie管理器 - 保存/加载/复用Cookie"""

    COOKIE_PATH = Path.home() / ".zzu_eval_cookies.json"

    def _read_cookie_file(self):
        """读取Cookie文件，返回dict格式（兼容旧格式）"""
        if not self.COOKIE_PATH.exists():
            return None
        try:
            with open(self.COOKIE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                # 旧格式：纯数组
                return {"cookies": data, "fp_visitor_id": ""}
            elif isinstance(data, dict):
                # 新格式：dict with cookies key
                return data
            return None
        except Exception:
            return None

    def save_cookies(self, session, domain_filter=None):
        """从requests.Session保存Cookie到JSON（新格式）"""
        cookies = []
        for cookie in session.cookies:
            if domain_filter and domain_filter not in (cookie.domain or ""):
                continue
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            })

        # 读取现有文件，保留fp_visitor_id
        existing = self._read_cookie_file()
        fp_visitor_id = ""
        if existing and existing.get("fp_visitor_id"):
            fp_visitor_id = existing["fp_visitor_id"]

        save_data = {
            "cookies": cookies,
            "fp_visitor_id": fp_visitor_id,
        }

        try:
            with open(self.COOKIE_PATH, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            # 设置文件权限为仅所有者可读写
            try:
                os.chmod(self.COOKIE_PATH, 0o600)
            except OSError:
                pass
            return True
        except Exception as e:
            print(f"    [!] 保存Cookie失败: {e}")
            return False

    def load_cookies(self, session, domain_filter=None):
        """从JSON加载Cookie到requests.Session（兼容旧格式）"""
        if not self.has_valid_cookies():
            return False
        try:
            data = self._read_cookie_file()
            if data is None:
                return False
            cookies = data.get("cookies", []) if isinstance(data, dict) else data
            for c in cookies:
                if domain_filter and domain_filter not in (c.get("domain") or ""):
                    continue
                session.cookies.set(
                    c["name"], c["value"],
                    domain=c.get("domain", ""),
                    path=c.get("path", "/"),
                )
            return True
        except Exception as e:
            print(f"    [!] 加载Cookie失败: {e}")
            return False

    def has_valid_cookies(self):
        """检查Cookie文件是否存在且非空（兼容旧格式）"""
        try:
            data = self._read_cookie_file()
            if data is None:
                return False
            if isinstance(data, dict):
                cookies = data.get("cookies", [])
                return bool(cookies)
            return bool(data)
        except Exception:
            return False

    def save_fp_visitor_id(self, fp_id):
        """保存fp_visitor_id到Cookie文件"""
        existing = self._read_cookie_file() or {"cookies": [], "fp_visitor_id": ""}
        existing["fp_visitor_id"] = fp_id
        try:
            with open(self.COOKIE_PATH, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            try:
                os.chmod(self.COOKIE_PATH, 0o600)
            except OSError:
                pass
        except Exception as e:
            print(f"    [!] 保存fp_visitor_id失败: {e}")

    def load_fp_visitor_id(self):
        """从Cookie文件加载fp_visitor_id，未找到返回None"""
        data = self._read_cookie_file()
        if data and isinstance(data, dict):
            fp_id = data.get("fp_visitor_id", "")
            if fp_id:
                return fp_id
        return None

    def clear_cookies(self):
        """删除Cookie文件"""
        try:
            if self.COOKIE_PATH.exists():
                self.COOKIE_PATH.unlink()
        except Exception:
            pass

    def try_login_with_cookies(self, session, deal_sso_url=DEAL_SSO_URL):
        """使用已保存的TGC Cookie尝试登录，返回token或None"""
        if not self.load_cookies(session, domain_filter="cas.s.zzu.edu.cn"):
            return None

        try:
            resp = session.get(deal_sso_url, allow_redirects=True, timeout=30)
            final_url = str(resp.url)
            token = self._extract_token_from_url(final_url)
            if token:
                return token

            # 如果被重定向到CAS登录页，说明TGC过期
            if "cas.s.zzu.edu.cn/cas/a/login" in final_url:
                print("    [!] TGC Cookie已过期，清除Cookie")
                self.clear_cookies()
                return None

            return None
        except Exception as e:
            print(f"    [!] Cookie登录失败: {e}")
            return None

    @staticmethod
    def _extract_token_from_url(url):
        """从URL中提取token"""
        if not url:
            return None
        # 尝试从hash fragment提取（支持 #token=xxx 和 #/path?token=xxx 格式）
        if "#" in url:
            fragment = url.split("#", 1)[-1]
            # 直接 #token=xxx 格式
            if fragment.startswith("token="):
                token = fragment.split("token=")[-1].split("&")[0]
                if token:
                    return unquote(token)
            # #/path?token=xxx 格式
            if "token=" in fragment:
                token_part = fragment.split("token=")[-1]
                token = token_part.split("&")[0]
                if token:
                    return unquote(token)
        # 尝试从query string提取
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "token" in params:
            return params["token"][0]
        return None


# ═══════════════════════════════════════════════════════════════
# 5. Chrome Cookie Importer Class
# ═══════════════════════════════════════════════════════════════

class CookieImporter:
    """从Chrome浏览器导入Cookie"""

    @staticmethod
    def _find_chrome_cookie_db():
        """跨平台检测Chrome Cookie数据库路径"""
        paths = []
        home = Path.home()

        # Windows
        win_path = home / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Cookies"
        if win_path.exists():
            paths.append(win_path)
        # Windows - 多Profile
        win_user_data = home / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
        if win_user_data.exists():
            for profile in win_user_data.iterdir():
                if profile.is_dir() and profile.name.startswith("Profile"):
                    cookie_file = profile / "Cookies"
                    if cookie_file.exists():
                        paths.append(cookie_file)

        # macOS
        mac_path = home / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Cookies"
        if mac_path.exists():
            paths.append(mac_path)

        # Linux
        linux_path = home / ".config" / "google-chrome" / "Default" / "Cookies"
        if linux_path.exists():
            paths.append(linux_path)

        return paths

    @staticmethod
    def _get_chrome_browser_key():
        """读取Chrome Local State，提取并解密浏览器密钥"""
        home = Path.home()
        local_state_paths = [
            home / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Local State",
            home / "Library" / "Application Support" / "Google" / "Chrome" / "Local State",
            home / ".config" / "google-chrome" / "Local State",
        ]

        for lsp in local_state_paths:
            if lsp.exists():
                try:
                    with open(lsp, 'r', encoding='utf-8') as f:
                        local_state = json.load(f)
                    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
                    # 去掉 'DPAPI' 前缀 (5 bytes)
                    if encrypted_key[:5] == b'DPAPI':
                        encrypted_key = encrypted_key[5:]
                    # Windows: DPAPI解密
                    if _HAS_WIN32CRYPT:
                        browser_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
                        return browser_key
                    return None
                except Exception as e:
                    print(f"    [!] 读取Chrome浏览器密钥失败: {e}")
                    return None
        return None

    @staticmethod
    def _dpapi_decrypt(data):
        """Windows DPAPI解密"""
        if not _HAS_WIN32CRYPT:
            raise EvalError("win32crypt未安装，无法解密Windows DPAPI数据。请运行: pip install pywin32")
        return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]

    @staticmethod
    def _aes_decrypt(encrypted_data, key):
        """AES-128-CBC解密，IV取前16字节"""
        try:
            iv = encrypted_data[:16]
            encrypted_data = encrypted_data[16:]
            if not _HAS_PYCRYPTODOME:
                raise EvalError("pycryptodome未安装")
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted_data)
            # PKCS7去填充
            pad_len = decrypted[-1]
            if 1 <= pad_len <= 16:
                decrypted = decrypted[:-pad_len]
            return decrypted.decode('utf-8')
        except Exception as e:
            raise EvalError(f"AES解密Cookie失败: {e}")

    @classmethod
    def decrypt_chrome_cookie_value(cls, encrypted_value, browser_key=None):
        """解密Chrome Cookie值"""
        if not encrypted_value:
            return ""

        # v10/v20 前缀 (Chrome 80+)
        if encrypted_value[:3] == b'v10' or encrypted_value[:3] == b'v20':
            if browser_key is None:
                browser_key = cls._get_chrome_browser_key()
            if browser_key is None:
                raise EvalError("无法获取Chrome浏览器密钥")
            return cls._aes_decrypt(encrypted_value[3:], browser_key)

        # 旧版Chrome: DPAPI直接解密
        if _HAS_WIN32CRYPT:
            try:
                return cls._dpapi_decrypt(encrypted_value).decode('utf-8')
            except Exception:
                pass

        return ""

    @classmethod
    def import_from_chrome(cls, domain_filter="cas.s.zzu.edu.cn"):
        """从Chrome导入Cookie"""
        if not _HAS_SQLITE3:
            raise EvalError("sqlite3不可用，无法读取Chrome Cookie数据库")

        cookie_db_paths = cls._find_chrome_cookie_db()
        if not cookie_db_paths:
            raise EvalError("未找到Chrome Cookie数据库")

        browser_key = cls._get_chrome_browser_key()
        all_cookies = []

        for db_path in cookie_db_paths:
            # 复制到临时文件避免锁定
            tmp_dir = tempfile.mkdtemp()
            tmp_db = os.path.join(tmp_dir, "Cookies")
            try:
                shutil.copy2(str(db_path), tmp_db)
            except Exception as e:
                print(f"    [!] 复制Cookie数据库失败: {e}")
                continue

            try:
                conn = sqlite3.connect(tmp_db)
                cursor = conn.cursor()
                if domain_filter:
                    cursor.execute(
                        "SELECT name, encrypted_value, host_key, path, is_secure, expires_utc "
                        "FROM cookies WHERE host_key LIKE ?",
                        (f"%{domain_filter}%",)
                    )
                else:
                    cursor.execute(
                        "SELECT name, encrypted_value, host_key, path, is_secure, expires_utc FROM cookies"
                    )
                rows = cursor.fetchall()
                conn.close()
            except Exception as e:
                print(f"    [!] 查询Cookie数据库失败: {e}")
                continue
            finally:
                try:
                    os.unlink(tmp_db)
                    os.rmdir(tmp_dir)
                except Exception:
                    pass

            for row in rows:
                name, encrypted_value, host_key, path, is_secure, expires_utc = row
                try:
                    value = cls.decrypt_chrome_cookie_value(encrypted_value, browser_key)
                    all_cookies.append({
                        "name": name,
                        "value": value,
                        "domain": host_key,
                        "path": path,
                        "secure": bool(is_secure),
                    })
                except Exception:
                    pass

        return all_cookies

    @staticmethod
    def inject_cookies_to_session(session, cookies):
        """将Cookie注入到requests.Session"""
        for c in cookies:
            session.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
            )

    @classmethod
    def quick_import(cls, session, cookie_string=None, from_chrome=False, domain="cas.s.zzu.edu.cn"):
        """便捷导入Cookie"""
        if cookie_string:
            # 解析 "name=value; name2=value2" 格式
            for pair in cookie_string.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    session.cookies.set(name.strip(), value.strip(), domain=domain)
            return True

        if from_chrome:
            try:
                cookies = cls.import_from_chrome(domain_filter=domain)
                cls.inject_cookies_to_session(session, cookies)
                return bool(cookies)
            except EvalError:
                raise
            except Exception as e:
                print(f"    [!] Chrome Cookie导入失败: {e}")
                return False

        return False


# ═══════════════════════════════════════════════════════════════
# 6. Auth Class
# ═══════════════════════════════════════════════════════════════

class LoginStrategy(Enum):
    AUTO = "auto"
    COOKIE_REUSE = "cookie_reuse"
    API_MFA = "api_mfa"
    PLAYWRIGHT = "playwright"
    COOKIE_IMPORT = "cookie_import"


class EvalAuth:
    """认证管理器 - 支持多种登录策略"""

    def __init__(self, api_client, cookie_manager=None):
        self.api_client = api_client
        self.cookie_manager = cookie_manager or CookieManager()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        # 加载或生成fp_visitor_id
        fp_id = self.cookie_manager.load_fp_visitor_id()
        if not fp_id:
            fp_id = secrets.token_hex(16)
            self.cookie_manager.save_fp_visitor_id(fp_id)
        self.api_client.fp_visitor_id = fp_id

    def login(self, username, password, strategy=LoginStrategy.AUTO, headless=True,
              cookie_import=False):
        """执行登录，返回 (token, user_info) 或抛出异常"""
        if strategy == LoginStrategy.AUTO:
            return self._login_auto(username, password, headless, cookie_import)
        elif strategy == LoginStrategy.COOKIE_REUSE:
            return self._login_cookie_reuse()
        elif strategy == LoginStrategy.API_MFA:
            return self._login_api_mfa(username, password)
        elif strategy == LoginStrategy.PLAYWRIGHT:
            return self._login_playwright(username, password, headless)
        elif strategy == LoginStrategy.COOKIE_IMPORT:
            return self._login_cookie_import()
        else:
            raise EvalAuthError(f"未知的登录策略: {strategy}")

    def _login_auto(self, username, password, headless, cookie_import):
        """AUTO策略：按顺序尝试 Cookie复用 → Chrome导入 → API登录 → Playwright"""
        # 1. Cookie复用
        print("    [AUTO] 尝试Cookie复用...")
        try:
            result = self._login_cookie_reuse()
            if result:
                print("    [✓] Cookie复用登录成功")
                return result
        except (EvalAuthError, EvalTokenExpiredError):
            pass

        # 2. Chrome Cookie导入
        if cookie_import:
            print("    [AUTO] 尝试Chrome Cookie导入...")
            try:
                result = self._login_cookie_import()
                if result:
                    print("    [✓] Chrome Cookie导入登录成功")
                    return result
            except (EvalAuthError, EvalTokenExpiredError):
                pass

        # 3. API登录（自动处理MFA）
        print("    [AUTO] 尝试API登录...")
        try:
            result = self._login_api_mfa(username, password)
            if result:
                print("    [✓] API登录成功")
                return result
        except EvalAuthError as e:
            print(f"    [!] API登录失败: {e}")

        # 4. Playwright
        if _HAS_PLAYWRIGHT:
            print("    [AUTO] 尝试Playwright登录...")
            try:
                result = self._login_playwright(username, password, headless)
                if result:
                    print("    [✓] Playwright登录成功")
                    return result
            except EvalAuthError as e:
                print(f"    [!] Playwright登录失败: {e}")

        raise EvalAuthError("所有登录策略均失败")

    def _login_cookie_reuse(self):
        """使用已保存的Cookie登录"""
        token = self.cookie_manager.try_login_with_cookies(
            self.api_client.session, DEAL_SSO_URL
        )
        if token:
            return self._finalize_login(token)
        return None

    def _login_cookie_import(self):
        """从Chrome导入Cookie登录"""
        try:
            CookieImporter.quick_import(
                self.api_client.session, from_chrome=True, domain="cas.s.zzu.edu.cn"
            )
        except EvalError as e:
            print(f"    [!] Chrome Cookie导入失败: {e}")
            return None

        # 用导入的Cookie访问DealSSO
        try:
            resp = self.api_client.session.get(DEAL_SSO_URL, allow_redirects=True, timeout=30)
            final_url = str(resp.url)
            token = CookieManager._extract_token_from_url(final_url)
            if token:
                return self._finalize_login(token)
            if "cas.s.zzu.edu.cn/cas/a/login" in final_url:
                print("    [!] Chrome导入的Cookie已过期")
                return None
        except Exception as e:
            print(f"    [!] Cookie导入后SSO跳转失败: {e}")
        return None

    def _login_api_mfa(self, username, password):
        """CAS SSO登录（自动处理MFA）"""
        return self._cas_sso_login_with_mfa(username, password)

    def _handle_mfa_after_login(self, username, encrypted_pwd, page_text, execution=""):
        """MFA安全验证流程"""
        session = self.api_client.session
        login_url = f"{CAS_LOGIN_URL}?service={CAS_SERVICE_URL}"

        try:
            # Step 1: detect MFA
            detect_resp = session.post(
                f"{CAS_BASE}/mfa/detect",
                data={"username": username, "password": encrypted_pwd, "fpVisitorId": self.api_client.fp_visitor_id},
                timeout=15,
            )
            detect_data = {}
            try:
                detect_data = detect_resp.json()
            except Exception:
                pass

            # 检查是否需要MFA
            mfa_data = detect_data.get("data", {})
            mfa_needed = mfa_data.get("need", True)

            if not mfa_needed:
                # 设备已信任，不需要MFA，提交带mfaState的登录表单
                print("    [MFA] 当前设备已信任，跳过安全验证")
                trusted_mfa_state = mfa_data.get("state", "")
                # 重新获取execution（可能已过期）
                new_execution = execution
                try:
                    resp2 = session.get(login_url, timeout=30)
                    soup2 = BeautifulSoup(resp2.text, 'html.parser')
                    exec_input = soup2.find('input', {'name': 'execution'})
                    if exec_input:
                        new_execution = exec_input.get('value', execution)
                except Exception:
                    pass
                form_data = {
                    "username": username,
                    "password": encrypted_pwd,
                    "captcha": "",
                    "currentMenu": "1",
                    "failN": "-1",
                    "mfaState": trusted_mfa_state,
                    "execution": new_execution,
                    "_eventId": "submit",
                    "geolocation": "",
                    "fpVisitorId": self.api_client.fp_visitor_id,
                    "trustAgent": "",
                    "submit1": "Login1",
                }
                form_headers = {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": CAS_BASE,
                    "Referer": f"{CAS_LOGIN_URL}?service={quote(CAS_SERVICE_URL)}",
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "same-origin",
                    "sec-fetch-user": "?1",
                    "upgrade-insecure-requests": "1",
                }
                resp = session.post(
                    f"{CAS_LOGIN_URL}?service={CAS_SERVICE_URL}",
                    data=form_data,
                    headers=form_headers,
                    allow_redirects=False,
                    timeout=30,
                )
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if "ticket=" in location:
                        return self._follow_deal_sso(resp)
                # 如果没成功跳转，打印调试信息并继续正常MFA流程
                print(f"    [MFA] 信任设备跳过失败(状态:{resp.status_code})，继续安全验证流程...")

            mfa_state = ""
            if detect_data.get("code") == 0 or detect_data.get("status") == 200:
                mfa_state = mfa_data.get("state", "")

            if not mfa_state:
                mfa_state_patterns = [
                    r'mfaState\s*:\s*"([A-Za-z0-9]+)"',
                    r'mfaState\s*=\s*"([A-Za-z0-9]+)"',
                    r'"mfaState"\s*:\s*"([A-Za-z0-9]+)"',
                    r"name='mfaState'\s+value='([A-Za-z0-9]+)'",
                ]
                for pattern in mfa_state_patterns:
                    match = re.search(pattern, page_text)
                    if match:
                        mfa_state = match.group(1)
                        break

            if not mfa_state:
                raise EvalAuthError("无法获取MFA状态")

            # Step 2: initByType securephone
            init_resp = session.get(
                f"{CAS_BASE}/mfa/initByType/securephone",
                params={"state": mfa_state},
                timeout=15,
            )
            init_data = {}
            try:
                init_data = init_resp.json()
            except Exception:
                pass
            mfa_info = init_data.get("data", {})
            attest_server_url = mfa_info.get("attestServerUrl", "")
            gid = mfa_info.get("gid", "")
            secure_phone = mfa_info.get("securePhone", mfa_info.get("phone", ""))

            if secure_phone:
                print(f"    [MFA] 安全手机: {secure_phone[:3]}****{secure_phone[-4:]}")

            # Step 3: 发送短信验证码
            if attest_server_url and gid:
                send_resp = session.post(
                    f"{attest_server_url}/api/guard/securephone/send",
                    json={"gid": gid},
                    timeout=15,
                )
                print("    [MFA] 短信验证码已发送")
            else:
                print("    [MFA] 尝试发送短信验证码...")
                try:
                    session.get(
                        f"{CAS_BASE}/mfa/initByType/securephone",
                        params={"state": mfa_state},
                        timeout=15,
                    )
                except Exception:
                    pass

            # Step 4: 用户输入验证码
            sms_code = input("    请输入收到的短信验证码: ").strip()
            if not sms_code:
                raise EvalAuthError("未输入短信验证码")

            # Step 5: 验证短信验证码
            if attest_server_url and gid:
                valid_resp = session.post(
                    f"{attest_server_url}/api/guard/securephone/valid",
                    json={"gid": gid, "code": sms_code},
                    timeout=15,
                )
                valid_data = valid_resp.json() if valid_resp.status_code == 200 else {}
                if valid_data.get("data", {}).get("status") != 2:
                    raise EvalAuthError("短信验证码验证失败")

            print("    [MFA] 短信验证成功！")

            # 询问是否设为可信客户端
            trust_choice = input("    是否将当前设备设为可信客户端？后续登录可跳过安全验证 (y/n): ").strip().lower()
            trust_agent = "true" if trust_choice == "y" else ""
            if trust_agent:
                print("    [✓] 已设为可信客户端")

            # Step 6: 重新获取CAS登录页面（刷新execution）
            new_execution = execution
            try:
                resp = session.get(login_url, timeout=30)
                soup = BeautifulSoup(resp.text, 'html.parser')
                execution_input = soup.find('input', {'name': 'execution'})
                if execution_input:
                    new_execution = execution_input.get('value', execution)
            except Exception:
                pass

            # Step 7: 提交带MFA的登录表单
            mfa_form_data = {
                "username": username,
                "password": encrypted_pwd,
                "captcha": "",
                "currentMenu": "1",
                "failN": "-1",
                "mfaState": mfa_state,
                "code": sms_code,
                "execution": new_execution,
                "_eventId": "submit",
                "geolocation": "",
                "fpVisitorId": self.api_client.fp_visitor_id,
                "trustAgent": trust_agent,
                "submit1": "Login1",
            }
            mfa_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": CAS_BASE,
                "Referer": f"{CAS_LOGIN_URL}?service={quote(CAS_SERVICE_URL)}",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
                "sec-fetch-user": "?1",
                "upgrade-insecure-requests": "1",
            }
            try:
                resp = session.post(
                    f"{CAS_LOGIN_URL}?service={CAS_SERVICE_URL}",
                    data=mfa_form_data,
                    headers=mfa_headers,
                    allow_redirects=False,
                    timeout=30,
                )
            except requests.RequestException as e:
                raise EvalNetworkError(f"提交MFA验证失败: {e}")

            # 检查是否302重定向含ticket
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                if "ticket=" in location:
                    return self._follow_deal_sso(resp)

        except EvalAuthError:
            raise
        except EvalNetworkError:
            raise
        except Exception as e:
            raise EvalAuthError(f"MFA验证流程失败: {e}")

        return self._follow_deal_sso(resp)

    def _cas_sso_login_with_mfa(self, username, password):
        """CAS SSO登录 - 自动处理MFA"""
        session = self.api_client.session

        # 0. 加载之前保存的CAS Cookie（TGC、CAS_MFA_TRUSTED等）
        # 这样CAS可以识别已认证的session或可信设备
        self.cookie_manager.load_cookies(session, domain_filter="cas.s.zzu.edu.cn")

        # 1. 获取登录页面
        login_url = f"{CAS_LOGIN_URL}?service={CAS_SERVICE_URL}"
        try:
            resp = session.get(login_url, timeout=30, allow_redirects=False)
            # 如果TGC有效，CAS会直接302到service URL
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                if "ticket=" in location:
                    print("    [CAS] TGC有效，跳过登录直接签发ticket")
                    return self._follow_deal_sso(resp)
                # 跟随重定向
                resp = session.get(location, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise EvalNetworkError(f"访问CAS登录页失败: {e}")

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 2. 解析表单参数
        execution = ""
        input_execution = soup.find('input', {'name': 'execution'})
        if input_execution:
            execution = input_execution.get('value', '')

        # 3. 加密密码
        encrypted_pwd = self._encrypt_password(password)

        # 4. 提交登录
        form_data = {
            "username": username,
            "password": encrypted_pwd,
            "captcha": "",
            "currentMenu": "1",
            "failN": "-1",
            "mfaState": "",
            "execution": execution,
            "_eventId": "submit",
            "geolocation": "",
            "fpVisitorId": self.api_client.fp_visitor_id,
            "trustAgent": "",
            "submit1": "Login1",
        }
        form_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": CAS_BASE,
            "Referer": f"{CAS_LOGIN_URL}?service={quote(CAS_SERVICE_URL)}",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        }

        try:
            resp = session.post(
                f"{CAS_LOGIN_URL}?service={CAS_SERVICE_URL}",
                data=form_data,
                headers=form_headers,
                allow_redirects=False,
                timeout=30,
            )
        except requests.RequestException as e:
            raise EvalNetworkError(f"提交CAS登录表单失败: {e}")

        # 如果直接302且含ticket，说明无需MFA
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if "ticket=" in location:
                return self._follow_deal_sso(resp)

        # 检测MFA
        if resp.status_code == 200:
            page_text = resp.text
            mfa_needed = (
                "mfaState" in page_text
                or "安全验证" in page_text
                or "mfaEnabled" in page_text
                or "appPushStatusAlertMessage" in page_text
            )

            if mfa_needed:
                return self._handle_mfa_after_login(username, encrypted_pwd, page_text, execution)

            raise EvalAuthError("CAS登录失败，可能账号密码错误")

        # 5. 处理重定向获取token
        return self._follow_deal_sso(resp)

    def _encrypt_password(self, password):
        """RSA加密密码"""
        session = self.api_client.session
        try:
            resp = session.get(CAS_PUBLIC_KEY_URL, timeout=15)
            resp.raise_for_status()
            public_key = resp.text.strip()
        except Exception as e:
            raise RuntimeError(f"获取RSA公钥失败: {e}，无法安全加密密码，登录终止") from e

        try:
            from Crypto.PublicKey import RSA
            from Crypto.Cipher import PKCS1_v1_5
            key = RSA.import_key(public_key)
            cipher = PKCS1_v1_5.new(key)
            encrypted = cipher.encrypt(password.encode('utf-8'))
            return "__RSA__" + base64.b64encode(encrypted).decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"RSA加密失败: {e}，无法安全加密密码，登录终止") from e

    def _follow_deal_sso(self, initial_response):
        """手动跟随重定向，提取token"""
        session = self.api_client.session
        resp = initial_response
        max_redirects = 10

        for _ in range(max_redirects):
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get('Location', '')
                if not location:
                    break
                # 处理相对URL
                if location.startswith('/'):
                    parsed = urlparse(str(resp.url) if hasattr(resp, 'url') and resp.url else CAS_BASE)
                    location = f"{parsed.scheme}://{parsed.netloc}{location}"
                try:
                    resp = session.get(location, allow_redirects=False, timeout=30)
                except requests.RequestException:
                    break
            else:
                break

        # 从最终URL提取token
        final_url = str(resp.url) if hasattr(resp, 'url') and resp.url else ""
        if not final_url and resp.status_code in (301, 302, 303, 307, 308):
            final_url = resp.headers.get('Location', '')

        token = CookieManager._extract_token_from_url(final_url)

        # 也尝试从响应体中提取
        if not token and resp.status_code == 200:
            token = CookieManager._extract_token_from_url(resp.text)

        if token:
            return self._finalize_login(token)

        # 如果重定向到了CAS登录页，说明登录失败
        if "cas.s.zzu.edu.cn/cas/a/login" in final_url:
            # 尝试提取CAS错误信息
            error_msg = "CAS登录失败，请检查账号密码"
            try:
                soup = BeautifulSoup(resp.text, 'html.parser')
                err_el = soup.find('div', {'id': 'msg'}) or soup.find('span', {'class': 'error'}) or soup.find('div', {'class': 'alert-danger'})
                if err_el and err_el.get_text(strip=True):
                    error_msg = f"CAS登录失败: {err_el.get_text(strip=True)}"
            except Exception:
                pass
            raise EvalAuthError(error_msg)

        raise EvalAuthError(f"未能从SSO跳转中提取token，最终URL: {final_url[:200]}")

    def _finalize_login(self, sso_token):
        """完成登录：获取用户上下文，设置session信息"""
        try:
            result = self.api_client.call_apiservice(
                "Login/GetUserContextByToken",
                request_params=sso_token,
                token=sso_token,
                encrypted=False,
            )
            if isinstance(result, dict):
                user_info = result.get("Value", result.get("Data", result))
                if isinstance(user_info, dict):
                    token = user_info.get("Token", sso_token)
                    self.api_client.set_token(token)
                    self.api_client.set_user_info(
                        user_info.get("Code", ""),
                        user_info.get("UniversityCode", "10459"),
                        semester=user_info.get("CurrentSemester"),
                    )
                    # 保存Cookie
                    self.cookie_manager.save_cookies(self.api_client.session)
                    if hasattr(self.api_client, 'fp_visitor_id') and self.api_client.fp_visitor_id:
                        self.cookie_manager.save_fp_visitor_id(self.api_client.fp_visitor_id)
                    return token, user_info
        except (EvalAPIError, EvalTokenExpiredError, EvalNetworkError) as e:
            print(f"    [!] 获取用户上下文失败: {e}")

        # 即使获取用户上下文失败，也返回token
        self.api_client.set_token(sso_token)
        return sso_token, {}

    def _login_playwright(self, username, password, headless=True):
        """Playwright浏览器登录 - 直接从浏览器URL提取token"""
        if not _HAS_PLAYWRIGHT:
            raise EvalAuthError("playwright未安装，无法使用浏览器登录")

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
        )
        self._page = self._context.new_page()
        self._page.on("dialog", lambda dialog: dialog.accept())

        # 拦截网络请求，捕获token
        captured_tokens = []

        def _on_response(response):
            try:
                url = response.url
                # 从URL中提取token
                t = CookieManager._extract_token_from_url(url)
                if t:
                    captured_tokens.append(t)
                # 从响应头中提取token
                header_token = response.headers.get("token", "")
                if header_token and header_token not in captured_tokens:
                    captured_tokens.append(header_token)
            except Exception:
                pass

        self._page.on("response", _on_response)

        try:
            # 直接访问CAS登录页
            cas_login_url = f"{CAS_LOGIN_URL}?service={quote(CAS_SERVICE_URL)}"
            print("    [Playwright] 正在打开CAS登录页面...")
            self._page.goto(cas_login_url, wait_until="domcontentloaded", timeout=30000)

            # 等待Vue渲染完成并填写表单
            print("    [Playwright] 正在填写登录表单...")
            try:
                self._page.wait_for_selector("input.el-input__inner", timeout=15000)
            except Exception:
                # 回退到SPA登录页
                print("    [Playwright] CAS表单未找到，尝试SPA登录页...")
                self._page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
                username_input = (
                    self._page.query_selector('input[placeholder*="学号"]')
                    or self._page.query_selector('input[placeholder*="账号"]')
                    or self._page.query_selector('.login-form input[type="text"]')
                )
                if not username_input:
                    raise EvalAuthError("未找到用户名输入框")
                username_input.fill(username)
                password_input = self._page.query_selector('input[type="password"]')
                if not password_input:
                    raise EvalAuthError("未找到密码输入框")
                password_input.fill(password)
                login_btn = (
                    self._page.query_selector('button.login-btn')
                    or self._page.query_selector('button:has-text("登录")')
                )
                if not login_btn:
                    raise EvalAuthError("未找到登录按钮")
                login_btn.click()
            else:
                # CAS Vue/Element UI 表单
                username_input = self._page.locator('input.el-input__inner[type="text"]').first
                password_input = self._page.locator('input.el-input__inner[type="password"]').first

                username_input.fill(username)
                password_input.fill(password)

                # 触发Vue响应式更新
                username_input.dispatch_event("input")
                password_input.dispatch_event("input")

                # 验证隐藏输入框是否同步
                try:
                    hidden_username = self._page.locator('input[name="username"][type="hidden"]').first
                    filled_user = hidden_username.input_value()
                    if filled_user != username:
                        self._page.evaluate(
                            """([u, p]) => {
                                const hu = document.querySelector('input[name="username"][type="hidden"]');
                                const hp = document.querySelector('input[name="password"][type="hidden"]');
                                if (hu) hu.value = u;
                                if (hp) hp.value = p;
                            }""",
                            [username, password],
                        )
                except Exception:
                    pass

                # 点击登录按钮
                login_btn = self._page.locator("button.login-btn").first
                login_btn.click()

            print("    [Playwright] 已点击登录，等待认证跳转...")

            # 等待登录完成 - 从浏览器URL直接提取token
            token = self._wait_for_token_in_browser(captured_tokens, max_wait=300, check_interval=1)

            if not token:
                # 最后的回退：用浏览器Cookie跟随DealSSO重定向
                print("    [Playwright] 尝试从Cookie跟随DealSSO重定向获取token...")
                for cookie in self._context.cookies():
                    self.api_client.session.cookies.set(
                        cookie["name"], cookie["value"],
                        domain=cookie.get("domain", ""),
                        path=cookie.get("path", "/"),
                    )
                token = self._cookie_deal_sso_fallback()

            if not token:
                raise EvalAuthError("登录后未获取到token，请尝试使用 --strategy api_mfa 策略")

            # 将浏览器Cookie同步到requests.Session
            for cookie in self._context.cookies():
                self.api_client.session.cookies.set(
                    cookie["name"], cookie["value"],
                    domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"),
                )

            # 用获取到的token初始化会话
            return self._finalize_login(token)

        except EvalAuthError:
            raise
        except Exception as e:
            raise EvalAuthError(f"Playwright登录失败: {e}")

    def _wait_for_token_in_browser(self, captured_tokens=None, max_wait=300, check_interval=1):
        """等待浏览器URL中出现token，从多种来源提取"""
        if captured_tokens is None:
            captured_tokens = []
        elapsed = 0
        mfa_prompted = False
        on_jxpj = False

        while elapsed < max_wait:
            current_url = self._page.url

            # 1. 从URL中提取token
            token = CookieManager._extract_token_from_url(current_url)
            if token:
                print(f"    [Playwright] 从浏览器URL提取到token")
                return token

            # 2. 从拦截的网络请求中提取token
            if captured_tokens:
                print(f"    [Playwright] 从网络请求中捕获到token")
                return captured_tokens[0]

            # 3. 检查是否已到达评价系统主页
            if "jxpj.v.zzu.edu.cn" in current_url and "/user/login" not in current_url and "cas.s.zzu.edu.cn" not in current_url:
                if not on_jxpj:
                    on_jxpj = True
                    print(f"    [Playwright] 已到达评价系统页面: {current_url[:100]}")

                # 从localStorage获取token
                try:
                    local_token = self._page.evaluate("() => localStorage.getItem('token')")
                    if local_token:
                        print(f"    [Playwright] 从localStorage提取到token")
                        return local_token
                except Exception:
                    pass

                # 从sessionStorage获取token
                try:
                    session_token = self._page.evaluate("() => sessionStorage.getItem('token')")
                    if session_token:
                        print(f"    [Playwright] 从sessionStorage提取到token")
                        return session_token
                except Exception:
                    pass

                # 从页面全局变量获取token
                try:
                    global_token = self._page.evaluate("""() => {
                        if (window.token) return window.token;
                        if (window.__token__) return window.__token__;
                        if (window.store && window.store.state && window.store.state.token) return window.store.state.token;
                        return null;
                    }""")
                    if global_token:
                        print(f"    [Playwright] 从全局变量提取到token")
                        return global_token
                except Exception:
                    pass

                # 等待页面完全加载后再检查URL
                if not token:
                    try:
                        self._page.wait_for_load_state("networkidle", timeout=5000)
                        final_url = self._page.url
                        token = CookieManager._extract_token_from_url(final_url)
                        if token:
                            return token
                        # 再次检查localStorage
                        local_token = self._page.evaluate("() => localStorage.getItem('token')")
                        if local_token:
                            return local_token
                    except Exception:
                        pass

            # 如果在CAS页面且需要MFA，提示用户
            if "cas.s.zzu.edu.cn" in current_url and not mfa_prompted:
                try:
                    mfa_visible = self._page.evaluate("""() => {
                        return !!document.querySelector('.mfa-content, .securephone-btn, [class*="mfa"]');
                    }""")
                    if mfa_visible:
                        print("    [Playwright] CAS需要安全验证，请在浏览器中完成验证...")
                        print("    [Playwright] 等待验证完成（最多5分钟）...")
                        mfa_prompted = True
                except Exception:
                    pass

            time.sleep(check_interval)
            elapsed += check_interval

        # 超时前最后检查一次
        if captured_tokens:
            return captured_tokens[0]

        return None

    def _cookie_deal_sso_fallback(self):
        """使用requests.Session中的Cookie跟随DealSSO重定向获取token"""
        session = self.api_client.session
        try:
            resp = session.get(DEAL_SSO_URL, timeout=30, allow_redirects=False)
            max_redirects = 10
            current_url = DEAL_SSO_URL

            for step in range(max_redirects):
                if resp.status_code not in (301, 302, 303, 307, 308):
                    break
                next_url = resp.headers.get("Location", "")
                if not next_url:
                    break
                if next_url.startswith("/"):
                    parsed = urlparse(current_url)
                    next_url = f"{parsed.scheme}://{parsed.netloc}{next_url}"
                if "cas.s.zzu.edu.cn/cas/a/login" in next_url:
                    return None
                token = CookieManager._extract_token_from_url(next_url)
                if token:
                    return token
                current_url = next_url
                try:
                    resp = session.get(current_url, timeout=30, allow_redirects=False)
                except requests.RequestException:
                    break

            # 检查最终URL和响应体
            token = CookieManager._extract_token_from_url(current_url)
            if token:
                return token
            if resp.status_code == 200:
                token = CookieManager._extract_token_from_url(resp.text)
                if token:
                    return token
        except Exception:
            pass
        return None

    def close_playwright(self):
        """关闭Playwright资源"""
        for resource in [self._page, self._context, self._browser]:
            if resource:
                try:
                    resource.close()
                except Exception:
                    pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._page = self._context = self._browser = self._playwright = None


# ═══════════════════════════════════════════════════════════════
# 8. Evaluator Class
# ═══════════════════════════════════════════════════════════════

class EvalAutoFiller:
    """评价自动填写器 - API直连模式

    完整流程（基于SPA逆向分析）：
    1. get_unfinished_tasks → GetMyTaskItemByAnswerStatus (old_api)
    2. get_questionnaire_header → GetFinalQuestionnaireHeaderAsync (questionnaire, 需PersonCode)
    3. get_questionnaire_detail → GetFinalQuestionnaireAsync (questionnaire)
    4. _generate_auth_key → RSA加密"DetailId&PersonCode" (公钥来自Login/GetPublicKey)
    5. _submit_single_course → Mycos.JP.Questionnaire.SaveAnswer (old_api)
    """

    def __init__(self, api_client, auth):
        self.api_client = api_client
        self.auth = auth
        self._rsa_public_key = None  # 缓存RSA公钥

    def get_unfinished_tasks(self):
        """获取未完成任务列表"""
        try:
            result = self.api_client.call_old_api(
                "Mycos.JP.MyTask.MyTask.GetMyTaskItemByAnswerStatus",
                request_params={
                    "Source": "pc",
                    "Status": "UnFinished",
                    "IsIncludeHistorySemester": 1,
                    "Filters": {},
                },
            )
        except EvalTokenExpiredError:
            raise
        except (EvalAPIError, EvalNetworkError) as e:
            print(f"    [!] 获取任务列表失败: {e}")
            return []

        if not isinstance(result, dict):
            return []

        items = []
        val = result.get("Value", result.get("Data"))
        if val:
            if isinstance(val, dict):
                items = val.get("List", val.get("Items", val.get("Data", val.get("Rows", []))))
            elif isinstance(val, list):
                items = val
        elif isinstance(result, list):
            items = result

        return items if isinstance(items, list) else []

    def get_questionnaire_header(self, questionnaire_id, task_id):
        """获取问卷头部信息（含课程教师列表和DetailId）

        API: FinalTaskAndQuestionnaire/GetFinalQuestionnaireHeaderAsync (questionnaire路由)
        关键参数: PersonCode（必须，否则返回"答题人不在问卷调查范围"）

        返回: CourseList，每项含TeacherList（DetailId, AnswerStatus等）
        """
        try:
            result = self.api_client.call_questionnaire(
                "FinalTaskAndQuestionnaire/GetFinalQuestionnaireHeaderAsync",
                request_params={
                    "QuestionnaireId": str(questionnaire_id),
                    "TaskId": int(task_id) if isinstance(task_id, str) else task_id,
                    "PersonCode": self.api_client.user_code,
                },
            )
            if isinstance(result, dict):
                val = result.get("Value", result.get("Data"))
                if val and isinstance(val, dict):
                    return val
        except (EvalAPIError, EvalNetworkError) as e:
            print(f"    [!] 获取问卷头部失败: {e}")
        return None

    def get_questionnaire_detail(self, questionnaire_id, task_info=None):
        """获取问卷题目详情

        Final类型: GetFinalQuestionnaireAsync → 返回Items数组（17个题目）
        每个Item结构: {Id, SortNumber, SubjectType, Score, Props: {Items: {Options: [...]}}}
        SubjectType: 1=单选, 4=文本题
        """
        eva_code = "Final"
        task_id = None
        if task_info:
            eva_code = task_info.get("EvaCode", "Final")
            task_id = task_info.get("TaskId")

        # Final类型专用API
        if eva_code == "Final":
            try:
                params = {"QuestionnaireId": str(questionnaire_id)}
                if task_id is not None:
                    params["TaskId"] = int(task_id) if isinstance(task_id, str) else task_id

                result = self.api_client.call_questionnaire(
                    "FinalTaskAndQuestionnaire/GetFinalQuestionnaireAsync",
                    request_params=params,
                )
                if isinstance(result, dict):
                    value = result.get("Value", result.get("Data"))
                    if value and isinstance(value, dict):
                        items = value.get("Items", [])
                        if items:
                            return value
            except (EvalAPIError, EvalNetworkError) as e:
                print(f"    [!] GetFinalQuestionnaireAsync失败: {e}")

        # 通用回退：old_api
        try:
            params = {"QuestionnaireId": str(questionnaire_id)}
            if task_id is not None:
                params["TaskId"] = int(task_id) if isinstance(task_id, str) else task_id

            result = self.api_client.call_old_api(
                "Mycos.JP.Questionnaire.GetQuestionnareDetail",
                request_params=params,
            )
            if isinstance(result, dict) and result.get("Value"):
                return result["Value"]
        except (EvalAPIError, EvalNetworkError) as e:
            print(f"    [!] GetQuestionnareDetail失败: {e}")

        return None

    def _get_rsa_public_key(self):
        """获取RSA公钥（缓存）"""
        if self._rsa_public_key:
            return self._rsa_public_key

        try:
            result = self.api_client.call_apiservice("Login/GetPublicKey")
            if isinstance(result, dict):
                val = result.get("Value", result.get("Data"))
                if val and isinstance(val, dict):
                    self._rsa_public_key = val
                    return val
        except (EvalAPIError, EvalNetworkError) as e:
            print(f"    [!] 获取RSA公钥失败: {e}")
        return None

    def _generate_auth_key(self, detail_id, person_code):
        """生成AuthKey: RSA加密"DetailId&PersonCode"

        算法: RSA-1024, PKCS1_v1_5填充, 输出hex字符串
        公钥来源: Login/GetPublicKey API → {PublicKey(指数), PublicValue(模数)}
        """
        pk = self._get_rsa_public_key()
        if not pk:
            return ""

        try:
            from Crypto.PublicKey import RSA
            from Crypto.Cipher import PKCS1_v1_5

            e = int(pk["PublicKey"], 16)
            n = int(pk["PublicValue"], 16)
            key = RSA.construct((n, e))
            cipher = PKCS1_v1_5.new(key)

            plaintext = f"{detail_id}&{person_code}"
            encrypted = cipher.encrypt(plaintext.encode("utf-8"))
            return encrypted.hex()
        except Exception as e:
            print(f"    [!] AuthKey生成失败: {e}")
            return ""

    def auto_fill_questionnaire(self, questionnaire_id, task_info=None):
        """自动填写并提交整个任务的所有课程评价

        完整流程:
        1. 获取主问卷课程教师列表 → GetFinalQuestionnaireHeaderAsync
        2. 获取子问卷课程（实验课等）→ FinalMyTask/GetMyTaskItemDetailAsync
        3. 对每个子问卷: 获取题目+header → 提交
        4. 对主问卷: 获取题目 → 提交未评价的教师
        """
        task_id = task_info.get("TaskId") if task_info else None
        eva_code = task_info.get("EvaCode", "Final") if task_info else "Final"

        success_count = 0
        fail_count = 0

        # 1. 获取子问卷课程（实验课等，使用不同QuestionnaireId）
        sub_courses = self._get_sub_questionnaire_courses(task_id)
        for sub in sub_courses:
            sub_qn_id = str(sub.get("QuestionnaireId", ""))
            sub_course_name = sub.get("CourseName", "?")
            if not sub_qn_id:
                continue
            print(f"      子问卷课程: {sub_course_name} (QuestionnaireId={sub_qn_id})")
            ok, msg = self.auto_fill_questionnaire(sub_qn_id, {
                "TaskId": task_id, "EvaCode": eva_code,
            })
            if ok:
                success_count += 1
            else:
                fail_count += 1
                print(f"        [✗] {msg}")

        # 2. 获取主问卷题目
        detail = self.get_questionnaire_detail(questionnaire_id, task_info)
        if not detail:
            if success_count > 0:
                return True, f"子问卷成功{success_count}门，主问卷获取失败"
            return False, "无法获取问卷详情"

        items = detail.get("Items", detail.get("Questions", []))
        if not items:
            if success_count > 0:
                return True, f"子问卷成功{success_count}门，主问卷无题目"
            return False, "问卷中没有题目"

        # 3. 获取主问卷课程教师列表
        header = self.get_questionnaire_header(questionnaire_id, task_id)
        if not header:
            if success_count > 0:
                return True, f"子问卷成功{success_count}门，主问卷header获取失败"
            return False, "无法获取问卷头部信息"

        course_list = header.get("CourseList", [])

        # 4. 收集主问卷中未评价的教师
        teachers_to_eval = []
        for cl in course_list:
            course_code = cl.get("CourseCode", "")
            course_name = cl.get("CourseName", "")
            for t in cl.get("TeacherList", []):
                if t.get("AnswerStatus", -1) == 0:
                    teachers_to_eval.append({
                        "course_code": course_code,
                        "course_name": course_name,
                        "teacher_name": t.get("TeacherName", ""),
                        "detail_id": t.get("DetailId"),
                        "class_code": t.get("ClassCode", ""),
                        "teacher_code": t.get("TeacherCode", ""),
                    })

        # 5. 逐个提交主问卷
        for i, teacher in enumerate(teachers_to_eval):
            print(f"      [{i+1}/{len(teachers_to_eval)}] {teacher['course_name']} - {teacher['teacher_name']}")
            ok, msg = self._submit_single_course(
                questionnaire_id, task_id, eva_code, items, teacher
            )
            if ok:
                success_count += 1
            else:
                fail_count += 1
                print(f"        [✗] {msg}")

            time.sleep(random.uniform(0.5, 1.5))

        total = success_count + fail_count
        if total == 0:
            return True, "所有课程已评价"
        if fail_count == 0:
            return True, f"成功提交{success_count}门课程评价"
        return False, f"成功{success_count}/{total}门, 失败{fail_count}门"

    def _get_sub_questionnaire_courses(self, task_id):
        """获取使用不同问卷的子课程（如实验课）

        FinalMyTask/GetMyTaskItemDetailAsync 返回使用非主问卷的课程列表，
        每项含QuestionnaireId（不同于主问卷）。
        """
        if not task_id:
            return []
        try:
            result = self.api_client.call_questionnaire(
                "FinalMyTask/GetMyTaskItemDetailAsync",
                request_params={
                    "TaskId": int(task_id) if isinstance(task_id, str) else task_id,
                    "PersonCode": self.api_client.user_code,
                },
            )
            if isinstance(result, dict):
                val = result.get("Value", result.get("Data"))
                if val and isinstance(val, dict):
                    items = val.get("Items", [])
                    # 过滤出QuestionnaireId与主问卷不同的课程
                    return [item for item in items if item.get("QuestionnaireId")]
        except (EvalAPIError, EvalNetworkError):
            pass
        return []

    def _submit_single_course(self, questionnaire_id, task_id, eva_code, items, teacher_info):
        """提交单个课程的评价"""
        detail_id = teacher_info["detail_id"]
        person_code = self.api_client.user_code

        # 1. 生成AuthKey
        auth_key = self._generate_auth_key(detail_id, person_code)
        if not auth_key:
            return False, "AuthKey生成失败"

        # 2. 构建Subjects答案
        subjects = self._build_subjects(items)

        # 3. 构建提交参数
        save_params = {
            "DetailId": detail_id,
            "status": "normal",
            "QuestionnaireId": str(questionnaire_id),
            "QuestionnaireType": eva_code,
            "Version": 2,
            "PersonCode": person_code,
            "TotalAnsweredSecond": random.randint(30, 120),
            "ClientType": 0,
            "Subjects": subjects,
            "AuthKey": auth_key,
            "IsChange": 0,
        }

        # 4. 调用SaveAnswer API
        try:
            result = self.api_client.call_old_api(
                "Mycos.JP.Questionnaire.SaveAnswer",
                request_params=save_params,
            )
            if isinstance(result, dict):
                val = result.get("Value")
                if val is True:
                    return True, "提交成功"
                msg = result.get("Message", "未知错误")
                return False, f"SaveAnswer返回: {msg}"
        except (EvalAPIError, EvalNetworkError) as e:
            return False, f"SaveAnswer异常: {e}"

        return False, "SaveAnswer未返回有效结果"

    def _build_subjects(self, items):
        """构建Subjects答案数组

        格式（从SPA抓包逆向）:
        - 单选题(SubjectType=1): {"SubjectId": id, "SubjectItems": [{"OptionId": 5}]}
        - 文本题(SubjectType=4): {"SubjectId": id, "SubjectItems": [{"OptionId": 1, "ItemValue": "文本"}]}
        """
        subjects = []
        for item in items:
            item_id = item.get("Id")
            subject_type = item.get("SubjectType")
            options = item.get("Props", {}).get("Items", {}).get("Options", [])

            if str(subject_type) == "4":
                # 文本题: OptionId=1, 带ItemValue
                subjects.append({
                    "SubjectId": item_id,
                    "SubjectItems": [{
                        "OptionId": 1,
                        "ItemValue": random.choice(POSITIVE_COMMENTS),
                    }]
                })
            elif options:
                # 单选题: 选"非常同意"（最后一个选项，OptionId=5, BandScore最高）
                best_opt = options[-1]
                subjects.append({
                    "SubjectId": item_id,
                    "SubjectItems": [{
                        "OptionId": best_opt.get("Id"),
                    }]
                })

        return subjects


# ═══════════════════════════════════════════════════════════════
# 9. Main Class - Hybrid Approach
# ═══════════════════════════════════════════════════════════════

class ZZUAutoEvaluate:
    """ZZU教学评价自动提交 - 混合模式（API优先 + Playwright回退）"""

    def __init__(self, username, password, headless=True, strategy=LoginStrategy.AUTO,
                 cookie_import=False, api_only=False):
        self.username = username
        self.password = password
        self.headless = headless
        self.strategy = strategy
        self.cookie_import = cookie_import
        self.api_only = api_only

        self.api_client = EvalAPIClient()
        self.cookie_manager = CookieManager()
        self.auth = EvalAuth(self.api_client, self.cookie_manager)
        self.filler = EvalAutoFiller(self.api_client, self.auth)

        self._token = None
        self._user_info = None
        self._semester = None

        # Playwright回退相关
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def login(self):
        """执行登录"""
        print("=" * 50)
        print("  ZZU 教学评价自动提交程序")
        print("=" * 50)
        print(f"\n[1] 登录中... (策略: {self.strategy.value})")

        try:
            result = self.auth.login(
                self.username, self.password,
                strategy=self.strategy,
                headless=self.headless,
                cookie_import=self.cookie_import,
            )
            if result:
                self._token, self._user_info = result
                if isinstance(self._user_info, dict) and self._user_info:
                    name = self._user_info.get("Name", "未知")
                    print(f"[✓] 登录成功！用户: {name}")
                    self._semester = self._user_info.get("CurrentSemester")
                else:
                    print("[✓] 登录成功！")
                return True
            else:
                print("[✗] 登录失败")
                return False
        except EvalAuthError as e:
            print(f"[✗] 登录失败: {e}")
            return False

    def get_unfinished_tasks(self):
        """获取未完成任务列表"""
        print("\n[2] 获取未完成任务列表...")
        try:
            tasks = self.filler.get_unfinished_tasks()
            print(f"    共找到 {len(tasks)} 个未完成任务")
            for i, t in enumerate(tasks):
                name = t.get("QuestionnaireName", "未知")
                eva_type = t.get("EvaTypeName", "")
                answered = t.get("AnsweredCount", 0)
                total = t.get("TotalAnswerCount", 0)
                print(f"    {i+1}. {name} ({eva_type}) [{answered}/{total}]")
            return tasks
        except EvalTokenExpiredError:
            print("    [!] Token已过期，请重新登录")
            return []
        except Exception as e:
            print(f"    [!] 获取任务列表异常: {e}")
            return []

    def batch_evaluate(self, whitelist=None, blacklist=None):
        """批量评价（API优先 + Playwright回退）"""
        tasks = self.get_unfinished_tasks()
        if not tasks:
            print("\n没有需要评价的任务，程序结束。")
            return "没有需要评价的任务"

        print(f"\n[3] 开始自动填写评价...")

        success_count = 0
        fail_count = 0
        results = []

        for i, task in enumerate(tasks):
            questionnaire_id = task.get("QuestionnaireId")
            q_name = task.get("QuestionnaireName", "未知")
            eva_type = task.get("EvaTypeName", "")
            answered = task.get("AnsweredCount", 0)
            total = task.get("TotalAnswerCount", 0)

            print(f"\n  [{i+1}/{len(tasks)}] {q_name} ({eva_type}) [{answered}/{total}]")

            try:
                ok, msg = self.filler.auto_fill_questionnaire(questionnaire_id, task)
                if ok:
                    success_count += 1
                    results.append({"task": q_name, "status": "成功", "reason": msg})
                    print(f"    [✓] {msg}")
                else:
                    fail_count += 1
                    results.append({"task": q_name, "status": "失败", "reason": msg})
                    print(f"    [✗] {msg}")
            except EvalTokenExpiredError:
                print("    [!] Token过期，尝试Playwright回退...")
                if self._has_playwright_available():
                    pw_report = self._playwright_full_evaluate(tasks, whitelist, blacklist)
                    return pw_report
                results.append({"task": q_name, "status": "失败", "reason": "Token过期"})
                fail_count += 1
            except Exception as e:
                fail_count += 1
                results.append({"task": q_name, "status": "异常", "reason": str(e)})
                print(f"    [✗] 异常: {e}")

        report = self._build_report(success_count, fail_count, results)
        return report

    def _has_playwright_available(self):
        """检查Playwright是否可用"""
        return _HAS_PLAYWRIGHT and not self.api_only

    def _playwright_full_evaluate(self, tasks, whitelist=None, blacklist=None):
        """完全使用Playwright进行评价"""
        if not self._ensure_playwright():
            return "Playwright不可用，无法回退"

        success_count = 0
        fail_count = 0
        results = []

        for task_index, task in enumerate(tasks):
            q_name = task.get("QuestionnaireName", "未知")
            print(f"\n  [Playwright] 任务: {q_name}")

            try:
                self._navigate_to_task_details(task, task_index)
                courses = self._get_course_list_from_details()
                if not courses:
                    continue

                filtered = self.filter_teachers(courses, whitelist, blacklist)
                eval_courses = [c for c in filtered if c.get("canEvaluate", False)]

                for course_info in eval_courses:
                    course_name = course_info.get("courseName", "未知")
                    teacher_name = course_info.get("teacherName", "未知")
                    try:
                        ok, msg = self.evaluate_single_course(task, task_index, course_name, teacher_name)
                        if ok:
                            success_count += 1
                            results.append({"task": q_name, "teacher": teacher_name, "status": "成功", "reason": msg})
                        else:
                            fail_count += 1
                            results.append({"task": q_name, "teacher": teacher_name, "status": "失败", "reason": msg})
                    except Exception as e:
                        fail_count += 1
                        results.append({"task": q_name, "teacher": teacher_name, "status": "异常", "reason": str(e)})

                    time.sleep(random.uniform(1.0, 2.5))
            except Exception as e:
                fail_count += 1
                print(f"    [✗] 异常: {e}")

        return self._build_report(success_count, fail_count, results)

    def _ensure_playwright(self):
        """确保Playwright已初始化"""
        if not _HAS_PLAYWRIGHT:
            print("    [!] Playwright未安装，无法使用浏览器回退")
            return False

        if self._page:
            return True

        # 如果auth已经启动了Playwright
        if self.auth._page:
            self._page = self.auth._page
            self._context = self.auth._context
            self._browser = self.auth._browser
            self._playwright = self.auth._playwright
            return True

        # 需要新启动Playwright
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)
            self._context = self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
            )
            self._page = self._context.new_page()
            self._page.on("dialog", lambda dialog: dialog.accept())

            # 设置已有的Cookie和token
            for cookie in self.api_client.session.cookies:
                self._context.add_cookies([{
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path or "/",
                }])

            if self._token:
                self._page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
                self._page.evaluate("([t]) => localStorage.setItem('token', t)", [self._token])
                if self._user_info:
                    self._page.evaluate(
                        "([u]) => localStorage.setItem('current-user', JSON.stringify(u))",
                        [self._user_info],
                    )

            return True
        except Exception as e:
            print(f"    [!] 启动Playwright失败: {e}")
            return False

    # ─── Playwright UI交互方法（回退用） ────────────────────────

    def _navigate_to_task_details(self, task, task_index):
        """导航到任务详情页"""
        eva_type = task.get("EvaType")
        eva_code = task.get("EvaCode")
        questionnaire_id = task.get("QuestionnaireId")
        task_id = task.get("TaskId")

        details_url = (
            f"{BASE_URL}/index.html?v=3.41.0"
            f"#/my-task/details/UnFinished/{task_index}/{eva_type}/{eva_code}/{questionnaire_id}/{task_id}"
            f"?semester={self._semester}"
        )

        self._page.goto(details_url, wait_until="networkidle", timeout=30000)
        time.sleep(3)
        self._page.wait_for_load_state("networkidle", timeout=30000)
        return self._page.url

    def _get_course_list_from_details(self):
        """从详情页获取课程列表"""
        courses = self._page.evaluate("""() => {
            const tbody = document.querySelector('.ant-table-tbody');
            if (!tbody) return [];
            const rows = tbody.querySelectorAll('tr');
            const courses = [];
            rows.forEach((row, index) => {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 7) {
                    const courseName = cells[0] ? cells[0].textContent.trim() : '';
                    const teacherName = cells[1] ? cells[1].textContent.trim() : '';
                    const taskType = cells[2] ? cells[2].textContent.trim() : '';
                    const status = cells[5] ? cells[5].textContent.trim() : '';
                    const evalSpan = cells[6] ? cells[6].querySelector('span[style*="cursor: pointer"]') : null;
                    courses.push({
                        index: index,
                        courseName: courseName,
                        teacherName: teacherName,
                        taskType: taskType,
                        status: status,
                        canEvaluate: !!evalSpan,
                        rowKey: row.getAttribute('data-row-key') || ''
                    });
                }
            });
            return courses;
        }""")
        return courses

    def _click_evaluate_for_course(self, course_name, teacher_name):
        """点击课程评价按钮"""
        result = self._page.evaluate("""([courseName, teacherName]) => {
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 7) {
                    const cName = cells[0] ? cells[0].textContent.trim() : '';
                    const tName = cells[1] ? cells[1].textContent.trim() : '';
                    if (cName === courseName && tName === teacherName) {
                        const evalSpan = cells[6] ? cells[6].querySelector('span[style*="cursor: pointer"]') : null;
                        if (evalSpan) {
                            evalSpan.click();
                            return true;
                        }
                    }
                }
            }
            return false;
        }""", [course_name, teacher_name])

        if result:
            time.sleep(5)
            self._page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(2)
        return result

    def _fill_answer_page(self):
        """填写评价表单页面"""
        try:
            self._page.wait_for_selector('.ant-radio-group', timeout=15000)
        except Exception:
            print("      等待表单加载超时")
            return False

        agree_labels = self._page.query_selector_all('label.ant-radio-wrapper')
        agree_count = 0
        for label in agree_labels:
            text = label.text_content().strip()
            if text == "非常同意":
                try:
                    label.click(timeout=3000)
                    agree_count += 1
                    time.sleep(0.1)
                except Exception:
                    pass

        total_radio_groups = len(set(
            r.get_attribute("name") or ""
            for r in self._page.query_selector_all('input[type="radio"]')
            if r.get_attribute("name")
        ))
        if agree_count < total_radio_groups:
            print(f"      [!] 选择题填写不完整: {agree_count}/{total_radio_groups}")
        else:
            print(f"      已选择 {agree_count} 个'非常同意'选项")

        textareas = self._page.query_selector_all('textarea')
        for i, textarea in enumerate(textareas):
            cls = textarea.get_attribute("class") or ""
            if "UEditoTextarea" in cls or "ant-input" in cls:
                comment = "。".join(random.sample(POSITIVE_COMMENTS, k=min(3, len(POSITIVE_COMMENTS))))
                if i > 0:
                    comment = "。".join(random.sample(POSITIVE_COMMENTS, k=min(2, len(POSITIVE_COMMENTS)))) + "。" + random.choice(POSITIVE_COMMENTS)
                try:
                    textarea.click()
                    time.sleep(0.3)
                    textarea.fill(comment)
                    print("      已填写评价文本")
                except Exception:
                    try:
                        self._page.evaluate("""(el, text) => {
                            el.focus();
                            el.value = text;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }""", textarea, comment)
                        print("      已填写评价文本（JS方式）")
                    except Exception as e:
                        print(f"      填写文本失败: {e}")

        checkbox_wrappers = self._page.query_selector_all('label.ant-checkbox-wrapper')
        for wrapper in checkbox_wrappers:
            cb = wrapper.query_selector('input[type="checkbox"]')
            if cb and not cb.is_checked():
                try:
                    wrapper.click()
                    time.sleep(0.1)
                except Exception:
                    pass

        return True

    def _handle_rating_reason_modal(self, max_attempts=3):
        """处理评分原因弹窗"""
        for attempt in range(max_attempts):
            try:
                modal = self._page.locator('.ant-modal-wrap:visible >> .ant-modal').first
                if not modal.is_visible(timeout=3000):
                    return

                modal_text = modal.text_content(timeout=3000)
                if "评分原因" not in modal_text and "填写原因" not in modal_text:
                    return

                ta = modal.locator('textarea').first
                if ta.is_visible(timeout=2000):
                    reason = random.choice(RATING_REASON_COMMENTS)
                    ta.click()
                    time.sleep(0.3)
                    ta.fill(reason)
                    time.sleep(0.3)

                confirm = modal.locator('button:has-text("确")').first
                if confirm.is_visible(timeout=2000):
                    confirm.click()
                    time.sleep(5)
                    self._page.wait_for_load_state("networkidle", timeout=15000)
                else:
                    return
            except Exception:
                return

    def _submit_answer(self):
        """提交答案"""
        submit_btn = self._page.query_selector('button[class*="submit"]')
        if not submit_btn:
            all_btns = self._page.query_selector_all('button')
            for btn in all_btns:
                text = btn.text_content().strip().replace(" ", "")
                if "提交" in text:
                    submit_btn = btn
                    break

        if not submit_btn:
            print("      未找到提交按钮")
            return False

        submit_btn.click()
        time.sleep(2)

        self._handle_rating_reason_modal()

        current_url = self._page.url
        if "/answer/" not in current_url:
            return True

        page_text = self._page.evaluate("document.body.textContent || ''")
        if "提交成功" in page_text or "保存成功" in page_text:
            return True

        try:
            modal = self._page.locator('.ant-modal-wrap:visible >> .ant-modal').first
            if modal.is_visible(timeout=2000):
                modal_text = modal.text_content(timeout=2000)
                if "成功" in modal_text:
                    return True
        except Exception:
            pass

        print("      [!] 提交后仍在答题页面，结果不确定")
        return False

    def evaluate_single_course(self, task, task_index, course_name, teacher_name):
        """评价单个课程（Playwright模式）"""
        print(f"      导航到任务详情页...")
        self._navigate_to_task_details(task, task_index)
        time.sleep(2)

        print(f"      点击课程 '{course_name}' 的评价按钮...")
        if not self._click_evaluate_for_course(course_name, teacher_name):
            print(f"      [✗] 无法点击评价按钮")
            return False, "无法点击评价按钮"

        current_url = self._page.url
        if "/exception/" in current_url:
            print(f"      [✗] 导航到异常页面")
            return False, "导航到异常页面"
        if "/answer/" not in current_url:
            print(f"      [✗] 未跳转到答题页面，当前URL: {current_url}")
            return False, "未跳转到答题页面"

        print(f"      填写评价表单...")
        if not self._fill_answer_page():
            return False, "填写表单失败"

        print(f"      提交评价...")
        if self._submit_answer():
            print(f"      [✓] 提交成功")
            return True, "提交成功"
        else:
            print(f"      [✗] 提交可能失败")
            return False, "提交结果不确定"

    def filter_teachers(self, courses, whitelist=None, blacklist=None):
        """过滤教师"""
        if whitelist and blacklist:
            print("    [!] 同时指定了白名单和黑名单，白名单优先生效")
        filtered = courses
        if whitelist:
            filtered = [c for c in filtered if c.get("teacherName", "") in whitelist]
        if blacklist and not whitelist:
            filtered = [c for c in filtered if c.get("teacherName", "") not in blacklist]
        return filtered

    @staticmethod
    def _build_report(success_count, fail_count, results):
        """构建评价报告"""
        lines = [
            "=" * 50,
            f"  评价完成！总计: {success_count + fail_count} | 成功: {success_count} | 失败: {fail_count}",
            "=" * 50,
        ]
        for r in results:
            task = r.get("task", "")
            teacher = r.get("teacher", "")
            status = r.get("status", "")
            reason = r.get("reason", "")
            if teacher:
                lines.append(f"  - {teacher} ({task}): {status} - {reason}")
            else:
                lines.append(f"  - {task}: {status} - {reason}")
        return "\n".join(lines)

    def close(self):
        """清理资源"""
        # 关闭auth的Playwright
        self.auth.close_playwright()

        # 关闭自己的Playwright
        errors = []
        for resource_name, resource in [
            ("page", self._page),
            ("context", self._context),
            ("browser", self._browser),
        ]:
            if resource:
                try:
                    resource.close()
                except Exception as e:
                    errors.append(f"{resource_name}: {e}")
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                errors.append(f"playwright: {e}")
        if errors:
            print(f"[!] 清理资源时发生错误: {'; '.join(errors)}")

        # 关闭requests.Session
        try:
            self.api_client.session.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# 10. CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZZU教学评价自动提交程序")
    parser.add_argument("-u", "--username", required=True, help="学号")
    parser.add_argument("-p", "--password", default="", help="密码（Cookie复用/导入时可选）")
    parser.add_argument("--strategy", default="auto",
                        choices=["auto", "cookie_reuse", "api_mfa", "playwright", "cookie_import"],
                        help="登录策略 (默认: auto)")
    parser.add_argument("--cookie-import", action="store_true", help="启用Chrome Cookie导入")
    parser.add_argument("--whitelist", nargs="*", help="教师白名单（仅评价这些教师的课程）")
    parser.add_argument("--blacklist", nargs="*", help="教师黑名单（排除这些教师的课程）")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--api-only", action="store_true", help="仅使用API模式（不使用Playwright UI交互）")
    args = parser.parse_args()

    strategy_map = {
        "auto": LoginStrategy.AUTO,
        "cookie_reuse": LoginStrategy.COOKIE_REUSE,
        "api_mfa": LoginStrategy.API_MFA,
        "playwright": LoginStrategy.PLAYWRIGHT,
        "cookie_import": LoginStrategy.COOKIE_IMPORT,
    }

    evaluator = ZZUAutoEvaluate(
        args.username, args.password,
        headless=not args.no_headless,
        strategy=strategy_map[args.strategy],
        cookie_import=args.cookie_import,
        api_only=args.api_only,
    )

    try:
        if evaluator.login():
            report = evaluator.batch_evaluate(whitelist=args.whitelist, blacklist=args.blacklist)
            print(report)
    finally:
        evaluator.close()
