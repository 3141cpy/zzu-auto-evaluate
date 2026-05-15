# -*- coding: utf-8 -*-
"""
郑州大学CAS系统自动登录模块
功能：模拟浏览器登录，获取选课所需的token和student_id，并更新到config.json
"""

import requests
from bs4 import BeautifulSoup
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64
import json
import logging
import re
from typing import Optional, Tuple

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ZZUCASLogin:
    """郑州大学CAS登录类"""

    # CAS系统相关URL
    CAS_LOGIN_PAGE_URL = "https://cas.s.zzu.edu.cn/cas/a/login"  # 正确的登录入口
    PUBLIC_KEY_URL = "https://cas.s.zzu.edu.cn/cas/jwt/publicKey"
    SERVICE_URL = "https://jwxt.zzu.edu.cn/student/sso/login"
    COURSE_SELECT_PAGE_URL = "https://jwxt.zzu.edu.cn/student/for-std/course-select"
    STUDENT_INFO_API = "https://jwxt.zzu.edu.cn/course-selection-api/api/v1/student/course-select/students"

    # 固定的fpVisitorId（根据抓包）
    FP_VISITOR_ID = "ae6ce9e6d1e14c1abc4609143ce4e1ae"

    def __init__(self):
        """初始化会话"""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

    def get_execution_value(self) -> Tuple[Optional[str], Optional[str]]:
        """
        步骤1：访问CAS登录页，提取execution参数

        Returns:
            (execution值, _eventId值)，失败返回(None, None)
        """
        logger.info("正在访问CAS登录页...")

        params = {"service": self.SERVICE_URL}

        try:
            response = self.session.get(
                self.CAS_LOGIN_PAGE_URL, params=params, timeout=30, allow_redirects=True
            )
            response.raise_for_status()

            logger.debug(f"登录页响应长度: {len(response.text)} 字符")

            # 打印Cookie信息
            cookies = self.session.cookies.get_dict()
            if cookies:
                logger.info(f"获取到Cookie: {list(cookies.keys())}")
                for key, val in cookies.items():
                    logger.debug(f"  {key}: {val[:50]}{'...' if len(val) > 50 else ''}")
            else:
                logger.warning("警告: 未获取到任何Cookie")

            # 打印获取到的Cookie
            cookies = self.session.cookies.get_dict()
            if cookies:
                logger.info(f"获取到会话Cookie: {list(cookies.keys())}")
                for key, val in cookies.items():
                    logger.debug(
                        f"  {key}: {val[:30]}..."
                        if len(val) > 30
                        else f"  {key}: {val}"
                    )
            else:
                logger.warning("未获取到任何Cookie，可能存在问题")

            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # 仅从fm1表单中提取execution（用户名密码登录表单）
            login_form = soup.find("form", {"id": "fm1"})

            if not login_form:
                logger.error("未找到id=fm1的登录表单")
                logger.debug(f"响应内容前500字符: {response.text[:500]}")
                return None, None

            # 从fm1表单中获取execution
            execution_input = login_form.find("input", {"name": "execution"})
            if execution_input:
                execution_value = execution_input.get("value")
                if execution_value:
                    logger.info(f"成功获取execution: {execution_value[:50]}...")
                    logger.debug(f"execution完整长度: {len(execution_value)} 字符")
                    return execution_value, "submit"
                else:
                    logger.error("execution输入框没有value属性")
            else:
                logger.error("fm1表单中未找到name=execution的输入框")

            logger.error("未能提取execution参数")
            return None, None

        except requests.RequestException as e:
            logger.error(f"访问登录页失败: {e}")
            return None, None

    def get_public_key(self) -> Optional[str]:
        """
        步骤2：获取RSA公钥

        Returns:
            公钥字符串，失败返回None
        """
        logger.info("正在获取RSA公钥...")

        try:
            response = self.session.get(self.PUBLIC_KEY_URL, timeout=30)
            response.raise_for_status()

            # 公钥直接返回PEM格式字符串，不是JSON
            public_key = response.text.strip()

            if public_key and "BEGIN PUBLIC KEY" in public_key:
                logger.info("成功获取RSA公钥")
                return public_key
            else:
                logger.error("响应中未包含有效公钥")
                return None

        except requests.RequestException as e:
            logger.error(f"获取公钥失败: {e}")
            return None

    def encrypt_password(self, password: str, public_key_str: str) -> Optional[str]:
        """
        使用RSA公钥加密密码

        Args:
            password: 明文密码
            public_key_str: PEM格式公钥字符串

        Returns:
            加密后的密码（带__RSA__前缀），失败返回None
        """
        logger.info("正在加密密码...")

        try:
            # 导入公钥
            public_key = RSA.import_key(public_key_str)

            # 使用PKCS1_v1_5填充
            cipher = PKCS1_v1_5.new(public_key)

            # 加密密码
            encrypted_bytes = cipher.encrypt(password.encode("utf-8"))

            # Base64编码
            encrypted_b64 = base64.b64encode(encrypted_bytes).decode("utf-8")

            # 添加前缀
            encrypted_password = f"__RSA__{encrypted_b64}"

            logger.info("密码加密成功")
            return encrypted_password

        except Exception as e:
            logger.error(f"密码加密失败: {e}")
            return None

    def submit_login(
        self, username: str, encrypted_password: str, execution: str
    ) -> Tuple[bool, Optional[str]]:
        """
        步骤3：提交登录表单

        Args:
            username: 学号
            encrypted_password: 加密后的密码
            execution: 动态参数

        Returns:
            (是否成功, ticket URL或错误信息)
        """
        logger.info("正在提交登录表单...")

        # 构造表单数据 - 严格按照抓包参数顺序
        form_data = [
            ("username", username),
            ("password", encrypted_password),
            ("captcha", ""),
            ("currentMenu", "1"),
            ("failN", "0"),  # 抓包中的实际值
            ("mfaState", ""),
            ("execution", execution),
            ("_eventId", "submit"),
            ("geolocation", ""),
            ("fpVisitorId", self.FP_VISITOR_ID),
            ("trustAgent", ""),
            ("submit1", "Login1"),
        ]

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://cas.s.zzu.edu.cn",
            "Referer": f"{self.CAS_LOGIN_PAGE_URL}?service={requests.utils.quote(self.SERVICE_URL)}",
        }

        try:
            # 不自动跟随重定向，手动处理
            response = self.session.post(
                self.CAS_LOGIN_PAGE_URL,
                params={"service": self.SERVICE_URL},
                data=form_data,
                headers=headers,
                timeout=30,
                allow_redirects=False,
            )

            # 检查是否重定向（登录成功）
            if response.status_code == 302:
                location = response.headers.get("Location", "")
                if "ticket=" in location:
                    logger.info(f"登录成功，获取到ticket重定向URL")
                    return True, location
                elif "/cas/a/login" in location:
                    # 重定向到备用登录页面，说明登录失败
                    # 尝试获取详细错误信息
                    error_detail = self._extract_error_message(location)
                    if error_detail:
                        logger.error(f"登录失败：{error_detail}")
                        return False, error_detail
                    else:
                        logger.error("登录失败：账号密码错误或账号不存在")
                        return False, "账号密码错误或账号不存在"
                else:
                    logger.error(f"重定向URL中未包含ticket: {location}")
                    return False, f"登录失败，重定向到: {location}"
            else:
                # 登录失败，尝试解析错误信息
                soup = BeautifulSoup(response.text, "html.parser")
                error_msg = soup.find("div", class_="alert-danger")
                if error_msg:
                    error_text = error_msg.get_text(strip=True)
                    logger.error(f"登录失败: {error_text}")
                    return False, error_text
                else:
                    logger.error(f"登录失败，状态码: {response.status_code}")
                    return False, f"HTTP {response.status_code}"

        except requests.RequestException as e:
            logger.error(f"提交登录请求失败: {e}")
            return False, str(e)

    def _extract_error_message(self, error_page_url: str) -> Optional[str]:
        """
        从错误页面提取详细的错误信息

        Args:
            error_page_url: 错误页面的URL

        Returns:
            错误信息字符串，未找到则返回None
        """
        try:
            response = self.session.get(error_page_url, timeout=30)
            soup = BeautifulSoup(response.text, "html.parser")

            error_messages = []

            # 1. 查找所有alert相关的类
            import re

            for tag in soup.find_all(["div", "span", "p"]):
                classes = tag.get("class", [])
                class_str = " ".join(str(c) for c in classes)
                if re.search(r"alert|error|warning|message|msg", class_str, re.I):
                    text = tag.get_text(strip=True)
                    if text and not text.startswith("{{") and len(text) > 5:
                        error_messages.append(text)

            # 2. 过滤掉无关的MFA提示信息
            filtered_errors = []
            for msg in error_messages:
                skip_keywords = [
                    "安全手机未绑定",
                    "安全邮箱未绑定",
                    "OTP令牌未绑定",
                    "安全手机验证",
                    "安全邮箱验证",
                    "OTP令牌验证",
                ]
                if not any(kw in msg for kw in skip_keywords):
                    filtered_errors.append(msg)

            if filtered_errors:
                return " | ".join(filtered_errors[:3])

            return None

        except Exception as e:
            logger.debug(f"提取错误信息失败: {e}")
            return None

    def follow_redirect_and_get_cookies(
        self, ticket_url: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        步骤4&5：跟随ticket重定向，获取JWT token和student_id

        Args:
            ticket_url: 包含ticket的重定向URL

        Returns:
            (是否成功, student_id, token)
        """
        logger.info("正在跟随重定向获取认证信息...")

        try:
            # 步骤1：访问ticket URL
            response = self.session.get(ticket_url, timeout=30, allow_redirects=True)
            logger.info(f"Ticket重定向后URL: {response.url}")

            # 步骤2：访问选课页面获取JWT token
            logger.info("正在访问选课页面获取JWT token...")
            course_page = self.session.get(self.COURSE_SELECT_PAGE_URL, timeout=30)

            # 从页面中提取JWT token
            jwt_match = re.search(
                r"https://jwxt\.zzu\.edu\.cn/course-selection/\?token=([a-zA-Z0-9_\-\.]+)",
                course_page.text,
            )

            if not jwt_match:
                logger.error("未能从选课页面提取JWT token")
                return False, None, None

            jwt_token = jwt_match.group(1)
            logger.info(f"成功获取JWT token: {jwt_token[:50]}...")

            # 步骤3：使用JWT token调用API获取student_id
            logger.info("正在调用API获取student_id...")

            api_headers = {
                "Accept": "application/json, text/plain, */*",
                "Authorization": jwt_token,
                "Referer": f"https://jwxt.zzu.edu.cn/course-selection/?token={jwt_token}",
            }

            api_response = self.session.get(
                self.STUDENT_INFO_API, headers=api_headers, timeout=30
            )

            if api_response.status_code != 200:
                logger.error(f"API请求失败，状态码: {api_response.status_code}")
                return False, None, None

            try:
                data = api_response.json()
                logger.debug(f"API响应: {data}")

                # 从响应中提取student_id
                # 响应格式: {"result": 0, "message": None, "data": [473220]}
                student_id = None

                if isinstance(data, dict):
                    # 标准响应格式
                    if "data" in data:
                        if isinstance(data["data"], list) and len(data["data"]) > 0:
                            # data是数组，取第一个元素
                            student_id = data["data"][0]
                        elif isinstance(data["data"], dict):
                            # data是字典
                            student_id = (
                                data["data"].get("studentId")
                                or data["data"].get("student_id")
                                or data["data"].get("id")
                            )
                        else:
                            # data直接是值
                            student_id = data["data"]
                    else:
                        # 尝试其他字段名
                        student_id = (
                            data.get("studentId")
                            or data.get("student_id")
                            or data.get("id")
                        )
                elif isinstance(data, list) and len(data) > 0:
                    student_id = data[0]

                if not student_id:
                    logger.error(f"API响应中未找到student_id: {data}")
                    return False, None, None

                logger.info(f"成功获取student_id: {student_id}")
                return True, str(student_id), jwt_token

            except json.JSONDecodeError:
                logger.error(f"API响应JSON解析失败: {api_response.text[:200]}")
                return False, None, None

        except requests.RequestException as e:
            logger.error(f"获取认证信息失败: {e}")
            return False, None, None

    def update_config(
        self, student_id: str, token: str, config_path: str = "config.json"
    ) -> bool:
        """
        更新配置文件

        Args:
            student_id: 学生ID
            token: 认证令牌
            config_path: 配置文件路径

        Returns:
            是否成功
        """
        logger.info(f"正在更新配置文件: {config_path}")

        try:
            # 读取现有配置
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                config = {}

            # 更新字段
            config["token"] = token
            config["student_id"] = student_id

            # 写回文件
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info("配置文件更新成功")
            return True

        except Exception as e:
            logger.error(f"更新配置文件失败: {e}")
            return False


def auto_login(username: str, password: str, config_path: str = "config.json") -> bool:
    """
    自动登录主函数

    Args:
        username: 学号
        password: 密码
        config_path: 配置文件路径

    Returns:
        是否成功
    """
    logger.info("=" * 50)
    logger.info("开始自动登录流程")
    logger.info(f"学号: {username}")
    logger.info("=" * 50)

    # 创建登录实例
    login = ZZUCASLogin()

    # 步骤1：获取execution
    execution, event_id = login.get_execution_value()
    if not execution:
        logger.error("登录失败：无法获取execution参数")
        return False

    # 步骤2：获取公钥
    public_key = login.get_public_key()
    if not public_key:
        logger.error("登录失败：无法获取RSA公钥")
        return False

    # 步骤3：加密密码
    encrypted_password = login.encrypt_password(password, public_key)
    if not encrypted_password:
        logger.error("登录失败：密码加密失败")
        return False

    # 步骤4：提交登录
    success, result = login.submit_login(username, encrypted_password, execution)
    if not success:
        logger.error(f"登录失败：{result}")
        return False

    # 步骤5：获取JWT token和student_id
    success, student_id, token = login.follow_redirect_and_get_cookies(result)
    if not success:
        logger.error("登录失败：无法获取认证信息")
        return False

    # 步骤6：更新配置文件
    if not student_id or not token:
        logger.error("登录失败：缺少必要字段")
        return False

    success = login.update_config(student_id, token, config_path)
    if not success:
        logger.error("登录失败：无法更新配置文件")
        return False

    logger.info("=" * 50)
    logger.info("登录成功！配置文件已更新")
    logger.info(f"student_id: {student_id}")
    logger.info(f"token: {token[:50]}...")
    logger.info("=" * 50)

    return True


if __name__ == "__main__":
    import getpass

    print("\n" + "=" * 50)
    print("郑州大学CAS自动登录工具")
    print("=" * 50)

    # 获取用户输入
    username = input("请输入学号: ").strip()
    password = getpass.getpass("请输入密码: ").strip()

    if not username or not password:
        print("错误：学号和密码不能为空")
        exit(1)

    # 执行登录
    success = auto_login(username, password)

    if success:
        print("\n✓ 登录成功！config.json 已更新")
    else:
        print("\n✗ 登录失败，请检查学号密码是否正确")
        exit(1)
