import os
import json
import time
import re
from datetime import datetime
from typing import Optional, Dict

from astrbot import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api.message_components import Plain, Json
from astrbot.api import AstrBotConfig

DEFAULT_TRIGGER_KEYWORDS = ["一起听", "一起来听", "listen together", "一起聽"]
DEFAULT_MONITORED_GROUPS = []
DEFAULT_LINK_PATTERN = (
    r"https?://"
    r"(?:st\.music\.163\.com|music\.163\.com|163cn\.tv|y\.music\.163\.com)"
    r"[^\s>)\]}\"\'`]*"
)
DEFAULT_REPLY_TEMPLATE = (
    "网易云音乐「一起听」邀请链接：\n"
    "{links}\n"
    "—— 来自 {sender_name} 的分享"
)
DEFAULT_SEND_FORMAT = "link"
DEFAULT_PREFIX_TEXT = ""
DEFAULT_SUFFIX_TEXT = ""


@register(
    "astrbot_plugin_netease_listentogether",
    "astrbot",
    "网易云音乐「一起听」链接提取插件 —— 监控群聊消息，自动存储一起听链接和卡片，通过触发词发送。",
    "1.0.0",
)
class Main(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.plugin_config = config if config else {}
        self.monitored_groups = DEFAULT_MONITORED_GROUPS
        self.trigger_keywords = DEFAULT_TRIGGER_KEYWORDS
        self.link_pattern = DEFAULT_LINK_PATTERN
        self.reply_template = DEFAULT_REPLY_TEMPLATE
        self.enable_monitoring = True
        self.send_format = DEFAULT_SEND_FORMAT
        self.prefix_text = DEFAULT_PREFIX_TEXT
        self.suffix_text = DEFAULT_SUFFIX_TEXT

        self._load_config()

        self._data_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "stored_data.json"
        )
        self._stored_data: Dict[str, dict] = self._load_stored_data()

        logger.info(
            f"[netease_listentogether] 插件已初始化，"
            f"监听群: {self.monitored_groups}, "
            f"触发词: {self.trigger_keywords}, "
            f"发送格式: {self.send_format}"
        )

    def _load_config(self):
        monitored_groups_raw = self.plugin_config.get("monitored_groups", "")
        if isinstance(monitored_groups_raw, str):
            self.monitored_groups = [
                gid.strip()
                for gid in monitored_groups_raw.replace(",", " ").split()
                if gid.strip()
            ]
        elif isinstance(monitored_groups_raw, list):
            self.monitored_groups = [str(g).strip() for g in monitored_groups_raw if str(g).strip()]

        trigger_keywords_raw = self.plugin_config.get("trigger_keywords", "")
        if isinstance(trigger_keywords_raw, str) and trigger_keywords_raw.strip():
            self.trigger_keywords = [
                kw.strip()
                for kw in trigger_keywords_raw.split(",")
                if kw.strip()
            ]
        elif isinstance(trigger_keywords_raw, list):
            self.trigger_keywords = [str(k).strip() for k in trigger_keywords_raw if str(k).strip()]

        link_pattern_raw = self.plugin_config.get("link_pattern", "")
        if link_pattern_raw and str(link_pattern_raw).strip():
            self.link_pattern = str(link_pattern_raw).strip()

        reply_template_raw = self.plugin_config.get("reply_template", "")
        if reply_template_raw and str(reply_template_raw).strip():
            self.reply_template = str(reply_template_raw)

        enable_raw = self.plugin_config.get("enable_monitoring", True)
        self.enable_monitoring = enable_raw

        send_format_raw = self.plugin_config.get("send_format", DEFAULT_SEND_FORMAT)
        if send_format_raw in ("link", "card", "both"):
            self.send_format = send_format_raw

        prefix_raw = self.plugin_config.get("prefix_text", DEFAULT_PREFIX_TEXT)
        self.prefix_text = str(prefix_raw) if prefix_raw else DEFAULT_PREFIX_TEXT

        suffix_raw = self.plugin_config.get("suffix_text", DEFAULT_SUFFIX_TEXT)
        self.suffix_text = str(suffix_raw) if suffix_raw else DEFAULT_SUFFIX_TEXT

    def _save_config(self):
        try:
            groups_str = ",".join(self.monitored_groups)
            keywords_str = ",".join(self.trigger_keywords)
            if hasattr(self.plugin_config, "__setitem__"):
                self.plugin_config["monitored_groups"] = groups_str
                self.plugin_config["trigger_keywords"] = keywords_str
                self.plugin_config["link_pattern"] = self.link_pattern
                self.plugin_config["reply_template"] = self.reply_template
                self.plugin_config["enable_monitoring"] = self.enable_monitoring
                self.plugin_config["send_format"] = self.send_format
                self.plugin_config["prefix_text"] = self.prefix_text
                self.plugin_config["suffix_text"] = self.suffix_text
        except Exception as e:
            logger.warning(f"[netease_listentogether] 同步配置失败: {e}")

    def _matches_trigger(self, text: str) -> bool:
        if not self.trigger_keywords:
            return True
        text_lower = text.lower()
        for keyword in self.trigger_keywords:
            if keyword.lower() in text_lower:
                return True
        return False

    def _contains_listentogether_card(self, text: str) -> bool:
        """检查文本是否包含一起听卡片的特征"""
        indicators = [
            "listen-together",
            "st.music.163.com",
        ]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in indicators)

    def _extract_netease_links(self, text: str) -> list:
        try:
            compiled_pattern = re.compile(self.link_pattern, re.IGNORECASE)
            matches = compiled_pattern.findall(text)
            seen = set()
            unique_links = []
            for link in matches:
                clean_link = link.strip()
                clean_link = clean_link.strip('`').strip("'").strip('"').strip('<').strip('>').strip('(').strip(')').strip('{').strip('}').strip('[').strip(']').strip()
                if clean_link and clean_link not in seen:
                    seen.add(clean_link)
                    unique_links.append(clean_link)
            return unique_links
        except re.error as e:
            logger.error(f"[netease_listentogether] 链接正则表达式解析错误: {e}")
            return []

    def _extract_json_content(self, json_data) -> str:
        try:
            data = json.loads(json_data) if isinstance(json_data, str) else json_data
        except (json.JSONDecodeError, TypeError):
            return ""

        texts = []

        def collect_strings(obj):
            if isinstance(obj, str):
                texts.append(obj)
            elif isinstance(obj, dict):
                for v in obj.values():
                    collect_strings(v)
            elif isinstance(obj, list):
                for item in obj:
                    collect_strings(item)

        collect_strings(data)
        return " ".join(texts)

    def _load_stored_data(self) -> Dict[str, dict]:
        """从本地文件加载存储的数据"""
        try:
            if os.path.exists(self._data_path):
                with open(self._data_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"[netease_listentogether] 已从本地文件加载 {len(data)} 条存储数据")
                return data
        except Exception as e:
            logger.warning(f"[netease_listentogether] 加载本地存储数据失败: {e}")
        return {}

    def _save_stored_data(self):
        """将存储的数据保存到本地文件"""
        try:
            with open(self._data_path, "w", encoding="utf-8") as f:
                json.dump(self._stored_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[netease_listentogether] 保存本地存储数据失败: {e}")

    def _store_data(self, group_id: str, link: str, json_data, sender_name: str):
        """存储链接和 JSON 卡片数据到本地文件"""
        self._stored_data[group_id] = {
            "link": link,
            "json_data": json_data,
            "sender_name": sender_name,
            "timestamp": time.time(),
        }
        self._save_stored_data()
        logger.info(
            f"[netease_listentogether] 群 {group_id} 存储链接: {link}"
        )

    def _get_stored_data(self, group_id: str) -> Optional[dict]:
        """获取存储的数据"""
        return self._stored_data.get(group_id)

    def _format_time_diff(self, timestamp: float) -> str:
        """计算并格式化时间差"""
        now = time.time()
        diff = now - timestamp
        if diff < 60:
            return f"{int(diff)}秒前"
        elif diff < 3600:
            return f"{int(diff // 60)}分钟前"
        elif diff < 86400:
            return f"{int(diff // 3600)}小时前"
        elif diff < 2592000:
            return f"{int(diff // 86400)}天前"
        elif diff < 31536000:
            return f"{int(diff // 2592000)}个月前"
        else:
            return f"{int(diff // 31536000)}年前"

    def _build_reply(self, link: str, sender_name: str, timestamp: Optional[float] = None) -> str:
        time_str = ""
        time_diff = ""
        if timestamp is not None:
            dt = datetime.fromtimestamp(timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            time_diff = self._format_time_diff(timestamp)
        
        parts = []
        
        if self.prefix_text:
            parts.append(self.prefix_text.format(time=time_str, time_diff=time_diff))
        
        reply_content = self.reply_template.format(
            links=link,
            sender_name=sender_name or "未知用户",
            time=time_str,
            time_diff=time_diff,
        )
        parts.append(reply_content)
        
        if self.suffix_text:
            parts.append(self.suffix_text.format(time=time_str, time_diff=time_diff))
        
        return "\n".join(parts)

    async def _send_json_card(self, event, json_data):
        """发送 JSON 卡片消息"""
        try:
            json_str = json_data if isinstance(json_data, str) else json.dumps(json_data)

            if hasattr(event, 'bot') and hasattr(event.bot, 'api') and hasattr(event.bot.api, 'call_action'):
                group_id = event.get_group_id()
                if group_id:
                    payloads = {
                        "group_id": int(group_id),
                        "message": [{"type": "json", "data": {"data": json_str}}]
                    }
                    await event.bot.api.call_action("send_group_msg", **payloads)
                    logger.info(f"[netease_listentogether] 已发送 JSON 卡片到群 {group_id}")
                else:
                    sender_id = event.get_sender_id()
                    payloads = {
                        "user_id": int(sender_id),
                        "message": [{"type": "json", "data": {"data": json_str}}]
                    }
                    await event.bot.api.call_action("send_private_msg", **payloads)
                    logger.info(f"[netease_listentogether] 已发送 JSON 卡片到用户 {sender_id}")
        except Exception as e:
            logger.error(f"[netease_listentogether] 发送 JSON 卡片失败: {e}")

    @event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.enable_monitoring:
            return

        group_id_str = event.get_group_id()
        if not group_id_str:
            return

        if self.monitored_groups and str(group_id_str) not in self.monitored_groups:
            return

        messages = event.get_messages()
        if not messages:
            return

        msg_str = event.get_message_str().strip()
        if msg_str.startswith("/"):
            return

        sender_name = event.get_sender_name() or "未知用户"
        has_trigger = False
        has_json_card = False
        extracted_links = []
        stored_json_data = None

        for msg in messages:
            if isinstance(msg, Plain):
                text = msg.text or ""

                if self._matches_trigger(text):
                    has_trigger = True

                links = self._extract_netease_links(text)
                extracted_links.extend(links)

            elif isinstance(msg, Json):
                json_content = msg.data
                extracted_text = self._extract_json_content(json_content)

                json_str = json_content if isinstance(json_content, str) else json.dumps(json_content)

                if self._contains_listentogether_card(json_str) or self._contains_listentogether_card(extracted_text):
                    has_json_card = True

                    links = self._extract_netease_links(extracted_text)
                    if links:
                        extracted_links.extend(links)

                    json_links = self._extract_netease_links(json_str)
                    for jl in json_links:
                        if jl not in extracted_links:
                            extracted_links.append(jl)

                    if json_content:
                        stored_json_data = json_content

        if has_json_card and extracted_links:
            main_link = extracted_links[0]
            self._store_data(str(group_id_str), main_link, stored_json_data, sender_name)
            return

        if has_trigger:
            stored = self._get_stored_data(str(group_id_str))
            if stored:
                timestamp = stored.get("timestamp")
                if self.send_format == "link" or self.send_format == "both":
                    reply = self._build_reply(stored["link"], stored["sender_name"], timestamp)
                    yield event.plain_result(reply)
                    logger.info(f"[netease_listentogether] 群 {group_id_str} 发送链接")

                if self.send_format == "card":
                    if stored.get("json_data"):
                        time_str = ""
                        time_diff = ""
                        if timestamp is not None:
                            dt = datetime.fromtimestamp(timestamp)
                            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                            time_diff = self._format_time_diff(timestamp)
                        if self.prefix_text:
                            yield event.plain_result(self.prefix_text.format(time=time_str, time_diff=time_diff))
                        await self._send_json_card(event, stored["json_data"])
                        if self.suffix_text:
                            yield event.plain_result(self.suffix_text.format(time=time_str, time_diff=time_diff))
                        logger.info(f"[netease_listentogether] 群 {group_id_str} 发送卡片")
                    else:
                        logger.warning(f"[netease_listentogether] 群 {group_id_str} 没有存储的卡片数据")
            else:
                logger.info(
                    f"[netease_listentogether] 群 {group_id_str} 触发词匹配，但没有存储的链接"
                )

    @filter.command_group("一起听")
    def yiqiting(self):
        pass

    @yiqiting.command("status")
    async def show_status(self, event: AstrMessageEvent):
        group_id_str = event.get_group_id()
        stored = self._get_stored_data(str(group_id_str)) if group_id_str else None
        if stored:
            age = time.time() - stored["timestamp"]
            if age < 60:
                time_str = f"{int(age)}秒前"
            elif age < 3600:
                time_str = f"{int(age // 60)}分钟前"
            else:
                time_str = f"{int(age // 3600)}小时前"
            yield event.plain_result(
                f"当前群存储的链接：\n"
                f"链接：{stored['link']}\n"
                f"分享者：{stored['sender_name']}\n"
                f"存储时间：{time_str}\n"
                f"卡片数据：{'已存储' if stored.get('json_data') else '未存储'}"
            )
        else:
            yield event.plain_result("当前群没有存储的一起听链接。")

    @yiqiting.command("config")
    async def show_config(self, event: AstrMessageEvent):
        status = "已启用" if self.enable_monitoring else "已停用"
        format_map = {"link": "纯文本链接", "card": "原始卡片", "both": "链接+卡片"}
        format_text = format_map.get(self.send_format, self.send_format)
        groups_text = "\n".join(f"• {g}" for g in self.monitored_groups) if self.monitored_groups else "• （监听所有群聊）"
        keywords_text = "\n".join(f"• {kw}" for kw in self.trigger_keywords) if self.trigger_keywords else "• （不限制关键词）"
        config_text = (
            f"插件状态：{status}\n"
            f"发送格式：{format_text}\n"
            f"监听群聊：\n{groups_text}\n"
            f"触发关键词：\n{keywords_text}\n"
            f"链接正则：{self.link_pattern[:80]}{'...' if len(self.link_pattern) > 80 else ''}\n"
            f"回复模板：{self.reply_template[:100]}{'...' if len(self.reply_template) > 100 else ''}"
        )
        yield event.plain_result(config_text)

    @yiqiting.command("clear")
    async def clear_stored(self, event: AstrMessageEvent):
        group_id_str = event.get_group_id()
        if not group_id_str:
            yield event.plain_result("此命令仅在群聊中使用。")
            return
        stored = self._get_stored_data(str(group_id_str))
        if stored:
            del self._stored_data[str(group_id_str)]
            self._save_stored_data()
            yield event.plain_result("已清除当前群存储的链接和卡片数据。")
            logger.info(f"[netease_listentogether] 群 {group_id_str} 已清除存储数据")
        else:
            yield event.plain_result("当前群没有存储的链接和卡片数据。")

    @yiqiting.command("keywords")
    async def show_keywords(self, event: AstrMessageEvent):
        keywords_text = "\n".join(f"• {kw}" for kw in self.trigger_keywords) if self.trigger_keywords else "• （无关键词，对所有消息进行链接检测）"
        yield event.plain_result(f"当前触发关键词：\n{keywords_text}")

    @yiqiting.command("add_keyword")
    async def add_keyword(self, event: AstrMessageEvent, keyword: str):
        if not keyword:
            yield event.plain_result("请提供要添加的关键词，例如：/一起听 add_keyword 新关键词")
            return
        
        if keyword in self.trigger_keywords:
            yield event.plain_result(f"关键词「{keyword}」已存在。")
            return
        
        self.trigger_keywords.append(keyword)
        self._save_config()
        yield event.plain_result(f"已添加关键词「{keyword}」。")
        logger.info(f"[netease_listentogether] 已添加关键词: {keyword}")

    @yiqiting.command("remove_keyword")
    async def remove_keyword(self, event: AstrMessageEvent, keyword: str):
        if not keyword:
            yield event.plain_result("请提供要删除的关键词，例如：/一起听 remove_keyword 旧关键词")
            return
        
        if keyword not in self.trigger_keywords:
            yield event.plain_result(f"关键词「{keyword}」不存在。")
            return
        
        self.trigger_keywords.remove(keyword)
        self._save_config()
        yield event.plain_result(f"已删除关键词「{keyword}」。")
        logger.info(f"[netease_listentogether] 已删除关键词: {keyword}")

    @yiqiting.command("help")
    async def show_help(self, event: AstrMessageEvent):
        help_text = (
            "网易云音乐「一起听」链接提取插件\n"
            "\n"
            "工作流程：\n"
            "1. 当群内发送「一起听」JSON卡片时，自动存储链接和卡片数据\n"
            "2. 当群内发送触发词时，根据配置的发送格式发送存储的内容\n"
            "\n"
            "发送格式（在 WebUI 配置中设置）：\n"
            "• link - 仅发送文本链接\n"
            "• card - 仅发送原始 JSON 卡片\n"
            "• both - 同时发送链接和卡片\n"
            "\n"
            "指令列表：\n"
            "• /一起听 config - 查看当前配置\n"
            "• /一起听 status - 查看当前群存储的链接\n"
            "• /一起听 clear - 清除当前群存储的链接和卡片\n"
            "• /一起听 keywords - 查看当前触发关键词\n"
            "• /一起听 add_keyword <关键词> - 添加触发关键词\n"
            "• /一起听 remove_keyword <关键词> - 删除触发关键词\n"
            "• /一起听 help - 显示帮助信息\n"
            "\n"
            "支持纯文本链接和 QQ 音乐分享卡片（JSON 格式）。"
        )
        yield event.plain_result(help_text)