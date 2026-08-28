"""SAML 2.0 Web SSO（轻量）：SP 元数据 + ACS；签名校验用 signxml/cryptography（无 xmlsec）。

生产：配置 MC_SAML_IDP_CERT(_FILE)，关闭 MC_SAML_ALLOW_UNSIGNED。
联调：MC_SAML_ALLOW_UNSIGNED=1 可跳过签名。
"""

from __future__ import annotations

import base64
import secrets
import zlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from lxml import etree
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import TokenOut

from ..core import api_messages as msg
from ..core.models import UserRow, new_id
from ..core.security import hash_password
from ..core.settings import (
    saml_acs_url,
    saml_allow_unsigned,
    saml_auto_provision,
    saml_clock_skew_sec,
    saml_default_role,
    saml_enabled,
    saml_frontend_redirect,
    saml_idp_cert_pem,
    saml_idp_entity_id,
    saml_idp_sso_url,
    saml_sp_entity_id,
)

_NS = {
    "saml2": "urn:oasis:names:tc:SAML:2.0:assertion",
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}


def saml_status() -> dict[str, Any]:
    ok = saml_enabled() and bool(saml_idp_sso_url() and saml_acs_url())
    cert = bool(saml_idp_cert_pem())
    return {
        "enabled": ok,
        "idp_sso_url": saml_idp_sso_url() if ok else "",
        "acs_url": saml_acs_url() if ok else "",
        "sp_entity_id": saml_sp_entity_id() if ok else "",
        "signature_verify": cert and not saml_allow_unsigned(),
        "allow_unsigned": saml_allow_unsigned(),
        "idp_cert_configured": cert,
    }


def _require() -> None:
    if not saml_enabled():
        raise RuntimeError(msg.AUTH_SAML_DISABLED)
    if not saml_idp_sso_url():
        raise RuntimeError(msg.AUTH_SAML_CONFIG_REQUIRED)


def sp_metadata_xml() -> str:
    entity = saml_sp_entity_id()
    acs = saml_acs_url()
    want_signed = "true" if saml_idp_cert_pem() and not saml_allow_unsigned() else "false"
    return (
        '<?xml version="1.0"?>'
        f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity}">'
        "<md:SPSSODescriptor "
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'AuthnRequestsSigned="false" WantAssertionsSigned="{want_signed}">'
        '<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified</md:NameIDFormat>'
        f'<md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location="{acs}" index="0" isDefault="true"/>'
        "</md:SPSSODescriptor>"
        "</md:EntityDescriptor>"
    )


def build_login_redirect_url() -> str:
    """SP-initiated：跳转到 IdP SSO（可选带压缩 AuthnRequest）。"""
    _require()
    sso = saml_idp_sso_url()
    req_id = "_" + secrets.token_hex(16)
    acs = saml_acs_url()
    issuer = saml_sp_entity_id()
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{req_id}" Version="2.0" '
        f'AssertionConsumerServiceURL="{acs}" '
        f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        "</samlp:AuthnRequest>"
    )
    raw = zlib.compress(xml.encode("utf-8"))[2:-4]  # DEFLATE raw
    saml_req = base64.b64encode(raw).decode("ascii")
    q = urlencode({"SAMLRequest": saml_req, "RelayState": "mc"})
    sep = "&" if "?" in sso else "?"
    return f"{sso}{sep}{q}"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _load_idp_cert():
    pem = saml_idp_cert_pem()
    if not pem:
        return None
    from cryptography import x509

    return x509.load_pem_x509_certificate(pem.encode("utf-8"))


def _verify_xml_signature(root: Any) -> None:
    """用 IdP 证书校验 XML-DSig；失败抛 ValueError。

    ``root`` 为 ``lxml.etree.fromstring`` 返回的元素（内部类型 ``_Element``，无公开别名）。
    """
    cert = _load_idp_cert()
    if cert is None:
        raise ValueError(
            "SAML signature required: set MC_SAML_IDP_CERT or MC_SAML_IDP_CERT_FILE "
            "(or MC_SAML_ALLOW_UNSIGNED=1 for lab only)"
        )
    has_sig = root.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature") is not None
    if not has_sig:
        raise ValueError("SAMLResponse missing Signature")
    try:
        from signxml import XMLVerifier
    except ImportError as exc:
        raise ValueError("signxml required for SAML signature verify") from exc
    try:
        XMLVerifier().verify(root, x509_cert=cert)
    except Exception as exc:  # noqa: BLE001 — 统一为业务错误
        raise ValueError(f"SAML signature verify failed: {exc}") from exc


