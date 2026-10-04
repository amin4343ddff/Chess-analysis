import io
import base64
import shutil
import requests
import chess
import chess.pgn
import chess.svg
import chess.engine
import streamlit as st

st.set_page_config(page_title="Chess Analyzer", page_icon="♟️")

CHESS_COM_BASE_URL = "https://api.chess.com/pub"
HEADERS = {"User-Agent": "ChessAnalyzer/1.0 (Streamlit app)"}
STOCKFISH_PATH = shutil.which("stockfish") or "/usr/games/stockfish"

MATE_SCORE = 10000
CLAMP = 1000

DRAW_RESULTS = {"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"}
DEPTHS = {"سريع": 0.1, "متوسط": 0.2, "عميق": 0.4}

CATEGORY_AR = {
    "best": "⭐ أفضل نقلة",
    "good": "✅ نقلة جيدة",
    "inaccuracy": "⚠️ نقلة غير دقيقة",
    "mistake": "❓ خطأ",
    "blunder": "❌ خطأ فادح",
}


def clean(h):
    return " ".join(line.strip() for line in h.splitlines())


# ---------- جلب المباراة ----------
def get_latest_game(username):
    username = username.strip().lower()
    if not username:
        raise ValueError("يرجى إدخال اسم مستخدم Chess.com.")

    r = requests.get(f"{CHESS_COM_BASE_URL}/player/{username}", headers=HEADERS, timeout=15)
    if r.status_code == 404:
        raise ValueError("لم يتم العثور على هذا الحساب في Chess.com.")
    r.raise_for_status()

    r = requests.get(f"{CHESS_COM_BASE_URL}/player/{username}/games/archives", headers=HEADERS, timeout=15)
    r.raise_for_status()
    archives = r.json().get("archives", [])
    if not archives:
        raise ValueError("هذا الحساب لا يحتوي على مباريات متاحة.")

    for month_url in reversed(archives):
        g = requests.get(month_url, headers=HEADERS, timeout=15)
        g.raise_for_status()
        for game in reversed(g.json().get("games", [])):
            if game.get("pgn"):
                return username, game

    raise ValueError("لم يتم العثور على أي مباراة لهذا الحساب.")


# ---------- التحليل ----------
def clamp(v):
    return max(-CLAMP, min(CLAMP, v))


def classify(played_uci, best_uci, loss):
    if best_uci and played_uci == best_uci:
        return "best"
    if loss <= 30:
        return "good"
    if loss <= 80:
        return "inaccuracy"
    if loss <= 200:
        return "mistake"
    return "blunder"


def eval_text(cp):
    if abs(cp) >= MATE_SCORE - 500:
        n = MATE_SCORE - abs(cp)
        if n == 0:
            return "كش مات"
        return f"مات في {n} " + ("للأبيض" if cp > 0 else "للأسود")
    return f"{cp / 100:+.2f}"


def analyze_game(pgn_text, think_time, progress):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("تعذر قراءة PGN لهذه المباراة.")

    moves = list(game.mainline_moves())
    board = game.board()
    records, cps = [], []
    total = len(moves) + 1

    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        for i in range(total):
            if board.is_game_over():
                if board.is_checkmate():
                    cp = -MATE_SCORE if board.turn == chess.WHITE else MATE_SCORE
                else:
                    cp = 0
                best = None
            else:
                info = engine.analyse(board, chess.engine.Limit(time=think_time))
                cp = info["score"].white().score(mate_score=MATE_SCORE)
                pv = info.get("pv")
                best = pv[0] if pv else None
            cps.append(cp)

            if i < len(moves):
                mv = moves[i]
                records.append({
                    "fen": board.fen(),
                    "uci": mv.uci(),
                    "san": board.san(mv),
                    "mover": board.turn,
                    "fullmove": board.fullmove_number,
                    "best_uci": best.uci() if best else None,
                    "best_san": board.san(best) if best else None,
                })
                board.push(mv)

            progress((i + 1) / total, f"تحليل {i + 1} من {total}")

    for i, r in enumerate(records):
        sign = 1 if r["mover"] == chess.WHITE else -1
        r["loss"] = max(0, clamp(sign * cps[i]) - clamp(sign * cps[i + 1]))
        r["cp_before"] = cps[i]
        r["cp_after"] = cps[i + 1]
        r["category"] = classify(r["uci"], r["best_uci"], r["loss"])

    return records


