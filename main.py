import os
import json
import time
import re
import asyncio
from datetime import datetime
from typing import Optional, Dict, List
from threading import Lock

from astrbot import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api.message_components import Plain, Json
from astrbot.api import AstrBotConfig

try:
    from NeteaseCloudMusic import NeteaseCloudMusicApi
except ImportError:
    NeteaseCloudMusicApi = None

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

SONG_ID_PATTERN = r"(?:song\?id=|song\.163\.com/song/|/song/)(\d+)"

TRACK_COLLECTION_DIR = "track_collection"
LOG_FILE = "playlist_ops.log"


@register(
    "astrbot_plugin_netease_listentogether",
    "astrbot",
    "网易云音乐群内严选歌单插件 —— 自动收集群内分享的曲目，管理网易云音乐歌单。",
    "2.0.0",
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

        self.target_playlist_id = ""
        self.auto_collect = False
        self.api_cookie = ""
        self.admin_user_ids = []
        self.log_operations = True

        self._lock = Lock()
        self._api_client = None

        self._load_config()

        self._data_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "stored_data.json"
        )
        self._collection_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            TRACK_COLLECTION_DIR
        )
        self._log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            LOG_FILE
        )

        os.makedirs(self._collection_path, exist_ok=True)

        self._stored_data: Dict[str, dict] = self._load_stored_data()
        self._collected_tracks: Dict[str, list] = self._load_collected_tracks()

        logger.info(
            f"[netease_listentogether] 插件已初始化，"
            f"监听群: {self.monitored_groups}, "
            f"目标歌单ID: {self.target_playlist_id}, "
            f"自动收集: {self.auto_collect}"
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

        self.target_playlist_id = str(self.plugin_config.get("target_playlist_id", "")).strip()
        self.auto_collect = self.plugin_config.get("auto_collect", False)
        self.api_cookie = str(self.plugin_config.get("api_cookie", "")).strip()
        self.log_operations = self.plugin_config.get("log_operations", True)

        admin_ids_raw = self.plugin_config.get("admin_user_ids", "")
        if isinstance(admin_ids_raw, str):
            self.admin_user_ids = [
                uid.strip()
                for uid in admin_ids_raw.replace(",", " ").split()
                if uid.strip()
            ]
        elif isinstance(admin_ids_raw, list):
            self.admin_user_ids = [str(u).strip() for u in admin_ids_raw if str(u).strip()]

    def _save_config(self):
        try:
            groups_str = ",".join(self.monitored_groups)
            keywords_str = ",".join(self.trigger_keywords)
            admin_ids_str = ",".join(self.admin_user_ids)
            if hasattr(self.plugin_config, "__setitem__"):
                self.plugin_config["monitored_groups"] = groups_str
                self.plugin_config["trigger_keywords"] = keywords_str
                self.plugin_config["link_pattern"] = self.link_pattern
                self.plugin_config["reply_template"] = self.reply_template
                self.plugin_config["enable_monitoring"] = self.enable_monitoring
                self.plugin_config["send_format"] = self.send_format
                self.plugin_config["prefix_text"] = self.prefix_text
                self.plugin_config["suffix_text"] = self.suffix_text
                self.plugin_config["target_playlist_id"] = self.target_playlist_id
                self.plugin_config["auto_collect"] = self.auto_collect
                self.plugin_config["api_cookie"] = self.api_cookie
                self.plugin_config["log_operations"] = self.log_operations
                self.plugin_config["admin_user_ids"] = admin_ids_str
        except Exception as e:
            logger.warning(f"[netease_listentogether] 同步配置失败: {e}")

    def _get_api_client(self):
        if NeteaseCloudMusicApi is None:
            logger.error("[netease_listentogether] NeteaseCloudMusic 库未安装")
            return None

        if self._api_client is None:
            self._api_client = NeteaseCloudMusicApi()

        if self.api_cookie:
            self._api_client.cookie = self.api_cookie

        return self._api_client

    def _log_operation(self, operation: str, details: str):
        if not self.log_operations:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {operation}: {details}"

        logger.info(f"[netease_listentogether] {log_entry}")

        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            logger.warning(f"[netease_listentogether] 写入日志文件失败: {e}")

    def _matches_trigger(self, text: str) -> bool:
        if not self.trigger_keywords:
            return True
        text_lower = text.lower()
        for keyword in self.trigger_keywords:
            if keyword.lower() in text_lower:
                return True
        return False

    def _contains_listentogether_card(self, text: str) -> bool:
        indicators = [
            "listen-together",
            "st.music.163.com",
        ]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in indicators)

    def _contains_song_share(self, text: str) -> bool:
        indicators = [
            "分享歌曲",
            "分享单曲",
            "y.music.163.com",
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

    def _extract_song_ids(self, text: str) -> list:
        try:
            pattern = re.compile(SONG_ID_PATTERN)
            matches = pattern.findall(text)
            seen = set()
            unique_ids = []
            for song_id in matches:
                if song_id and song_id not in seen:
                    seen.add(song_id)
                    unique_ids.append(song_id)
            return unique_ids
        except re.error as e:
            logger.error(f"[netease_listentogether] 歌曲ID正则表达式解析错误: {e}")
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
        try:
            with open(self._data_path, "w", encoding="utf-8") as f:
                json.dump(self._stored_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[netease_listentogether] 保存本地存储数据失败: {e}")

    def _load_collected_tracks(self) -> Dict[str, list]:
        result = {}
        try:
            if os.path.exists(self._collection_path):
                for filename in os.listdir(self._collection_path):
                    if filename.endswith(".json"):
                        group_id = filename[:-5]
                        filepath = os.path.join(self._collection_path, filename)
                        with open(filepath, "r", encoding="utf-8") as f:
                            result[group_id] = json.load(f)
            logger.info(f"[netease_listentogether] 已加载 {len(result)} 个群的曲目收集数据")
        except Exception as e:
            logger.warning(f"[netease_listentogether] 加载曲目收集数据失败: {e}")
        return result

    def _save_collected_tracks(self, group_id: str):
        try:
            filepath = os.path.join(self._collection_path, f"{group_id}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._collected_tracks.get(group_id, []), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[netease_listentogether] 保存曲目收集数据失败: {e}")

    def _store_data(self, group_id: str, link: str, json_data, sender_name: str):
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
        return self._stored_data.get(group_id)

    def _add_track_to_collection(self, group_id: str, song_id: str, song_name: str, sender_name: str):
        with self._lock:
            if group_id not in self._collected_tracks:
                self._collected_tracks[group_id] = []

            for track in self._collected_tracks[group_id]:
                if track.get("song_id") == song_id:
                    return False

            self._collected_tracks[group_id].append({
                "song_id": song_id,
                "song_name": song_name,
                "sender_name": sender_name,
                "shared_time": time.time(),
                "added_to_playlist": False,
            })
            self._save_collected_tracks(group_id)
            return True

    def _format_time_diff(self, timestamp: float) -> str:
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

    def _check_admin(self, event: AstrMessageEvent) -> bool:
        if not self.admin_user_ids:
            return True

        sender_id = str(event.get_sender_id())
        return sender_id in self.admin_user_ids

    async def _api_request(self, api_name: str, params: dict = None) -> dict:
        client = self._get_api_client()
        if client is None:
            return {"code": -1, "message": "NeteaseCloudMusic API 客户端不可用，请安装依赖库"}

        try:
            result = client.request(api_name, params)
            return result
        except Exception as e:
            logger.error(f"[netease_listentogether] API 调用失败 [{api_name}]: {e}")
            return {"code": -1, "message": f"API 调用失败: {str(e)}"}

    async def _add_songs_to_playlist(self, song_ids: list) -> tuple[bool, str]:
        if not self.target_playlist_id:
            return False, "未配置目标歌单ID，请先通过 /一起听 set_playlist 设置"

        ids_str = ",".join(song_ids)
        result = await self._api_request("playlist_tracks", {
            "op": "add",
            "pid": self.target_playlist_id,
            "tracks": ids_str,
        })

        if result.get("code") == 200:
            self._log_operation("添加歌曲到歌单", f"歌单 {self.target_playlist_id}, 歌曲IDs: {ids_str}")
            return True, f"成功添加 {len(song_ids)} 首歌曲到歌单"
        else:
            error_msg = result.get("message", "未知错误")
            self._log_operation("添加歌曲失败", f"歌单 {self.target_playlist_id}, 错误: {error_msg}")
            return False, f"添加失败: {error_msg}"

    async def _remove_songs_from_playlist(self, song_ids: list) -> tuple[bool, str]:
        if not self.target_playlist_id:
            return False, "未配置目标歌单ID，请先通过 /一起听 set_playlist 设置"

        ids_str = ",".join(song_ids)
        result = await self._api_request("playlist_tracks", {
            "op": "del",
            "pid": self.target_playlist_id,
            "tracks": ids_str,
        })

        if result.get("code") == 200:
            self._log_operation("从歌单移除歌曲", f"歌单 {self.target_playlist_id}, 歌曲IDs: {ids_str}")
            return True, f"成功移除 {len(song_ids)} 首歌曲"
        else:
            error_msg = result.get("message", "未知错误")
            self._log_operation("移除歌曲失败", f"歌单 {self.target_playlist_id}, 错误: {error_msg}")
            return False, f"移除失败: {error_msg}"

    async def _clear_playlist(self) -> tuple[bool, str]:
        if not self.target_playlist_id:
            return False, "未配置目标歌单ID，请先通过 /一起听 set_playlist 设置"

        result = await self._api_request("playlist_detail", {"id": self.target_playlist_id})

        if result.get("code") != 200:
            return False, f"获取歌单详情失败: {result.get('message', '未知错误')}"

        playlist = result.get("playlist", {})
        track_ids = [str(t.get("id")) for t in playlist.get("trackIds", [])]

        if not track_ids:
            return True, "歌单已经是空的"

        all_removed = True
        for i in range(0, len(track_ids), 500):
            batch = track_ids[i:i+500]
            success, msg = await self._remove_songs_from_playlist(batch)
            if not success:
                all_removed = False
                break

        if all_removed:
            self._log_operation("清空歌单", f"歌单 {self.target_playlist_id}")
            return True, f"成功清空歌单，共移除 {len(track_ids)} 首歌曲"
        else:
            return False, "清空歌单时部分歌曲移除失败"

    async def _get_playlist_info(self) -> dict:
        if not self.target_playlist_id:
            return {"error": "未配置目标歌单ID"}

        result = await self._api_request("playlist_detail", {"id": self.target_playlist_id})

        if result.get("code") != 200:
            return {"error": f"获取歌单详情失败: {result.get('message', '未知错误')}"}

        playlist = result.get("playlist", {})
        return {
            "name": playlist.get("name", "未知歌单"),
            "creator": playlist.get("creator", {}).get("nickname", "未知"),
            "track_count": playlist.get("trackCount", 0),
            "play_count": playlist.get("playCount", 0),
            "subscribed_count": playlist.get("subscribedCount", 0),
            "description": playlist.get("description", ""),
        }

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
        has_song_share = False
        extracted_links = []
        stored_json_data = None
        collected_song_ids = []

        for msg in messages:
            if isinstance(msg, Plain):
                text = msg.text or ""

                if self._matches_trigger(text):
                    has_trigger = True

                links = self._extract_netease_links(text)
                extracted_links.extend(links)

                if self.auto_collect and self.target_playlist_id:
                    song_ids = self._extract_song_ids(text)
                    collected_song_ids.extend(song_ids)

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

                if self._contains_song_share(json_str) or self._contains_song_share(extracted_text):
                    has_song_share = True

                    if self.auto_collect and self.target_playlist_id:
                        song_ids = self._extract_song_ids(json_str)
                        collected_song_ids.extend(song_ids)
                        song_ids = self._extract_song_ids(extracted_text)
                        collected_song_ids.extend(song_ids)

                    links = self._extract_netease_links(json_str)
                    for link in links:
                        if link not in extracted_links:
                            extracted_links.append(link)

                    links = self._extract_netease_links(extracted_text)
                    for link in links:
                        if link not in extracted_links:
                            extracted_links.append(link)

        if collected_song_ids:
            for song_id in collected_song_ids:
                song_info = await self._api_request("song_detail", {"ids": song_id})
                song_name = "未知歌曲"
                if song_info.get("code") == 200 and song_info.get("songs"):
                    song_name = song_info["songs"][0].get("name", "未知歌曲")

                added = self._add_track_to_collection(str(group_id_str), song_id, song_name, sender_name)
                if added:
                    self._log_operation("收集曲目", f"群 {group_id_str}, 歌曲 {song_name}(ID: {song_id}), 分享者: {sender_name}")
                    logger.info(f"[netease_listentogether] 群 {group_id_str} 收集曲目: {song_name} (ID: {song_id})")

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
            f"目标歌单ID：{self.target_playlist_id or '未设置'}\n"
            f"自动收集：{'已启用' if self.auto_collect else '已停用'}\n"
            f"API Cookie：{'已配置' if self.api_cookie else '未配置'}\n"
            f"管理员：{', '.join(self.admin_user_ids) if self.admin_user_ids else '所有人'}\n"
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

    @yiqiting.command("set_playlist")
    async def set_playlist(self, event: AstrMessageEvent, playlist_id: str):
        if not playlist_id:
            yield event.plain_result("请提供歌单ID，例如：/一起听 set_playlist 123456789")
            return

        self.target_playlist_id = playlist_id.strip()
        self._save_config()
        self._log_operation("设置目标歌单", f"歌单ID: {self.target_playlist_id}")
        yield event.plain_result(f"已设置目标歌单ID为 {self.target_playlist_id}")

    @yiqiting.command("set_cookie")
    async def set_cookie(self, event: AstrMessageEvent, cookie: str):
        if not cookie:
            yield event.plain_result("请提供 API Cookie，例如：/一起听 set_cookie your_cookie_here")
            return

        self.api_cookie = cookie.strip()
        self._save_config()
        self._api_client = None
        self._log_operation("设置 API Cookie", "Cookie 已更新")
        yield event.plain_result("已设置 API Cookie")

    @yiqiting.command("set_admin")
    async def set_admin(self, event: AstrMessageEvent, user_ids_str: str):
        if not user_ids_str:
            yield event.plain_result("请提供管理员用户ID，例如：/一起听 set_admin 123,456")
            return

        self.admin_user_ids = [uid.strip() for uid in user_ids_str.replace(",", " ").split() if uid.strip()]
        self._save_config()
        self._log_operation("设置管理员", f"管理员IDs: {', '.join(self.admin_user_ids)}")
        yield event.plain_result(f"已设置管理员用户ID: {', '.join(self.admin_user_ids)}")

    @yiqiting.command("toggle_collect")
    async def toggle_collect(self, event: AstrMessageEvent):
        self.auto_collect = not self.auto_collect
        self._save_config()
        self._log_operation("切换自动收集", f"状态: {'启用' if self.auto_collect else '停用'}")
        yield event.plain_result(f"已{'启用' if self.auto_collect else '停用'}自动收集群内曲目")

    @yiqiting.command("add_song")
    async def add_song(self, event: AstrMessageEvent, song_ids_str: str):
        if not self._check_admin(event):
            yield event.plain_result("权限不足，仅管理员可执行此操作。")
            return

        if not song_ids_str:
            yield event.plain_result("请提供歌曲ID，例如：/一起听 add_song 12345678")
            return

        song_ids = [sid.strip() for sid in song_ids_str.replace(",", " ").split() if sid.strip()]
        if not song_ids:
            yield event.plain_result("未提供有效的歌曲ID")
            return

        yield event.plain_result(f"正在添加 {len(song_ids)} 首歌曲到歌单...")
        success, msg = await self._add_songs_to_playlist(song_ids)

        if success:
            for sid in song_ids:
                self._log_operation("手动添加歌曲", f"歌曲ID: {sid}")
        yield event.plain_result(msg)

    @yiqiting.command("remove_song")
    async def remove_song(self, event: AstrMessageEvent, song_ids_str: str):
        if not self._check_admin(event):
            yield event.plain_result("权限不足，仅管理员可执行此操作。")
            return

        if not song_ids_str:
            yield event.plain_result("请提供歌曲ID，例如：/一起听 remove_song 12345678")
            return

        song_ids = [sid.strip() for sid in song_ids_str.replace(",", " ").split() if sid.strip()]
        if not song_ids:
            yield event.plain_result("未提供有效的歌曲ID")
            return

        yield event.plain_result(f"正在从歌单移除 {len(song_ids)} 首歌曲...")
        success, msg = await self._remove_songs_from_playlist(song_ids)
        yield event.plain_result(msg)

    @yiqiting.command("clear_playlist")
    async def clear_playlist(self, event: AstrMessageEvent):
        if not self._check_admin(event):
            yield event.plain_result("权限不足，仅管理员可执行此操作。")
            return

        yield event.plain_result("正在清空歌单，请稍候...")
        success, msg = await self._clear_playlist()
        yield event.plain_result(msg)

    @yiqiting.command("playlist_info")
    async def playlist_info(self, event: AstrMessageEvent):
        yield event.plain_result("正在获取歌单信息，请稍候...")
        info = await self._get_playlist_info()

        if "error" in info:
            yield event.plain_result(info["error"])
            return

        desc = info.get("description", "")
        if len(desc) > 200:
            desc = desc[:200] + "..."

        yield event.plain_result(
            f"歌单名称：{info['name']}\n"
            f"创建者：{info['creator']}\n"
            f"曲目数量：{info['track_count']}\n"
            f"播放次数：{info['play_count']}\n"
            f"收藏人数：{info['subscribed_count']}\n"
            f"歌单描述：{desc}"
        )

    @yiqiting.command("collected")
    async def show_collected(self, event: AstrMessageEvent):
        group_id_str = event.get_group_id()
        if not group_id_str:
            yield event.plain_result("此命令仅在群聊中使用。")
            return

        tracks = self._collected_tracks.get(str(group_id_str), [])
        if not tracks:
            yield event.plain_result("当前群没有收集的曲目。")
            return

        limit = 20
        tracks_shown = tracks[-limit:]
        text = f"当前群收集的曲目（最近 {len(tracks_shown)} 首）：\n\n"
        for i, track in enumerate(tracks_shown, 1):
            status = "✓" if track.get("added_to_playlist") else "○"
            time_diff = self._format_time_diff(track.get("shared_time", time.time()))
            text += f"{i}. {status} {track['song_name']} (ID: {track['song_id']})\n   分享者: {track['sender_name']} | {time_diff}\n"

        if len(tracks) > limit:
            text += f"\n... 还有 {len(tracks) - limit} 首曲目未显示"

        yield event.plain_result(text)

    @yiqiting.command("add_collected")
    async def add_collected_to_playlist(self, event: AstrMessageEvent):
        if not self._check_admin(event):
            yield event.plain_result("权限不足，仅管理员可执行此操作。")
            return

        group_id_str = event.get_group_id()
        if not group_id_str:
            yield event.plain_result("此命令仅在群聊中使用。")
            return

        tracks = self._collected_tracks.get(str(group_id_str), [])
        unadded_tracks = [t for t in tracks if not t.get("added_to_playlist")]

        if not unadded_tracks:
            yield event.plain_result("没有待添加的曲目，所有曲目已添加到歌单。")
            return

        song_ids = [str(t["song_id"]) for t in unadded_tracks]
        yield event.plain_result(f"正在将 {len(song_ids)} 首收集的曲目添加到歌单...")

        success, msg = await self._add_songs_to_playlist(song_ids)

        if success:
            with self._lock:
                for track in self._collected_tracks.get(str(group_id_str), []):
                    track["added_to_playlist"] = True
            self._save_collected_tracks(str(group_id_str))
            self._log_operation("批量添加收集曲目", f"群 {group_id_str}, 数量: {len(song_ids)}")

        yield event.plain_result(msg)

    @yiqiting.command("clear_collected")
    async def clear_collected(self, event: AstrMessageEvent):
        if not self._check_admin(event):
            yield event.plain_result("权限不足，仅管理员可执行此操作。")
            return

        group_id_str = event.get_group_id()
        if not group_id_str:
            yield event.plain_result("此命令仅在群聊中使用。")
            return

        count = len(self._collected_tracks.get(str(group_id_str), []))
        if count == 0:
            yield event.plain_result("当前群没有收集的曲目。")
            return

        with self._lock:
            self._collected_tracks[str(group_id_str)] = []
        self._save_collected_tracks(str(group_id_str))
        self._log_operation("清空收集曲目", f"群 {group_id_str}, 数量: {count}")
        yield event.plain_result(f"已清空当前群收集的 {count} 首曲目记录。")

    @yiqiting.command("search")
    async def search_song(self, event: AstrMessageEvent, keyword: str):
        if not keyword:
            yield event.plain_result("请提供搜索关键词，例如：/一起听 search 林俊杰")
            return

        yield event.plain_result(f"正在搜索「{keyword}」，请稍候...")
        result = await self._api_request("search", {"keywords": keyword, "type": "1", "limit": "10"})

        if result.get("code") != 200:
            yield event.plain_result(f"搜索失败: {result.get('message', '未知错误')}")
            return

        songs = result.get("result", {}).get("songs", [])
        if not songs:
            yield event.plain_result(f"未找到与「{keyword}」相关的歌曲。")
            return

        text = f"搜索结果（前 {len(songs)} 首）：\n\n"
        for i, song in enumerate(songs, 1):
            name = song.get("name", "未知")
            artists = ", ".join(a.get("name", "未知") for a in song.get("artists", []))
            album = song.get("album", {}).get("name", "未知")
            song_id = song.get("id", "")
            text += f"{i}. {name}\n   歌手: {artists}\n   专辑: {album}\n   ID: {song_id}\n\n"

        yield event.plain_result(text)

    @yiqiting.command("help")
    async def show_help(self, event: AstrMessageEvent):
        help_text = (
            "网易云音乐群内严选歌单插件\n"
            "\n"
            "功能介绍：\n"
            "1. 自动收集群内分享的网易云音乐曲目\n"
            "2. 管理网易云音乐目标歌单\n"
            "3. 搜索歌曲并添加到歌单\n"
            "\n"
            "基础指令：\n"
            "• /一起听 config - 查看当前配置\n"
            "• /一起听 status - 查看当前群存储的链接\n"
            "• /一起听 clear - 清除当前群存储的链接和卡片\n"
            "• /一起听 keywords - 查看当前触发关键词\n"
            "• /一起听 add_keyword <关键词> - 添加触发关键词\n"
            "• /一起听 remove_keyword <关键词> - 删除触发关键词\n"
            "• /一起听 help - 显示帮助信息\n"
            "\n"
            "歌单管理指令（需要管理员权限）：\n"
            "• /一起听 set_playlist <歌单ID> - 设置目标歌单ID\n"
            "• /一起听 set_cookie <Cookie> - 设置网易云 API Cookie\n"
            "• /一起听 set_admin <用户ID列表> - 设置管理员用户ID\n"
            "• /一起听 toggle_collect - 切换自动收集群内曲目\n"
            "• /一起听 add_song <歌曲ID列表> - 手动添加歌曲到歌单\n"
            "• /一起听 remove_song <歌曲ID列表> - 从歌单移除歌曲\n"
            "• /一起听 clear_playlist - 清空目标歌单\n"
            "• /一起听 playlist_info - 查看目标歌单信息\n"
            "• /一起听 collected - 查看当前群收集的曲目\n"
            "• /一起听 add_collected - 将收集的曲目添加到歌单\n"
            "• /一起听 clear_collected - 清空当前群收集曲目\n"
            "• /一起听 search <关键词> - 搜索歌曲\n"
            "\n"
            "配置说明：\n"
            "1. 通过 WebUI 或 /一起听 set_cookie 配置网易云 API Cookie\n"
            "2. 通过 /一起听 set_playlist 设置目标歌单ID\n"
            "3. 通过 /一起听 set_admin 设置管理员权限\n"
            "4. 通过 /一起听 toggle_collect 启用/停用自动收集\n"
            "\n"
            "依赖库：NeteaseCloudMusic\n"
            "文档：https://docs.neteasecloudmusicapi.binaryify.com/#/"
        )
        yield event.plain_result(help_text)
