import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="사용자 행동 탐색 대시보드", layout="wide")
st.title("사용자 행동 탐색 대시보드")
st.caption("주별 세션 퍼널 | 플랫폼 · 유입 경로별 | 2025.07 ~ 2026.06")

# ------------------------------------------------------------
# 0. 필요한 데이터만 추출 — 쓸 테이블과 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 처음 한 번만 만듦
# ------------------------------------------------------------
DATA_DIR = "data"                         # 원본 CSV를 넣어 둔 폴더
NEEDED = {                                # 이번 대시보드에 필요한 테이블과 컬럼
    "app_events": ["event_id", "event_datetime", "customer_id", "session_id",
                   "event_name", "platform", "traffic_source"],
}

@st.cache_resource
def get_db():                             # 필요한 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 만듦 (처음 한 번만)
    con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, cols in NEEDED.items():
        pd.read_csv(f"{DATA_DIR}/{name}.csv", usecols=cols).to_sql(name, con, index=False)
    # 5주차 제외 규칙: QA 계정 제외 · 중복 이벤트 제거
    con.execute("""
        CREATE TABLE events AS
        SELECT event_id, event_datetime, customer_id, session_id, event_name, platform, traffic_source
          FROM (SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY session_id, event_datetime, event_name
                                          ORDER BY event_id) AS dup
                  FROM app_events
                 WHERE customer_id NOT LIKE 'QA%')
         WHERE dup = 1
    """)
    # 세션별로 묶는 집계가 빨라지도록 session_id에 인덱스를 붙임 (없으면 첫 실행이 몇 분 걸릴 수 있음)
    con.execute("CREATE INDEX idx_events_session ON events(session_id)")
    return con

# ------------------------------------------------------------
# 1. 데이터 준비 — 정제된 events 테이블을 SQL로 집계
# ------------------------------------------------------------
@st.cache_data
def query(sql):                           # SQL을 실행해 표로 돌려줌
    return pd.read_sql(sql, get_db())

# 주 × 플랫폼 × 유입 경로별 세션 퍼널
SQL_WEEKLY_FUNNEL = """
WITH s AS (                                 -- 세션의 첫 이벤트로 플랫폼 · 유입 경로 · 주 정하기
    SELECT session_id, platform, traffic_source,
           DATE(MIN(event_datetime), 'weekday 0', '-6 days') AS 주시작일
      FROM events
     GROUP BY session_id
)
SELECT s.주시작일,
       s.platform         AS 플랫폼,
       s.traffic_source AS 유입경로,
       COUNT(DISTINCT e.session_id)                                                                                                 AS 세션수,
       COUNT(DISTINCT CASE WHEN e.event_name = 'view_restaurant' THEN e.session_id END)   AS 조회세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'add_to_cart'     THEN e.session_id END)   AS 장바구니세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'begin_checkout'  THEN e.session_id END)   AS 결제시작세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'order_complete'  THEN e.session_id END)   AS 주문세션,
       SUM(CASE WHEN e.event_name = 'payment_fail' THEN 1 ELSE 0 END)                     AS 결제실패
  FROM events e
  JOIN s ON e.session_id = s.session_id
 WHERE s.주시작일 < '2026-06-29'            -- 이틀치뿐인 마지막 주 제외
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3
"""

@st.cache_data
def load_data():
    data = query(SQL_WEEKLY_FUNNEL)
    data["주시작일"] = pd.to_datetime(data["주시작일"]).dt.date
    return data

df = load_data()                        # 주 × 플랫폼 × 유입 경로별 세션 퍼널

# ------------------------------------------------------------
# 사이드바 필터
# ------------------------------------------------------------
st.sidebar.header("필터")

weeks = sorted(df["주시작일"].unique())
selected_period = st.sidebar.select_slider(
    "기간",
    options=weeks,
    value=(weeks[0], weeks[-1])
)

platforms = sorted(df["플랫폼"].unique())
selected_platforms = st.sidebar.multiselect(
    "플랫폼",
    options=platforms,
    default=platforms
)

traffic_sources = sorted(df["유입경로"].unique())
selected_traffic_sources = st.sidebar.multiselect(
    "유입 경로",
    options=traffic_sources,
    default=traffic_sources
)

# 평소 범위 기준 기간 슬라이더 추가
default_baseline_end_idx = min(25, len(weeks) - 1)
selected_baseline_period = st.sidebar.select_slider(
    "평소 범위 기준 기간",
    options=weeks,
    value=(weeks[0], weeks[default_baseline_end_idx]),
    help="문제가 없던 기간을 고르세요. 이 기간의 주별 값 범위를 '평소 범위'로 씁니다."
)

