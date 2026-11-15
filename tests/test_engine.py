import unittest

from engine import Board, Search, choose_move, run_agent


def perft(board, depth):
    if depth == 0:
        return 1
    return sum(perft(board.play(move), depth - 1) for move in board.legal())


class BoardTests(unittest.TestCase):
    def test_initial_position_has_twenty_legal_moves(self):
        board = Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        moves = {m.uci for m in board.legal()}
        self.assertEqual(len(moves), 20)
        self.assertIn("e2e4", moves)
        self.assertIn("g1f3", moves)

    def test_perft_regressions(self):
        cases = (
            ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
             (20, 400, 8902, 197281)),
            ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
             (14, 191, 2812)),
        )
        for fen, expected in cases:
            board = Board(fen)
            for depth, total in enumerate(expected, 1):
                with self.subTest(fen=fen, depth=depth):
                    self.assertEqual(perft(board, depth), total)

    def test_king_cannot_walk_into_attack_and_castling_available(self):
        board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        moves = {m.uci for m in board.legal()}
        self.assertIn("e1g1", moves)
        self.assertIn("e1c1", moves)
        attacked = Board("4r1k1/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertNotIn("e1e2", {m.uci for m in attacked.legal()})

    def test_en_passant_and_promotion_generation(self):
        ep = Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        self.assertIn("e5d6", {m.uci for m in ep.legal()})
        promo = Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        moves = {m.uci for m in promo.legal()}
        self.assertTrue({"a7a8q", "a7a8r", "a7a8b", "a7a8n"}.issubset(moves))

    def test_play_updates_special_move_state(self):
        board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        after = board.play(next(m for m in board.legal() if m.uci == "e1g1"))
        self.assertEqual(after.squares[6], "K")
        self.assertEqual(after.squares[5], "R")
        self.assertNotIn("K", after.castling)
        ep = Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        after_ep = ep.play(next(m for m in ep.legal() if m.uci == "e5d6"))
        self.assertEqual(after_ep.squares[35], ".")

    def test_castling_through_check_is_forbidden_and_rook_capture_clears_right(self):
        through_check = Board("4kr2/8/8/8/8/8/8/4K2R w K - 0 1")
        self.assertNotIn("e1g1", {m.uci for m in through_check.legal()})
        capture = Board("r3k3/8/8/8/8/8/8/R3K3 w q - 0 1")
        move = next(m for m in capture.legal() if m.uci == "a1a8")
        self.assertNotIn("q", capture.play(move).castling)


class SearchTests(unittest.TestCase):
    def test_transposition_bounds_and_reuse(self):
        board = Board("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
        expected, _ = Search(5000)._negamax(board, 2, -100001, 100001)

        for alpha, beta, expected_flag in (
                (expected + 1, expected + 2, -1),
                (expected - 2, expected - 1, 1)):
            with self.subTest(expected_flag=expected_flag):
                search = Search(5000)
                score, _ = search._negamax(board, 2, alpha, beta)
                key = (tuple(board.squares), board.white, board.castling,
                       board.ep, board.halfmove)
                self.assertEqual(search.tt[key][2], expected_flag)

                reused, _ = search._negamax(board, 2, -100001, 100001)
                fresh, _ = Search(5000)._negamax(
                    board, 2, -100001, 100001)
                self.assertEqual(reused, fresh)
                self.assertEqual(fresh, expected)

    def test_transposition_key_includes_halfmove_clock(self):
        search = Search(5000)
        board = Board("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
        search._negamax(board, 1, -100001, 100001)
        board.halfmove = 99
        search._negamax(board, 1, -100001, 100001)
        self.assertEqual(len(search.tt), 2)

    def test_search_returns_only_a_supplied_legal_root_move(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        result = choose_move(fen, ["e2e4", "d2d4"], node_limit=300, depth=3)
        self.assertIn(result, {"e2e4", "d2d4"})

    def test_fixed_node_search_is_repeatable_and_handles_terminal(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        a = Search(250).choose(fen, [m.uci for m in Board(fen).legal()], depth=3)
        b = Search(250).choose(fen, [m.uci for m in Board(fen).legal()], depth=3)
        self.assertEqual(a, b)
        self.assertIsNone(choose_move("4k3/8/8/8/8/8/8/4K3 w - - 0 1", []))

    def test_initial_move_develops_a_piece(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        moves = [m.uci for m in Board(fen).legal()]
        self.assertIn(Search(12000).choose(fen, moves, depth=4),
                      {"g1f3", "b1c3", "e2e4", "d2d4", "c2c4"})

    def test_finds_mate_in_one(self):
        fen = "7k/8/5KQ1/8/8/8/8/8 w - - 0 1"
        legal = [m.uci for m in Board(fen).legal()]
        move = choose_move(fen, legal, node_limit=3000, depth=3)
        self.assertEqual(move, "g6g7")
        after = Board(fen).play(next(m for m in Board(fen).legal() if m.uci == move))
        self.assertTrue(after.in_check())
        self.assertEqual(list(after.legal()), [])

    def test_takes_free_rook(self):
        fen = "r3k3/8/8/8/8/8/8/R3K3 w - - 0 1"
        move = choose_move(fen, [m.uci for m in Board(fen).legal()],
                           node_limit=3000, depth=3)
        self.assertEqual(move, "a1a8")


class ApiLoopTests(unittest.TestCase):
    def test_completed_game_starts_next_until_done(self):
        initial = {
            "game": 1, "fen": "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1",
            "status": "your_move", "legal_moves": ["e2e4"],
        }
        after_move = {"game": 1, "status": "over"}
        second = {"game": 2, "status": "over"}
        done = {"status": "done", "games": 2}
        responses = [initial, after_move, second, done]
        calls = []

        def fake_post(url, payload):
            calls.append((url, payload))
            return responses.pop(0)

        result = run_agent(fake_post, "http://env/")
        self.assertEqual(result, done)
        self.assertEqual(calls, [
            ("http://env/game", {}),
            ("http://env/move", {"game": 1, "move": "e2e4"}),
            ("http://env/game", {}),
            ("http://env/game", {}),
        ])
        self.assertEqual(responses, [])

    def test_empty_legal_list_resigns(self):
        active = {
            "game": 3, "fen": "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
            "status": "your_move", "legal_moves": [],
        }
        over = {"game": 3, "status": "over"}
        done = {"status": "done"}
        responses = [active, over, done]
        calls = []

        def fake_post(url, payload):
            calls.append((url, payload))
            return responses.pop(0)

        self.assertEqual(run_agent(fake_post, "http://env"), done)
        self.assertEqual(calls, [
            ("http://env/game", {}),
            ("http://env/resign", {"game": 3}),
            ("http://env/game", {}),
        ])


if __name__ == "__main__":
    unittest.main()
