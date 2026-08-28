"""HTTP 请求关键字（httpx）。关键字 id 见 keyword_defs 定义（参考 align-http-protocol.md）。

header/request 既接受 dict（变量持有），也接受字符串（JSON 或 k:v 多行）。
响应通过 OUT 变量名回写：resp_code / resp_body / resp_header / response_time。
"""

from __future__ import annotations

import json as _json
import os
import re
import time
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

# noinspection PyUnresolvedReferences
import httpx

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from .mock_server import get_mock_server
from ...runtime.paths import join_project, to_native


def _parse_mapping(val: Any) -> dict:
    """把 header/cookie 参数解析成 dict。支持 dict / JSON 串 / 'k:v' 多行。"""
    if not val:
        return {}
    if isinstance(val, dict):
        return dict(val)
    s = str(val).strip()
    if s.startswith("{"):
        # noinspection PyBroadException
        try:
            return dict(_json.loads(s))
        except Exception:
            pass
    out: dict = {}
    for line in s.replace(";", "\n").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _body(request: Any) -> tuple[Optional[str], Optional[dict]]:
    """返回 (content, json_obj)。dict→json；字符串→content。"""
    if request in (None, ""):
        return None, None
    if isinstance(request, (dict, list)):
        return None, request
    return str(request), None


def _collect_out(
    resp: httpx.Response,
    elapsed_ms: int,
    resp_code,
    resp_body,
    resp_header,
    response_time,
    redirect_url,
    resp_cookie="",
) -> dict:
    out: dict[str, Any] = {}
    if resp_code:
        out[resp_code] = resp.status_code
    if resp_body:
        out[resp_body] = resp.text
    if resp_header:
        out[resp_header] = dict(resp.headers)
    if resp_cookie:
        out[resp_cookie] = dict(resp.cookies)
    if response_time:
        out[response_time] = elapsed_ms
    if redirect_url and resp.history:
        out[redirect_url] = str(resp.url)
    return out


def _send_httpx(
    state: Any,
    method: str,
    target: str,
    *,
    headers: Any,
    cookies: Any,
    content: Any,
    json_obj: Any,
    params: dict[str, str],
    timeout: float,
    follow: bool,
    proxy_url: str,
) -> httpx.Response:
    """会话内复用 Client；无会话则短生命周期 Client。始终返回 Response。"""
    if state is not None:
        return state.client.request(
            method,
            target,
            headers=headers or None,
            cookies=cookies or None,
            content=content,
            json=json_obj,
            params=params or None,
            timeout=timeout,
            follow_redirects=follow,
        )
    cli_kwargs: dict[str, Any] = {
        "follow_redirects": follow,
        "timeout": timeout,
    }
    if proxy_url:
        cli_kwargs["proxy"] = proxy_url
    with httpx.Client(**cli_kwargs) as cli:
        return cli.request(
            method,
            target,
            headers=headers or None,
            cookies=cookies or None,
            content=content,
            json=json_obj,
        )


def _record_last_http(ctx: Optional[ExecutionContext], resp: httpx.Response, elapsed_ms: int) -> None:
    if ctx is None:
        return
    setattr(
        ctx,
        "last_http",
        {
            "status": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "body": resp.text,
            "headers": dict(resp.headers),
            "cookies": dict(resp.cookies),
            "url": str(resp.url),
        },
    )


