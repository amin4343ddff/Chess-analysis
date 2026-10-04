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

    lastmove
