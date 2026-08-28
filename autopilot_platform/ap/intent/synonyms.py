"""意图目标名词的中英同义小表（不做动作词）。

用于：过滤 / 预裁剪焦点、启发式 XPath。不收录「点击/输入/打开」这类动作，
避免半页可点控件被加分。
"""

from __future__ import annotations

import re

# 每组互为同义；大小写不敏感。只放控件文案 / resource-id 里会出现的目标名词。
_GROUPS: tuple[frozenset[str], ...] = (
    # 账号
    frozenset({"登录", "登入", "登陆", "login", "signin", "sign-in", "sign in", "log in", "log-in"}),
    frozenset({"注册", "signup", "sign-up", "sign up", "register"}),
    frozenset({"退出", "登出", "注销", "logout", "signout", "sign-out", "sign out", "log out"}),
    frozenset({"密码", "口令", "password", "passwd", "pwd"}),
    frozenset({"用户名", "账号", "帐户", "账户", "username", "userid", "user id", "account"}),
    frozenset({"验证码", "校验码", "captcha", "otp", "verify code", "verification code"}),
    frozenset({"邮箱", "邮件", "电子邮箱", "email", "e-mail", "mail"}),
    frozenset({"手机号", "手机", "电话", "phone", "mobile", "tel"}),
    # 导航 / 表单按钮文案
    frozenset({"设置", "设定", "settings", "setting", "preferences", "prefs"}),
    frozenset({"搜索", "查找", "检索", "search", "find"}),
    frozenset({"首页", "主页", "主屏幕", "home", "homepage", "homescreen"}),
    frozenset({"菜单", "menu", "menubar"}),
    frozenset({"更多", "more"}),
    frozenset({"取消", "cancel"}),
    frozenset({"确定", "确认", "提交", "完成", "ok", "okay", "confirm", "submit", "done", "apply"}),
    frozenset({"保存", "save", "store"}),
    frozenset({"下一步", "继续", "next", "continue"}),
    frozenset({"上一步", "上一页", "previous", "prev"}),
    frozenset({"关闭", "关掉", "close", "dismiss"}),
    frozenset({"返回", "back"}),
    frozenset({"帮助", "help", "faq"}),
    # 系统 / 设置页（中英混排很常见）
    frozenset({"wifi", "wi-fi", "wlan", "无线局域网", "无线网络", "无线网"}),
    frozenset({"蓝牙", "bluetooth", "bt"}),
    frozenset({"通知", "消息通知", "notification", "notifications"}),
    frozenset({"显示", "屏幕", "display", "screen", "brightness"}),
    frozenset({"声音", "音量", "铃声", "sound", "volume", "audio"}),
    frozenset({"电池", "电量", "battery", "power"}),
    frozenset({"存储", "储存", "空间", "storage", "memory"}),
    frozenset({"应用", "应用程序", "软件", "apps", "applications", "application"}),
    frozenset({"权限", "许可", "permission", "permissions"}),
    frozenset({"网络", "联网", "network", "internet", "connectivity"}),
    frozenset({"飞行模式", "airplane", "aeroplane", "airplane mode", "flight mode"}),
    frozenset({"定位", "位置", "location", "gps"}),
    frozenset({"关于", "about", "about phone"}),
    frozenset({"语言", "language", "locale"}),
    frozenset({"时间", "日期", "time", "date", "clock"}),
    frozenset({"隐私", "privacy"}),
    frozenset({"安全", "security"}),
    frozenset({"热点", "个人热点", "hotspot", "tethering"}),
    # 常见业务控件
    frozenset({"购物车", "购物袋", "cart", "bag", "basket"}),
    frozenset({"订单", "order", "orders"}),
    frozenset({"支付", "付款", "结账", "pay", "payment", "checkout"}),
    frozenset({"地址", "收货地址", "address"}),
    frozenset({"收藏", "喜欢", "favorite", "favourite", "bookmark", "wishlist"}),
    frozenset({"分享", "share"}),
    frozenset({"刷新", "reload", "refresh"}),
    frozenset({"筛选", "过滤", "filter"}),
    frozenset({"排序", "sort"}),
    frozenset({"编辑", "修改", "edit", "modify"}),
    frozenset({"删除", "移除", "delete", "remove"}),
    frozenset({"添加", "新增", "add", "create"}),
    frozenset({"详情", "详细", "detail", "details"}),
    frozenset({"个人中心", "我的", "profile", "account center"}),
    frozenset({"消息", "消息中心", "message", "messages", "inbox", "chat"}),
    frozenset({"相机", "拍照", "camera", "photo"}),
    frozenset({"相册", "图库", "gallery", "photos", "album"}),
)