# 집단 조건(플랫폼·유입경로)만 적용한 데이터 g
g = df[
    (df["플랫폼"].isin(selected_platforms)) &
    (df["유입경로"].isin(selected_traffic_sources))
]

# 기존 f는 g에 기간 조건을 더해 만듦
f = g[
    (g["주시작일"] >= selected_period[0]) &
    (g["주시작일"] <= selected_period[1])
]

if f.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다. 필터를 바꿔 주세요.")
    st.stop()

# ------------------------------------------------------------
# 2. KPI 카드
# ------------------------------------------------------------
def rate(a, b):
    return a / b * 100 if b else 0

t = f[["세션수", "결제시작세션", "주문세션"]].sum()
c1, c2, c3 = st.columns(3)
c1.metric("세션 수", f"{t['세션수']:,}개")
c2.metric("주문 전환율 (방문 → 주문)", f"{rate(t['주문세션'], t['세션수']):.1f}%")
c3.metric("결제 전환율 (결제 시작 → 주문)", f"{rate(t['주문세션'], t['결제시작세션']):.1f}%")

st.divider()

# ------------------------------------------------------------
# 3. 차트
# ------------------------------------------------------------
left, right = st.columns(2)

# 3-1. 주별 결제 전환율 (플랫폼별)
wp = f.groupby(["주시작일", "플랫폼"])[["결제시작세션", "주문세션"]].sum().reset_index()
wp["결제전환율"] = (wp["주문세션"] / wp["결제시작세션"] * 100).round(1)
fig1 = px.line(wp, x="주시작일", y="결제전환율", color="플랫폼", markers=True,
               title="주별 결제 전환율 (플랫폼별)")
fig1.update_layout(yaxis_title="결제 전환율 (%)", xaxis_title="")
left.plotly_chart(fig1, width="stretch")

# 3-2. 세션 퍼널
steps = {"1.방문": "세션수", "2.식당조회": "조회세션", "3.장바구니": "장바구니세션",
         "4.결제시작": "결제시작세션", "5.주문완료": "주문세션"}
fun = pd.DataFrame({"단계": list(steps), "세션수": [f[c].sum() for c in steps.values()]})
fig2 = px.funnel(fun, x="세션수", y="단계", title="세션 퍼널")
right.plotly_chart(fig2, width="stretch")

# 3-3. 유입 경로별 주문 전환율
ws = f.groupby("유입경로")[["세션수", "주문세션"]].sum().reset_index()
ws["주문전환율"] = (ws["주문세션"] / ws["세션수"] * 100).round(1)
ws = ws.sort_values("주문전환율")
fig3 = px.bar(ws, x="주문전환율", y="유입경로", orientation="h", text_auto=".1f",
              hover_data=["세션수"], title="유입 경로별 주문 전환율")
fig3.update_xaxes(range=[0, ws["주문전환율"].max() * 1.2] if not ws.empty and ws["주문전환율"].max() > 0 else [0, 100])
fig3.update_layout(xaxis_title="주문 전환율 (%)", yaxis_title="")
st.plotly_chart(fig3, width="stretch")

st.divider()

# ------------------------------------------------------------
# 4. 집단 비교 영역
# ------------------------------------------------------------
st.header("집단 비교")
compare_by = st.radio("비교 기준", ["플랫폼", "유입경로"], horizontal=True)
col_name = "플랫폼" if compare_by == "플랫폼" else "유입경로"

funnel_cols = ["세션수", "조회세션", "장바구니세션", "결제시작세션", "주문세션"]
grouped = f.groupby(col_name)[funnel_cols].sum().reset_index()

if (grouped["세션수"] < 500).any():
    st.caption("⚠️ 세션 수가 500개 미만인 집단이 있어 값이 크게 흔들릴 수 있습니다.")

# 누적 전환율 데이터 생성 (첫 단계 대비 %)
cum_list = []
for _, row in grouped.iterrows():
    base = row["세션수"]
    for step_name, col in {"1.방문": "세션수", "2.식당조회": "조회세션", "3.장바구니": "장바구니세션", "4.결제시작": "결제시작세션", "5.주문완료": "주문세션"}.items():
        val = row[col]
        pct = (val / base * 100) if base > 0 else 0
        cum_list.append({
            col_name: row[col_name],
            "단계": step_name,
            "누적전환율": round(pct, 1),
            "세션수": val
        })
df_cum = pd.DataFrame(cum_list)

