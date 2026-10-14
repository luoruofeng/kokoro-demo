"""Kokoro-82M (v1.0) 支持的语言、音色清单与示例文案。

数据来源：hexgrad/Kokoro-82M 的 VOICES.md（音色等级为官方标注的
“Overall Grade”，代表该音色训练数据的质量与时长）。
音色 id 前缀含义：<语言><性别>_<名字>，f=女声，m=男声。
"""
from __future__ import annotations

REPO_ID = "hexgrad/Kokoro-82M"

LANG_NAMES = {
    "a": "American English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "p": "Brazilian Portuguese",
    "j": "Japanese",
    "z": "Mandarin Chinese",
}

# g2p 说明：a/b 走 misaki[en]（spacy + espeak-ng 兜底），
# e/f/h/i/p 走 espeak-ng，j 走 misaki[ja]（cutlet/pyopenjtalk），z 走 misaki[zh]（jieba+pypinyin）
LANGUAGES: list[dict] = [
    {
        "code": "a",
        "name": "美式英语",
        "english": "American English",
        "flag": "🇺🇸",
        "speech": "en-US",
        "g2p": "misaki[en] + espeak-ng 兜底",
        "tip": "训练数据最充足，af_heart / af_bella 是全模型最自然的音色。",
        "voices": [
            ("af_heart", "Heart", "f", "A", "官方 A 级，默认首选"),
            ("af_bella", "Bella", "f", "A-", "表现力强，情绪丰富"),
            ("af_nicole", "Nicole", "f", "B-", "略带气声，适合朗读"),
            ("af_aoede", "Aoede", "f", "C+", ""),
            ("af_kore", "Kore", "f", "C+", ""),
            ("af_sarah", "Sarah", "f", "C+", ""),
            ("af_alloy", "Alloy", "f", "C", ""),
            ("af_nova", "Nova", "f", "C", ""),
            ("af_sky", "Sky", "f", "C-", ""),
            ("am_fenrir", "Fenrir", "m", "C+", "男声里最稳的之一"),
            ("am_michael", "Michael", "m", "C+", ""),
            ("am_puck", "Puck", "m", "C+", ""),
            ("am_echo", "Echo", "m", "D", ""),
            ("am_eric", "Eric", "m", "D", ""),
            ("am_liam", "Liam", "m", "D", ""),
            ("am_onyx", "Onyx", "m", "D", ""),
            ("af_jessica", "Jessica", "f", "D", ""),
            ("af_river", "River", "f", "D", ""),
            ("am_santa", "Santa", "m", "D-", ""),
            ("am_adam", "Adam", "m", "F+", "音质较弱，仅作对比"),
        ],
        "samples": [
            "Kokoro is an open source text to speech model with only eighty two million parameters, "
            "yet it sounds remarkably close to a human voice.",
            "According to the report, the package costs $19.99 and arrives within 3 to 5 business days.",
            "Hello! I'm running entirely on your own computer. No cloud, no API key, no internet required.",
        ],
    },
    {
        "code": "b",
        "name": "英式英语",
        "english": "British English",
        "flag": "🇬🇧",
        "speech": "en-GB",
        "g2p": "misaki[en] (british) + espeak-ng 兜底",
        "tip": "同一套英文 G2P，仅音素规则与音色不同，可和美式英语直接对比。",
        "voices": [
            ("bf_emma", "Emma", "f", "B-", "最自然的女声"),
            ("bf_isabella", "Isabella", "f", "C", ""),
            ("bm_fable", "Fable", "m", "C", ""),
            ("bm_george", "George", "m", "C", "标准 BBC 味"),
            ("bm_lewis", "Lewis", "m", "D+", ""),
            ("bf_alice", "Alice", "f", "D", ""),
            ("bf_lily", "Lily", "f", "D", ""),
            ("bm_daniel", "Daniel", "m", "D", ""),
        ],
        "samples": [
            "Good afternoon, and welcome to the British English demonstration. Rather lovely weather "
            "we're having, isn't it?",
            "The train to Edinburgh departs from platform nine at a quarter past six in the evening.",
        ],
    },
    {
        "code": "e",
        "name": "西班牙语",
        "english": "Spanish",
        "flag": "🇪🇸",
        "speech": "es-ES",
        "g2p": "espeak-ng (es)",
        "tip": "拉丁语系里表现最稳的一档，音素由 espeak-ng 生成。",
        "voices": [
            ("ef_dora", "Dora", "f", "—", "唯一女声"),
            ("em_alex", "Alex", "m", "—", ""),
            ("em_santa", "Santa", "m", "—", ""),
        ],
        "samples": [
            "Hola, esta es una demostración de síntesis de voz en español. Kokoro puede hablar nueve idiomas "
            "sin necesidad de internet.",
            "El tren sale a las 7:45 de la mañana y cuesta 12,50 euros por persona.",
        ],
    },
    {
        "code": "f",
        "name": "法语",
        "english": "French",
        "flag": "🇫🇷",
        "speech": "fr-FR",
        "g2p": "espeak-ng (fr-fr)",
        "tip": "官方只有 1 个法语女声 ff_siwis，但等级高达 B-。",
        "voices": [
            ("ff_siwis", "Siwis", "f", "B-", "唯一法语音色，质量不错"),
        ],
        "samples": [
            "Bonjour, ceci est une démonstration de synthèse vocale en français. Kokoro fonctionne "
            "entièrement sur votre ordinateur.",
            "Le quatorze juillet 1789, la Révolution française a commencé à Paris.",
        ],
    },
    {
        "code": "h",
        "name": "印地语",
        "english": "Hindi",
        "flag": "🇮🇳",
        "speech": "hi-IN",
        "g2p": "espeak-ng (hi)",
        "tip": "天城文由 espeak-ng 直接转音素，展示非拉丁文字的处理能力。",
        "voices": [
            ("hf_alpha", "Alpha", "f", "C", ""),
            ("hf_beta", "Beta", "f", "C", ""),
            ("hm_omega", "Omega", "m", "C", ""),
            ("hm_psi", "Psi", "m", "C", ""),
        ],
        "samples": [
            "नमस्ते, यह बहुभाषी वाक् संश्लेषण का प्रदर्शन है। कोकोरो आपके कंप्यूटर पर ही चलता है।",
            "आज का तापमान बत्तीस डिग्री सेल्सियस है और शाम को बारिश हो सकती है।",
        ],
    },
    {
        "code": "i",
        "name": "意大利语",
        "english": "Italian",
        "flag": "🇮🇹",
        "speech": "it-IT",
        "g2p": "espeak-ng (it)",
        "tip": "元音饱满、节奏感强，很适合试听语速效果。",
        "voices": [
            ("if_sara", "Sara", "f", "C", ""),
            ("im_nicola", "Nicola", "m", "C", ""),
        ],
        "samples": [
            "Ciao, questa è una dimostrazione di sintesi vocale in italiano. Kokoro può parlare nove lingue "
            "diverse.",
            "Il treno per Roma parte alle otto e mezza dal binario dodici.",
        ],
    },
    {
        "code": "p",
        "name": "葡式（巴西）",
        "english": "Brazilian Portuguese",
        "flag": "🇧🇷",
        "speech": "pt-BR",
        "g2p": "espeak-ng (pt-br)",
        "tip": "葡语发音鼻化元音多，是检验音素映射的好例子。",
        "voices": [
            ("pf_dora", "Dora", "f", "—", ""),
            ("pm_alex", "Alex", "m", "—", ""),
            ("pm_santa", "Santa", "m", "—", ""),
        ],
        "samples": [
            "Olá, esta é uma demonstração de síntese de voz em português do Brasil. O Kokoro funciona no seu "
            "próprio computador.",
            "As passagens custam quinhentos e cinquenta reais e a viagem dura cerca de duas horas.",
        ],
    },
    {
        "code": "j",
        "name": "日语",
        "english": "Japanese",
        "flag": "🇯🇵",
        "speech": "ja-JP",
        "g2p": "misaki[ja]（cutlet + unidic-lite）",
        "tip": "需要 fugashi/unidic-lite/pyopenjtalk，已随本项目安装。",
        "voices": [
            ("jf_alpha", "Alpha", "f", "C+", "日语最佳音色"),
            ("jf_gongitsune", "Gongitsune", "f", "C", ""),
            ("jf_tebukuro", "Tebukuro", "f", "C", ""),
            ("jf_nezumi", "Nezumi", "f", "C-", ""),
            ("jm_kumo", "Kumo", "m", "C-", ""),
        ],
        "samples": [
            "こんにちは。これは日本語の音声合成のデモです。ココロは九つの言語を話すことができます。",
            "新幹線は午前九時十五分に東京駅を出発します。料金は一万三千円です。",
        ],
    },
    {
        "code": "z",
        "name": "中文（普通话）",
        "english": "Mandarin Chinese",
        "flag": "🇨🇳",
        "speech": "zh-CN",
        "g2p": "misaki[zh]（jieba + pypinyin + 数字归一化）",
        "tip": "v1.0 中文音色官方评级为 D，可听但偏机械；"
               "如需更好的中文效果，可另行下载 Kokoro-82M-v1.1-zh。",
        "voices": [
            ("zf_xiaoxiao", "晓晓", "f", "D", "默认中文女声"),
            ("zf_xiaobei", "小北", "f", "D", ""),
            ("zf_xiaoni", "小妮", "f", "D", ""),
            ("zf_xiaoyi", "小艺", "f", "D", ""),
            ("zm_yunyang", "云扬", "m", "D", ""),
            ("zm_yunjian", "云健", "m", "D", ""),
            ("zm_yunxi", "云希", "m", "D", ""),
            ("zm_yunxia", "云夏", "m", "D", ""),
        ],
        "samples": [
            "你好，这是一段中文语音合成的演示。Kokoro 只有八千二百万个参数，却能在本地流畅地朗读中文。",
            "今天是 2026 年 10 月 14 日，气温 22 摄氏度，预计傍晚有雨，出门记得带伞。",
            "人工智能正在改变我们学习和工作的方式。让机器开口说话，是其中最有温度的一步。",
        ],
    },
]

LANG_BY_CODE = {item["code"]: item for item in LANGUAGES}

# 每种语言的默认音色：取官方等级最高的那个
DEFAULT_VOICE = {
    "a": "af_heart",
    "b": "bf_emma",
    "e": "ef_dora",
    "f": "ff_siwis",
    "h": "hf_alpha",
    "i": "if_sara",
    "p": "pf_dora",
    "j": "jf_alpha",
    "z": "zf_xiaoxiao",
}
