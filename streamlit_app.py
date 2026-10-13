import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="사용자 행동 탐색 대시보드", layout="wide")
st.title("사용자 행동 탐색 대시보드")
st.caption("주별 세션 퍼널 | 플랫폼 · 유입 경로별 | 2025.07 ~ 2026.06")

AI_NOTES = {
    "전체": "전체 28840개 세션 중 주문 전환율은 14.5%, 결제 전환율은 80.5%이며 가장 낮은 단계는 41.4%인 장바구니 단계였다. 전체적인 이탈은 장바구니 단계에서 가장 크게 발생하는 것으로 보인다.",
    "Android": "안드로이드 16053개 세션의 주문 전환율은 14.3%, 결제 전환율은 76.8%였으며 2026-04-13 주부터 2026-05-25 주까지 결제 전환율이 크게 낮아지며 결제실패가 집중되었다. 이 시기 안드로이드 플랫폼의 결제 과정에 기술적 장애나 문제가 있었는지 확인이 필요하다.",
    "iOS": "아이오닉(iOS) 또는 iOS 12787개 세션의 주문 전환율은 14.8%, 결제 전환율은 85.5%로 안드로이드보다 높았고 장바구니 전환율은 40.8%였다. 안드로이드와 달리 4~5월에 특별한 결제 전환율 하락 없이 안정적인 흐름을 유지한 것으로 보인다.",
    "organic": "오가닉(organic) 유입은 22489개 세션으로 전체의 다수를 차지하며 주문 전환율 16.0%, 결제 전환율 80.4%, 장바구니 전환율 41.4%를 기록했다. 전체 평균과 유사한 자연 유입 패턴을 보이는 것으로 보인다.",
    "paid_ad": "유료 광고(paid_ad)는 1595개 세션으로 500개를 초과하며 주문 전환율 26.3%, 결제 전환율 90.3%, 장바구니 전환율 53.7%로 다른 경로보다 효율이 높았다. 광고를 통해 유입된 사용자의 구매 의도가 상대적으로 더 뚜렷했던 것으로 보인다.",
    "push": "푸시(push) 유입은 4635개 세션이며 2026-02-02 주에 처음 나타났고 주문 전환율 3.2%, 가장 낮은 조회 전환율은 28.4%였다. 푸시를 통해 유입된 사용자의 초기 관심도와 참여율이 상대적으로 낮았던 것으로 보인다.",
    "referral": "레퍼럴(referral) 유입은 세션 수가 121개로 500개 미만이며 주문 전환율과 결제 전환율 모두 0.0%, 최저 전환율은 0.0%인 주문 단계였다. 표본 크기가 너무 작아 해당 경로의 효과를 단정하기 어렵추가적인 데이터 확인이 필요하다."
}

AI_SOURCE = "bot: Gemini가 미리 만든 해설 · 전체 기간 기준"

# ------------------------------------------------------------
# 0. 필요한 데이터만 추출 — 쓸 테이블과 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 처음 한 번만 만듦
# ------------------------------------------------------------
DATA_DIR = "data"                        # 원본 CSV를 넣어 둔 폴더
NEEDED = {                                # 이번 대시보드에 필요한 테이블과 컬럼
    "app_events": ["event_id", "event_datetime", "customer_id", "session_id",
                   "event_name", "platform", "traffic_source"],
}

@st.cache_resource
def get_db():                            # 필요한 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 만듦 (처음 한 번만)
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
def query(sql):                         # SQL을 실행해 표로 돌려줌
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
       COUNT(DISTINCT e.session_id)                                                                                                                                                                                                                           AS 세션수,
       COUNT(DISTINCT CASE WHEN e.event_name = 'view_restaurant' THEN e.session_id END)   AS 조회세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'add_to_cart'     THEN e.session_id END)   AS 장바구니세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'begin_checkout'  THEN e.session_id END)   AS 결제시작세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'order_complete'  THEN e.session_id END)   AS 주문세션,
       SUM(CASE WHEN e.event_name = 'payment_fail' THEN 1 ELSE 0 END)                     AS 결제실패
  FROM events e
  JOIN s ON e.session_id = s.session_id
 WHERE s.주시작일 < '2026-06-29'           -- 이틀치뿐인 마지막 주 제외
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

# ------------------------------------------------------------
# 사이드바 데이터 다운로드 버튼 추가
# ------------------------------------------------------------
st.sidebar.html("<div style='margin-top: 30px;'></div>")
st.sidebar.subheader("데이터 다운로드")
download_col1, download_col2 = st.sidebar.columns(2)

with download_col1:
    st.download_button(
        label="전체 다운로드",
        data=df.to_csv(index=False, encoding="utf-8-sig"),
        file_name="전체_데이터.csv",
        mime="text/csv",
        width="stretch"
    )

