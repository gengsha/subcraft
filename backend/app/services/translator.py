"""翻译服务：OpenAI 兼容 API（GPT/DeepSeek/Kimi 等）与 DeepL。

批处理策略：将多条字幕按编号拼成一批发送，回复按编号解析对齐；
数量不一致时对该批降级为逐条翻译，保证时间轴绝不错位。
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from ..models import Segment

ProgressCb = Callable[[float, str], None]

# whisper 语言码 -> DeepL 语言码
DEEPL_LANG_MAP = {
    "zh": "ZH", "en": "EN-US", "ja": "JA", "ko": "KO", "fr": "FR",
    "de": "DE", "es": "ES", "ru": "RU", "it": "IT", "pt": "PT-PT",
    "ar": "AR", "th": "TH", "vi": "VI", "id": "ID", "hi": "HI",
}

# 编号格式: "1." / "1、" / "1:" / "[1]" / "(1)" / "（1）" 等；裸数字+空格不算编号，避免误吞正文
_LINE_RE = re.compile(r"^\s*(?:[\[(\（【]\s*(\d+)\s*[\])\）】]|(\d+)\s*[.、:：)）\-])\s*(.*)$")


def parse_numbered_lines(text: str) -> list[str]:
    """解析 '1. xxx' 形式的回复为有序列表（容错多种编号格式）。"""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    items: dict[int, str] = {}
    plain: list[str] = []
    for ln in lines:
        m = _LINE_RE.match(ln)
        num = (m.group(1) or m.group(2)) if m else None
        content = (m.group(3) if m else ln).strip()
        if num is not None:
            items[int(num)] = content
        elif content:
            plain.append(content)
    if items:
        return [items[k] for k in sorted(items)]
    return plain


class OpenAICompatTranslator:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url or None)
        self.model = model

    def _chat(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是专业字幕翻译。用户会发来带编号的多行字幕，"
                        "请逐行翻译并保持相同编号与原行数，不要合并或拆分行，"
                        "只输出译文，不要任何解释。译文需口语化、简洁，符合字幕习惯。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""

    def translate_batch(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        prompt = (
            f"将以下字幕从 {source_lang} 翻译为 {target_lang}：\n"
            + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
        )
        result = parse_numbered_lines(self._chat(prompt))
        if len(result) == len(texts):
            return result
        # 数量不齐：逐条重试，保证对齐
        out: list[str] = []
        for t in texts:
            single = parse_numbered_lines(
                self._chat(f"将以下字幕从 {source_lang} 翻译为 {target_lang}：\n1. {t}")
            )
            out.append(single[0] if single else t)
        return out


class DeepLTranslator:
    def __init__(self, api_key: str) -> None:
        # ':fx' 结尾为免费版 key
        host = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        self.url = f"{host}/v2/translate"
        self.key = api_key

    def translate_batch(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        target = DEEPL_LANG_MAP.get(target_lang, target_lang.upper())
        source = DEEPL_LANG_MAP.get(source_lang, source_lang.upper())
        if source.startswith("EN"):
            source = "EN"
        resp = httpx.post(
            self.url,
            data={
                "auth_key": self.key,
                "text": texts,
                "source_lang": source,
                "target_lang": target,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return [t["text"] for t in data.get("translations", [])]


def get_ai_provider(provider_id: str | None = None) -> dict | None:
    """按 id 取 AI 厂商配置；不传 id 时返回第一个。"""
    from ..config import store

    providers = store.get("ai_providers", []) or []
    if provider_id:
        found = next((p for p in providers if p.get("id") == provider_id), None)
        if found:
            return found
    return providers[0] if providers else None


def _get_translator(
    provider: str,
    provider_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
):
    from ..config import store

    if provider == "deepl":
        key = api_key or store.get("deepl_api_key")
        if not key:
            raise RuntimeError("未配置 DeepL API Key（设置页中填写）")
        return DeepLTranslator(key)
    p = get_ai_provider(provider_id) or {}
    key = api_key or p.get("api_key", "")
    if not key:
        name = p.get("name") or "AI 翻译接口"
        raise RuntimeError(f"未配置 {name} 的 API Key（设置页中添加/填写）")
    return OpenAICompatTranslator(
        key,
        base_url or p.get("base_url", ""),
        model or p.get("model", "gpt-4o-mini"),
    )


def translate_segments(
    segments: list[Segment],
    source_lang: str,
    target_lang: str,
    provider: str = "openai",
    provider_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    batch_size: int = 25,
    concurrency: int = 4,
    progress_cb: ProgressCb | None = None,
) -> list[Segment]:
    """翻译字幕段（保持时间轴不变），分批并发处理。"""
    translator = _get_translator(provider, provider_id, api_key, base_url, model)
    batches: list[list[int]] = []
    for i in range(0, len(segments), batch_size):
        batches.append(list(range(i, min(i + batch_size, len(segments)))))
    results: dict[int, str] = {}
    done = 0

    def work(batch: list[int]) -> None:
        nonlocal done
        texts = [segments[i].text for i in batch]
        translated = translator.translate_batch(texts, source_lang, target_lang)
        for idx, text in zip(batch, translated):
            results[idx] = text
        done += len(batch)
        if progress_cb:
            progress_cb(min(done / max(len(segments), 1), 0.99), f"翻译中 {done}/{len(segments)}")

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(work, batches))

    return [
        Segment(start=s.start, end=s.end, text=results.get(i, s.text))
        for i, s in enumerate(segments)
    ]
