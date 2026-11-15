from dataclasses import dataclass
import json
import os
from urllib.request import Request, urlopen

VALUES = {"p": 100, "n": 320, "b": 335, "r": 500, "q": 900, "k": 0}
FILES = "abcdefgh"
KNIGHT = ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1))
KING = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
ROOK = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def sq_name(s):
    return FILES[s % 8] + str(s // 8 + 1)


def parse_sq(name):
    return FILES.index(name[0]) + 8 * (int(name[1]) - 1)


@dataclass(frozen=True)
class Move:
    src: int
    dst: int
    promotion: str = ""
    @property
    def uci(self):
        return sq_name(self.src) + sq_name(self.dst) + self.promotion


class Board:
    def __init__(self, fen):
        fields = fen.split()
        rows = fields[0].split("/")
        self.squares = ["."] * 64
        for row, text in enumerate(rows):
            rank = 7 - row
            file = 0
            for c in text:
                if c.isdigit(): file += int(c)
                else:
                    self.squares[rank * 8 + file] = c
                    file += 1
        self.white = fields[1] == "w"
        self.castling = fields[2] if len(fields) > 2 else "-"
        self.ep = parse_sq(fields[3]) if len(fields) > 3 and fields[3] != "-" else -1
        self.halfmove = int(fields[4]) if len(fields) > 4 else 0
        self.fullmove = int(fields[5]) if len(fields) > 5 else 1

    def copy(self):
        b = object.__new__(Board)
        b.squares = self.squares.copy()
        b.white, b.castling, b.ep = self.white, self.castling, self.ep
        b.halfmove, b.fullmove = self.halfmove, self.fullmove
        return b

    def king(self, white):
        target = "K" if white else "k"
        try: return self.squares.index(target)
        except ValueError: return -1

    def attacked(self, square, by_white):
        f, r = square % 8, square // 8
        pawn = "P" if by_white else "p"
        source_rank = r - (1 if by_white else -1)
        if 0 <= source_rank < 8:
            for df in (-1, 1):
                ff = f + df
                if 0 <= ff < 8 and self.squares[source_rank * 8 + ff] == pawn: return True
        knight = "N" if by_white else "n"
        for df, dr in KNIGHT:
            ff, rr = f + df, r + dr
            if 0 <= ff < 8 and 0 <= rr < 8 and self.squares[rr * 8 + ff] == knight: return True
        king = "K" if by_white else "k"
        for df, dr in KING:
            ff, rr = f + df, r + dr
            if 0 <= ff < 8 and 0 <= rr < 8 and self.squares[rr * 8 + ff] == king: return True
        for dirs, pieces in ((ROOK, "RQ" if by_white else "rq"),
                             (DIAGONAL, "BQ" if by_white else "bq")):
            for df, dr in dirs:
                ff, rr = f + df, r + dr
                while 0 <= ff < 8 and 0 <= rr < 8:
                    p = self.squares[rr * 8 + ff]
                    if p != ".":
                        if p in pieces: return True
                        break
                    ff += df; rr += dr
        return False

    def in_check(self, white=None):
        if white is None: white = self.white
        k = self.king(white)
        return k >= 0 and self.attacked(k, not white)

    def pseudo(self):
        side = self.white
        for s, p in enumerate(self.squares):
            if p == "." or p.isupper() != side: continue
            f, r, kind = s % 8, s // 8, p.lower()
            if kind == "p":
                step = 1 if side else -1
                nr = r + step
                if 0 <= nr < 8:
                    d = nr * 8 + f
                    if self.squares[d] == ".":
                        yield from self._pawn_move(s, d, nr)
                        if r == (1 if side else 6) and self.squares[d + step * 8] == ".":
                            yield Move(s, d + step * 8)
                    for df in (-1, 1):
                        nf = f + df
                        if 0 <= nf < 8:
                            d = nr * 8 + nf
                            target = self.squares[d]
                            if target != "." and target.isupper() != side or d == self.ep:
                                yield from self._pawn_move(s, d, nr)
            elif kind in "nk":
                for df, dr in KNIGHT if kind == "n" else KING:
                    nf, nr = f + df, r + dr
                    if 0 <= nf < 8 and 0 <= nr < 8:
                        d = nr * 8 + nf
                        if self.squares[d] == "." or self.squares[d].isupper() != side: yield Move(s, d)
                if kind != "k": continue
                home = 0 if side else 7
                if s == home * 8 + 4 and not self.in_check(side):
                    rights = "KQ" if side else "kq"
                    for short in (True, False):
                        right = rights[0 if short else 1]
                        rook_file = 7 if short else 0
                        between = (5, 6) if short else (1, 2, 3)
                        transit = (5, 6) if short else (3, 2)
                        if right in self.castling and self.squares[home * 8 + rook_file] == ("R" if side else "r") and all(self.squares[home * 8 + x] == "." for x in between) and all(not self.attacked(home * 8 + x, not side) for x in transit):
                            yield Move(s, home * 8 + (6 if short else 2))
            else:
                dirs = KING if kind == "q" or kind == "r" else ((1, 1), (1, -1), (-1, 1), (-1, -1))
                if kind == "r": dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
                for df, dr in dirs:
                    nf, nr = f + df, r + dr
                    while 0 <= nf < 8 and 0 <= nr < 8:
                        d = nr * 8 + nf
                        if self.squares[d] == ".": yield Move(s, d)
                        else:
                            if self.squares[d].isupper() != side: yield Move(s, d)
                            break
                        nf += df; nr += dr

    @staticmethod
    def _pawn_move(s, d, rank):
        if rank in (0, 7):
            for p in "qrbn": yield Move(s, d, p)
        else: yield Move(s, d)

    def play(self, m):
        b = self.copy(); p = b.squares[m.src]; target = b.squares[m.dst]
        b.squares[m.src] = "."
        if p.lower() == "p" and m.dst == self.ep and target == ".":
            b.squares[m.dst + (-8 if self.white else 8)] = "."
        b.squares[m.dst] = (m.promotion.upper() if self.white else m.promotion) if m.promotion else p
        if p.lower() == "k" and abs(m.dst - m.src) == 2:
            home = 0 if self.white else 7
            rook_src, rook_dst = (home * 8 + 7, home * 8 + 5) if m.dst > m.src else (home * 8, home * 8 + 3)
            b.squares[rook_dst] = b.squares[rook_src]; b.squares[rook_src] = "."
        rights = b.castling
        if p == "K": rights = rights.replace("K", "").replace("Q", "")
        if p == "k": rights = rights.replace("k", "").replace("q", "")
        for sq, chars in ((0, "Q"), (7, "K"), (56, "q"), (63, "k")):
            if m.src == sq or m.dst == sq:
                for c in chars: rights = rights.replace(c, "")
        b.castling = rights or "-"
        b.ep = (m.src + m.dst) // 2 if p.lower() == "p" and abs(m.dst - m.src) == 16 else -1
        b.halfmove = 0 if p.lower() == "p" or target != "." else b.halfmove + 1
        if not self.white: b.fullmove += 1
        b.white = not self.white
        return b

    def legal(self):
        for m in self.pseudo():
            if not self.play(m).in_check(self.white): yield m


def evaluate(board):
    total = 0
    for s, p in enumerate(board.squares):
        if p == ".": continue
        white = p.isupper(); kind = p.lower(); f, r = s % 8, s // 8
        advance = r if white else 7 - r
        center = 7 - (abs(2 * f - 7) + abs(2 * r - 7)) // 2
        score = VALUES[kind]
        if kind in "nb":
            score += center * 4
            home = (0 if white else 7) * 8
            if s in (home + 1, home + 6) and kind == "n": score -= 12
            elif s in (home + 2, home + 5) and kind == "b": score -= 8
            else: score += 8
        elif kind == "p": score += advance * (5 if f in (3, 4) else 1) + center
        elif kind == "k":
            score += (advance * 5 if board.squares.count("q") + board.squares.count("Q") == 0
                      else -center * 3)
        total += score if white else -score
    return total if board.white else -total


class Search:
    def __init__(self, node_limit=12000):
        self.node_limit = node_limit
        self.nodes = 0
        self.tt = {}

    @staticmethod
    def _order(board, moves):
        def key(m):
            victim = board.squares[m.dst]
            if board.squares[m.src].lower() == "p" and m.dst == board.ep and victim == ".": victim = "p"
            capture = VALUES.get(victim.lower(), 0) if victim != "." else 0
            attacker = VALUES[board.squares[m.src].lower()]
            return (1 if m.promotion else 0, capture * 10 - attacker if capture else 0, m.uci)
        return sorted(moves, key=key, reverse=True)

    def _negamax(self, board, depth, alpha, beta):
        self.nodes += 1
        original, upper = alpha, beta
        key = (tuple(board.squares), board.white, board.castling, board.ep,
               board.halfmove)
        entry = self.tt.get(key)
        ttmove = None
        if entry:
            td, ts, flag, tm = entry
            ttmove = tm
            if td >= depth:
                if flag == 0: return ts, tm
                if flag < 0: beta = min(beta, ts)
                else: alpha = max(alpha, ts)
                if alpha >= beta: return ts, tm
        legal = list(board.legal())
        if not legal:
            return (-100000 + (4 - depth) if board.in_check() else 0), None
        if depth <= 0:
            return self._quiescence(board, alpha, beta, legal), None
        if self.nodes >= self.node_limit:
            return evaluate(board), None
        best = None; value = -100001
        ordered = self._order(board, legal)
        if ttmove in ordered: ordered.remove(ttmove); ordered.insert(0, ttmove)
        for i, move in enumerate(ordered):
            child = board.play(move)
            if i:
                score, _ = self._negamax(child, depth - 1, -alpha - 1, -alpha)
                score = -score
                if alpha < score < beta:
                    score, _ = self._negamax(child, depth - 1, -beta, -alpha)
                    score = -score
            else:
                score, _ = self._negamax(child, depth - 1, -beta, -alpha)
                score = -score
            if score > value: value, best = score, move
            alpha = max(alpha, score)
            if alpha >= beta or self.nodes >= self.node_limit: break
        if self.nodes < self.node_limit:
            flag = -1 if value <= original else 1 if value >= upper else 0
            self.tt[key] = (depth, value, flag, best)
        return value, best

    def _quiescence(self, board, alpha, beta, legal=None, qdepth=8):
        if self.nodes >= self.node_limit: return evaluate(board)
        checked = board.in_check()
        if legal is None: legal = list(board.legal())
        if not legal: return -100000 if checked else 0
        if qdepth <= 0: return evaluate(board) - (40 if checked else 0)
        stand = -100001 if checked else evaluate(board)
        if not checked:
            if stand >= beta: return stand
            alpha = max(alpha, stand)
        for move in self._order(board, legal):
            target = board.squares[move.dst]
            capture = target != "." or (board.squares[move.src].lower() == "p" and move.dst == board.ep)
            if not checked and not capture and not move.promotion: continue
            self.nodes += 1
            score = -self._quiescence(board.play(move), -beta, -alpha, qdepth=qdepth - 1)
            stand = max(stand, score)
            alpha = max(alpha, score)
            if alpha >= beta or self.nodes >= self.node_limit: break
        return stand

    def choose(self, fen, legal_moves, depth=4):
        self.nodes = 0
        self.tt.clear()
        board = Board(fen)
        roots = {m.uci: m for m in board.legal()}
        candidates = [roots[x] for x in legal_moves if x in roots]
        if not candidates: return None
        best = candidates[0]
        ordered = self._order(board, candidates)
        for current_depth in range(1, max(1, depth) + 1):
            iteration_best = None
            best_score = -100001
            alpha = -100001
            complete = True
            for move in ordered:
                if self.nodes >= self.node_limit:
                    complete = False
                    break
                score, _ = self._negamax(board.play(move), current_depth - 1,
                                          -100001, -alpha)
                score = -score
                if self.nodes >= self.node_limit:
                    complete = False
                    break
                if score > best_score:
                    best_score, iteration_best = score, move
                alpha = max(alpha, score)
            if not complete or iteration_best is None:
                break
            best = iteration_best
        return best.uci


def choose_move(fen, legal_moves, node_limit=12000, depth=4):
    return Search(node_limit).choose(fen, legal_moves, depth)


def _post_json(url, payload):
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def run_agent(post=None, env_url=None):
    if post is None:
        post = _post_json
    if env_url is None:
        env_url = os.environ["MAKEFUN_ENV_URL"]
    base = env_url.rstrip("/")
    while True:
        game = post(base + "/game", {})
        if game.get("status") == "done":
            return game
        while game.get("status") != "over":
            game_number = game["game"]
            legal = game.get("legal_moves", [])
            if not legal:
                game = post(base + "/resign", {"game": game_number})
                break
            move = choose_move(game["fen"], legal)
            if move not in legal:
                game = post(base + "/resign", {"game": game_number})
                break
            game = post(base + "/move", {"game": game_number, "move": move})


if __name__ == "__main__":
    run_agent()
