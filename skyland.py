import hashlib
import hmac
import json
import time
from typing import Any, Callable, Dict, List
from urllib import parse

import requests
from loguru import logger

from securitySm import get_d_id

APP_CODE = "4ca99fa6b56cc2ba"

# API URLs
SIGN_URL = "https://zonai.skland.com/api/v1/game/attendance"
BINDING_URL = "https://zonai.skland.com/api/v1/game/player/binding"
GRANT_CODE_URL = "https://as.hypergryph.com/user/oauth2/v2/grant"
CRED_CODE_URL = "https://zonai.skland.com/web/v1/user/auth/generate_cred_by_code"

# 签名请求头一定要这个顺序，否则失败
HEADER_FOR_SIGN = {
    "platform": "",
    "timestamp": "",
    "dId": "",
    "vName": "",
}


class SkylandClientException(Exception):
    """Custom exception for Skyland client errors."""


class SkylandClient:
    """森空岛签到客户端，用于明日方舟每日签到。"""

    def __init__(self, token: str):
        if not token:
            raise SkylandClientException("SKYLAND_TOKEN is required.")

        self.token = token
        self._cred = ""
        self._sign_token = ""
        self._header = {
            "cred": "",
            "User-Agent": "Skland/1.0.1 (com.hypergryph.skland; build:100001014; Android 31; ) Okhttp/4.11.0",
            "Accept-Encoding": "gzip",
            "Connection": "close",
        }
        self._header_login = {
            "User-Agent": "Skland/1.0.1 (com.hypergryph.skland; build:100001014; Android 31; ) Okhttp/4.11.0",
            "Accept-Encoding": "gzip",
            "Connection": "close",
            "dId": get_d_id(),
        }
        self.result: Dict[str, str] = {}
        self.exceptions: List[Exception] = []

    @staticmethod
    def _generate_signature(token: str, path: str, body_or_query: str):
        """
        计算请求签名。

        签名算法：
        1. 拼接 path + body_or_query + timestamp + header_for_sign JSON
        2. 使用 token 做 HMAC-SHA256
        3. 对结果做 MD5
        """
        # 时间戳偏移 -2 秒，避免服务端时间校验问题
        t = str(int(time.time()) - 2)
        token_bytes = token.encode("utf-8")
        header_ca = json.loads(json.dumps(HEADER_FOR_SIGN))
        header_ca["timestamp"] = t
        header_ca_str = json.dumps(header_ca, separators=(",", ":"))
        s = path + body_or_query + t + header_ca_str
        hex_s = hmac.new(token_bytes, s.encode("utf-8"), hashlib.sha256).hexdigest()
        md5 = hashlib.md5(hex_s.encode("utf-8")).hexdigest()
        logger.debug("计算签名: {}", md5)
        return md5, header_ca

    def _get_sign_header(self, url: str, method: str, body: Any) -> Dict[str, str]:
        """为请求添加签名头。"""
        p = parse.urlparse(url)
        h = self._header.copy()
        if method.lower() == "get":
            h["sign"], header_ca = self._generate_signature(self._sign_token, p.path, p.query)
        else:
            h["sign"], header_ca = self._generate_signature(
                self._sign_token, p.path, json.dumps(body)
            )
        h.update(header_ca)
        return h

    def _get_grant_code(self) -> str:
        """使用鹰角通行证 token 获取授权码。"""
        response = requests.post(
            GRANT_CODE_URL,
            json={"appCode": APP_CODE, "token": self.token, "type": 0},
            headers=self._header_login,
            timeout=15,
        )
        resp = response.json()
        if response.status_code != 200:
            raise SkylandClientException(f"获得认证代码失败：{resp}")
        if resp.get("status") != 0:
            raise SkylandClientException(f'获得认证代码失败：{resp["msg"]}')
        return resp["data"]["code"]

    def _get_cred(self, grant_code: str) -> Dict[str, str]:
        """使用授权码获取 cred 和 sign token。"""
        resp = requests.post(
            CRED_CODE_URL,
            json={"code": grant_code, "kind": 1},
            headers=self._header_login,
            timeout=15,
        ).json()
        if resp["code"] != 0:
            raise SkylandClientException(f'获得cred失败：{resp["message"]}')
        return resp["data"]

    def _authenticate(self):
        """完成认证流程：token → grant_code → cred。"""
        grant_code = self._get_grant_code()
        cred_data = self._get_cred(grant_code)
        self._sign_token = cred_data["token"]
        self._cred = cred_data["cred"]
        self._header["cred"] = self._cred
        logger.debug("森空岛认证成功")

    def _get_binding_list(self) -> List[Dict[str, Any]]:
        """获取绑定的明日方舟角色列表。"""
        headers = self._get_sign_header(BINDING_URL, "get", None)
        resp = requests.get(BINDING_URL, headers=headers, timeout=15).json()
        if resp["code"] != 0:
            raise SkylandClientException(f'请求角色列表失败：{resp["message"]}')
        characters = []
        for game in resp["data"]["list"]:
            if game.get("appCode") != "arknights":
                continue
            characters.extend(game.get("bindingList", []))
        return characters

    def _sign_character(self, character: Dict[str, Any]):
        """对单个角色执行签到。"""
        nick = character.get("nickName", "未知")
        channel = character.get("channelName", "")
        body = {"gameId": 1, "uid": character.get("uid")}
        headers = self._get_sign_header(SIGN_URL, "post", body)
        resp = requests.post(SIGN_URL, headers=headers, json=body, timeout=15).json()

        if resp["code"] != 0:
            msg = f"角色{nick}({channel})签到失败：{resp.get('message')}"
            self.exceptions.append(SkylandClientException(msg))
            logger.warning(msg)
            return

        awards = resp.get("data", {}).get("awards", [])
        for award in awards:
            res = award["resource"]
            count = award.get("count") or 1
            msg = f"角色{nick}({channel})签到成功，获得{res['name']}×{count}"
            self.result[f"{nick}_{res['name']}"] = msg
            logger.info(msg)

    def start(self):
        """执行完整的签到流程。"""
        self._authenticate()
        characters = self._get_binding_list()

        if not characters:
            logger.warning("未找到绑定的明日方舟角色")
            return

        logger.info("找到 {} 个明日方舟角色，开始签到", len(characters))
        for character in characters:
            self._sign_character(character)

        self._log()

    @property
    def msg(self) -> str:
        return ", ".join(self.result.values()) + "!" if self.result else ""

    def _log(self):
        """记录结果，如有失败则抛出异常。"""
        if msg := self.msg:
            logger.info(msg)
        if self.exceptions:
            raise SkylandClientException("; ".join(map(str, self.exceptions)))