def _parse_xs_datetime(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_conditions(root: Any) -> None:
    """校验 Assertion Conditions：时间窗与 Audience。"""
    from datetime import timedelta

    skew = saml_clock_skew_sec()
    now = datetime.now(timezone.utc)
    audiences_expected = {a for a in (saml_sp_entity_id(), saml_acs_url()) if a}

    for el in root.iter():
        if _local(el.tag) != "Conditions":
            continue
        nb = _parse_xs_datetime(el.get("NotBefore") or "")
        na = _parse_xs_datetime(el.get("NotOnOrAfter") or "")
        if nb is not None and now + timedelta(seconds=skew) < nb:
            raise ValueError("SAML Assertion NotBefore in the future")
        if na is not None and now - timedelta(seconds=skew) >= na:
            raise ValueError("SAML Assertion expired (NotOnOrAfter)")

        found: list[str] = []
        for child in el.iter():
            if _local(child.tag) == "Audience" and (child.text or "").strip():
                found.append(child.text.strip())
        if found and audiences_expected and not (set(found) & audiences_expected):
            raise ValueError(f"SAML Audience mismatch: {found[0]!r}")


def parse_saml_response(saml_response_b64: str) -> dict[str, str]:
    """解析 SAMLResponse，返回 nameid / username 等。"""
    try:
        xml_bytes = base64.b64decode(saml_response_b64)
    except Exception as exc:  # noqa: BLE001 — base64 解码统一为业务错误
        raise ValueError("invalid SAMLResponse encoding") from exc
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError("invalid SAMLResponse XML") from exc

    if saml_allow_unsigned():
        has_sig = root.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature") is not None
        # 联调：无签名放行；若已签名且配了证书则仍校验（防误配）
        if has_sig and saml_idp_cert_pem():
            _verify_xml_signature(root)
    else:
        _verify_xml_signature(root)

    # Issuer 校验（可选配置）
    expected_idp = saml_idp_entity_id()
    if expected_idp:
        issuers = root.xpath(
            "//saml2:Issuer/text() | //saml:Issuer/text()",
            namespaces={
                "saml2": _NS["saml2"],
                "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
            },
        )
        if not issuers:
            issuers = [
                (el.text or "").strip()
                for el in root.iter()
                if _local(el.tag) == "Issuer" and (el.text or "").strip()
            ]
        if issuers and expected_idp not in issuers:
            raise ValueError(f"unexpected Issuer: {issuers[0]!r}")

    _validate_conditions(root)

    nameid = ""
    for el in root.iter():
        if _local(el.tag) == "NameID" and (el.text or "").strip():
            nameid = el.text.strip()
            break
    if not nameid:
        raise ValueError("NameID missing in SAMLResponse")

    attrs: dict[str, str] = {}
    for el in root.iter():
        if _local(el.tag) == "Attribute":
            name = el.get("Name") or el.get("FriendlyName") or ""
            vals = [
                (c.text or "").strip()
                for c in el
                if _local(c.tag) == "AttributeValue" and (c.text or "").strip()
            ]
            if name and vals:
                attrs[name] = vals[0]

    username = (
        attrs.get("uid")
        or attrs.get("username")
        or attrs.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")
        or attrs.get("email")
        or attrs.get("mail")
        or nameid
    )
    if "@" in username:
        username = username.split("@", 1)[0]
    username = "".join(c if c.isalnum() or c in "._-" else "_" for c in username.strip())[:64]
    if not username:
        username = f"saml_{secrets.token_hex(4)}"

    return {"nameid": nameid, "username": username}


def resolve_or_create_saml_user(db: Session, *, nameid: str, username: str) -> UserRow:
    row = db.scalars(select(UserRow).where(UserRow.saml_nameid == nameid)).first()
    if row is not None:
        return row

    existing = db.scalars(select(UserRow).where(UserRow.username == username)).first()
    if existing is not None:
        if existing.saml_nameid and existing.saml_nameid != nameid:
            username = f"{username}_{secrets.token_hex(2)}"
        else:
            existing.saml_nameid = nameid
            db.commit()
            db.refresh(existing)
            return existing

    if not saml_auto_provision():
        raise PermissionError(msg.AUTH_SAML_USER_NOT_PROVISIONED)

    base = username
    n = 0
    while db.scalars(select(UserRow).where(UserRow.username == username)).first():
        n += 1
        username = f"{base}_{n}"

    row = UserRow(
        id=new_id(),
        username=username,
        password_hash=hash_password(secrets.token_urlsafe(24)),
        role=saml_default_role(),
        saml_nameid=nameid,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        raced = db.scalars(select(UserRow).where(UserRow.saml_nameid == nameid)).first()
        if raced is not None:
            return raced
        raise


def complete_saml_login(db: Session, *, saml_response_b64: str) -> TokenOut:
    claims = parse_saml_response(saml_response_b64)
    user = resolve_or_create_saml_user(db, nameid=claims["nameid"], username=claims["username"])
    from .session_tokens import issue_session

    return issue_session(db, user)


def frontend_success_redirect(token: TokenOut) -> str:
    """把 token 放进 URL fragment，避免进 access log / Referer。"""
    base = saml_frontend_redirect().strip() or "/"
    if "#" in base:
        base = base.split("#", 1)[0]
    base = base.rstrip("/") or ""
    params = {
        "saml": "1",
        "access_token": token.access_token,
        "username": token.user.username,
        "role": token.user.role,
        "user_id": token.user.id,
    }
    if token.refresh_token:
        params["refresh_token"] = token.refresh_token
    q = urlencode(params)
    return f"{base}/#{q}" if base else f"/#{q}"
