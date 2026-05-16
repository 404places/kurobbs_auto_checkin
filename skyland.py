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
SIGN_URLS = {
    "arknights": "https://zonai.skland.com/api/v1/game/attendance",
    "endfield": "https://zonai.skland.com/web/v1/game/endfield/attendance",
}
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


# 支持签到的游戏 appCode
ATTENDANCE_AVAILABLE_APPCODES = {"arknights", "endfield"}


class SkylandClient:
    """森空岛签到客户端，支持明日方舟和终末地每日签到。"""

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
            body_str = body if isinstance(body, str) else json.dumps(body)
            h["sign"], header_ca = self._generate_signature(
                self._sign_token, p.path, body_str
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
        """获取绑定的角色列表（明日方舟 + 终末地）。"""
        headers = self._get_sign_header(BINDING_URL, "get", None)
        resp = requests.get(BINDING_URL, headers=headers, timeout=15).json()
        if resp["code"] != 0:
            raise SkylandClientException(f'请求角色列表失败：{resp["message"]}')
        characters = []
        for game in resp["data"]["list"]:
            if game.get("appCode") not in ATTENDANCE_AVAILABLE_APPCODES:
                continue
            for binding in game.get("bindingList", []):
                # 保留 gameId、gameName 和 appCode 用于签到请求
                binding["_gameId"] = binding.get("gameId", game.get("gameId"))
                binding["_gameName"] = game.get("gameName", game.get("appCode"))
                binding["_appCode"] = game.get("appCode")
                characters.append(binding)
        return characters

    def _sign_arknights(self, character: Dict[str, Any]):
        """对明日方舟角色执行签到。"""
        nick = character.get("nickName", "未知")
        channel = character.get("channelName", "")
        game_id = character.get("_gameId", 1)
        label = f"[明日方舟] {nick}({channel})"

        sign_url = SIGN_URLS["arknights"]
        body = {"gameId": game_id, "uid": character.get("uid")}
        headers = self._get_sign_header(sign_url, "post", body)
        resp = requests.post(sign_url, headers=headers, json=body, timeout=15).json()

        if resp["code"] != 0:
            err_msg = resp.get("message", "")
            if "重复签到" in err_msg or "已签到" in err_msg:
                msg = f"{label} 今日已签到"
                self.result[f"{nick}_repeat"] = msg
                logger.info(msg)
            else:
                msg = f"{label} 签到失败：{err_msg}"
                self.exceptions.append(SkylandClientException(msg))
                logger.warning(msg)
            return

        awards = resp.get("data", {}).get("awards", [])
        for award in awards:
            res = award["resource"]
            count = award.get("count") or 1
            msg = f"{label} 签到成功，获得{res['name']}×{count}"
            self.result[f"{nick}_{res['name']}"] = msg
            logger.info(msg)

    def _sign_endfield(self, character: Dict[str, Any]):
        """对终末地角色执行签到（按 role 签到，与明日方舟流程不同）。"""
        nick = character.get("nickName", "未知")
        channel = character.get("channelName", "")
        roles = character.get("roles", [])

        if not roles:
            msg = f"[终末地] {nick}({channel}) 没有角色数据"
            logger.warning(msg)
            return

        sign_url = SIGN_URLS["endfield"]
        for role in roles:
            role_nick = role.get("nickname", nick)
            role_id = role.get("roleId", "")
            server_id = role.get("serverId", "")
            label = f"[终末地] {role_nick}({channel})"

            # 终末地签到用空 body，通过 header 传角色信息
            headers = self._get_sign_header(sign_url, "post", "")
            headers["Content-Type"] = "application/json"
            headers["sk-game-role"] = f"3_{role_id}_{server_id}"
            headers["referer"] = "https://game.skland.com/"
            headers["origin"] = "https://game.skland.com"

            resp = requests.post(sign_url, headers=headers, timeout=15).json()

            if resp["code"] != 0:
                err_msg = resp.get("message", "")
                if "重复签到" in err_msg or "已签到" in err_msg:
                    msg = f"{label} 今日已签到"
                    self.result[f"{role_nick}_repeat"] = msg
                    logger.info(msg)
                else:
                    msg = f"{label} 签到失败：{err_msg}"
                    self.exceptions.append(SkylandClientException(msg))
                    logger.warning(msg)
                continue

            # 终末地的奖励格式不同：awardIds + resourceInfoMap
            award_ids = resp.get("data", {}).get("awardIds", [])
            resource_map = resp.get("data", {}).get("resourceInfoMap", {})
            for award in award_ids:
                aid = str(award.get("id", ""))
                if aid in resource_map:
                    info = resource_map[aid]
                    name = info.get("name", "未知")
                    count = info.get("count", 1)
                    msg = f"{label} 签到成功，获得{name}×{count}"
                    self.result[f"{role_nick}_{name}"] = msg
                    logger.info(msg)

            if not award_ids:
                msg = f"{label} 签到成功"
                self.result[f"{role_nick}_sign"] = msg
                logger.info(msg)

    def start(self):
        """执行完整的签到流程。"""
        self._authenticate()
        characters = self._get_binding_list()

        if not characters:
            logger.warning("未找到绑定的角色（支持：明日方舟、终末地）")
            return

        logger.info("找到 {} 个角色，开始签到", len(characters))
        for character in characters:
            app_code = character.get("_appCode", "arknights")
            if app_code == "endfield":
                self._sign_endfield(character)
            else:
                self._sign_arknights(character)

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
