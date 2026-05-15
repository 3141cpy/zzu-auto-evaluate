import random
import json
import time
import argparse
from playwright.sync_api import sync_playwright

POSITIVE_COMMENTS = [
    "老师教学认真负责，课堂内容丰富充实",
    "教学方式生动有趣，能够很好地调动学生积极性",
    "老师备课充分，讲解清晰易懂",
    "课堂互动性强，注重培养学生的思考能力",
    "老师耐心解答学生疑问，关心学生学习进度",
    "教学内容与时俱进，理论与实践结合紧密",
    "老师教学经验丰富，能够深入浅出地讲解难点",
    "课堂氛围活跃，学生参与度高",
    "老师治学严谨，对学生要求合理",
    "教学效果显著，学生收获很大",
]

RATING_REASON_COMMENTS = [
    "该教师教学态度认真，备课充分，课堂讲解清晰，能够很好地解答学生疑问，教学效果优秀。",
    "老师教学水平很高，课堂内容丰富，注重理论与实践结合，对学生负责，值得高度评价。",
    "教师教学经验丰富，课堂互动性强，能够深入浅出地讲解重点难点，学生收获很大。",
]

BASE_URL = "https://jxpj.v.zzu.edu.cn"
LOGIN_URL = f"{BASE_URL}/index.html?v=3.41.0"
CRYPTOJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js"

CALL_API_JS = """
async ([apiName, requestParams, pageContext, semester]) => {
    const AES_KEY = "nfZYwnW2ppQc3CXr";
    const SALT = "d^PrEK&c";

    function aesEncrypt(plaintext) {
        const key = CryptoJS.enc.Utf8.parse(AES_KEY);
        const data = CryptoJS.enc.Utf8.parse(plaintext);
        const encrypted = CryptoJS.AES.encrypt(data, key, {
            mode: CryptoJS.mode.ECB,
            padding: CryptoJS.pad.Pkcs7
        });
        return encrypted.toString();
    }

    function aesDecrypt(ciphertext) {
        const key = CryptoJS.enc.Utf8.parse(AES_KEY);
        const decrypted = CryptoJS.AES.decrypt(ciphertext, key, {
            mode: CryptoJS.mode.ECB,
            padding: CryptoJS.pad.Pkcs7
        });
        return CryptoJS.enc.Utf8.stringify(decrypted).toString();
    }

    let token = localStorage.getItem('token') || '';
    const userInfo = JSON.parse(localStorage.getItem('current-user') || '{}');
    const visitorObj = JSON.parse(localStorage.getItem('visitorObj') || '{}');

    const systemParams = {
        DegreeLevel: 0,
        Token: token,
        UserCode: userInfo.Code || '',
        UniversityCode: userInfo.UniversityCode || '10459',
        ApiName: apiName,
        ClientTime: new Date().toISOString().replace('T', ' ').substring(0, 19),
        ClientId: visitorObj.ClientId || '',
        ClientType: 0,
        RequestOriginPageAddress: window.location.href
    };

    if (pageContext) {
        systemParams.PageContext = pageContext;
    }
    if (semester) {
        systemParams.Semester = semester;
    }

    const body = {
        SystemParams: systemParams,
        RequestParams: requestParams || {}
    };

    const bodyStr = JSON.stringify(body);
    const encryptedBody = aesEncrypt(bodyStr + SALT);

    const url = window.config.url + '?ApiName=' + apiName;
    const resp = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json, text/plain, */*'
        },
        body: encryptedBody
    });

    const respText = await resp.text();

    let data;
    try {
        data = JSON.parse(respText);
    } catch(e) {
        try {
            const decrypted = aesDecrypt(respText);
            const trimmed = decrypted.substring(0, decrypted.length - SALT.length);
            data = JSON.parse(trimmed);
        } catch(e2) {
            data = {Code: '-1', Message: 'Response parse error', raw: respText.substring(0, 200)};
        }
    }

    if (data && data.Token) {
        localStorage.setItem('token', data.Token);
    }

    return data;
}
"""


