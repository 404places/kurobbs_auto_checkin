import os
import sys
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from loguru import logger

# -------------------------
# 基础配置与工具函数
# -------------------------

def get_session():
    """
    获取配置了重试机制的 requests Session
    """
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        max_retries=3,
        pool_connections=10,
        pool_maxsize=10
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

http = get_session()

# -------------------------
# 推送渠道实现
# -------------------------

def telegram(title: str, content: str):
    """
    Telegram 推送
    环境变量:
        TELEGRAM_BOT_TOKEN: 机器人的 Token
        TELEGRAM_CHAT_ID: 接收消息的 Chat ID
        TELEGRAM_API_URL: (可选) 反代地址，默认为 api.telegram.org
        TELEGRAM_HTTP_PROXY: (可选) 代理地址
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        return

    api_url = os.getenv("TELEGRAM_API_URL", "api.telegram.org")
    proxy = os.getenv("TELEGRAM_HTTP_PROXY")
    
    proxies = None
    if proxy:
        proxies = {'http': proxy, 'https': proxy}
        
    url = f"https://{api_url}/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": f"{title}\n{content}"
    }
    
    try:
        resp = http.post(url, json=data, proxies=proxies, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("ok"):
            logger.info("Telegram 推送成功")
        else:
            logger.error(f"Telegram 推送失败: {result.get('description')}")
    except Exception as e:
        logger.error(f"Telegram 推送异常: {e}")

def wecom_app(title: str, content: str):
    """
    企业微信应用消息推送
    环境变量:
        WECOM_CORPID: 企业ID
        WECOM_SECRET: 应用 Secret
        WECOM_AGENTID: 应用 AgentID
        WECOM_TOUSER: (可选) 接收用户，默认 @all
    """
    corpid = os.getenv("WECOM_CORPID")
    secret = os.getenv("WECOM_SECRET")
    agentid = os.getenv("WECOM_AGENTID")
    
    if not corpid or not secret or not agentid:
        return

    touser = os.getenv("WECOM_TOUSER", "@all")

    try:
        # 获取 Access Token
        token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corpid}&corpsecret={secret}"
        token_resp = http.get(token_url, timeout=10).json()
        access_token = token_resp.get("access_token")
        
        if not access_token:
            logger.error(f"企业微信获取 Token 失败: {token_resp}")
            return

        # 发送消息
        send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
        data = {
            "touser": touser,
            "msgtype": "text",
            "agentid": agentid,
            "text": {
                "content": f"{title}\n{content}"
            },
            "safe": 0
        }
        
        resp = http.post(send_url, json=data, timeout=10)
        result = resp.json()
        
        if result.get("errcode") == 0:
            logger.info("企业微信应用推送成功")
        else:
            logger.error(f"企业微信应用推送失败: {result.get('errmsg')}")

    except Exception as e:
        logger.error(f"企业微信应用推送异常: {e}")

def wecom_robot(title: str, content: str):
    """
    企业微信群机器人推送
    环境变量:
        WECOM_ROBOT_KEY: 机器人的 key
    """
    key = os.getenv("WECOM_ROBOT_KEY")
    if not key:
        return

    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    data = {
        "msgtype": "text",
        "text": {
            "content": f"{title}\n{content}"
        }
    }

    try:
        resp = http.post(url, json=data, timeout=10)
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info("企业微信机器人推送成功")
        else:
            logger.error(f"企业微信机器人推送失败: {result}")
    except Exception as e:
        logger.error(f"企业微信机器人推送异常: {e}")

def dingtalk_robot(title: str, content: str):
    """
    钉钉群机器人推送
    环境变量:
        DINGTALK_ACCESS_TOKEN: 机器人的 access_token
        DINGTALK_SECRET: (可选) 加签密钥
    """
    token = os.getenv("DINGTALK_ACCESS_TOKEN")
    if not token:
        return

    secret = os.getenv("DINGTALK_SECRET")
    url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"

    if secret:
        timestamp = str(round(time.time() * 1000))
        secret_enc = secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        url = f"{url}&timestamp={timestamp}&sign={sign}"

    data = {
        "msgtype": "text",
        "text": {
            "content": f"{title}\n{content}"
        }
    }

    try:
        resp = http.post(url, json=data, timeout=10)
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info("钉钉机器人推送成功")
        else:
            logger.error(f"钉钉机器人推送失败: {result}")
    except Exception as e:
        logger.error(f"钉钉机器人推送异常: {e}")

def feishu_robot(title: str, content: str):
    """
    飞书机器人推送（卡片消息）
    环境变量:
        FEISHU_BOT_TOKEN: 飞书机器人的 token (或者完整的 webhook url)
    """
    token = os.getenv("FEISHU_BOT_TOKEN")
    if not token:
        return
    
    if "open.feishu.cn" in token:
        url = token
    else:
        url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{token}"

    # 根据标题判断颜色：有异常用红色，否则用绿色
    header_color = "red" if "异常" in title or "失败" in title else "green"

    # 将每行内容转为卡片元素
    content_elements = []
    for line in content.split("\n"):
        if line.strip():
            content_elements.append({
                "tag": "markdown",
                "content": line
            })

    data = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": header_color
            },
            "elements": content_elements
        }
    }
    
    try:
        resp = http.post(url, json=data, timeout=10)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info("飞书机器人推送成功")
        else:
            logger.error(f"飞书机器人推送失败: {result}")
    except Exception as e:
        logger.error(f"飞书机器人推送异常: {e}")

def gotify(title: str, content: str):
    """
    Gotify 推送
    环境变量:
        GOTIFY_URL: 服务器地址
        GOTIFY_TOKEN: 应用 Token
    """
    url = os.getenv("GOTIFY_URL")
    token = os.getenv("GOTIFY_TOKEN")
    
    if not url or not token:
        return
        
    if not url.endswith("/"):
        url += "/"
        
    push_url = f"{url}message?token={token}"
    data = {
        "title": title,
        "message": content,
        "priority": 5
    }
    
    try:
        resp = http.post(push_url, json=data, timeout=10)
        resp.raise_for_status()
        logger.info("Gotify 推送成功")
    except Exception as e:
        logger.error(f"Gotify 推送异常: {e}")

# -------------------------
# 主入口
# -------------------------

def push(title: str, content: str):
    """
    执行所有配置了环境变量的推送渠道
    """
    logger.info("开始执行消息推送...")
    
    # 依次尝试各个推送渠道
    # 如果对应的环境变量未设置，函数内部会直接返回，不会报错
    
    telegram(title, content)
    wecom_app(title, content)
    wecom_robot(title, content)
    dingtalk_robot(title, content)
    feishu_robot(title, content)
    gotify(title, content)
    
    # 这里可以继续添加其他推送方式的调用
    
    logger.info("消息推送流程结束")

if __name__ == "__main__":
    # 测试代码
    push("测试标题", "这是一条测试消息\n包含换行")
