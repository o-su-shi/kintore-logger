"""
筋トレ記録アプリ
- Python / Streamlit
- データ保存: ローカルは SQLite、クラウドは Postgres を自動切り替え（SQLAlchemy）
- 種目を予測変換で選択 → 重量・回数を最大5セット記録 → 推移（最大重量・推定1RM）を観察
- ダンベル種目は「片方の重量」を入力
"""

import datetime
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
)

from streamlit_searchbox import st_searchbox

from exercises import search_exercises, get_info, is_dumbbell, DUMBBELL

DB_PATH = Path(__file__).parent / "workouts.db"
MAX_SETS = 5

# --- テーブル定義（1行＝1セット） ---
metadata = MetaData()
sets_t = Table(
    "sets", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("date", String, nullable=False),
    Column("ts", String, nullable=False),        # 同じ記録操作をまとめるキー
    Column("exercise", String, nullable=False),
    Column("equipment", String, nullable=False),
    Column("set_no", Integer, nullable=False),
    Column("weight", Float, nullable=False),      # ダンベルは片方の重量
    Column("reps", Integer, nullable=False),
)


# ----------------------------------------------------------------------------
# データベース
# ----------------------------------------------------------------------------
def _database_url() -> str:
    url = None
    try:
        url = st.secrets.get("DATABASE_URL")
    except Exception:
        url = None
    url = url or os.environ.get("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        return url
    return f"sqlite:///{DB_PATH}"


@st.cache_resource
def get_engine():
    return create_engine(_database_url(), pool_pre_ping=True)


def init_db() -> None:
    metadata.create_all(get_engine())


def add_workout(date, exercise, equipment, sets) -> None:
    """sets: [(set_no, weight, reps), ...] を1回の操作としてまとめて記録。"""
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with get_engine().begin() as conn:
        for set_no, weight, reps in sets:
            conn.execute(
                insert(sets_t).values(
                    date=str(date), ts=ts, exercise=exercise,
                    equipment=equipment, set_no=set_no,
                    weight=weight, reps=reps,
                )
            )


def delete_workout(ts: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(delete(sets_t).where(sets_t.c.ts == ts))


def fetch_sets(date=None, exercise=None) -> pd.DataFrame:
    stmt = select(sets_t)
    if date is not None:
        stmt = stmt.where(sets_t.c.date == str(date))
    if exercise is not None:
        stmt = stmt.where(sets_t.c.exercise == exercise)
    stmt = stmt.order_by(sets_t.c.date.desc(), sets_t.c.ts.desc(), sets_t.c.set_no)
    with get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


# ----------------------------------------------------------------------------
# ヘルパー
# ----------------------------------------------------------------------------
def flash(message: str, icon: str = "✅") -> None:
    st.session_state["_flash"] = (message, icon)


def show_flash() -> None:
    data = st.session_state.pop("_flash", None)
    if data:
        st.toast(data[0], icon=data[1])


def epley_1rm(weight: float, reps: int) -> float:
    """エプリー式の推定1RM。reps=1なら weight そのもの。"""
    if reps <= 1:
        return weight
    return weight * (1 + reps / 30)


def _exercise_search(query: str):
    q = (query or "").strip()
    if not q:
        return []
    return [(name, name) for name in search_exercises(q, 8)]


# ----------------------------------------------------------------------------
# 画面
# ----------------------------------------------------------------------------
def page_record() -> None:
    st.markdown("##### 🏋️ 種目を選ぶ")
    st.caption("種目名を入力すると候補が出ます（漢字・ひらがな・カタカナ・略語OK）")

    selected = st_searchbox(
        _exercise_search,
        placeholder="例：ベンチ / スクワット / だんべるかーる",
        key="ex_search",
        rerun_on_update=True,
    )
    if selected is not None and st.session_state.get("_picked") != selected:
        st.session_state["_picked"] = selected
        st.rerun()

    exercise = st.session_state.get("_picked")
    if not exercise:
        st.info("まず種目を選んでください。")
        return

    part, equip = get_info(exercise) or ("", "")
    dumbbell = equip == DUMBBELL
    st.markdown(f"### {exercise}")
    badge = f"📍{part}　🛠️{equip}"
    if dumbbell:
        badge += "　⚠️重量は**片方**を入力"
    st.caption(badge)

    date = st.date_input("日付", value=datetime.date.today())

    weight_label = "重量(片方 kg)" if dumbbell else "重量(kg)"
    st.markdown(f"##### セット入力（最大{MAX_SETS}・やった分だけでOK）")

    with st.form("set_form", clear_on_submit=False):
        rows = []
        # 見出し
        h1, h2, h3 = st.columns([1, 2, 2])
        h1.caption("セット")
        h2.caption(weight_label)
        h3.caption("回数(reps)")
        for i in range(1, MAX_SETS + 1):
            c1, c2, c3 = st.columns([1, 2, 2])
            c1.markdown(f"**{i}**")
            w = c2.number_input(
                f"w{i}", min_value=0.0, max_value=500.0, step=1.0,
                value=0.0, label_visibility="collapsed", key=f"w{i}",
            )
            r = c3.number_input(
                f"r{i}", min_value=0, max_value=100, step=1,
                value=0, label_visibility="collapsed", key=f"r{i}",
            )
            rows.append((i, w, r))

        submitted = st.form_submit_button(
            "✅ 記録する", use_container_width=True, type="primary"
        )
        if submitted:
            valid = [(n, w, r) for (n, w, r) in rows if r > 0]
            if not valid:
                st.error("少なくとも1セット、回数を入力してください。")
            else:
                add_workout(date, exercise, equip, valid)
                flash(f"🏋️ {exercise} を{len(valid)}セット記録！")
                for i in range(1, MAX_SETS + 1):
                    st.session_state.pop(f"w{i}", None)
                    st.session_state.pop(f"r{i}", None)
                st.rerun()

    # 今日の同種目の記録を表示
    today_df = fetch_sets(date=date, exercise=exercise)
    if not today_df.empty:
        st.divider()
        st.markdown("##### 📋 この日の記録")
        for ts, g in today_df.groupby("ts", sort=False):
            sets_txt = "　".join(
                f"{int(row.set_no)}set: {row.weight:g}kg×{int(row.reps)}"
                for row in g.itertuples()
            )
            st.write(f"・{sets_txt}")


def page_progress() -> None:
    st.subheader("📈 推移")
    all_df = fetch_sets()
    if all_df.empty:
        st.info("まだ記録がありません。")
        return

    exs = sorted(all_df["exercise"].unique().tolist())
    ex = st.selectbox("種目を選択", exs)
    df = all_df[all_df["exercise"] == ex].copy()
    dumbbell = is_dumbbell(ex)

    # 推定1RM
    df["e1rm"] = df.apply(lambda r: epley_1rm(r["weight"], int(r["reps"])), axis=1)
    daily = (
        df.groupby("date")
        .agg(最大重量=("weight", "max"), 推定1RM=("e1rm", "max"))
        .reset_index()
        .sort_values("date")
    )
    daily["推定1RM"] = daily["推定1RM"].round(1)

    unit = "kg（片方）" if dumbbell else "kg"
    c1, c2, c3 = st.columns(3)
    c1.metric("記録日数", f"{len(daily)}日")
    c2.metric("自己最高重量", f"{daily['最大重量'].max():g}")
    c3.metric("推定1RM最高", f"{daily['推定1RM'].max():g}")
    if dumbbell:
        st.caption("※ダンベル種目のため重量は「片方」表示です")

    base = alt.Chart(daily).encode(x=alt.X("date:O", title=None))
    line_1rm = base.mark_line(point=True, color="#e4572e").encode(
        y=alt.Y("推定1RM:Q", title=unit), tooltip=["date", "推定1RM"]
    )
    line_max = base.mark_line(point=True, color="#1f77b4", strokeDash=[4, 3]).encode(
        y="最大重量:Q", tooltip=["date", "最大重量"]
    )
    st.altair_chart((line_1rm + line_max).properties(height=300),
                    use_container_width=True)
    st.caption("🔴実線＝推定1RM　🔵破線＝その日の最大重量")


def page_history() -> None:
    st.subheader("📅 履歴")
    df = fetch_sets()
    if df.empty:
        st.info("まだ記録がありません。")
        return
    for date in df["date"].unique().tolist():
        day = df[df["date"] == date]
        n_ex = day["exercise"].nunique()
        with st.expander(f"{date}　（{n_ex}種目）"):
            for ts, g in day.groupby("ts", sort=False):
                ex = g.iloc[0]["exercise"]
                dumb = g.iloc[0]["equipment"] == DUMBBELL
                sets_txt = " / ".join(
                    f"{row.weight:g}kg×{int(row.reps)}" for row in g.itertuples()
                )
                cols = st.columns([5, 1])
                tag = "（片方）" if dumb else ""
                cols[0].write(f"**{ex}**{tag}　{sets_txt}")
                if cols[1].button("🗑️", key=f"del_{ts}"):
                    delete_workout(ts)
                    st.rerun()


# ----------------------------------------------------------------------------
# メイン
# ----------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="筋トレ記録",
        page_icon="🏋️",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    init_db()
    show_flash()

    st.title("🏋️ 筋トレ記録")
    tab_rec, tab_prog, tab_hist = st.tabs(["記録", "推移", "履歴"])
    with tab_rec:
        page_record()
    with tab_prog:
        page_progress()
    with tab_hist:
        page_history()


if __name__ == "__main__":
    main()