# noinspection PyPep8Naming
def _request(
    ctx: Optional[ExecutionContext],
    method: str,
    url: str,
    header,
    request,
    auto_redirect,
    timeOut,
    resp_code,
    resp_body,
    resp_header,
    response_time,
    redirect_url,
    req_cookie="",
    refer_proxy_var="NONE",
    resp_cookie="",
) -> dict:
    from .session import get_http_session, merge_headers, proxy_to_url  # 延迟：拆 client↔session 环

    state = get_http_session(ctx) if ctx is not None else None
    headers = merge_headers(state, header)
    cookies = _cookies(req_cookie)
    content, json_obj = _body(request)
    follow = str(auto_redirect).lower() != "false"
    timeout = 20.0
    if timeOut not in (None, ""):
        try:
            timeout = min(float(timeOut), 60.0)
        except (TypeError, ValueError):
            pass

    target = (url or "").strip()
    params: dict[str, str] = {}
    if state is not None:
        target = state.resolve_url(target)
        params.update(state.query_defaults)

    proxy_cfg: Any = refer_proxy_var
    if isinstance(refer_proxy_var, str) and refer_proxy_var not in ("", "NONE", "none"):
        # 支持传入变量名或直接 dict（resolve 后）
        if ctx is not None and refer_proxy_var in getattr(ctx, "variables", {}):
            proxy_cfg = ctx.get_var(refer_proxy_var)
    proxy_url = proxy_to_url(proxy_cfg)

    start = time.monotonic()
    resp = _send_httpx(
        state,
        method,
        target,
        headers=headers,
        cookies=cookies,
        content=content,
        json_obj=json_obj,
        params=params,
        timeout=timeout,
        follow=follow,
        proxy_url=proxy_url,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    _record_last_http(ctx, resp, elapsed_ms)
    if ctx is not None:
        ctx.log(f"{method.upper()} {resp.url} → {resp.status_code} ({elapsed_ms}ms)")
    return _collect_out(
        resp,
        elapsed_ms,
        resp_code,
        resp_body,
        resp_header,
        response_time,
        redirect_url,
        resp_cookie=resp_cookie,
    )


_OUT = ["resp_code", "resp_body", "resp_header", "resp_cookie", "response_time", "redirect_url"]


# noinspection PyPep8Naming
@keyword("http_get", name="发送GET请求", category="Http",
         out_params=_OUT, legacy_impl="HttpKeyword:doGet")
def http_get(ctx, url="", header="", request="",
             auto_redirect="true", timeOut="",
             req_cookie="", refer_proxy_var="NONE",
             resp_code="", resp_body="", resp_header="", resp_cookie="",
             response_time="", redirect_url="", **_kw) -> dict:
    return _request(ctx, "GET", url, header, request, auto_redirect,
                    timeOut, resp_code, resp_body, resp_header, response_time, redirect_url,
                    req_cookie=req_cookie, refer_proxy_var=refer_proxy_var, resp_cookie=resp_cookie)


# noinspection PyPep8Naming
@keyword("http_post", name="发送POST请求", category="Http",
         out_params=_OUT, legacy_impl="HttpKeyword:doPost")
def http_post(ctx, url="", header="", request="",
              auto_redirect="true", timeOut="",
              req_cookie="", refer_proxy_var="NONE",
              resp_code="", resp_body="", resp_header="", resp_cookie="",
              response_time="", redirect_url="", **_kw) -> dict:
    return _request(ctx, "POST", url, header, request, auto_redirect,
                    timeOut, resp_code, resp_body, resp_header, response_time, redirect_url,
                    req_cookie=req_cookie, refer_proxy_var=refer_proxy_var, resp_cookie=resp_cookie)


# noinspection PyPep8Naming
@keyword("http_put", name="发送PUT请求", category="Http",
         out_params=_OUT, legacy_impl="HttpKeyword:doPut")
def http_put(ctx, url="", header="", request="",
             auto_redirect="true", timeOut="",
             req_cookie="", refer_proxy_var="NONE",
             resp_code="", resp_body="", resp_header="", resp_cookie="",
             response_time="", redirect_url="", **_kw) -> dict:
    return _request(ctx, "PUT", url, header, request, auto_redirect,
                    timeOut, resp_code, resp_body, resp_header, response_time, redirect_url,
                    req_cookie=req_cookie, refer_proxy_var=refer_proxy_var, resp_cookie=resp_cookie)


# noinspection PyPep8Naming
@keyword("http_delete", name="发送DELETE请求", category="Http",
         out_params=_OUT, legacy_impl="HttpKeyword:doDelete")
def http_delete(ctx, url="", header="", request="",
                auto_redirect="true", timeOut="",
                req_cookie="", refer_proxy_var="NONE",
                resp_code="", resp_body="", resp_header="", resp_cookie="",
                response_time="", redirect_url="", **_kw) -> dict:
    return _request(ctx, "DELETE", url, header, request, auto_redirect,
                    timeOut, resp_code, resp_body, resp_header, response_time, redirect_url,
                    req_cookie=req_cookie, refer_proxy_var=refer_proxy_var, resp_cookie=resp_cookie)


# noinspection PyPep8Naming
@keyword("http_patch", name="发送PATCH请求", category="Http", out_params=_OUT)
def http_patch(ctx, url="", header="", request="",
               auto_redirect="true", timeOut="",
               req_cookie="", refer_proxy_var="NONE",
               resp_code="", resp_body="", resp_header="", resp_cookie="",
               response_time="", redirect_url="", **_kw) -> dict:
    return _request(ctx, "PATCH", url, header, request, auto_redirect,
                    timeOut, resp_code, resp_body, resp_header, response_time, redirect_url,
                    req_cookie=req_cookie, refer_proxy_var=refer_proxy_var, resp_cookie=resp_cookie)


# noinspection PyPep8Naming
@keyword("http_head", name="发送HEAD请求", category="Http", out_params=_OUT)
def http_head(ctx, url="", header="", request="",
              auto_redirect="true", timeOut="",
              req_cookie="", refer_proxy_var="NONE",
              resp_code="", resp_body="", resp_header="", resp_cookie="",
              response_time="", redirect_url="", **_kw) -> dict:
    return _request(ctx, "HEAD", url, header, request, auto_redirect,
                    timeOut, resp_code, resp_body, resp_header, response_time, redirect_url,
                    req_cookie=req_cookie, refer_proxy_var=refer_proxy_var, resp_cookie=resp_cookie)


# noinspection PyPep8Naming
@keyword("http_options", name="发送OPTIONS请求", category="Http", out_params=_OUT)
def http_options(ctx, url="", header="", request="",
                 auto_redirect="true", timeOut="",
                 req_cookie="", refer_proxy_var="NONE",
                 resp_code="", resp_body="", resp_header="", resp_cookie="",
                 response_time="", redirect_url="", **_kw) -> dict:
    return _request(ctx, "OPTIONS", url, header, request, auto_redirect,
                    timeOut, resp_code, resp_body, resp_header, response_time, redirect_url,
                    req_cookie=req_cookie, refer_proxy_var=refer_proxy_var, resp_cookie=resp_cookie)


@keyword("http_add_header", name="添加请求头", category="Http",
         out_params=["reference"], legacy_impl="HttpKeyword:addHeader")
def add_header(ctx: ExecutionContext, header="", key="", value="", reference="", **_kw) -> dict:
    from .session import get_http_session  # 延迟：拆 client↔session 环

    headers = _parse_mapping(header)
    headers[key] = value
    state = get_http_session(ctx)
    if state is not None and not header:
        # 无入参 header 时写入会话默认头，便于后续请求继承
        state.default_headers[str(key)] = str(value)
        try:
            state.client.headers[str(key)] = str(value)
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
    return {reference: headers} if reference else {}



# ---------------------------------------------------------------------------
# 扩展关键字（原 client_ext.py，HttpKeyword 其余）。
# cookie 在本框架内用 dict[name->value] 持有；header 用 dict 持有。
# Mock 类关键字改用内置通用 Mock Server 中性实现（见 mock_server.py）；代理认证类仅生成配置对象。
# ---------------------------------------------------------------------------


def _cookies(val: Any) -> dict:
    """把 cookie 参数解析成 dict[name->value]。支持 dict / JSON / 'k:v' / 'k=v'。"""
    if not val:
        return {}
    if isinstance(val, dict):
        return dict(val)
    s = str(val).strip()
    out = _parse_mapping(s)
    if out:
        return out
    # 退化处理 name=value;name2=value2
    for line in s.replace(";", "\n").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# noinspection PyPep8Naming,PyUnusedLocal
@keyword("http_post_mock", name="HTTP_POST请求(mock)", category="Http",
         out_params=["mock_info", "resp_code", "resp_header", "resp_cookie",
                     "resp_body", "redirect_url"],
         legacy_impl="HttpKeyword:doPostAndQueryRequestMessage")
def http_post_mock(_ctx, url="", interface="", req_cookie="", header="", request="",
                   encode="UTF-8", mock_info="", resp_code="", resp_header="",
                   resp_cookie="", resp_body="", redirect_url="", **_kw) -> dict:
    """发送 POST 并回读 mock 收到的请求报文（中性实现，基于内置通用 Mock Server）。"""
    headers = _parse_mapping(header)
    cookies = _cookies(req_cookie)
    content, json_obj = _body(request)
    with httpx.Client(follow_redirects=True, timeout=20.0) as cli:
        resp = cli.post(url, headers=headers or None, cookies=cookies or None,
                        content=content, json=json_obj)
    out: dict = {}
    if resp_code:
        out[resp_code] = resp.status_code
    if resp_header:
        out[resp_header] = dict(resp.headers)
    if resp_cookie:
        out[resp_cookie] = dict(resp.cookies)
    if resp_body:
        out[resp_body] = resp.text
    if redirect_url and resp.history:
        out[redirect_url] = str(resp.url)
    if mock_info:
        out[mock_info] = get_mock_server().received.get(urlparse(url).path, "")
    return out


@keyword("http_get_download", name="HTTP_GET下载请求", category="Http",
         out_params=["resp_code", "resp_header", "resp_cookie", "download_file_path"],
         legacy_impl="HttpKeyword:doGetDownload")
def http_get_download(ctx, url="", req_cookie="", header="",
                      resp_code="", resp_header="", resp_cookie="", file_selector="本地",
                      file_path="", download_file_path="", **_kw) -> dict:
    headers = _parse_mapping(header)
    cookies = _cookies(req_cookie)
    with httpx.Client(follow_redirects=True, timeout=20.0) as cli:
        resp = cli.get(url, headers=headers or None, cookies=cookies or None)
    filename = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "download"
    base = to_native(file_path)
    if file_selector == "工程":
        proj = getattr(ctx, "project_path", None) or os.getcwd()
        base = join_project(proj, base) if base else to_native(proj)
    elif not base:
        raise KeywordError("本地下载路径 file_path 不能为空。")
    os.makedirs(base, exist_ok=True)
    full = os.path.join(base, filename)
    with open(full, "wb") as f:
        f.write(resp.content)
    saved = full if file_selector == "本地" else os.path.join(file_path, filename)
    out: dict = {}
    if resp_code:
        out[resp_code] = resp.status_code
    if resp_header:
        out[resp_header] = dict(resp.headers)
    if resp_cookie:
        out[resp_cookie] = dict(resp.cookies)
    if download_file_path:
        out[download_file_path] = saved
    return out


# 文件后缀 -> content-type（对照 Java contentTypeTable）
_CT = {"png": "image/png", "gif": "image/gif", "jpeg": "image/jpeg",
       "jpg": "image/jpeg", "tiff": "image/tiff", "bmp": "image/bmp"}


# noinspection PyPep8Naming
@keyword("http_post_Multipart", name="HTTP文件上传", category="Http",
         out_params=["resp_code", "resp_header", "resp_cookie", "resp_body"],
         legacy_impl="HttpKeyword:doPostMultipart")
def http_post_multipart(ctx, http_method="POST", url="", req_cookie="", header="",
                        filePath="", fileKey="file", textBody="",
                        resp_code="", resp_header="", resp_cookie="", resp_body="",
                        **_kw) -> dict:
    headers = _parse_mapping(header)
    cookies = _cookies(req_cookie)
    if filePath:
        rel = to_native(filePath)
        proj = getattr(ctx, "project_path", None) or os.getcwd()
        path = join_project(proj, rel)
        ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
        ct = _CT.get(ext)
        with open(path, "rb") as f:
            content = f.read()
        files = {fileKey: (os.path.basename(path), content, ct) if ct
                 else (os.path.basename(path), content)}
    else:
        files = {fileKey: ("", b"")}
    data: dict = {}
    if textBody:
        for kv in textBody.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                if v == "STR.EMPTY":
                    v = ""
                elif v == "STR.NULL":
                    continue
                data[k] = v
    method = "PUT" if str(http_method).upper() == "PUT" else "POST"
    with httpx.Client(follow_redirects=True, timeout=10.0) as cli:
        resp = cli.request(method, url, headers=headers or None,
                           cookies=cookies or None, files=files, data=data or None)
    out: dict = {}
    if resp_code:
        out[resp_code] = resp.status_code
    if resp_header:
        out[resp_header] = dict(resp.headers)
    if resp_cookie:
        out[resp_cookie] = dict(resp.cookies)
    if resp_body:
        out[resp_body] = resp.text
    return out


@keyword("http_remove_header", name="删除头域", category="Http",
         out_params=["reference"], legacy_impl="HttpKeyword:removeHeader")
def http_remove_header(_ctx, header="", key="", reference="", **_kw) -> dict:
    headers = _parse_mapping(header)
    headers.pop(key, None)
    return {reference: headers}


@keyword("http_verify_header", name="校验头域", category="Http",
         out_params=[], legacy_impl="HttpKeyword:verifyHeader")
def http_verify_header(_ctx, header="", key="", text="", matched="true",
                       mode="精确匹配", **_kw) -> dict:
    headers = _parse_mapping(header)
    if key not in headers:
        raise KeywordError(f"头域中不存在 Key {key}")
    actual = str(headers[key])
    if mode == "模糊匹配":
        is_matched = text in actual
    elif mode == "正则表达式匹配":
        is_matched = re.fullmatch(text, actual) is not None
    else:
        is_matched = actual == text
    expect = str(matched).lower() != "false"
    if is_matched != expect:
        raise KeywordError(
            f"校验头域内容失败, 实际值是[{actual}], 期望值是[{text}], "
            f"预期匹配状态是[{expect}].")
    return {}


@keyword("http_add_cookie", name="添加cookie", category="Http",
         out_params=["cookie"], legacy_impl="HttpKeyword:addCookie")
def http_add_cookie(_ctx, pre_cookie="", name="", value="", cookie="", **_kw) -> dict:
    cookies = _cookies(pre_cookie)
    cookies[name] = value
    return {cookie: cookies}


# noinspection PyPep8Naming
@keyword("http_getCookieValue_BycookieName", name="获取Cookie值", category="Http",
         out_params=["cookieValue"], legacy_impl="HttpKeyword:getCookieValueByName")
def http_get_cookie_value(_ctx, cookie="", cookieName="", cookieValue="", **_kw) -> dict:
    cookies = _cookies(cookie)
    if cookieName not in cookies:
        raise KeywordError(f"您输入的cookie/集合中不存在与名称{cookieName}匹配的cookie，请检查!")
    return {cookieValue: cookies[cookieName]}


# noinspection PyPep8Naming,PyUnusedLocal
@keyword("http_setMock", name="埋桩", category="Http",
         out_params=[], legacy_impl="HttpKeyword:setMock")
def http_set_mock(ctx, serviceCode="", operation="", caseIdAppend="", httpBody="",
                  msg_template_path="", isReplace="no", replaceElement="", **_kw) -> dict:
    """登记一个桩响应到内置通用 Mock Server（中性实现，不依赖私有桩平台）。

    路由 = /serviceCode/operation；响应体 = httpBody。
    mock 服务基址写入变量 mock_base_url，桩完整地址写入 mock_last_url，供后续请求引用。
    """
    srv = get_mock_server()
    parts = [p.strip("/") for p in (serviceCode, operation) if p and p.strip("/")]
    route = "/" + "/".join(parts) if parts else "/mock"
    url = srv.set_stub(route, 200, httpBody or "")
    ctx.set_var("mock_base_url", srv.base_url())
    ctx.set_var("mock_last_url", url)
    return {}


@keyword("http_cleanMock", name="清除桩", category="Http",
         out_params=[], legacy_impl="HttpKeyword:cleanMock")
def http_clean_mock(_ctx, **_kw) -> dict:
    """清空内置 Mock Server 的全部桩与记录（中性实现）。"""
    get_mock_server().clear()
    return {}


# ---- Mock 桩服务生命周期/模式（中性实现，包到内置 MockServer）----
# noinspection PyPep8Naming,PyUnusedLocal,PyShadowingBuiltins
@keyword("http_startMockStubServer", name="启动桩服务器", category="Http",
         legacy_impl="MockKeyword:startMockStubServer")
def http_start_mock_stub_server(ctx: ExecutionContext, port="", type="", exception="",
                                mode="normal", connectTimeout="", timeOut="", **_kw) -> None:
    """启动内置中性 Mock 桩服务；基址写入变量 mock_base_url。mode 记录桩行为模式。"""
    srv = get_mock_server()
    srv.start()
    srv.mode = mode or "normal"
    ctx.set_var("mock_base_url", srv.base_url())
    ctx.log(f"桩服务已启动: {srv.base_url()}（模式 {srv.mode}）")


# noinspection PyPep8Naming,PyUnusedLocal,PyShadowingBuiltins
@keyword("http_stopMockStubServer", name="停止桩服务器", category="Http",
         legacy_impl="MockKeyword:stopMockStubServer")
def http_stop_mock_stub_server(_ctx: ExecutionContext, port="", type="", **_kw) -> None:
    """停止内置 Mock 桩服务。"""
    get_mock_server().stop()


# noinspection PyPep8Naming,PyUnusedLocal
@keyword("http_setMockMode", name="设置桩模式", category="Http",
         legacy_impl="MockKeyword:setMockMode")
def http_set_mock_mode(_ctx: ExecutionContext, port="", mode="normal", **_kw) -> None:
    """设置 Mock 桩服务模式(normal/exception/timeout…)。"""
    get_mock_server().mode = mode or "normal"


# noinspection PyPep8Naming,PyUnusedLocal
@keyword("http_getMockMode", name="获取桩模式", category="Http",
         out_params=["mode"], legacy_impl="MockKeyword:getMockMode")
def http_get_mock_mode(_ctx: ExecutionContext, port="", mode="", **_kw) -> dict:
    """读取当前 Mock 桩服务模式，写入输出变量。"""
    return {mode: get_mock_server().mode}


# ---- Hessian 报文字段（参考实现本质是 k=v 文本解析，非真 Hessian 序列化）----
def _parse_kv(text: str) -> dict:
    """把 k=v 文本(以换行/;/&/, 分隔)解析成字典。"""
    out: dict[str, str] = {}
    for seg in re.split(r"[\r\n;&,]+", str(text or "")):
        if "=" in seg:
            k, _, v = seg.partition("=")
            out[k.strip()] = v.strip()
    return out


# noinspection PyPep8Naming
@keyword("getHessianField", name="获取Hessian消息字段", category="Http",
         out_params=["varFieldValue"], legacy_impl="HessianKeyword:getHessianField")
def get_hessian_field(_ctx: ExecutionContext, text="", fieldName="", varFieldValue="",
                      **_kw) -> dict:
    """从 k=v 报文文本中取 fieldName 的值，写入输出变量。"""
    return {varFieldValue: _parse_kv(text).get(fieldName, "")}


# noinspection PyPep8Naming
@keyword("verifyHessianField", name="校验Hessian消息体", category="Http",
         legacy_impl="HessianKeyword:verifyHessianField")
def verify_hessian_field(_ctx: ExecutionContext, text="", expect="", mode="精确匹配",
                         **_kw) -> None:
    """校验报文文本：mode=模糊匹配 时判包含，否则判精确相等；不符抛 KeywordError。"""
    body = str(text or "")
    ok = (expect in body) if "模糊" in str(mode) else (body.strip() == str(expect).strip())
    if not ok:
        raise KeywordError(f"Hessian 报文校验失败({mode}): 期望[{expect}] 实际[{body[:200]}]")


# noinspection PyPep8Naming
@keyword("MQ_get_UID", name="获取唯一UID(48位)", category="Http",
         out_params=["UID"], legacy_impl="MqKeyword:getUID")
def mq_get_uid(_ctx: ExecutionContext, UID="", **_kw) -> dict:  # noqa: N803
    """生成 48 位唯一串(uuid×2 去横线取前 48 位)，写入输出变量。"""
    val = (uuid.uuid4().hex + uuid.uuid4().hex)[:48]
    return {UID: val}


@keyword("http_setproxy", name="定义http代理", category="Http",
         out_params=["out_proxy"], legacy_impl="HttpKeyword:setHttpProxy")
def http_set_proxy(_ctx, host="", port="", user="NONE", password="NONE",
                   out_proxy="", **_kw) -> dict:
    # 仅生成代理配置对象（供后续请求引用）；内网认证(IT auth)服务无法纯实现，故跳过。
    proxy = {"host": host, "port": port, "user": user, "password": password}
    return {out_proxy: proxy} if out_proxy else {}
