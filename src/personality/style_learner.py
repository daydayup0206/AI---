"""
风格学习器：从聊天记录中自动提取目标人物的说话风格特征。

输入: data/training/<name>_her_style.jsonl
输出: 风格配置文件 + 分析报告
"""

import json
import re
from collections import Counter
from pathlib import Path


class StyleLearner:
    """分析聊天记录，提取说话风格特征。"""

    def __init__(self, messages: list[dict]):
        self.messages = messages
        self.texts = [m["text"] for m in messages if m.get("text", "").strip()]
        self.all_text = "\n".join(self.texts)
        self.total = len(self.texts)

    # ── 句子长度分析 ──────────────────────────────────

    def analyze_length(self) -> dict:
        lengths = [len(t) for t in self.texts]
        if not lengths:
            return {}

        avg_len = sum(lengths) / len(lengths)
        sorted_lens = sorted(lengths)
        median = sorted_lens[len(sorted_lens) // 2]

        # 长度分布
        very_short = sum(1 for l in lengths if l <= 5)      # "好的" "嗯" "噢"
        short = sum(1 for l in lengths if 6 <= l <= 15)
        medium = sum(1 for l in lengths if 16 <= l <= 40)
        long = sum(1 for l in lengths if 41 <= l <= 100)
        very_long = sum(1 for l in lengths if l > 100)

        length_label = ""
        if avg_len < 10:
            length_label = "极短句（碎片化表达）"
        elif avg_len < 20:
            length_label = "短句为主"
        elif avg_len < 35:
            length_label = "中短句为主"
        elif avg_len < 60:
            length_label = "中等长度"
        else:
            length_label = "偏长句"

        return {
            "avg_chars": round(avg_len, 1),
            "median_chars": median,
            "min_chars": min(lengths),
            "max_chars": max(lengths),
            "label": length_label,
            "distribution": {
                "极短(≤5)": f"{very_short}条 ({very_short/self.total*100:.0f}%)",
                "短(6-15)": f"{short}条 ({short/self.total*100:.0f}%)",
                "中(16-40)": f"{medium}条 ({medium/self.total*100:.0f}%)",
                "长(41-100)": f"{long}条 ({long/self.total*100:.0f}%)",
                "超长(>100)": f"{very_long}条 ({very_long/self.total*100:.0f}%)",
            },
        }

    # ── 语气词分析 ──────────────────────────────────

    def analyze_tone_markers(self) -> dict:
        """检测语气词、口头禅、标点习惯。"""
        # 语气词
        tone_words = {
            "呀": 0, "呢": 0, "嘛": 0, "哦": 0, "噢": 0, "啦": 0,
            "吖": 0, "咯": 0, "哈": 0, "诶": 0, "哇": 0, "哟": 0,
            "吧": 0, "呗": 0, "嗯": 0, "呃": 0,
        }
        for text in self.texts:
            for word in tone_words:
                tone_words[word] += text.count(word)

        # 按频率排序
        active_tones = sorted(
            [(w, c) for w, c in tone_words.items() if c > self.total * 0.02],
            key=lambda x: -x[1],
        )

        # 标点习惯
        punctuation = {
            "感叹号！": len(re.findall(r"！+", self.all_text)),
            "问号？": len(re.findall(r"？+", self.all_text)),
            "省略号…": len(re.findall(r"…+", self.all_text)),
            "波浪号~": len(re.findall(r"~+", self.all_text)),
            "hhh/哈哈哈": len(re.findall(r"h{2,}|哈{2,}|呵{2,}", self.all_text, re.I)),
            "？？？(连问)": len(re.findall(r"？{2,}", self.all_text)),
            "！！！(连叹)": len(re.findall(r"！{2,}", self.all_text)),
        }

        # 习惯后缀
        suffix_patterns = {
            "～结尾": len(re.findall(r"～$", self.all_text, re.MULTILINE)),
            "...结尾": len(re.findall(r"\.{2,}$", self.all_text, re.MULTILINE)),
            "！结尾": len(re.findall(r"！$", self.all_text, re.MULTILINE)),
            "？结尾": len(re.findall(r"？$", self.all_text, re.MULTILINE)),
        }

        return {
            "active_tone_words": [w for w, _ in active_tones],
            "tone_word_counts": {w: c for w, c in active_tones},
            "punctuation": punctuation,
            "sentence_endings": suffix_patterns,
        }

    # ── 高频词汇 & 口头禅 ──────────────────────────────

    def analyze_vocabulary(self) -> dict:
        """提取高频词汇和口头禅。"""
        # 排除常见功能词
        stop_chars = set("的是不我一有个在上人们来大就到时地以为可以生中这你她他它着之里后去说没也看要了好得还下那出对想自能会过子小么什天起都样而长把话多手面心动如现用开所方前因只从很但点被")

        # 2-gram 短语
        bigrams = Counter()
        for text in self.texts:
            cleaned = re.sub(r"[^一-鿿]", "", text)  # 只留中文
            for i in range(len(cleaned) - 1):
                bigram = cleaned[i : i + 2]
                if bigram[0] not in stop_chars or bigram[1] not in stop_chars:
                    bigrams[bigram] += 1

        top_bigrams = [(bg, c) for bg, c in bigrams.most_common(30) if c >= 5]

        # 口头禅检测：2-4字词高频出现
        phrase_counter = Counter()
        for text in self.texts:
            # 提取常见短语模式
            for phrase in re.findall(r"[一-鿿]{2,4}", text):
                if phrase not in ("就是", "不是", "这个", "那个", "可以", "没有"):
                    phrase_counter[phrase] += 1

        top_phrases = [
            (p, c) for p, c in phrase_counter.most_common(40)
            if c >= self.total * 0.01 and c >= 3
        ]

        return {
            "top_bigrams": top_bigrams[:20],
            "top_phrases": top_phrases[:25],
            "total_unique_phrases": len(phrase_counter),
        }

    # ── 常用表情/颜文字 ──────────────────────────────

    def analyze_expressions(self) -> dict:
        """分析表情和颜文字使用习惯。"""
        # 微信表情关键词
        emoji_keywords = ["[表情]", "[动画表情]", "[图片]", "[语音]", "[视频]"]

        # 颜文字/kaomoji
        kaomoji_patterns = [
            r"\([^)]*[ω･▽╹◕＾ˊథㅂ∇ヘóò∀дェ＞<≥≤][^)]*\)",
            r"⁄\([^)]*\)",
            r"[\(（][一-鿿]{1,3}[\)）]",
            r"[　-〿㈀-㋿︀-️＀-￯]",
            r"orz|OTL|2333|hhh+|www",
        ]

        kaomoji_count = 0
        for pat in kaomoji_patterns:
            kaomoji_count += len(re.findall(pat, self.all_text, re.I))

        # 微信表情
        wx_emoji_count = sum(self.all_text.count(k) for k in emoji_keywords)

        # 数字表情（如 4️⃣ 555 666）
        number_emoji = len(re.findall(r"\d[️⃣-⃣]|\b[5]{2,}\b|\b[6]{2,}\b|\b[2]{3,}\b", self.all_text))

        return {
            "kaomoji_count": kaomoji_count,
            "wx_emoji_count": wx_emoji_count,
            "number_emoji_count": number_emoji,
            "has_custom_emoji": kaomoji_count + number_emoji > self.total * 0.05,
        }

    # ── 多消息连发习惯 ──────────────────────────────

    def analyze_burst_pattern(self) -> dict:
        """分析连发消息的习惯。"""
        raw_messages = [m.get("raw_messages", []) for m in self.messages]
        burst_sizes = [len(rm) for rm in raw_messages if rm]

        if not burst_sizes:
            return {}

        avg_burst = sum(burst_sizes) / len(burst_sizes)
        single = sum(1 for b in burst_sizes if b == 1)
        double = sum(1 for b in burst_sizes if b == 2)
        triple = sum(1 for b in burst_sizes if 3 <= b <= 5)
        many = sum(1 for b in burst_sizes if b > 5)

        return {
            "avg_messages_per_burst": round(avg_burst, 1),
            "max_burst": max(burst_sizes),
            "burst_distribution": {
                "单条": f"{single}次 ({single/len(burst_sizes)*100:.0f}%)",
                "2连发": f"{double}次 ({double/len(burst_sizes)*100:.0f}%)",
                "3-5连发": f"{triple}次 ({triple/len(burst_sizes)*100:.0f}%)",
                "5+连发": f"{many}次 ({many/len(burst_sizes)*100:.0f}%)",
            },
            "style": "碎片化连发" if avg_burst >= 2.5 else "偶尔连发" if avg_burst >= 1.5 else "单条发送",
        }

    # ── 称呼习惯 ──────────────────────────────────

    def analyze_terms_of_endearment(self, my_name_hint: str = "") -> dict:
        """检测她对"我"的称呼习惯。"""
        # 常见称呼模式
        patterns = {
            "宝贝": r"宝贝",
            "亲爱的": r"亲爱的",
            "老公": r"老公",
            "哥哥": r"哥哥",
            "宝": r"(?<!\w)宝(?!宝|贝|宝|贵的)",
            "你呀": r"你呀",
            "你呢": r"你呢",
        }

        found = {}
        for name, pat in patterns.items():
            count = len(re.findall(pat, self.all_text))
            if count >= 3:
                found[name] = count

        # 检测"你"字的使用模式
        you_count = self.all_text.count("你")
        you_rate = you_count / max(1, len(self.all_text))

        return {
            "endearment_terms": found,
            "you_usage_rate": round(you_rate * 100, 1),
            "likely_uses_terms": len(found) > 0,
        }

    # ── 综合报告 ──────────────────────────────────

    def generate_report(self, target_name: str = "") -> str:
        """生成完整的风格分析报告。"""
        length = self.analyze_length()
        tone = self.analyze_tone_markers()
        vocab = self.analyze_vocabulary()
        expr = self.analyze_expressions()
        burst = self.analyze_burst_pattern()
        endear = self.analyze_terms_of_endearment()

        name = target_name or "目标人物"

        lines = [
            f"╔{'═'*58}╗",
            f"║  {name} 的说话风格分析报告",
            f"╚{'═'*58}╝",
            "",
            "── 句子长度 ──",
            f"  平均: {length.get('avg_chars', '?')} 字 | 中位数: {length.get('median_chars', '?')} 字",
            f"  范围: {length.get('min_chars', '?')} - {length.get('max_chars', '?')} 字",
            f"  类型: {length.get('label', '?')}",
            f"  分布: {length.get('distribution', {})}",
            "",
            "── 连发习惯 ──",
            f"  平均连发: {burst.get('avg_messages_per_burst', '?')} 条/轮",
            f"  最多连发: {burst.get('max_burst', '?')} 条",
            f"  风格: {burst.get('style', '?')}",
            "",
            "── 语气特征 ──",
            f"  常用语气词: {', '.join(tone.get('active_tone_words', [])[:8])}",
            f"  标点习惯:",
        ]

        for k, v in tone.get("punctuation", {}).items():
            if v > 0:
                lines.append(f"    {k}: {v} 次")

        lines += [
            "",
            "── 口头禅 & 高频短语 ──",
        ]
        for phrase, count in vocab.get("top_phrases", [])[:15]:
            lines.append(f"  「{phrase}」: {count} 次")

        lines += [
            "",
            "── 表情使用 ──",
            f"  颜文字/字符表情: {expr.get('kaomoji_count', 0)} 次",
            f"  微信表情: {expr.get('wx_emoji_count', 0)} 次",
            f"  数字表情: {expr.get('number_emoji_count', 0)} 次",
            "",
            "── 称呼习惯 ──",
        ]
        if endear.get("endearment_terms"):
            for term, count in endear["endearment_terms"].items():
                lines.append(f"  「{term}」: {count} 次")
        else:
            lines.append("  (未检测到特定爱称)")

        return "\n".join(lines)

    # ── 生成人设配置 ──────────────────────────────────

    def generate_persona_config(self) -> dict:
        """生成可直接合并到 config.yaml 的 speaking_style 配置。"""
        length = self.analyze_length()
        tone = self.analyze_tone_markers()
        vocab = self.analyze_vocabulary()
        burst = self.analyze_burst_pattern()
        endear = self.analyze_terms_of_endearment()

        habits = []

        # 句子长度习惯
        habits.append(f"回复{length.get('label', '短句为主')}，平均{length.get('avg_chars', 20)}字")

        # 连发习惯
        burst_style = burst.get("style", "")
        if burst_style == "碎片化连发":
            habits.append("喜欢一次性连发多条短消息，像真实微信聊天一样分行发送")
        elif burst_style == "偶尔连发":
            habits.append("偶尔连发2-3条消息")

        # 高频语气词
        active_tones = tone.get("active_tone_words", [])
        if active_tones:
            top_tones = active_tones[:5]
            habits.append(f"经常使用{'、'.join(f'「{t}」' for t in top_tones)}等语气词")

        # 标点习惯
        punct = tone.get("punctuation", {})
        if punct.get("hhh/哈哈哈", 0) > 10:
            habits.append("笑的时候用「hhh」或「哈哈哈」")
        if punct.get("！！！(连叹)", 0) > 5:
            habits.append("兴奋时用多个感叹号！！！")
        if punct.get("？？？(连问)", 0) > 5:
            habits.append("惊讶/疑问时用？？？")

        # 口头禅
        top_phrases = vocab.get("top_phrases", [])[:5]
        if top_phrases:
            phrase_str = "、".join(f"「{p}」" for p, _ in top_phrases)
            habits.append(f"口头禅包括：{phrase_str}")

        # 称呼
        endear_terms = endear.get("endearment_terms", {})
        if endear_terms:
            top_terms = sorted(endear_terms.items(), key=lambda x: -x[1])[:3]
            term_str = "、".join(f"「{t}」" for t, _ in top_terms)
            habits.append(f"习惯用{term_str}称呼对方")

        # 推断语气
        tone_label = "自然、口语化"
        if "呀" in active_tones or "呢" in active_tones:
            tone_label = "活泼、俏皮"
        if "hhh" in str(punct) or "哈" in str(active_tones):
            tone_label += "、爱笑"

        return {
            "tone": tone_label,
            "sentence_length": f"{length.get('label', '中短句为主')}（平均{length.get('avg_chars', '?')}字）",
            "habits": habits,
            "topics": [
                "日常吐槽和分享",
                "工作/上班的牢骚",
                "旅行和出去玩",
                "互相关心和逗趣",
            ],
        }


# ── 命令行 ──────────────────────────────────────────────

def main():
    import sys

    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # 找最新的 her_style.jsonl
    training_dir = Path(r"E:\new-learning\ai女友\data\training")
    her_files = list(training_dir.glob("*_her_style.jsonl"))

    if not her_files:
        print("[!] 未找到 *_her_style.jsonl 文件")
        print("[!] 请先运行 python parse_chat_export.py")
        sys.exit(1)

    # 取最新的
    her_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    her_file = her_files[0]

    target_name = her_file.stem.replace("_her_style", "")

    print(f"[*] 读取: {her_file}")
    messages = [json.loads(l) for l in open(her_file, "r", encoding="utf-8") if l.strip()]
    print(f"[+] 加载 {len(messages)} 条消息")

    learner = StyleLearner(messages)

    # 生成报告
    report = learner.generate_report(target_name)
    print()
    print(report)

    # 生成配置
    config = learner.generate_persona_config()
    config_path = training_dir / f"{target_name}_style_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"\n[+] 风格配置已保存: {config_path}")

    # 同时保存报告
    report_path = training_dir / f"{target_name}_style_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[+] 分析报告已保存: {report_path}")


if __name__ == "__main__":
    main()
