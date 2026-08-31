from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WeChatErrorInfo:
    category: str
    retryable: bool
    operator_action: str


ERRORS: dict[int, WeChatErrorInfo] = {
    40001: WeChatErrorInfo("token_invalid", True, "刷新 access_token 后重试一次"),
    40007: WeChatErrorInfo("invalid_media", False, "重新上传有效素材"),
    40013: WeChatErrorInfo("invalid_app_id", False, "检查 AppID"),
    40014: WeChatErrorInfo("token_invalid", True, "刷新 access_token 后重试一次"),
    40164: WeChatErrorInfo("ip_whitelist", False, "把服务器出口 IP 加入公众号白名单"),
    42001: WeChatErrorInfo("token_expired", True, "刷新 access_token 后重试一次"),
    45009: WeChatErrorInfo("rate_limit", True, "等待限流窗口后指数退避"),
    48001: WeChatErrorInfo("no_permission", False, "检查账号认证与接口权限"),
}


def map_wechat_error(code: int) -> WeChatErrorInfo:
    if code in ERRORS:
        return ERRORS[code]
    if code == -1 or code >= 50000:
        return WeChatErrorInfo("system_busy", True, "指数退避后重试")
    return WeChatErrorInfo("wechat_error", False, "查看微信官方错误码并人工处理")