class ZZUAutoEvaluate:
    def __init__(self, username, password, headless=True):
        self.username = username
        self.password = password
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._token = None
        self._user_info = None
        self._semester = None

    def login(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
        )
        self._page = self._context.new_page()

        self._page.on("dialog", lambda dialog: dialog.accept())

        captured_token = [None]

        def on_response(response):
            if captured_token[0]:
                return
            if "apiservice" in response.url or "apis.do" in response.url:
                try:
                    body = response.text()
                    data = json.loads(body)
                    if isinstance(data, dict):
                        token = data.get("Token") or (
                            data.get("Value", {}).get("Token")
                            if isinstance(data.get("Value"), dict)
                            else None
                        )
                        if token:
                            captured_token[0] = token
                except Exception:
                    pass

        self._page.on("response", on_response)

        try:
            print("[1] 正在打开登录页面...")
            self._page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)

            print("[2] 正在填写登录表单...")
            username_input = (
                self._page.query_selector('input[placeholder*="学号"]')
                or self._page.query_selector('input[placeholder*="账号"]')
                or self._page.query_selector('.login-form input[type="text"]')
            )
            if not username_input:
                raise RuntimeError("未找到用户名输入框")
            username_input.fill(self.username)

            password_input = self._page.query_selector('input[type="password"]')
            if not password_input:
                raise RuntimeError("未找到密码输入框")
            password_input.fill(self.password)

            login_btn = (
                self._page.query_selector('button.login-btn')
                or self._page.query_selector('button:has-text("登录")')
            )
            if not login_btn:
                raise RuntimeError("未找到登录按钮")
            login_btn.click()
            print("[3] 已点击登录，等待认证跳转...")

            try:
                self._page.wait_for_url("**/my-task/**", timeout=60000)
            except Exception:
                time.sleep(5)
                self._page.wait_for_load_state("networkidle", timeout=30000)

            current_url = self._page.url
            if "cas.s.zzu.edu.cn" in current_url:
                raise RuntimeError("登录失败，页面仍停留在CAS认证页，请检查账号密码")

            time.sleep(5)
            self._page.wait_for_load_state("networkidle", timeout=30000)

            self._token = captured_token[0]
            if not self._token:
                raise RuntimeError("登录后未获取到token")

            user_info_str = self._page.evaluate("localStorage.getItem('current-user')")
            if user_info_str:
                self._user_info = json.loads(user_info_str)
                print(f"[✓] 登录成功！用户: {self._user_info.get('Name', '未知')}")
            else:
                print("[✓] 登录成功！")

            self._semester = (
                self._user_info.get("CurrentSemester")
                if self._user_info and self._user_info.get("CurrentSemester")
                else None
            )
            if not self._semester:
                self._semester = self._page.evaluate("""() => {
                    const url = window.location.href;
                    const match = url.match(/semester=([^&]+)/);
                    return match ? match[1] : null;
                }""")
            if not self._semester:
                print("[!] 无法自动获取学期信息，请在URL中确认学期参数")

            self._page.evaluate("([t]) => localStorage.setItem('token', t)", [self._token])

            print("[4] 加载加密库...")
            self._page.evaluate("([url]) => {" +
                "return new Promise((resolve, reject) => {" +
                "if (typeof CryptoJS !== 'undefined') { resolve(); return; }" +
                "const script = document.createElement('script');" +
                "script.src = url;" +
                "document.head.appendChild(script);" +
                "script.onload = resolve;" +
                "script.onerror = reject;" +
                "});" +
                "}", [CRYPTOJS_URL])
            time.sleep(2)

            return True
        except Exception as e:
            print(f"[✗] 登录失败: {e}")
            return False

    def _call_api(self, api_name, request_params=None, page_context=None, semester=None):
        try:
            result = self._page.evaluate(
                CALL_API_JS,
                [
                    api_name,
                    request_params or {},
                    page_context,
                    semester or self._semester,
                ]
            )
            if result and result.get("Token"):
                self._token = result["Token"]
            return result
        except Exception as e:
            print(f"    [!] API调用异常 ({api_name}): {e}")
            return None

    def get_unfinished_tasks(self):
        result = self._call_api(
            "Mycos.JP.MyTask.MyTask.GetMyTaskItemByAnswerStatus",
            request_params={
                "Source": "pc",
                "Status": "UnFinished",
                "IsIncludeHistorySemester": 1,
                "Filters": {}
            },
            page_context={
                "PageIndex": 1,
                "PageSize": 100,
                "SortBy": "QuestionnaireName",
                "Direction": "asc",
                "IsGBKSort": False
            }
        )
        if not result:
            return []

        code = result.get("Code")
        if str(code) == "-3":
            print(f"    [!] Token已过期，请重新登录")
            return []

        items = []
        if result.get("Value"):
            val = result["Value"]
            if isinstance(val, dict):
                items = val.get("Items", val.get("items", []))
            elif isinstance(val, list):
                items = val
        elif result.get("Data"):
            data = result["Data"]
            if isinstance(data, dict):
                items = data.get("Items", data.get("items", []))
            elif isinstance(data, list):
                items = data
        return items if isinstance(items, list) else []

    def _navigate_to_task_details(self, task, task_index):
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
        try:
            self._page.wait_for_selector('.ant-radio-group', timeout=15000)
        except Exception:
            print(f"      等待表单加载超时")
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
                    print(f"      已填写评价文本")
                except Exception:
                    try:
                        self._page.evaluate("""(el, text) => {
                            el.focus();
                            el.value = text;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }""", textarea, comment)
                        print(f"      已填写评价文本（JS方式）")
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
        submit_btn = self._page.query_selector('button[class*="submit"]')
        if not submit_btn:
            all_btns = self._page.query_selector_all('button')
            for btn in all_btns:
                text = btn.text_content().strip().replace(" ", "")
                if "提交" in text:
                    submit_btn = btn
                    break

        if not submit_btn:
            print(f"      未找到提交按钮")
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

        print(f"      [!] 提交后仍在答题页面，结果不确定")
        return False

    def evaluate_single_course(self, task, task_index, course_name, teacher_name):
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
            return False, f"未跳转到答题页面"

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
        if whitelist and blacklist:
            print(f"    [!] 同时指定了白名单和黑名单，白名单优先生效")
        filtered = courses
        if whitelist:
            filtered = [c for c in filtered if c.get("teacherName", "") in whitelist]
        if blacklist and not whitelist:
            filtered = [c for c in filtered if c.get("teacherName", "") not in blacklist]
        return filtered

    def batch_evaluate(self, whitelist=None, blacklist=None):
        print("=" * 50)
        print("  ZZU 教学评价自动提交程序")
        print("=" * 50)

        print("\n[1/4] 获取未完成任务列表...")
        tasks = self.get_unfinished_tasks()
        print(f"    共找到 {len(tasks)} 个未完成任务")

        if not tasks:
            print("\n没有需要评价的任务，程序结束。")
            return "没有需要评价的任务"

        for i, t in enumerate(tasks):
            name = t.get("QuestionnaireName", "未知")
            eva_type = t.get("EvaTypeName", "")
            answered = t.get("AnsweredCount", 0)
            total = t.get("TotalAnswerCount", 0)
            print(f"    {i+1}. {name} ({eva_type}) [{answered}/{total}]")

        success_count = 0
        fail_count = 0
        results = []

        print(f"\n[2/4] 逐个处理任务...")
        for task_index, task in enumerate(tasks):
            task_id = task.get("TaskId")
            questionnaire_id = task.get("QuestionnaireId")
            q_name = task.get("QuestionnaireName", "未知")
            eva_type = task.get("EvaTypeName", "")
            answered = task.get("AnsweredCount", 0)
            total = task.get("TotalAnswerCount", 0)

            print(f"\n  任务: {q_name} ({eva_type}) [{answered}/{total}]")

            print(f"    导航到任务详情页...")
            self._navigate_to_task_details(task, task_index)

            print(f"    获取课程列表...")
            courses = self._get_course_list_from_details()
            print(f"    共 {len(courses)} 门课程")

            if not courses:
                has_empty_table = self._page.query_selector('.ant-table-placeholder, .ant-empty')
                if has_empty_table:
                    print(f"    任务详情页无课程数据（可能已全部评价完成）")
                else:
                    print(f"    [!] 未获取到课程列表，页面可能未正确加载")
                continue

            for c in courses:
                status = c.get("status", "")
                can_eval = c.get("canEvaluate", False)
                teacher = c.get("teacherName", "未知")
                course = c.get("courseName", "未知")
                print(f"      - {course} ({teacher}) 状态:{status} 可评价:{can_eval}")

            filtered_courses = self.filter_teachers(courses, whitelist, blacklist)
            if whitelist:
                print(f"    白名单筛选: {whitelist}")
            if blacklist:
                print(f"    黑名单筛选: {blacklist}")
            print(f"    筛选后剩余 {len(filtered_courses)} 门课程待评价")

            eval_courses = [c for c in filtered_courses if c.get("canEvaluate", False)]
            if not eval_courses:
                print(f"    没有可评价的课程，跳过此任务")
                continue

            print(f"\n[3/4] 开始评价 ({len(eval_courses)} 门课程)...")
            for course_info in eval_courses:
                course_name = course_info.get("courseName", "未知")
                teacher_name = course_info.get("teacherName", "未知")

                print(f"\n    评价: {course_name} - {teacher_name}")

                try:
                    ok, msg = self.evaluate_single_course(task, task_index, course_name, teacher_name)
                    if ok:
                        success_count += 1
                        results.append({"teacher": teacher_name, "course": course_name, "task": q_name, "status": "成功", "reason": msg})
                    else:
                        fail_count += 1
                        results.append({"teacher": teacher_name, "course": course_name, "task": q_name, "status": "失败", "reason": msg})
                except Exception as e:
                    print(f"      [✗] 发生异常: {e}")
                    fail_count += 1
                    results.append({"teacher": teacher_name, "course": course_name, "task": q_name, "status": "异常", "reason": str(e)})

                time.sleep(random.uniform(1.0, 2.5))

        print(f"\n[4/4] 评价完成！")
        print("=" * 50)
        print(f"  总计: {success_count + fail_count} | 成功: {success_count} | 失败: {fail_count}")
        print("=" * 50)

        report_lines = [f"评价完成！总计 {success_count + fail_count} 个任务，成功 {success_count} 个，失败 {fail_count} 个"]
        for r in results:
            report_lines.append(f"  - {r['teacher']} - {r['course']} ({r['task']}): {r['status']} - {r['reason']}")
        return "\n".join(report_lines)

    def close(self):
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZZU教学评价自动提交程序")
    parser.add_argument("-u", "--username", required=True, help="学号")
    parser.add_argument("-p", "--password", required=True, help="密码")
    parser.add_argument("--whitelist", nargs="*", help="教师白名单（仅评价这些教师的课程）")
    parser.add_argument("--blacklist", nargs="*", help="教师黑名单（排除这些教师的课程）")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    args = parser.parse_args()

    evaluator = ZZUAutoEvaluate(args.username, args.password, headless=not args.no_headless)
    try:
        if evaluator.login():
            report = evaluator.batch_evaluate(whitelist=args.whitelist, blacklist=args.blacklist)
            print(report)
    finally:
        evaluator.close()