with download_col2:
    st.download_button(
        label="부분 다운로드",
        data=f.to_csv(index=False, encoding="utf-8-sig"),
        file_name="필터적용_데이터.csv",
        mime="text/csv",
        width="stretch"
    )

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

# ------------------------------------------------------------
# 규칙 기반 설명 문장 (st.info)
# ------------------------------------------------------------
def generate_rule_explanation(g_data, f_data, baseline_period):
    # 1. 선택된 기간 검증 (마지막 4주 계산을 위해 최소 4주 필요)
    f_sorted = f_data.sort_values("주시작일")
    f_weeks = f_sorted["주시작일"].unique()
    if len(f_weeks) < 4:
        return "주문 전환율: 비교하려면 선택 기간을 4주 이상 골라 주세요", "결제 전환율: 비교하려면 선택 기간을 4주 이상 골라 주세요"
    
    # 최근 4주 데이터
    recent_4w_dates = f_weeks[-4:]
    recent_df = f_sorted[f_sorted["주시작일"].isin(recent_4w_dates)]
    recent_sums = recent_df[["세션수", "결제시작세션", "주문세션"]].sum()
    
    recent_order_rate = rate(recent_sums["주문세션"], recent_sums["세션수"])
    recent_checkout_rate = rate(recent_sums["주문세션"], recent_sums["결제시작세션"])
    
    start_week_str = str(recent_4w_dates[0])
    period_str = f"{start_week_str}부터 4주"
    
    # 2. 기준 기간 데이터 준비 및 검증
    base_df = g_data[
        (g_data["주시작일"] >= baseline_period[0]) &
        (g_data["주시작일"] <= baseline_period[1])
    ]
    
    # 주별로 합산 후 전환율 계산 (분모가 0인 주는 제외)
    base_weekly = base_df.groupby("주시작일")[["세션수", "결제시작세션", "주문세션"]].sum().reset_index()
    
    # 주문 전환율 주별 시리즈
    order_rates = []
    checkout_rates = []
    for _, row in base_weekly.iterrows():
        if row["세션수"] > 0:
            order_rates.append(row["주문세션"] / row["세션수"] * 100)
        if row["결제시작세션"] > 0:
            checkout_rates.append(row["주문세션"] / row["결제시작세션"] * 100)
            
    if len(order_rates) < 4 or len(checkout_rates) < 4:
        msg = "기준 기간을 이 집단의 데이터가 있는 시기로 옮겨 주세요"
        return f"주문 전환율: {msg}", f"결제 전환율: {msg}"
        
    order_min, order_max = min(order_rates), max(order_rates)
    checkout_min, checkout_max = min(checkout_rates), max(checkout_rates)
    
    # 문장 생성 함수
    def build_sentence(metric_name, recent_val, p_min, p_max):
        if recent_val < p_min:
            diff = p_min - recent_val
            return f"{metric_name}은 {period_str} 동안 {recent_val:.1f}%로, 평소 범위({p_min:.1f}% ~ {p_max:.1f}%)보다 {diff:.1f}%p 낮습니다."
        elif recent_val > p_max:
            diff = recent_val - p_max
            return f"{metric_name}은 {period_str} 동안 {recent_val:.1f}%로, 평소 범위({p_min:.1f}% ~ {p_max:.1f}%)보다 {diff:.1f}%p 높습니다."
        else:
            return f"{metric_name}은 {period_str} 동안 {recent_val:.1f}%로, 평소 범위({p_min:.1f}% ~ {p_max:.1f}%) 안에 있습니다."

    order_msg = build_sentence("주문 전환율", recent_order_rate, order_min, order_max)
    checkout_msg = build_sentence("결제 전환율", recent_checkout_rate, checkout_min, checkout_max)
    
    return order_msg, checkout_msg

ord_text, chk_text = generate_rule_explanation(g, f, selected_baseline_period)
with st.container(border=True):
    st.markdown("**📏 지금 숫자 읽기**")
    st.markdown(f"- {ord_text}")
    st.markdown(f"- {chk_text}")
    st.caption(f"📏 자동 계산 · 평소 범위 기준 기간 {selected_baseline_period[0]} ~ {selected_baseline_period[1]} (주별 값)")
    
    with st.expander("🤖 AI 해설 · 전체", expanded=False):
        st.write(AI_NOTES["전체"])
    st.caption(AI_SOURCE)

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

with st.expander(f"🤖 AI 해설 · {selected_group}", expanded=False):
    note_text = AI_NOTES.get(selected_group, "이 집단의 해설은 아직 없습니다.")
    st.write(note_text)
st.caption(AI_SOURCE)