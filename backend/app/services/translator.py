"""翻译服务：OpenAI 兼容 API（GPT/DeepSeek/Kimi 等）与 DeepL。

批处理策略：将多条字幕按编号拼成一批发送，回复按编号解析对齐；
数量不一致时对该批降级为逐条翻译，保证时间轴绝不错位。

上下文与术语：每批附带前几条原文作为「仅供参考、不要翻译」的上下文，
并可附带用户术语表（每行「原文=译文」），保证人名、术语跨批次一致。
"""
from __future__ import annotations

import inspect
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


CONTEXT_LINES = 3  # 每批附带的前文条数


def parse_glossary(text: str | None) -> list[tuple[str, str]]:
    """解析术语表：每行「原文=译文」（也接受 → / => / 制表符）；# 开头为注释。"""
    out: list[tuple[str, str]] = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.split(r"\s*(?:=>|→|=|\t)\s*", ln, maxsplit=1)
        if len(m) == 2 and m[0] and m[1]:
            out.append((m[0], m[1]))
    return out


def _build_prompt(texts: list[str], source_lang: str, target_lang: str,
                  context: list[str] | None, glossary: list[tuple[str, str]] | None) -> str:
    parts: list[str] = []
    if glossary:
        used = [(s, t) for s, t in glossary if any(s.lower() in x.lower() for x in texts)]
        if used:
            parts.append("术语表（必须按此翻译）：\n" + "\n".join(f"{s} = {t}" for s, t in used))
    if context:
        parts.append("前文（仅供理解语境，不要翻译、不要输出）：\n" + "\n".join(context))
    parts.append(
        f"将以下字幕从 {source_lang} 翻译为 {target_lang}：\n"
        + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    )
    return "\n\n".join(parts)


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

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        context: list[str] | None = None,
        glossary: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        result = parse_numbered_lines(self._chat(_build_prompt(texts, source_lang, target_lang, context, glossary)))
        if len(result) == len(texts):
            return result
        # 数量不齐：逐条重试，保证对齐；逐条时仍带上紧邻前文与术语
        out: list[str] = []
        for i, t in enumerate(texts):
            prev = (list(context or []) + texts[:i])[-CONTEXT_LINES:]
            single = parse_numbered_lines(self._chat(_build_prompt([t], source_lang, target_lang, prev, glossary)))
            out.append(single[0] if single else t)
        return out


class DeepLTranslator:
    def __init__(self, api_key: str) -> None:
        # ':fx' 结尾为免费版 key
        host = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        self.url = f"{host}/v2/translate"
        self.key = api_key

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        context: list[str] | None = None,
        glossary: list[tuple[str, str]] | None = None,  # DeepL 术语表需预先建表，这里不使用
    ) -> list[str]:
        target = DEEPL_LANG_MAP.get(target_lang, target_lang.upper())
        source = DEEPL_LANG_MAP.get(source_lang, source_lang.upper())
        if source.startswith("EN"):
            source = "EN"
        data: dict = {
            "auth_key": self.key,
            "text": texts,
            "source_lang": source,
            "target_lang": target,
        }
        if context:
            data["context"] = "\n".join(context)  # DeepL 原生支持 context 参数（不计费）
        resp = httpx.post(
            self.url,
            data=data,
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
    glossary: str | None = None,
) -> list[Segment]:
    """翻译字幕段（保持时间轴不变），分批并发处理。

    glossary 为术语表文本（每行「原文=译文」）；不传时读取设置里的 translation_glossary。
    """
    from ..config import store

    translator = _get_translator(provider, provider_id, api_key, base_url, model)
    terms = parse_glossary(glossary if glossary is not None else store.get("translation_glossary", ""))
    try:
        params = inspect.signature(translator.translate_batch).parameters
        rich = "context" in params or any(p.kind is p.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        rich = False
    batches: list[list[int]] = []
    for i in range(0, len(segments), batch_size):
        batches.append(list(range(i, min(i + batch_size, len(segments)))))
    results: dict[int, str] = {}
    done = 0

    def work(batch: list[int]) -> None:
        nonlocal done
        texts = [segments[i].text for i in batch]
        if rich:
            first = batch[0]
            ctx = [s.text for s in segments[max(0, first - CONTEXT_LINES):first]]
            translated = translator.translate_batch(texts, source_lang, target_lang, context=ctx, glossary=terms)
        else:
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