# ---------- العرض ----------
def board_html(records, idx, user_color):
    r = records[idx]
    board = chess.Board(r["fen"])

    arrows = []
    if r["best_uci"]:
        m = chess.Move.from_uci(r["best_uci"])
        arrows.append(chess.svg.Arrow(m.from_square, m.to_square, color="#15781Bcc"))
    if r["category"] in ("inaccuracy", "mistake", "blunder"):
        m = chess.Move.from_uci(r["uci"])
        arrows.append(chess.svg.Arrow(m.from_square, m.to_square, color="#cc0000cc"))

    lastmove = chess.Move.from_uci(records[idx - 1]["uci"]) if idx > 0 else None
    check = board.king(board.turn) if board.is_check() else None

    svg = chess.svg.board(board, orientation=user_color, arrows=arrows,
                          lastmove=lastmove, check=check, size=480)
    b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")

    who = "نقلتك" if r["mover"] == user_color else "نقلة الخصم"
    num = f'{r["fullmove"]}.' if r["mover"] == chess.WHITE else f'{r["fullmove"]}...'

    if r["category"] == "best":
        explain = "هذه نفس نقلة المحرك الأفضل (السهم الأخضر)."
    else:
        explain = (f'النقلة الأفضل: <b dir="ltr">{r["best_san"]}</b> (السهم الأخضر). '
                   f'النقلة التي لُعبت خسّرت حوالي <b>{r["loss"] / 100:.1f}</b> بيدق')
        explain += " (السهم الأحمر)." if r["category"] in ("inaccuracy", "mistake", "blunder") else "."

    return f"""
    <div style="max-width:480px;margin:auto;">
      <img src="data:image/svg+xml;base64,{b64}" style="width:100%;">
    </div>
    <div dir="rtl" style="font-size:16px;line-height:1.9;margin-top:10px;">
      <b>{who}:</b> <span dir="ltr"><b>{num} {r["san"]}</b></span> — {CATEGORY_AR[r["category"]]}<br>
      {explain}<br>
      التقييم قبل النقلة: <span dir="ltr">{eval_text(r["cp_before"])}</span>
      | بعدها: <span dir="ltr">{eval_text(r["cp_after"])}</span>
      <span style="opacity:.6">(موجب = أفضل للأبيض)</span>
    </div>"""


def summary_html(records, user_color):
    mine = [r for r in records if r["mover"] == user_color]
    counts = {k: 0 for k in CATEGORY_AR}
    for r in mine:
        counts[r["category"]] += 1
    avg = sum(r["loss"] for r in mine) / max(1, len(mine))
    rows = "".join(
        f"<tr><td>{CATEGORY_AR[k]}</td><td style='padding:0 14px'><b>{counts[k]}</b></td></tr>"
        for k in CATEGORY_AR)
    return f"""<div dir="rtl">
      <h4>📊 ملخص أدائك ({len(mine)} نقلة)</h4>
      <table>{rows}</table>
      <p>متوسط الخسارة لكل نقلة: <b>{avg / 100:.2f}</b> بيدق</p>
      <p>🟢 السهم الأخضر = أفضل نقلة &nbsp; 🔴 السهم الأحمر = النقلة التي لعبتها (إذا كانت سيئة)</p>
    </div>"""


# ---------- أزرار التنقل ----------
def go_prev():
    st.session_state.idx = max(0, st.session_state.idx - 1)


def go_next():
    n = len(st.session_state.data["records"])
    st.session_state.idx = min(n - 1, st.session_state.idx + 1)