# 단계 전환율 데이터 생성 (직전 단계 대비 %)
step_list = []
for _, row in grouped.iterrows():
    s_vis = row["세션수"]
    s_view = row["조회세션"]
    s_cart = row["장바구니세션"]
    s_chk = row["결제시작세션"]
    s_ord = row["주문세션"]
    
    transitions = [
        ("방문 → 조회", s_view, s_vis),
        ("조회 → 장바구니", s_cart, s_view),
        ("장바구니 → 결제시작", s_chk, s_cart),
        ("결제시작 → 주문", s_ord, s_chk)
    ]
    
    for step_name, curr, prev in transitions:
        rate_val = (curr / prev * 100) if prev > 0 else 0
        step_list.append({
            col_name: row[col_name],
            "단계전환": step_name,
            "단계전환율": round(rate_val, 1),
            "기준세션": prev
        })
df_step = pd.DataFrame(step_list)

left_comp, right_comp = st.columns(2)

# 왼쪽: 누적 전환율 퍼널 차트
fig_cum = px.funnel(df_cum, x="누적전환율", y="단계", color=col_name,
                    title="누적 전환율 퍼널 (첫 단계 대비 %)", hover_data=["세션수"])
fig_cum.update_layout(xaxis_title="누적 전환율 (%)", yaxis_title="")
left_comp.plotly_chart(fig_cum, width="stretch")

# 오른쪽: 단계 전환율 막대 차트 (barmode="group")
fig_step = px.bar(df_step, x="단계전환", y="단계전환율", color=col_name, barmode="group",
                  text="단계전환율", hover_data=["기준세션"], title="단계 전환율 (직전 단계 대비 %)")
fig_step.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
fig_step.update_layout(yaxis_title="단계 전환율 (%)", xaxis_title="")
right_comp.plotly_chart(fig_step, width="stretch")

st.divider()

# ------------------------------------------------------------
# 5. 드릴다운: 언제부터, 무엇 때문일까 영역
# ------------------------------------------------------------
st.header("드릴다운: 언제부터, 무엇 때문일까")

available_groups = sorted(f[col_name].unique())
drill_col1, drill_col2 = st.columns(2)
with drill_col1:
    selected_group = st.selectbox("자세히 볼 집단", available_groups)
with drill_col2:
    selected_step_label = st.selectbox("단계", [
        "방문 → 식당조회",
        "식당조회 → 장바구니",
        "장바구니 → 결제시작",
        "결제시작 → 주문"
    ])

step_mapping_pairs = {
    "방문 → 식당조회": ("세션수", "조회세션"),
    "식당조회 → 장바구니": ("조회세션", "장바구니세션"),
    "장바구니 → 결제시작": ("장바구니세션", "결제시작세션"),
    "결제시작 → 주문": ("결제시작세션", "주문세션")
}
prev_col, curr_col = step_mapping_pairs[selected_step_label]
other_col = "유입경로" if col_name == "플랫폼" else "플랫폼"

# 차트 ① 데이터 준비
df_drill = f[f[col_name] == selected_group].copy()
weekly_drill = df_drill.groupby(["주시작일", other_col])[[prev_col, curr_col]].sum().reset_index()

weekly_drill["전환율"] = weekly_drill.apply(
    lambda r: (r[curr_col] / r[prev_col] * 100) if r[prev_col] > 0 else None,
    axis=1
)

fig_drill_1 = px.line(
    weekly_drill,
    x="주시작일",
    y="전환율",
    color=other_col,
    markers=True,
    title=f"① {selected_group}의 주별 {selected_step_label} 전환율 — {other_col}별로 쪼개 보기"
)
fig_drill_1.update_layout(yaxis_title="전환율 (%)", xaxis_title="")
st.plotly_chart(fig_drill_1, width="stretch")
st.caption("모든 갈래가 같은 시점에 함께 움직였다면, 그 축은 원인이 아닙니다.")

# 차트 ② 데이터 준비
df_fail = f.copy()
df_fail["분류"] = df_fail[col_name].apply(lambda x: selected_group if x == selected_group else "그 외")
weekly_fail = df_fail.groupby(["주시작일", "분류"])["결제실패"].sum().reset_index()

color_map = {selected_group: "darkred", "그 외": "lightgray"}

fig_drill_2 = px.bar(
    weekly_fail,
    x="주시작일",
    y="결제실패",
    color="분류",
    barmode="group",
    color_discrete_map=color_map,
    title=f"주별 결제실패 건수 ({selected_group} vs 그 외)"
)
fig_drill_2.update_layout(yaxis_title="결제실패 건수", xaxis_title="")
st.plotly_chart(fig_drill_2, width="stretch")
st.caption("문제가 생긴 시점과 함께 움직였다면 원인 후보입니다. 함께 움직였다고 원인이 확정되지는 않습니다.")