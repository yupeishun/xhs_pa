#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书评论采集器 v2.3  实时写入版 + AI情绪分析 + 楼中楼支持
"""
import asyncio
import json
import random
from tkinter import ttk, scrolledtext, messagebox, filedialog, PhotoImage
from pathlib import Path
import re
import getpass
import uuid
import sys
import os
import time
from pathlib import Path
import threading
import logging
from datetime import datetime
from PIL import Image, ImageTk

# -------------------- 情绪分析工具函数 --------------------
import pandas as pd
import jieba
import requests

# 默认的API配置 - 适配智谱AI
DEFAULT_API_CONFIG = {
    "api_key": "",
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "model": "glm-4.5-flash",
    "prompt": "请分析以下小红书评论的情感倾向，每条评论用斜杠/分隔。请为每条评论标注情感标签：正向、负向或中性。请严格按照这个格式回复：标签1/标签2/标签3...（不要有其他内容）"
}

POS = {
    "好看": 2, "精致": 2, "美": 2, "仙气": 2, "出片": 2,
    "惊艳": 3, "高级": 2, "质感": 2, "细腻": 2, "梦幻": 2,
    "粉嫩": 1, "马卡龙": 1, "奶油": 1, "莫兰迪": 1, "氛围": 1,
    "治愈": 2, "少女心": 2, "ins风": 2, "韩系": 1, "日系": 1,
    "复古": 1, "百搭": 1, "高颜值": 2, "神仙": 3, "绝美": 3,
    "丝滑": 2, "紧实": 2, "牢固": 2, "顺滑": 2, "咔哒": 2,
    "手感": 2, "解压": 2, "爽": 2, "带感": 2, "Q弹": 1,
    "圆润": 1, "无割手": 2, "棱角处理": 2, "公差小": 2,
    "喜欢": 2, "爱": 2, "值": 2, "划算": 2, "真香": 3,
    "送礼": 1, "仪式感": 2, "走心": 2, "心意": 1,
    "成就感": 2, "上头": 2, "入坑": 2, "种草": 2,
    "回购": 2, "必入": 3, "闭眼入": 3, "冲": 2,
    "官方": 1, "正品": 1, "包邮": 1, "顺丰": 1,
    "客服秒回": 2, "补件快": 3, "秒发": 1
}

NEG = {
    "丑": 2, "土": 2, "塑料": 2, "地摊": 2, "廉价": 2,
    "难看": 2, "辣眼": 3, "翻车": 2, "幻灭": 2,
    "色差": 2, "显脏": 2, "发黄": 2, "发黑": 2,
    "掉色": 3, "褪色": 3, "染色": 2,
    "易散": 3, "松": 2, "掉件": 3, "缺件": 3,
    "难拼": 2, "手疼": 2, "割手": 3, "锋利": 3,
    "咬合差": 2, "缝隙大": 2, "歪": 2, "斜": 2,
    "鼓包": 2, "起翘": 2, "白痕": 2, "断裂": 3,
    "脆": 2, "一掰就断": 3, "卡不紧": 2, "咔咔响": 2,
    "贵": 1, "不值": 2, "血亏": 3, "被割": 3,
    "失望": 2, "踩雷": 3, "拔草": 2, "劝退": 2,
    "鸡肋": 2, "占灰": 2, "积灰": 2, "吃灰": 2,
    "重复": 1, "无聊": 1, "幼稚": 1,
    "假货": 3, "盗版": 3, "二手": 2, "盒损": 1,
    "少件": 3, "漏发": 3, "补件慢": 2, "客服已读不回": 2,
    "邮费贵": 1, "到付": 2, "七天无理由拒": 2
}

NEU = {"还行", "一般", "凑合", "过得去", "中规中矩", "正常", "普通",
       "不好不坏", "就那样", "没啥感觉", "无功无过", "凑合用", "能看"}


def clean(txt: str) -> str:
    txt = re.sub(r"[\U00010000-\U0010ffff]", "", str(txt))
    txt = re.sub(r"[～~！!？?。，；;：:\s]+", " ", txt)
    return txt.strip()


def score_sent(txt: str) -> int:
    txt = txt.lower()
    s = 0
    for w, v in POS.items():
        if w in txt: s += v
    for w, v in NEG.items():
        if w in txt: s -= v
    if any(w in txt for w in NEU): s = 0
    return s


def label_sent(sc: int) -> str:
    return "正向" if sc > 0 else ("负向" if sc < 0 else "中性")


# -------------------- AI情绪分析类 --------------------
class AIEmotionAnalyzer:
    def __init__(self, api_config=None):
        # 使用硬编码的默认配置，避免打包时配置丢失
        self.api_config = {
            "api_key": "",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4.5-flash",
            "prompt": "请分析以下小红书评论的情感倾向，每条评论用斜杠/分隔。请为每条评论标注情感标签：正向、负向或中性。请严格按照这个格式回复：标签1/标签2/标签3...（不要有其他内容）"
        }
        if api_config:
            self.api_config.update(api_config)
        self.session = requests.Session()

    def update_api_config(self, new_config):
        """更新API配置"""
        self.api_config.update(new_config)

    def analyze_comments_batch(self, comments):
        """批量分析评论情绪（10-20条一批）"""
        if not self.api_config.get("api_key"):
            raise ValueError("API密钥未配置，请先在设置中配置API密钥")

        # 批量处理：10-20条评论为一批
        batch_size = min(20, max(10, len(comments) // 5 + 1))
        batches = [comments[i:i + batch_size] for i in range(0, len(comments), batch_size)]

        all_results = []

        for batch_idx, batch in enumerate(batches):
            try:
                # 更清晰的评论编号
                numbered_comments = [f"{i + 1}. {comment}" for i, comment in enumerate(batch)]
                comments_text = "\n".join(numbered_comments)

                # 构建请求 - 适配智谱AI
                headers = {
                    "Authorization": f"Bearer {self.api_config['api_key']}",
                    "Content-Type": "application/json"
                }

                # 更明确的prompt，要求逐条分析
                prompt_content = f"""请分析以下{len(batch)}条小红书评论的情感倾向。

    评论列表：
    {comments_text}

    要求：
    1. 为每条评论单独分析情感
    2. 只使用以下三种标签：正向、负向、中性
    3. 按照评论顺序，用中文顿号「、」分隔输出标签
    4. 不要添加任何解释文字，只输出标签

    请输出：标签1、标签2、标签3...（共{len(batch)}个标签）"""

                data = {
                    "model": self.api_config.get("model", "glm-4.5-flash"),
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt_content
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 800,  # 增加token限制
                    "top_p": 0.7
                }

                # 发送请求到智谱AI，增加超时时间
                base_url = self.api_config.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
                response = self.session.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=60  # 增加到60秒
                )

                if response.status_code == 200:
                    result = response.json()
                    # 智谱AI的返回格式
                    labels_text = result["choices"][0]["message"]["content"].strip()

                    # 记录原始返回以便调试
                    self._log(f"批次{batch_idx + 1} AI原始返回: {labels_text}")

                    # 解析标签
                    labels = self._parse_ai_response(labels_text, len(batch))

                    # 确保标签数量与评论数量一致
                    if len(labels) == len(batch):
                        all_results.extend(labels)
                        self._log(f"✅ 批次{batch_idx + 1} AI分析成功: {len(labels)}个标签")
                    else:
                        # 如果不一致，使用规则匹配作为后备
                        self._log(
                            f"❌ 批次{batch_idx + 1} AI返回标签数量不匹配 (AI: {len(labels)}, 实际: {len(batch)})，使用规则匹配")
                        fallback_results = [self._fallback_analyze(comment) for comment in batch]
                        all_results.extend(fallback_results)

                else:
                    self._log(f"❌ 批次{batch_idx + 1} API请求失败: {response.status_code}")
                    # 使用规则匹配作为后备
                    fallback_results = [self._fallback_analyze(comment) for comment in batch]
                    all_results.extend(fallback_results)

            except requests.exceptions.Timeout:
                self._log(f"❌ 批次{batch_idx + 1} 请求超时，使用规则匹配")
                # 超时时使用规则匹配
                fallback_results = [self._fallback_analyze(comment) for comment in batch]
                all_results.extend(fallback_results)

            except Exception as e:
                self._log(f"❌ 批次{batch_idx + 1} 分析出错: {str(e)}，使用规则匹配")
                # 使用规则匹配作为后备
                fallback_results = [self._fallback_analyze(comment) for comment in batch]
                all_results.extend(fallback_results)

        return all_results

    def _parse_ai_response(self, response_text, expected_count):
        """解析AI返回的文本，提取情感标签"""
        # 清理响应文本
        response_text = response_text.strip()

        # 首先尝试提取用中文顿号分隔的标签
        if "、" in response_text:
            labels = [label.strip() for label in response_text.split("、")]
            labels = [label for label in labels if label and len(label) <= 4]  # 过滤空标签和过长的文本
        else:
            # 尝试其他分隔符
            separators = ['/', '，', ',', ' ', '|', '\n']
            labels = []
            for sep in separators:
                if sep in response_text:
                    temp_labels = [label.strip() for label in response_text.split(sep)]
                    temp_labels = [label for label in temp_labels if label and len(label) <= 4]
                    if len(temp_labels) >= expected_count:
                        labels = temp_labels
                        break

            # 如果没有找到合适的分隔符，尝试正则匹配
            if not labels:
                import re
                # 匹配中文情感词
                pattern = r'[正负中][向性]|积极|消极'
                matches = re.findall(pattern, response_text)
                if matches:
                    labels = matches

        # 标准化标签
        standardized_labels = []
        for label in labels:
            label_lower = label.lower()
            if any(word in label_lower for word in ["正向", "积极", "正面", "好评", "好", "不错", "喜欢"]):
                standardized_labels.append("正向")
            elif any(word in label_lower for word in ["负向", "消极", "负面", "差评", "差", "不好", "讨厌"]):
                standardized_labels.append("负向")
            elif any(word in label_lower for word in ["中性", "中立", "一般", "普通", "还行"]):
                standardized_labels.append("中性")
            else:
                # 无法识别的标签，使用中性作为默认
                standardized_labels.append("中性")

        # 如果标签数量不够，用中性填充
        while len(standardized_labels) < expected_count:
            standardized_labels.append("中性")

        # 如果标签数量过多，截取前expected_count个
        if len(standardized_labels) > expected_count:
            standardized_labels = standardized_labels[:expected_count]

        return standardized_labels

    def _fallback_analyze(self, comment):
        """后备方案：使用规则匹配分析情绪"""
        score = score_sent(comment)
        return label_sent(score)

    def _log(self, message):
        """记录日志"""
        logging.info(f"AI分析器: {message}")


# -------------------- GUI 部分 --------------------
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog


def setup_playwright_path():
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
        browser_path = os.path.join(base_path, 'ms-playwright')
        if os.path.exists(browser_path):
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = browser_path
    else:
        browser_path = os.path.join(os.path.dirname(__file__), 'ms-playwright')
        if os.path.exists(browser_path):
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = browser_path


setup_playwright_path()

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class XHSScraperGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("小红书评论采集器 v2.3")
        self.root.geometry("1100x850")
        self.root.configure(bg='#f5f5f7')

        # 设置样式
        self.setup_styles()

        self.is_running = False
        self.current_task = None
        self.scraper_instance = None
        self.ai_analyzer = AIEmotionAnalyzer()
        self.setup_ui()

    def setup_styles(self):
        """设置现代化样式"""
        style = ttk.Style()
        style.theme_use('clam')

        # 配置深灰色主题颜色
        self.primary_color = '#e0e0e0'
        self.secondary_color = '#3498db'
        self.accent_color = '#e74c3c'
        self.success_color = '#2ecc71'
        self.bg_color = '#2c2c2c'  # 深灰色背景
        self.card_bg = '#3a3a3a'  # 深灰色卡片背景

        # 配置样式
        style.configure('TFrame', background=self.bg_color)
        style.configure('TLabel', background=self.bg_color, font=('Segoe UI', 10), foreground='#e0e0e0')
        style.configure('Title.TLabel', background=self.bg_color, font=('Segoe UI', 16, 'bold'),
                        foreground='#ffffff')
        style.configure('Card.TFrame', background=self.card_bg, relief='solid', borderwidth=1)
        style.configure('Card.TLabelframe', background=self.card_bg, relief='solid', borderwidth=1)
        style.configure('Card.TLabelframe.Label', background=self.card_bg, font=('Segoe UI', 11, 'bold'),
                        foreground='#ffffff')

        # 按钮样式
        style.configure('Primary.TButton', font=('Segoe UI', 10, 'bold'),
                        background=self.secondary_color, foreground='white')
        style.map('Primary.TButton',
                  background=[('active', self.primary_color), ('pressed', self.primary_color)])

        style.configure('Secondary.TButton', font=('Segoe UI', 9),
                        background='#4a4a4a', foreground=self.primary_color)
        style.map('Secondary.TButton',
                  background=[('active', '#5a5a5a'), ('pressed', '#5a5a5a')])

        style.configure('Accent.TButton', font=('Segoe UI', 9, 'bold'),
                        background=self.accent_color, foreground='white')
        style.map('Accent.TButton',
                  background=[('active', '#c0392b'), ('pressed', '#c0392b')])

        # 进度条样式
        style.configure('Custom.Horizontal.TProgressbar',
                        background=self.success_color,
                        troughcolor='#ecf0f1',
                        bordercolor='#bdc3c7',
                        lightcolor=self.success_color,
                        darkcolor=self.success_color)

    def setup_ui(self):
        # 主容器
        main_container = ttk.Frame(self.root, padding="20")
        main_container.pack(fill=tk.BOTH, expand=True)

        # 标题区域
        title_frame = ttk.Frame(main_container)
        title_frame.pack(fill=tk.X, pady=(0, 20))

        ttk.Label(title_frame, text="小红书评论采集器", style='Title.TLabel').pack(side=tk.LEFT)

        version_label = ttk.Label(title_frame, text="v2.3", foreground='#b0b0b0', font=('Segoe UI', 10))
        version_label.pack(side=tk.RIGHT)

        # 创建选项卡
        notebook = ttk.Notebook(main_container)

        # 在选项卡右侧添加大图
        try:
            # 加载图片
            icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
            if os.path.exists(icon_path):
                # 打开图片并调整大小到200x200
                image = Image.open(icon_path)
                image = image.resize((200, 200), Image.Resampling.LANCZOS)  # 增大图片尺寸
                self.icon_image = ImageTk.PhotoImage(image)

                # 创建图片展示区域
                image_frame = ttk.Frame(main_container, style='Card.TFrame')
                image_frame.pack(fill=tk.X, pady=10, padx=20)

                # 添加图片标签
                icon_label = ttk.Label(image_frame, image=self.icon_image, background=self.card_bg)
                icon_label.pack(expand=True, padx=20, pady=20)
        except Exception as e:
            print(f"无法加载图片: {e}")
        notebook.pack(fill=tk.BOTH, expand=True)

        # 采集配置选项卡
        self.setup_collection_tab(notebook)

        # AI配置选项卡
        self.setup_ai_tab(notebook)

        # 日志选项卡
        self.setup_log_tab(notebook)

        # 状态栏
        self.setup_status_bar(main_container)

        self.setup_log_redirection()
        self.collected_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.api_key_visible = False

    def setup_collection_tab(self, notebook):
        """设置采集配置选项卡"""
        collection_frame = ttk.Frame(notebook, padding=15)
        notebook.add(collection_frame, text="采集配置")

        # 创建左右布局的主框架
        main_layout = ttk.Frame(collection_frame)
        main_layout.pack(fill=tk.BOTH, expand=True)

        # 左侧工具按钮区域
        tools_sidebar = ttk.LabelFrame(main_layout, text="数据分析工具", padding=15, style='Card.TLabelframe', width=200)
        tools_sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 15))
        tools_sidebar.pack_propagate(False)  # 防止框架收缩

        # 垂直排列的工具按钮
        ttk.Button(tools_sidebar, text="🤖 AI情绪分析", command=self.generate_ai_csv,
                   style='Secondary.TButton', width=15).pack(fill=tk.X, pady=5)

        ttk.Button(tools_sidebar, text="📊 规则情绪分析", command=self.generate_rule_csv,
                   style='Secondary.TButton', width=15).pack(fill=tk.X, pady=5)

        ttk.Button(tools_sidebar, text="🐛 调试数据", command=self.debug_data_integrity,
                   style='Secondary.TButton', width=15).pack(fill=tk.X, pady=5)

        ttk.Button(tools_sidebar, text="❓ 使用说明", command=self.show_help,
                   style='Secondary.TButton', width=15).pack(fill=tk.X, pady=5)

        # 右侧配置和进度区域
        config_area = ttk.Frame(main_layout)
        config_area.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 配置卡片
        config_card = ttk.LabelFrame(config_area, text="基本设置", padding=15, style='Card.TLabelframe')
        config_card.pack(fill=tk.X, pady=(0, 15))

        # 关键词和数量
        input_frame = ttk.Frame(config_card)
        input_frame.pack(fill=tk.X, pady=5)

        ttk.Label(input_frame, text="搜索关键词:", font=('Segoe UI', 10)).grid(row=0, column=0, sticky=tk.W,
                                                                               padx=(0, 10))
        self.keyword_var = tk.StringVar(value="积木花")
        keyword_entry = ttk.Entry(input_frame, textvariable=self.keyword_var, width=25, font=('Segoe UI', 10))
        keyword_entry.grid(row=0, column=1, padx=(0, 30))

        ttk.Label(input_frame, text="最大采集数:", font=('Segoe UI', 10)).grid(row=0, column=2, sticky=tk.W,
                                                                               padx=(0, 10))
        self.max_cards_var = tk.StringVar(value="30")
        max_entry = ttk.Entry(input_frame, textvariable=self.max_cards_var, width=10, font=('Segoe UI', 10))
        max_entry.grid(row=0, column=3)

        # 保存路径
        path_frame = ttk.Frame(config_card)
        path_frame.pack(fill=tk.X, pady=10)

        ttk.Label(path_frame, text="保存路径:", font=('Segoe UI', 10)).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.save_path_var = tk.StringVar(value=str(Path.home() / "Desktop" / "小红书采集数据"))
        self.save_path_entry = ttk.Entry(path_frame, textvariable=self.save_path_var, width=60, font=('Segoe UI', 10))
        self.save_path_entry.grid(row=0, column=1, padx=(0, 10))
        ttk.Button(path_frame, text="浏览", command=self.browse_save_path, style='Secondary.TButton').grid(row=0,
                                                                                                           column=2)

        # 控制按钮区域
        control_frame = ttk.Frame(config_area)
        control_frame.pack(fill=tk.X, pady=(0, 15))

        self.start_button = ttk.Button(control_frame, text="🚀 开始采集", command=self.start_scraping,
                                       style='Primary.TButton', width=15)
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_button = ttk.Button(control_frame, text="⏹️ 停止采集", command=self.stop_scraping,
                                      state=tk.DISABLED, style='Accent.TButton', width=15)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(control_frame, text="📁 打开文件夹", command=self.open_save_folder,
                   style='Secondary.TButton', width=15).pack(side=tk.LEFT, padx=(0, 10))

        # 进度区域
        progress_card = ttk.LabelFrame(config_area, text="采集进度", padding=15, style='Card.TLabelframe')
        progress_card.pack(fill=tk.X, pady=(0, 15))

        self.progress_var = tk.StringVar(value="准备就绪，请输入关键词并点击开始采集")
        progress_label = ttk.Label(progress_card, textvariable=self.progress_var, font=('Segoe UI', 10))
        progress_label.pack(anchor=tk.W, pady=(0, 10))

        self.progress_bar = ttk.Progressbar(progress_card, style='Custom.Horizontal.TProgressbar')
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))

        self.stats_var = tk.StringVar(value="已采集: 0 | 成功: 0 | 失败: 0")
        stats_label = ttk.Label(progress_card, textvariable=self.stats_var, font=('Segoe UI', 10))
        stats_label.pack(anchor=tk.W)

    def setup_ai_tab(self, notebook):
        """设置AI配置选项卡"""
        ai_frame = ttk.Frame(notebook, padding=15)
        notebook.add(ai_frame, text="AI配置")

        # API配置卡片
        api_card = ttk.LabelFrame(ai_frame, text="GLM-4.5-flash API配置", padding=15, style='Card.TLabelframe')
        api_card.pack(fill=tk.X, pady=(0, 15))

        # API密钥
        key_frame = ttk.Frame(api_card)
        key_frame.pack(fill=tk.X, pady=10)

        ttk.Label(key_frame, text="API密钥:", font=('Segoe UI', 10)).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.api_key_var = tk.StringVar(value="")
        api_key_entry = ttk.Entry(key_frame, textvariable=self.api_key_var, width=60,
                                  font=('Segoe UI', 10), show="*")
        api_key_entry.grid(row=0, column=1, padx=(0, 10))
        ttk.Button(key_frame, text="显示/隐藏", command=self.toggle_api_key_visibility,
                   style='Secondary.TButton', width=10).grid(row=0, column=2)

        # API地址和模型
        api_config_frame = ttk.Frame(api_card)
        api_config_frame.pack(fill=tk.X, pady=10)

        ttk.Label(api_config_frame, text="API地址:", font=('Segoe UI', 10)).grid(row=0, column=0, sticky=tk.W,
                                                                                 padx=(0, 10))
        self.api_url_var = tk.StringVar(value="https://open.bigmodel.cn/api/paas/v4")
        api_url_entry = ttk.Entry(api_config_frame, textvariable=self.api_url_var, width=40, font=('Segoe UI', 10))
        api_url_entry.grid(row=0, column=1, padx=(0, 30))

        ttk.Label(api_config_frame, text="模型:", font=('Segoe UI', 10)).grid(row=0, column=2, sticky=tk.W,
                                                                              padx=(0, 10))
        self.api_model_var = tk.StringVar(value="glm-4.5-flash")
        model_entry = ttk.Entry(api_config_frame, textvariable=self.api_model_var, width=20, font=('Segoe UI', 10))
        model_entry.grid(row=0, column=3, padx=(0, 10))

        # 测试连接按钮
        test_frame = ttk.Frame(api_card)
        test_frame.pack(fill=tk.X, pady=10)

        ttk.Button(test_frame, text="测试连接", command=self.test_api_connection,
                   style='Primary.TButton', width=12).pack(side=tk.LEFT)

        # 使用说明
        help_card = ttk.LabelFrame(ai_frame, text="使用说明", padding=15, style='Card.TLabelframe')
        help_card.pack(fill=tk.X)

        help_text = """1. 获取API密钥：访问智谱AI开放平台 (https://open.bigmodel.cn/) 注册并获取API密钥
2. 配置API信息：将获取的API密钥填入上方输入框
3. 测试连接：点击"测试连接"按钮验证配置是否正确
4. 开始分析：在"采集配置"选项卡中使用AI情绪分析功能

注意：使用AI情绪分析功能需要有效的API密钥和网络连接"""

        help_label = ttk.Label(help_card, text=help_text, font=('Segoe UI', 10),
                               background=self.card_bg, justify=tk.LEFT)
        help_label.pack(anchor=tk.W)

    def setup_log_tab(self, notebook):
        """设置日志选项卡"""
        log_frame = ttk.Frame(notebook, padding=15)
        notebook.add(log_frame, text="运行日志")

        # 日志区域
        log_card = ttk.LabelFrame(log_frame, text="实时日志", padding=10, style='Card.TLabelframe')
        log_card.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_card, height=25, font=("Consolas", 9),
                                                  wrap=tk.WORD, bg='#f8f9fa', fg='#2c3e50')
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def setup_status_bar(self, parent):
        """设置状态栏"""
        status_frame = ttk.Frame(parent, relief='solid', borderwidth=1)
        status_frame.pack(fill=tk.X, pady=(10, 0))

        self.status_var = tk.StringVar(value="✅ 就绪")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, font=('Segoe UI', 9),
                                 foreground='#7f8c8d')
        status_label.pack(side=tk.LEFT, padx=5, pady=2)

        # 添加版本信息
        version_info = ttk.Label(status_frame, text="小红书评论采集器 v2.3 © 2023",
                                 font=('Segoe UI', 9), foreground='#7f8c8d')
        version_info.pack(side=tk.RIGHT, padx=5, pady=2)

    # ---------------- 日志重定向 ----------------
    def setup_log_redirection(self):
        class TextHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget

            def emit(self, record):
                msg = self.format(record)
                self.widget.after(0, lambda: (self.widget.insert(tk.END, msg + '\n'),
                                              self.widget.see(tk.END),
                                              self.widget.update_idletasks()))

        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        for h in logger.handlers[:]: logger.removeHandler(h)
        logger.addHandler(TextHandler(self.log_text))

    # ---------------- API相关功能 ----------------
    def toggle_api_key_visibility(self):
        """切换API密钥显示/隐藏"""
        self.api_key_visible = not self.api_key_visible
        if self.api_key_visible:
            messagebox.showinfo("API密钥", f"当前API密钥: {self.api_key_var.get()}")
        else:
            pass

    def test_api_connection(self):
        """测试API连接"""
        api_config = {
            "api_key": self.api_key_var.get(),
            "base_url": self.api_url_var.get(),
            "model": self.api_model_var.get()
        }

        if not api_config["api_key"]:
            messagebox.showerror("错误", "请输入API密钥")
            return

        try:
            # 创建新的分析器实例进行测试
            analyzer = AIEmotionAnalyzer(api_config)

            # 测试评论
            test_comments = [
                "这个产品质量很好，很喜欢",
                "质量太差了，很失望",
                "一般般，没什么特别的感觉",
                "超级好用，强烈推荐",
                "完全不值这个价格"
            ]

            self.log("开始API连接测试...")
            results = analyzer.analyze_comments_batch(test_comments)

            if results and len(results) == len(test_comments):
                # 显示详细结果
                result_text = "API连接测试成功！\n\n测试结果：\n"
                for i, (comment, label) in enumerate(zip(test_comments, results)):
                    result_text += f"{i + 1}. {comment}\n    → {label}\n"

                messagebox.showinfo("测试成功", result_text)
                self.log("✅ API连接测试成功")
                # 测试成功后更新主分析器配置
                self.update_ai_analyzer_config()
            else:
                messagebox.showwarning("测试警告",
                                       f"API连接成功但返回结果异常\n"
                                       f"期望: {len(test_comments)}个结果\n"
                                       f"实际: {len(results) if results else 0}个结果")

        except Exception as e:
            messagebox.showerror("测试失败", f"API连接测试失败: {str(e)}")
            self.log(f"❌ API连接测试失败: {str(e)}")

    def update_ai_analyzer_config(self):
        """更新AI分析器配置"""
        new_config = {
            "api_key": self.api_key_var.get(),
            "base_url": self.api_url_var.get(),
            "model": self.api_model_var.get()
        }
        self.ai_analyzer.update_api_config(new_config)
        self.log("✅ AI分析器配置已更新")

    # ---------------- 按钮功能 ----------------
    def browse_save_path(self):
        folder = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if folder: self.save_path_var.set(folder)

    def open_save_folder(self):
        save_path = Path(self.save_path_var.get())
        try:
            if save_path.exists():
                os.startfile(save_path)
            else:
                messagebox.showinfo("提示", "文件夹不存在，请先开始采集创建文件夹")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件夹: {e}")

    def show_help(self):
        messagebox.showinfo("使用说明",
                            "1. 输入关键词、数量、保存路径\n"
                            "2. 配置AI情绪分析API（支持GLM-4.5-flash）\n"
                            "3. 点击'测试连接'验证配置\n"
                            "4. 点击'开始采集'\n"
                            "5. 每次都需扫码登录，后续自动复用 cookie\n"
                            "6. 采集完成可点击AI或规则情绪分析\n\n"
                            "GLM-4.5-flash配置：\n"
                            "- API地址: https://open.bigmodel.cn/api/paas/v4\n"
                            "- 模型: glm-4.5-flash\n"
                            "- API密钥: 从智谱AI平台获取API密钥\n\n"
                            "有啥问题联系开发者,微信ID小帮手"
                            "图标是可以换的")

    def log(self, msg, level=logging.INFO):
        logging.log(level, msg)

    def update_progress(self, msg):
        self.progress_var.set(msg)
        self.root.update_idletasks()

    def update_stats(self):
        self.stats_var.set(f"已采集: {self.collected_count} | 成功: {self.success_count} | 失败: {self.failed_count}")
        if self.max_cards_var.get().isdigit() and int(self.max_cards_var.get()) > 0:
            self.progress_bar['value'] = (self.collected_count / int(self.max_cards_var.get())) * 100

    # ---------------- 数据调试功能 ----------------
    def debug_data_integrity(self):
        """调试数据完整性 - 找出丢失的评论"""
        folder = Path(self.save_path_var.get())
        json_files = list(folder.glob("*_comments_*.json"))

        if not json_files:
            messagebox.showinfo("提示", "未找到JSON文件")
            return

        latest_json = max(json_files, key=lambda x: x.stat().st_mtime)

        try:
            posts = json.loads(latest_json.read_text(encoding='utf-8'))

            # 详细分析每个帖子
            result_text = f"JSON文件: {latest_json.name}\n"
            result_text += f"帖子总数: {len(posts)}\n\n"

            total_comments = 0
            all_comments_list = []

            for i, post in enumerate(posts):
                comments = post.get("评论", [])
                title = post.get("标题", "无标题")[:50]
                total_comments += len(comments)

                result_text += f"帖子{i + 1}: {title}\n"
                result_text += f"  评论数: {len(comments)}\n"
                result_text += f"  点赞数: {post.get('点赞数', 0)}\n"
                result_text += f"  收藏数: {post.get('收藏数', 0)}\n"

                # 记录前几条评论作为样本
                sample_comments = comments[:3] if len(comments) > 3 else comments
                for j, comment in enumerate(sample_comments):
                    result_text += f"    评论{j + 1}: {comment[:30]}...\n"

                result_text += "\n"

                # 收集所有评论
                all_comments_list.extend(comments)

            result_text += f"=== 统计汇总 ===\n"
            result_text += f"总评论数: {total_comments}\n"
            result_text += f"实际评论条数: {len(all_comments_list)}\n"

            # 检查是否有重复计数问题
            unique_comments = set(all_comments_list)
            result_text += f"去重后评论数: {len(unique_comments)}\n"

            if len(all_comments_list) != total_comments:
                result_text += f"⚠️ 数据不一致: 列表长度 {len(all_comments_list)} != 统计总数 {total_comments}\n"

            # 显示在日志中
            self.log("🔍 数据完整性调试报告:")
            self.log(result_text)

            messagebox.showinfo("数据调试报告", f"详细报告已输出到日志窗口\n总评论数: {total_comments}")

        except Exception as e:
            messagebox.showerror("错误", f"调试数据时出错: {e}")

    # ---------------- 情绪CSV生成 ----------------
    def generate_rule_csv(self):
        """使用规则匹配生成情绪CSV"""
        folder = Path(self.save_path_var.get())
        json_files = list(folder.glob("*_comments_*.json"))
        if not json_files:
            messagebox.showerror("错误", "未找到任何评论 JSON 文件，请先采集！")
            return
        latest_json = max(json_files, key=lambda x: x.stat().st_mtime)
        csv_file = latest_json.with_name(latest_json.stem + "_sentiment_rule.csv")

        try:
            posts = json.loads(latest_json.read_text(encoding='utf-8'))
        except Exception as e:
            messagebox.showerror("错误", f"JSON 读取失败：{e}")
            return

        records = []
        for post in posts:
            title = post.get("标题", "")
            author = post.get("作者", "")
            likes = post.get("点赞数", 0)
            collects = post.get("收藏数", 0)
            for c in post.get("评论", []):
                records.append({
                    "标题": title,
                    "作者": author,
                    "点赞数": likes,
                    "收藏数": collects,
                    "评论内容": c.strip()
                })

        df = pd.DataFrame(records)
        df["clean"] = df["评论内容"].apply(clean)
        df["score"] = df["评论内容"].apply(lambda x: sum(score_sent(s) for s in re.split(r"[。！？;；\n]+", x)))
        df["sentiment"] = df["score"].apply(label_sent)

        try:
            df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            self.log(f"✅ 规则情绪CSV已生成 → {csv_file}")
            messagebox.showinfo("完成", f"规则情绪CSV已生成！\n{csv_file}")
            os.startfile(csv_file)
        except Exception as e:
            messagebox.showerror("错误", f"CSV 写入失败：{e}")

    def generate_ai_csv(self):
        """使用AI分析生成情绪CSV - 修复版"""
        if not self.api_key_var.get():
            messagebox.showerror("错误", "请先配置API密钥以使用AI情绪分析")
            return

        folder = Path(self.save_path_var.get())
        json_files = list(folder.glob("*_comments_*.json"))
        if not json_files:
            messagebox.showerror("错误", "未找到任何评论 JSON 文件，请先采集！")
            return

        latest_json = max(json_files, key=lambda x: x.stat().st_mtime)
        csv_file = latest_json.with_name(latest_json.stem + "_sentiment_ai.csv")

        try:
            posts = json.loads(latest_json.read_text(encoding='utf-8'))
        except Exception as e:
            messagebox.showerror("错误", f"JSON 读取失败：{e}")
            return

        # 收集所有评论 - 修复：确保完整收集
        all_comments = []
        post_info = []  # 保存每条评论对应的帖子信息

        # 详细统计每个帖子的评论数
        self.log("📊 开始统计各帖子评论数量:")
        total_comments_count = 0

        for post_idx, post in enumerate(posts):
            comments = post.get("评论", [])
            title = post.get("标题", "无标题")[:30] + "..." if len(post.get("标题", "")) > 30 else post.get("标题",
                                                                                                            "无标题")

            self.log(f"  帖子{post_idx + 1}: '{title}' → {len(comments)} 条评论")
            total_comments_count += len(comments)

            # 详细记录每条评论
            for comment_idx, c in enumerate(comments):
                comment_text = c.strip()
                if comment_text:  # 只处理非空评论
                    all_comments.append(comment_text)
                    post_info.append({
                        "标题": post.get("标题", ""),
                        "作者": post.get("作者", ""),
                        "点赞数": post.get("点赞数", 0),
                        "收藏数": post.get("收藏数", 0),
                        "评论内容": comment_text,
                        "帖子索引": post_idx,
                        "评论索引": comment_idx
                    })
                else:
                    self.log(f"    ⚠️ 跳过空评论: 帖子{post_idx + 1} 第{comment_idx + 1}条")

        self.log(f"📊 数据完整性报告:")
        self.log(f"  JSON文件总评论数: {total_comments_count} 条")
        self.log(f"  非空评论数: {len(all_comments)} 条")
        self.log(f"  空评论数: {total_comments_count - len(all_comments)} 条")

        if total_comments_count != len(all_comments):
            self.log(f"  ⚠️ 警告: 有 {total_comments_count - len(all_comments)} 条空评论被跳过")

        if not all_comments:
            messagebox.showinfo("提示", "没有找到可分析的评论")
            return

        # 更新AI分析器配置
        self.update_ai_analyzer_config()

        # 显示进度对话框
        progress_window = tk.Toplevel(self.root)
        progress_window.title("AI情绪分析中")
        progress_window.geometry("500x150")
        progress_window.transient(self.root)
        progress_window.grab_set()

        ttk.Label(progress_window, text="正在使用GLM-4.5-flash分析评论情绪...", font=("Microsoft YaHei", 10)).pack(
            pady=10)
        progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(progress_window, variable=progress_var, maximum=100)
        progress_bar.pack(fill=tk.X, padx=20, pady=5)
        status_label = ttk.Label(progress_window, text=f"准备开始... 共 {len(all_comments)} 条评论")
        status_label.pack()

        # 添加详细统计标签
        stats_label = ttk.Label(progress_window, text="")
        stats_label.pack()

        # 创建停止标志
        stop_analysis = threading.Event()

        def analyze_in_thread():
            try:
                # 使用AI分析 - 修复：更稳健的分批处理
                self.log(f"开始AI情绪分析，共 {len(all_comments)} 条评论")
                sentiments = []
                processed_count = 0
                batch_size = 15  # 减小批次大小提高稳定性

                total_batches = (len(all_comments) + batch_size - 1) // batch_size

                def update_progress_ui(batch_num, processed, total_batches, total_comments):
                    progress = (processed / total_comments) * 100
                    progress_var.set(progress)
                    status_label.config(text=f"处理中: {batch_num}/{total_batches} 批次")
                    stats_label.config(text=f"已处理: {processed}/{total_comments} 条评论")
                    progress_window.update()

                # 分批处理并更新进度
                for batch_idx in range(0, len(all_comments), batch_size):
                    if stop_analysis.is_set():  # 检查是否停止
                        self.log("AI分析被用户停止")
                        break

                    batch_end = min(batch_idx + batch_size, len(all_comments))
                    batch = all_comments[batch_idx:batch_end]
                    current_batch = (batch_idx // batch_size) + 1

                    # 在UI线程中更新进度
                    self.root.after(0, lambda: update_progress_ui(
                        current_batch, processed_count, total_batches, len(all_comments)
                    ))

                    try:
                        self.log(f"分析批次 {current_batch}/{total_batches}，包含 {len(batch)} 条评论")
                        batch_results = self.ai_analyzer.analyze_comments_batch(batch)

                        # 验证返回结果数量
                        if len(batch_results) == len(batch):
                            sentiments.extend(batch_results)
                            processed_count += len(batch)
                            self.log(f"✅ 批次 {current_batch}/{total_batches} 分析完成")
                        else:
                            self.log(f"⚠️ 批次 {current_batch} 返回结果数量不匹配，使用后备方案")
                            # 使用后备方案处理这个批次
                            fallback_results = [self.ai_analyzer._fallback_analyze(comment) for comment in batch]
                            sentiments.extend(fallback_results)
                            processed_count += len(batch)

                    except Exception as e:
                        self.log(f"❌ 批次 {current_batch} 分析失败: {str(e)}，使用后备方案")
                        # 失败时使用规则匹配
                        fallback_results = [self.ai_analyzer._fallback_analyze(comment) for comment in batch]
                        sentiments.extend(fallback_results)
                        processed_count += len(batch)

                    # 短暂暂停，避免API限制
                    if current_batch % 5 == 0:
                        time.sleep(1)

                # 最终验证
                self.log(f"分析完成: 期望 {len(all_comments)} 条，实际 {len(sentiments)} 条")

                # 如果数量不匹配，使用规则匹配补充
                if len(sentiments) < len(all_comments):
                    self.log(f"⚠️ 结果数量不足，使用规则匹配补充 {len(all_comments) - len(sentiments)} 条")
                    for i in range(len(sentiments), len(all_comments)):
                        sentiments.append(self.ai_analyzer._fallback_analyze(all_comments[i]))

                # 创建结果DataFrame - 修复：确保数据完整
                result_data = []
                for i, info in enumerate(post_info):
                    if i < len(sentiments):
                        result_data.append({
                            "标题": info["标题"],
                            "作者": info["作者"],
                            "点赞数": info["点赞数"],
                            "收藏数": info["收藏数"],
                            "评论内容": info["评论内容"],
                            "clean": clean(info["评论内容"]),
                            "score": score_sent(info["评论内容"]),
                            "sentiment": sentiments[i],
                            "分析方法": "AI分析(GLMs)"
                        })
                    else:
                        # 如果超出sentiments范围，使用规则匹配
                        fallback_sentiment = self.ai_analyzer._fallback_analyze(info["评论内容"])
                        result_data.append({
                            "标题": info["标题"],
                            "作者": info["作者"],
                            "点赞数": info["点赞数"],
                            "收藏数": info["收藏数"],
                            "评论内容": info["评论内容"],
                            "clean": clean(info["评论内容"]),
                            "score": score_sent(info["评论内容"]),
                            "sentiment": fallback_sentiment,
                            "分析方法": "规则匹配(后备)"
                        })

                df = pd.DataFrame(result_data)

                # 验证最终数据完整性
                if len(df) != len(post_info):
                    self.log(f"❌ 严重错误: 最终DataFrame行数 {len(df)} 不等于原始评论数 {len(post_info)}")
                    # 尝试重新构建确保完整性
                    result_data = []
                    for i, info in enumerate(post_info):
                        sentiment = sentiments[i] if i < len(sentiments) else self.ai_analyzer._fallback_analyze(
                            info["评论内容"])
                        result_data.append({
                            "标题": info["标题"],
                            "作者": info["作者"],
                            "点赞数": info["点赞数"],
                            "收藏数": info["收藏数"],
                            "评论内容": info["评论内容"],
                            "clean": clean(info["评论内容"]),
                            "score": score_sent(info["评论内容"]),
                            "sentiment": sentiment,
                            "分析方法": "AI分析(GLMs)" if i < len(sentiments) else "规则匹配(后备)"
                        })
                    df = pd.DataFrame(result_data)

                # 保存CSV文件
                df.to_csv(csv_file, index=False, encoding='utf-8-sig')

                # 最终统计 - 修复统计逻辑
                ai_processed_count = len([s for s in sentiments if s in ["正向", "负向", "中性"]])
                fallback_count = len([d for d in result_data if d.get("分析方法") == "规则匹配(后备)"])

                progress_window.destroy()
                self.log(f"✅ AI情绪CSV已生成 → {csv_file}")
                self.log(f"📊 分析统计: 总共分析 {len(df)} 条评论")
                self.log(f"  - AI分析: {ai_processed_count} 条")
                self.log(f"  - 后备方案: {fallback_count} 条")

                self.root.after(0, lambda: messagebox.showinfo("完成",
                                                               f"AI情绪分析完成！\n"
                                                               f"成功分析 {len(df)} 条评论\n"
                                                               f"AI分析: {ai_processed_count} 条\n"
                                                               f"后备方案: {fallback_count} 条\n"
                                                               f"文件: {csv_file}"))
                self.root.after(0, lambda: os.startfile(csv_file))

            except Exception as e:
                progress_window.destroy()
                error_msg = f"AI分析失败：{str(e)}"
                self.root.after(0, lambda: messagebox.showerror("错误", error_msg))
                self.log(f"❌ AI分析失败: {str(e)}")
                import traceback
                self.log(f"详细错误: {traceback.format_exc()}")

        # 添加停止按钮
        stop_button = ttk.Button(progress_window, text="停止分析",
                                 command=lambda: stop_analysis.set())
        stop_button.pack(pady=5)

        # 在新线程中执行分析
        analysis_thread = threading.Thread(target=analyze_in_thread, daemon=True)
        analysis_thread.start()

    # ---------------- 采集控制 ----------------
    def start_scraping(self):
        if self.is_running: return
        kw = self.keyword_var.get().strip()
        if not kw:
            messagebox.showerror("错误", "请输入搜索关键词");
            return
        try:
            max_cards = int(self.max_cards_var.get())
            if not (1 <= max_cards <= 200): raise ValueError
        except ValueError:
            messagebox.showerror("错误", "请输入有效的最大采集数量 (1-200)");
            return
        save_path = Path(self.save_path_var.get())
        if not save_path.parent.exists():
            messagebox.showerror("错误", "保存路径无效");
            return
        if not PLAYWRIGHT_AVAILABLE:
            messagebox.showerror("错误", "浏览器引擎未就绪");
            return

        self.collected_count = self.success_count = self.failed_count = 0
        self.update_stats()
        self.is_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("🟡 采集进行中...")
        self.log_text.delete(1.0, tk.END)
        self.log("=" * 50)
        self.log(f"开始采集 - 关键词: {kw}, 数量: {max_cards}")
        self.log("=" * 50)

        self.current_task = threading.Thread(target=self.run_scraper, args=(kw, max_cards, save_path), daemon=True)
        self.current_task.start()

    def stop_scraping(self):
        if self.is_running:
            self.is_running = False
            self.log("正在停止采集...", logging.WARNING)
            self.status_var.set("🟠 正在停止...")

    def run_scraper(self, keyword, max_cards, save_path):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.async_main(keyword, max_cards, save_path))
        except Exception as e:
            self.log(f"采集过程中发生错误: {e}", logging.ERROR)
            self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
        finally:
            self.root.after(0, self.on_scraping_finished)

    async def async_main(self, keyword, max_cards, save_path):
        self.scraper_instance = XHSScraper(keyword, max_cards, save_path, self)
        await self.scraper_instance.run()

    def on_scraping_finished(self):
        self.is_running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.progress_bar['value'] = 100
        self.status_var.set("✅ 采集完成")
        messagebox.showinfo("完成", f"采集完成！\n成功: {self.success_count} 条\n失败: {self.failed_count} 条")


# -------------------- 采集核心（实时写入版 + 楼中楼支持） --------------------
class XHSScraper:
    def __init__(self, keyword, max_cards, save_path, gui):
        self.KEYWORD = keyword
        self.MAX_CARDS = max_cards
        self.SAVE_DIR = Path(save_path)
        self.gui = gui
        self.SAVE_DIR.mkdir(exist_ok=True)

        self.SAVE_FILE = self.SAVE_DIR / f"{keyword}_comments_{datetime.now():%Y%m%d_%H%M%S}.json"
        self.COOKIE_FILE = self.SAVE_DIR / "xhs_cookies.json"
        self.SEEN_FILE = self.SAVE_DIR / f"{keyword}_seen.json"
        self.ACCOUNT = f"{getpass.getuser()}_{str(uuid.getnode())[-4:]}"
        self.FP_FILE = self.SAVE_DIR / f"fp_{self.ACCOUNT}.json"

        self.SAVE_FILE.touch(exist_ok=True)
        if self.SAVE_FILE.read_text(encoding='utf8').strip() == '':
            self.SAVE_FILE.write_text('[]', encoding='utf8')

        self.TEMP_RESULTS = []
        self.SEEN = set()
        self.load_seen()

    # ---------------- 工具方法 ----------------
    def log(self, msg):
        self.gui.log(msg)

    def update_progress(self, msg):
        self.gui.update_progress(msg)

    def update_stats(self, collected=0, success=0, failed=0):
        if collected: self.gui.collected_count = collected
        if success:   self.gui.success_count = success
        if failed:    self.gui.failed_count = failed
        self.gui.update_stats()

    def load_seen(self):
        if self.SEEN_FILE.exists() and self.SEEN_FILE.stat().st_size:
            try:
                self.SEEN.update(json.loads(self.SEEN_FILE.read_text()))
            except json.JSONDecodeError:
                self.SEEN = set()

    def persist_seen(self):
        self.SEEN_FILE.write_text(json.dumps(list(self.SEEN), ensure_ascii=False, indent=2), encoding='utf8')

    def parse_num(self, txt: str) -> int:
        if not txt: return 0
        txt = txt.strip()
        try:
            return int(float(txt.replace("万", "")) * 10000) if "万" in txt else int(txt)
        except Exception:
            return 0

    def random_viewport(self):
        return {"width": random.choice([1366, 1440, 1536, 1920]),
                "height": random.choice([768, 900, 1080])}

    def random_ua(self):
        chrome_ver = random.randint(110, 118)
        os_token = random.choice(["Windows NT 10.0; Win64; x64", "Macintosh; Intel Mac OS X 10_15_7"])
        return (f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_ver}.0.0.0 Safari/537.36")

    def load_or_create_fp(self):
        if self.FP_FILE.exists():
            return json.loads(self.FP_FILE.read_text())
        fp = {
            "viewport": self.random_viewport(),
            "ua": self.random_ua(),
            "vendor": random.choice(["Google Inc. (NVIDIA)", "Intel Inc.", "Google Inc. (AMD)"]),
            "renderer": random.choice([
                "ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 6GB Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "Intel Iris OpenGL Engine",
                "ANGLE (AMD, Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"
            ]),
            "color_scheme": random.choice(["light", "dark"]),
            "device_scale_factor": random.choice([1, 1.25, 1.5]),
        }
        self.FP_FILE.write_text(json.dumps(fp, indent=2))
        return fp

    # ---------------- 登录 ----------------
    async def ensure_login(self, page):
        self.log(">>> 正在访问小红书...")
        await page.goto("https://www.xiaohongshu.com ", wait_until="domcontentloaded")
        if self.COOKIE_FILE.exists():
            self.log(">>> 检测到本地 cookie，已自动加载")
            await page.context.add_cookies(json.loads(self.COOKIE_FILE.read_text()))
            await page.reload()
        else:
            self.log(">>> 请手动扫码登录小红书，登录后程序会自动继续...")
            max_wait = 180
            for i in range(max_wait):
                await asyncio.sleep(1)
                if not self.gui.is_running:
                    raise Exception("用户停止采集")
                login_indicators = await page.locator('text=登录, text=立即登录, [data-testid="login-btn"]').count()
                user_indicators = await page.locator('.user-avatar, .avatar, [data-testid="user-avatar"]').count()
                if login_indicators == 0 or user_indicators > 0:
                    self.log(">>> 登录成功！自动继续...")
                    cookies = await page.context.cookies()
                    self.COOKIE_FILE.write_text(json.dumps(cookies), encoding='utf8')
                    self.log(">>> cookie 已保存，下次自动复用")
                    return
                if i % 30 == 0 and i > 0:
                    self.log(f">>> 等待登录... ({i // 60}分{i % 60}秒)")
            self.log(">>> 登录超时，但继续尝试搜索...")

    # ---------------- 搜索 ----------------
    async def do_search(self, page):
        self.log(f">>> 正在搜索关键词: {self.KEYWORD}")
        await page.wait_for_selector('input[placeholder*="搜索"]', timeout=360_000)
        search_box = page.locator('input[placeholder*="搜索"]').first
        await search_box.click()
        await asyncio.sleep(random.uniform(0.8, 1.2))
        await search_box.fill(self.KEYWORD)
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await search_box.press("Enter")
        for _ in range(60):
            await asyncio.sleep(0.5)
            if await page.locator("section.note-item").count():
                self.log(">>> 搜索成功，卡片已出现！")
                return
        raise RuntimeError("30 秒内无卡片，可能被反爬")

    # ---------------- 展开评论（增强版：支持楼中楼） ----------------
    async def expand_comments(self, page):
        """
        评论区持续滚动 + 动态展开楼中楼
        退出条件：连续5次检测不到任何新“展开”按钮或“查看更多”按钮
        """
        try:
            container = await page.wait_for_selector(".note-scroller", timeout=10_000)
        except:
            self.log(">>> 未找到评论区容器，跳过评论展开")
            return

        clicked_buttons = set()  # 已点过的楼中楼按钮标识
        no_new_rounds = 0  # 连续“无新按钮”计数
        max_quiet = 5  # 连续无新按钮退出阈值

        while no_new_rounds < max_quiet:
            if not self.gui.is_running:
                raise Exception("用户停止采集")

            # 1. 滚到底部，触发懒加载
            await container.evaluate("node => node.scrollTop = node.scrollHeight")
            await asyncio.sleep(random.uniform(1.8, 2.5))

            # 2. 回弹一小段，保证下次还能触发加载
            await container.evaluate("node => node.scrollTop -= 200")
            await asyncio.sleep(random.uniform(0.3, 0.6))

            # 3. 检测并点击新出现的楼中楼“展开”按钮（div.show-more）
            reply_btns = page.locator('div.show-more:has-text("展开"), div.show-more:has-text("条回复")')
            new_clicks = 0
            for i in range(await reply_btns.count()):
                try:
                    btn = reply_btns.nth(i)
                    if not await btn.is_visible():
                        continue
                    text = await btn.inner_text()
                    cls = await btn.get_attribute("class") or ""
                    btn_id = f"{text.strip()}_{cls.strip()}"
                    if btn_id not in clicked_buttons:
                        await btn.scroll_into_view_if_needed()
                        await btn.click(timeout=3_000)
                        clicked_buttons.add(btn_id)
                        new_clicks += 1
                        await asyncio.sleep(0.25)
                except Exception:
                    continue

            # 4. 主评论“查看更多”按钮（只点一次就够）
            more_btn = page.locator('text=查看更多评论')
            more_clicked = False
            if await more_btn.count() and await more_btn.is_visible():
                try:
                    await more_btn.click(timeout=3_000)
                    await asyncio.sleep(1)
                    more_clicked = True
                except:
                    pass

            # 5. 统计当前总评论条数（主+子）
            total_now = await page.locator(
                ".comment-item, .sub-comment-item, .reply-item"
            ).count()

            self.log(f">>> 本轮展开楼中楼 {new_clicks} 个，"
                     f"点击“查看更多”={more_clicked}，"
                     f"当前共 {total_now} 条评论")

            # 6. 判断是否可以提前退出
            if new_clicks == 0 and not more_clicked:
                no_new_rounds += 1
            else:
                no_new_rounds = 0

        self.log(f">>> 评论区展开完成，共点击 {len(clicked_buttons)} 个楼中楼按钮")

    # ---------------- 抽取评论与元数据（最新结构版） ----------------
    async def get_comments(self, page):
        """
        抽取评论与元数据（楼中楼版）
        1. 统一抓取 div.content > span.note-text > span 文本（主+子评论）
        2. 按“楼层索引+内容”去重，保序
        其余字段逻辑不变
        """
        try:
            await page.wait_for_selector(".note-scroller", timeout=10_000)
            await self.expand_comments(page)
        except Exception as e:
            self.log(f">>> 展开评论时出错: {e}")

        comments = []
        try:
            content_elements = await page.locator(
                "div.content > span.note-text > span"
            ).all()

            # 去重保序：同楼层同内容才合并
            seen = set()
            for idx, el in enumerate(content_elements):
                text = (await el.inner_text()).strip()
                if text and len(text) > 1:
                    key = f"{idx}_{text}"  # 楼层索引 + 内容
                    if key not in seen:
                        seen.add(key)
                        comments.append(text)
        except Exception as e:
            self.log(f">>> 获取评论时出错: {e}")

        # ----------- 以下与原函数完全一致 -----------
        async def get_count(sel):
            try:
                if await page.locator(sel).count():
                    return self.parse_num(await page.locator(sel).first.inner_text())
            except:
                pass
            return 0

        likes = await get_count(".like-wrapper .count")
        collects = await get_count(".collect-wrapper .count")
        comments_count = await get_count(".chat-wrapper .count")

        title = desc = author = ""
        try:
            if await page.locator("#detail-title").count():
                title = (await page.locator("#detail-title").inner_text()).strip()
        except:
            pass
        try:
            if await page.locator("#detail-desc").count():
                desc = (await page.locator("#detail-desc").inner_text()).strip()
        except:
            pass
        try:
            if await page.locator(".author-container .author-name").count():
                author = (await page.locator(".author-container .author-name").inner_text()).strip()
        except:
            pass

        img_urls = []
        try:
            for el in await page.locator("div.swiper-slide, div.img-container, div[data-swiper-slide-index]").all():
                style = await el.get_attribute("style")
                if style and "background-image" in style:
                    m = re.search(r'url\("(.+?)"\)', style)
                    if m:
                        img_urls.append(m.group(1).split("?")[0])
            for img in await page.locator("div.note-content img").all():
                src = await img.get_attribute("src")
                if src and "avatar" not in src and "emoji" not in src and "profile" not in src:
                    img_urls.append(src.split("?")[0])
            for img in await page.locator(".comment-picture img").all():
                src = await img.get_attribute("src")
                if src:
                    img_urls.append(src.split("?")[0])
            img_urls = list(dict.fromkeys(img_urls))
        except Exception as e:
            self.log(f">>> 获取图片时出错: {e}")

        href = ""
        try:
            a_elem = await page.query_selector('a[data-testid="note-link"]') or \
                     await page.query_selector("section.note-item a")
            if a_elem:
                href = await a_elem.get_attribute("href") or ""
        except:
            pass

        return {
            "评论": comments,
            "点赞数": likes,
            "收藏数": collects,
            "评论数": comments_count,
            "标题": title,
            "内容": desc,
            "作者": author,
            "url": "https://www.xiaohongshu.com" + href if href else "",
            "正文图片": img_urls,
            "采集时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    # ---------------- 主采集循环 ----------------
    async def get_note_cards(self, page, max_cards: int = 200):
        success, failed = 0, 0
        for scroll in range(30):
            if not self.gui.is_running:
                break
            cards = await page.query_selector_all('section.note-item:has(a[href*="explore"])')
            self.update_progress(f"第 {scroll + 1} 滚，发现 {len(cards)} 张卡片，已采集 {success}/{max_cards}")
            for idx in range(len(cards)):
                if not self.gui.is_running or success >= max_cards:
                    return success, failed
                card = cards[idx]
                a_ele = await card.query_selector("a")
                href = await a_ele.get_attribute("href") if a_ele else ""
                note_id = href.split("?")[0].split("/")[-1] if href else str(hash(await card.inner_html()))
                if note_id in self.SEEN:
                    continue
                try:
                    if await page.locator("div.note-detail-mask").count():
                        await page.locator("div.note-detail-mask").evaluate("node => node.style.display='none'")
                    await card.scroll_into_view_if_needed(timeout=8_000)
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                    await card.click()
                    self.gui.collected_count += 1
                    self.SEEN.add(note_id)
                    self.persist_seen()

                    info = await self.get_comments(page)

                    # ======== 实时写入 ========
                    try:
                        with self.SAVE_FILE.open('r', encoding='utf8') as f:
                            arr = json.load(f)
                    except (json.JSONDecodeError, ValueError):
                        arr = []
                    arr.append(info)
                    with self.SAVE_FILE.open('w', encoding='utf8') as f:
                        json.dump(arr, f, ensure_ascii=False, indent=2)
                    # ======== 写入完成 ========

                    self.TEMP_RESULTS.append(info)  # 原统计用
                    success += 1
                    self.gui.success_count = success
                    self.log(f"[{success}/{max_cards}] ✅ 成功采集笔记: {note_id}，评论数: {len(info['评论'])}")
                    self.update_stats(success=success)

                    await page.go_back()
                    await page.wait_for_selector("section.note-item", timeout=10_000)
                    await asyncio.sleep(random.uniform(2, 4))
                except Exception as e:
                    self.log(f"[{success + failed + 1}/{max_cards}] ❌ 采集失败：{e}")
                    failed += 1
                    self.gui.failed_count = failed
                    self.SEEN.add(note_id)
                    self.persist_seen()
                    self.update_stats(failed=failed)

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(2.5, 3.5))
        return success, failed

    # ---------------- 浏览器启动 & 总控 ----------------
    async def run(self):
        self.log(">>> 启动浏览器...")
        async with async_playwright() as p:
            fp = self.load_or_create_fp()
            launch_options = {
                'headless': False,
                'args': [
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding'
                ]
            }
            if getattr(sys, 'frozen', False):
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                        chrome_path, _ = winreg.QueryValueEx(key, None)
                        if os.path.exists(chrome_path):
                            launch_options['executable_path'] = chrome_path
                            self.log(">>> 使用系统 Chrome 浏览器")
                except:
                    self.log(">>> 使用 Playwright 内置浏览器")

            browser = await p.chromium.launch(**launch_options)
            context = await browser.new_context(
                viewport=fp["viewport"],
                user_agent=fp["ua"],
                locale="zh-CN",
                color_scheme=fp["color_scheme"],
                device_scale_factor=fp["device_scale_factor"],
                permissions=["notifications"],
                extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
            )
            await context.add_init_script(f"""
                Object.defineProperty(WebGLRenderingContext.prototype, 'getParameter', {{
                    value: function(p) {{
                        const vendor = '{fp["vendor"]}';
                        const renderer = '{fp["renderer"]}';
                        if (p === 37445) return vendor;
                        if (p === 37446) return renderer;
                        return getParameter.call(this, p);
                    }}
                }});
                Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
            """)
            page = await context.new_page()
            try:
                await self.ensure_login(page)
                await self.do_search(page)
                self.log(f">>> 开始采集，目标数量: {self.MAX_CARDS}")
                success, failed = await self.get_note_cards(page, max_cards=self.MAX_CARDS)
                self.log(">>> 采集完成，正在保存数据...")
                self.log(f">>> 统计: 成功 {success} 条, 失败 {failed} 条")
                self.log(f">>> 实时保存路径: {self.SAVE_FILE}")
            except Exception as e:
                self.log(f"❌ 采集过程中发生错误: {str(e)}", logging.ERROR)
            finally:
                self.log(">>> 关闭浏览器...")
                await browser.close()


# -------------------- 入口 --------------------
def main():
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    root = tk.Tk()
    app = XHSScraperGUI(root)
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2
    y = (root.winfo_screenheight() - root.winfo_reqheight()) // 2
    root.geometry(f"+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()