def go_mistake():
    d = st.session_state.data
    for i in range(st.session_state.idx + 1, len(d["records"])):
        r = d["records"][i]
        if r["mover"] == d["user_color"] and r["category"] in ("mistake", "blunder"):
            st.session_state.idx = i
            return
    st.toast("لا يوجد خطأ آخر لك بعد هذه النقلة.")


def go_worst():
    d = st.session_state.data
    mine = [(r["loss"], i) for i, r in enumerate(d["records"]) if r["mover"] == d["user_color"]]
    if mine:
        st.session_state.idx = max(mine)[1]


# ---------- الواجهة ----------
if "data" not in st.session_state:
    st.session_state.data = None
if "idx" not in st.session_state:
    st.session_state.idx = 0

st.markdown("<h1 style='text-align:center'>♟️ Chess Analyzer</h1>"
            "<p dir='rtl' style='text-align:center'>اكتب اسمك في Chess.com ليحلل التطبيق آخر مباراة لك</p>",
            unsafe_allow_html=True)

username = st.text_input("اسم المستخدم في Chess.com", placeholder="مثال: hikaru")
depth_label = st.selectbox("دقة التحليل", list(DEPTHS.keys()), index=1)

if st.button("🔍 جلب وتحليل آخر مباراة", type="primary", use_container_width=True):
    bar = st.progress(0, text="جاري جلب المباراة...")
    try:
        uname, game = get_latest_game(username)

        w, b = game.get("white", {}), game.get("black", {})
        if w.get("username", "").lower() == uname:
            user_color, user_result = chess.WHITE, w.get("result", "")
        else:
            user_color, user_result = chess.BLACK, b.get("result", "")

        records = analyze_game(game["pgn"], DEPTHS[depth_label],
                               lambda f, t: bar.progress(f, text=t))
        if not records:
            raise ValueError("المباراة لا تحتوي على نقلات.")

        if user_result == "win":
            outcome = "🏆 فوز"
        elif user_result in DRAW_RESULTS:
            outcome = "🤝 تعادل"
        else:
            outcome = "❌ خسارة"

        status = f"""<div dir="rtl" style="line-height:1.9">
          ✅ تم تحليل آخر مباراة<br>
          ♙ الأبيض: <b>{w.get('username', '?')}</b> ({w.get('rating', '?')}) &nbsp;
          ♟ الأسود: <b>{b.get('username', '?')}</b> ({b.get('rating', '?')})<br>
          🎨 تلعب بـ: <b>{'الأبيض' if user_color == chess.WHITE else 'الأسود'}</b> &nbsp; 🏁 نتيجتك: <b>{outcome}</b><br>
          ⏱️ {game.get('time_class', '?')} ({game.get('time_control', '?')})
          &nbsp; <a href="{game.get('url', '#')}" target="_blank">رابط المباراة</a>
        </div>"""

        st.session_state.data = {
            "records": records,
            "user_color": user_color,
            "status": status,
        }
        st.session_state.idx = 0
        bar.empty()

    except ValueError as e:
        bar.empty()
        st.session_state.data = None
        st.error(str(e))
    except requests.exceptions.RequestException as e:
        bar.empty()
        st.session_state.data = None
        st.error(f"خطأ في الاتصال بـ Chess.com: {e}")
    except Exception as e:
        bar.empty()
        st.session_state.data = None
        st.error(f"خطأ غير متوقع: {e}")

data = st.session_state.data
if data:
    records = data["records"]
    user_color = data["user_color"]

    st.markdown(clean(data["status"]), unsafe_allow_html=True)
    st.markdown(clean(summary_html(records, user_color)), unsafe_allow_html=True)

    if len(records) > 1:
        st.slider("رقم النقلة", 0, len(records) - 1, key="idx")

    c1, c2 = st.columns(2)
    c1.button("◀ السابقة", on_click=go_prev, use_container_width=True)
    c2.button("التالية ▶", on_click=go_next, use_container_width=True)
    c3, c4 = st.columns(2)
    c3.button("خط
