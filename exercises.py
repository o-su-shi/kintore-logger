"""
筋トレ種目データベース + 予測変換（あいまい検索）。

- EXERCISES: 種目名 -> (部位, 器具)
    器具が "ダンベル" の種目は「片方の重量」を入力する想定。
- ALIASES: 略語・かな読み・英語などを正式名へ名寄せ。
- _normalize: 全角/半角・大文字小文字・カタカナ→ひらがな を吸収。
- search_exercises: 入力文字から候補を絞り込む（予測変換用）。
"""

import difflib
import re
import unicodedata

# 器具の種類
BARBELL = "バーベル"
DUMBBELL = "ダンベル"   # 片方の重量を記録
MACHINE = "マシン"
CABLE = "ケーブル"
BODYWEIGHT = "自重"

# 形式: "種目名": (部位, 器具)
EXERCISES = {
    # ===== 胸 =====
    "ベンチプレス": ("胸", BARBELL),
    "インクラインベンチプレス": ("胸", BARBELL),
    "デクラインベンチプレス": ("胸", BARBELL),
    "ダンベルベンチプレス": ("胸", DUMBBELL),
    "インクラインダンベルプレス": ("胸", DUMBBELL),
    "ダンベルフライ": ("胸", DUMBBELL),
    "インクラインダンベルフライ": ("胸", DUMBBELL),
    "チェストプレス": ("胸", MACHINE),
    "ペックフライ": ("胸", MACHINE),
    "ケーブルクロスオーバー": ("胸", CABLE),
    "腕立て伏せ": ("胸", BODYWEIGHT),
    "ディップス": ("胸", BODYWEIGHT),
    # ===== 背中 =====
    "デッドリフト": ("背中", BARBELL),
    "ベントオーバーロウ": ("背中", BARBELL),
    "懸垂": ("背中", BODYWEIGHT),
    "ラットプルダウン": ("背中", MACHINE),
    "シーテッドロウ": ("背中", MACHINE),
    "ダンベルロウ": ("背中", DUMBBELL),
    "ワンハンドロウ": ("背中", DUMBBELL),
    "ケーブルロウ": ("背中", CABLE),
    "プルオーバー": ("背中", DUMBBELL),
    "バックエクステンション": ("背中", BODYWEIGHT),
    "シュラッグ": ("背中", DUMBBELL),
    # ===== 肩 =====
    "ショルダープレス": ("肩", BARBELL),
    "ダンベルショルダープレス": ("肩", DUMBBELL),
    "アーノルドプレス": ("肩", DUMBBELL),
    "サイドレイズ": ("肩", DUMBBELL),
    "フロントレイズ": ("肩", DUMBBELL),
    "リアレイズ": ("肩", DUMBBELL),
    "リアデルトフライ": ("肩", MACHINE),
    "アップライトロウ": ("肩", BARBELL),
    "フェイスプル": ("肩", CABLE),
    # ===== 脚 =====
    "スクワット": ("脚", BARBELL),
    "フロントスクワット": ("脚", BARBELL),
    "レッグプレス": ("脚", MACHINE),
    "レッグエクステンション": ("脚", MACHINE),
    "レッグカール": ("脚", MACHINE),
    "ルーマニアンデッドリフト": ("脚", BARBELL),
    "ブルガリアンスクワット": ("脚", DUMBBELL),
    "ランジ": ("脚", DUMBBELL),
    "ダンベルスクワット": ("脚", DUMBBELL),
    "カーフレイズ": ("脚", DUMBBELL),
    "ヒップスラスト": ("脚", BARBELL),
    "アダクション": ("脚", MACHINE),
    "アブダクション": ("脚", MACHINE),
    # ===== 腕（二頭） =====
    "バーベルカール": ("二頭", BARBELL),
    "ダンベルカール": ("二頭", DUMBBELL),
    "ハンマーカール": ("二頭", DUMBBELL),
    "インクラインカール": ("二頭", DUMBBELL),
    "コンセントレーションカール": ("二頭", DUMBBELL),
    "プリーチャーカール": ("二頭", BARBELL),
    "ケーブルカール": ("二頭", CABLE),
    # ===== 腕（三頭） =====
    "トライセプスプレスダウン": ("三頭", CABLE),
    "フレンチプレス": ("三頭", DUMBBELL),
    "ライイングトライセプスエクステンション": ("三頭", BARBELL),
    "キックバック": ("三頭", DUMBBELL),
    "ナローベンチプレス": ("三頭", BARBELL),
    "オーバーヘッドエクステンション": ("三頭", DUMBBELL),
    # ===== 腹 =====
    "クランチ": ("腹", BODYWEIGHT),
    "レッグレイズ": ("腹", BODYWEIGHT),
    "プランク": ("腹", BODYWEIGHT),
    "アブローラー": ("腹", BODYWEIGHT),
    "ロシアンツイスト": ("腹", DUMBBELL),
    "ハンギングレッグレイズ": ("腹", BODYWEIGHT),
    "ケーブルクランチ": ("腹", CABLE),
}