_COMPACT_RE = re.compile(r"[\s_\-]+")
_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _compact(text: str) -> str:
    return _COMPACT_RE.sub("", (text or "").strip().lower())


def _is_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


def _index() -> tuple[dict[str, frozenset[str]], list[tuple[str, frozenset[str]]]]:
    """精确键 → 组；以及带空格/连字符的短语（用于整句扫描）。"""
    exact: dict[str, frozenset[str]] = {}
    phrases: list[tuple[str, frozenset[str]]] = []
    for group in _GROUPS:
        for alias in group:
            key = alias.lower()
            exact[key] = group
            packed = _compact(alias)
            if packed and packed != key:
                exact[packed] = group
            if " " in key or "-" in key:
                phrases.append((key, group))
    return exact, phrases


_EXACT, _PHRASES = _index()


def _groups_for_text(text: str) -> list[frozenset[str]]:
    raw = (text or "").strip()
    if not raw:
        return []
    low = raw.lower()
    packed = _compact(low)
    found: list[frozenset[str]] = []
    seen: set[int] = set()

    def _add(alias_group: frozenset[str]) -> None:
        ident = id(alias_group)
        if ident in seen:
            return
        seen.add(ident)
        found.append(alias_group)

    hit = _EXACT.get(low) or _EXACT.get(packed)
    if hit:
        _add(hit)
    for tok in _WORD_RE.findall(low):
        if len(tok) < 2:
            continue
        g = _EXACT.get(tok) or (_EXACT.get(_compact(tok)) if len(tok) >= 4 else None)
        if g:
            _add(g)
    for phrase, group in _PHRASES:
        if phrase in low or (len(_compact(phrase)) >= 4 and _compact(phrase) in packed):
            _add(group)
    if _is_cjk(low):
        for alias, group in _EXACT.items():
            if _is_cjk(alias) and alias in low:
                _add(group)
    return found


def expand_intent_tokens(tokens: set[str], raw: str = "") -> set[str]:
    """把已切出的 token 扩展为同组中英别名（含去空格形式）。"""
    out = {t for t in tokens if t}
    for group in _groups_for_text(raw):
        out.update(group)
        out.update(_compact(a) for a in group if _compact(a))
    for tok in list(tokens):
        for group in _groups_for_text(tok):
            out.update(group)
            out.update(_compact(a) for a in group if _compact(a))
    return {t for t in out if len(t) >= 2}


def target_aliases(target: str, *, limit: int = 5) -> list[str]:
    """启发式 XPath 用：原文在前，再补最多 ``limit-1`` 个跨语言别名。"""
    raw = (target or "").strip()
    if not raw:
        return []
    out = [raw]
    seen = {raw.lower(), _compact(raw)}
    prefer_cjk = not _is_cjk(raw)
    extras: list[str] = []
    for group in _groups_for_text(raw):
        ranked = sorted(
            group,
            key=lambda a: (
                0 if _is_cjk(a) == prefer_cjk else 1,
                0 if " " not in a else 1,
                len(a),
            ),
        )
        extras.extend(ranked)
    for alias in extras:
        key = alias.lower()
        packed = _compact(alias)
        if key in seen or packed in seen:
            continue
        if alias == raw:
            continue
        out.append(alias)
        seen.add(key)
        if packed:
            seen.add(packed)
        if len(out) >= max(1, int(limit)):
            break
    return out