# 別名（略語・かな・英語）→ 正式名（EXERCISESのキー）
ALIASES = {
    "ベンチ": "ベンチプレス",
    "bp": "ベンチプレス",
    "インクライン": "インクラインベンチプレス",
    "ダンベルプレス": "ダンベルベンチプレス",
    "デッド": "デッドリフト",
    "dl": "デッドリフト",
    "ベントロウ": "ベントオーバーロウ",
    "ラットプル": "ラットプルダウン",
    "懸垂": "懸垂",
    "チンニング": "懸垂",
    "プルアップ": "懸垂",
    "ローイング": "シーテッドロウ",
    "ショルダー": "ショルダープレス",
    "サイレイ": "サイドレイズ",
    "スクワット": "スクワット",
    "スクワ": "スクワット",
    "rdl": "ルーマニアンデッドリフト",
    "ルーマニアン": "ルーマニアンデッドリフト",
    "ブルガリアン": "ブルガリアンスクワット",
    "レッグエク": "レッグエクステンション",
    "カール": "ダンベルカール",
    "ハンマー": "ハンマーカール",
    "プレスダウン": "トライセプスプレスダウン",
    "プランク": "プランク",
    "腹筋": "クランチ",
    "アブローラー": "アブローラー",
    "腕立て": "腕立て伏せ",
    "腕立": "腕立て伏せ",
    "ディップ": "ディップス",
    "ヒップスラスト": "ヒップスラスト",
}


def _kata_to_hira(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.strip().lower().replace(" ", "").replace("　", "")
    return _kata_to_hira(t)


def _build_table():
    """正規化キー -> 正式名 の検索テーブル。"""
    table = {}
    for name in EXERCISES:
        table[_normalize(name)] = name
    for alias, canonical in ALIASES.items():
        if canonical in EXERCISES:
            table[_normalize(alias)] = canonical
    return table


_TABLE = _build_table()


def list_exercises() -> list:
    return list(EXERCISES.keys())


def get_info(name: str):
    """種目名 -> (部位, 器具)。別名も解決。無ければ None。"""
    if name in EXERCISES:
        return EXERCISES[name]
    canonical = ALIASES.get(name)
    if canonical and canonical in EXERCISES:
        return EXERCISES[canonical]
    return None


def is_dumbbell(name: str) -> bool:
    info = get_info(name)
    return bool(info and info[1] == DUMBBELL)


def search_exercises(query: str, limit: int = 8) -> list:
    """入力文字に近い種目名（正式名）を関連度順に返す（予測変換用）。"""
    q = _normalize(query)
    if not q:
        return []
    scored = {}
    for key, name in _TABLE.items():
        if key == q:
            score = 100
        elif key.startswith(q):
            score = 90
        elif q in key:
            score = 80
        elif key in q:
            score = 70
        else:
            ratio = difflib.SequenceMatcher(None, q, key).ratio()
            score = int(ratio * 60) if ratio >= 0.5 else 0
        if score <= 0:
            continue
        if name not in scored or score > scored[name]:
            scored[name] = score
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], len(kv[0])))
    return [name for name, _ in ranked[:limit]]
